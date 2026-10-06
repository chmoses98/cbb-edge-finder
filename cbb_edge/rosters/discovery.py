"""Official men's basketball roster-page discovery and platform detection (Wave 7).

For one team's official athletics site (from the NCAA Membership Directory registry,
``models/rosters/ncaa_athletics_domains.json``) find the current men's basketball
roster page with as few requests as possible. Every request goes through the
chokepoint (``school_athletics``: >= 5 s between requests to any one host), robots.txt
is consulted first, and the search stops at the first page that parses as a roster.

Order (fixed; no search engine, no spidering):

1. the site home page: platform detection + any men's basketball roster link on it;
2. the platform's own route (SIDEARM / WMT ``/sports/mens-basketball/roster``,
   PrestoSports ``/sports/mbkb/<season>/roster``);
3. a very small set of conventional paths;
4. one level of links from the men's basketball page found on the home page.

Wave 8: links are also read from JSON-escaped URLs in the page (written with backslash-escaped slashes,
e.g. Drupal navigation data), and a men's basketball roster link from the official
home page to ANOTHER host is followed only when that host is already registered to the
same team (``team_hosts``). An unregistered one is recorded as ``linked_to`` evidence
and never requested: the registry adds it, under the deterministic rule in
``ncaa_directory.linked_host_ok``, at its next refresh.

At most ``MAX_REQUESTS`` page requests per team (robots.txt aside).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlsplit

from cbb_edge.data.http import RedirectNotAuthorized, fetch
from cbb_edge.rosters import robots
from cbb_edge.rosters.parsers import parse_roster

SOURCE = "school_athletics"
MAX_REQUESTS = 6
MIN_PLAYERS = 8  # a men's basketball roster page lists at least this many players

PLATFORM_MARKERS = {
    "sidearm": ("sidearmsports", "sidearm-", "s-person-card", "sidearm_"),
    "wmt": ("wmt.digital", "wmt-", "wmtwidgets", "wmt_", "wmtsports"),
    "presto": ("prestosports", "presto-", "/sports/mbkb/"),
}
MBB = r"(?:mens-basketball|mens_basketball|mbball|mbkb|m-baskbl|mbasketball|mens-bball|mbb)"


def season_path(season: int) -> str:
    return f"{season - 1}-{str(season)[2:]}"


def detect_platform(html: str) -> str:
    low = html.lower()
    hits = {p: sum(low.count(m) for m in ms) for p, ms in PLATFORM_MARKERS.items()}
    best = max(hits, key=lambda k: hits[k])
    return best if hits[best] > 0 else "generic"


ESCAPED_URL = r"https?:\\/\\/[A-Za-z0-9.-]+(?:\\/[A-Za-z0-9._~%+-]+)+(?:\\/)?"


def _links(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html, flags=re.S | re.I):
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((urljoin(base, unescape(m.group(1))), text))
    # URLs inside JSON / script data, written with escaped slashes (no link text)
    for m in re.finditer(ESCAPED_URL, html):
        out.append((m.group(0).replace("\\/", "/"), ""))
    return out


def _same_site(url: str, host: str, extra: frozenset[str] = frozenset()) -> bool:
    h = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return any(h == x or h.endswith("." + x) or x.endswith("." + h) for x in {host, *extra})


def roster_links(html: str, base: str, host: str, extra: frozenset[str] = frozenset()) -> list[str]:
    """Links that look like the men's basketball roster (women's excluded), on the
    site's own host or another host registered to the same team (``extra``)."""
    out = []
    for u, t in _links(html, base):
        lu = u.lower()
        if not _same_site(u, host, extra) or "women" in lu or "wbb" in lu or "wbkb" in lu:
            continue
        if (
            re.search(MBB, lu)
            and "roster" in lu
            or (
                "roster" in lu
                and re.search(r"men'?s basketball", t, flags=re.I)
                and "women" not in t.lower()
            )
        ):
            out.append(u.split("?")[0])
    return list(dict.fromkeys(out))


def offsite_roster_links(html: str, base: str, host: str) -> list[str]:
    """Men's basketball roster links (by path) from the official page to OTHER hosts."""
    out = []
    for u, _t in _links(html, base):
        lu = u.lower()
        h = (urlsplit(u).hostname or "").lower().removeprefix("www.")
        if not h or _same_site(u, host) or "women" in lu:
            continue
        if re.search(MBB, lu) and "roster" in lu:
            out.append(u.split("?")[0])
    return list(dict.fromkeys(out))


def sport_links(html: str, base: str, host: str) -> list[str]:
    out = []
    for u, _t in _links(html, base):
        lu = u.lower()
        if _same_site(u, host) and re.search(MBB, lu) and "women" not in lu and "roster" not in lu:
            out.append(u.split("?")[0])
    return list(dict.fromkeys(out))[:2]


def platform_paths(platform: str, season: int) -> list[str]:
    sp = season_path(season)
    common = ["/sports/mens-basketball/roster", f"/sports/mbkb/{sp}/roster"]
    if platform == "presto":
        return [f"/sports/mbkb/{sp}/roster", "/sports/mens-basketball/roster"]
    if platform == "wmt":
        return ["/sports/mens-basketball/roster", "/sports/mbball/roster"]
    return common


@dataclass
class Discovery:
    team_id: str
    base_url: str
    host: str
    platform: str = "unknown"
    roster_url: str | None = None
    method: str | None = None
    requests: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    page_path: str | None = None
    page_meta: dict[str, Any] | None = None
    players: list[dict[str, Any]] = field(default_factory=list)
    season_label: int | None = None
    error: str | None = None
    redirect_to: str | None = None  # an unregistered host the official link redirects to
    stamp: str | None = None
    linked_to: str | None = None  # unregistered roster link on the official home page
    linked_evidence: dict[str, Any] | None = None


def _get(d: Discovery, url: str, stamp: str) -> str | None:
    if d.requests >= MAX_REQUESTS:
        return None
    if not robots.allowed(SOURCE, url, stamp):
        host = (urlsplit(url).hostname or "").lower()
        if host in robots.redirects:
            d.redirect_to = d.redirect_to or robots.redirects[host]
            d.attempts.append({"url": url, "result": "redirect_unregistered",
                               "to": robots.redirects[host]})  # fmt: skip
        else:
            why = robots.status.get(host, "")
            res = "robots_disallowed" if why in ("ok", "") else f"robots_unavailable:{why}"
            d.attempts.append({"url": url, "result": res})
        return None
    d.requests += 1
    key = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1])[:150]
    try:
        r = fetch(SOURCE, url, dest=f"pages/{stamp}/{d.team_id}/{key}.html", not_found_ok=True,
                  timeout=30, max_attempts=2)  # fmt: skip
    except RedirectNotAuthorized as e:
        d.redirect_to = d.redirect_to or e.target
        d.attempts.append({"url": url, "result": "redirect_unregistered", "to": e.target})
        return None
    except Exception as e:  # noqa: BLE001  one site never stops the run
        d.attempts.append({"url": url, "result": f"error:{type(e).__name__}:{str(e)[:120]}"})
        return None
    if r is None:
        d.attempts.append({"url": url, "result": "404"})
        return None
    d.attempts.append({"url": url, "result": "ok", "final_url": r.meta.get("final_url")})
    d._last = r  # type: ignore[attr-defined]
    return r.path.read_text(errors="replace")


def _try_roster(d: Discovery, url: str, html: str | None, method: str, season: int,
                stamp: str = "") -> bool:  # fmt: skip
    if html is None:
        return False
    parsed = parse_roster(html, d.platform, url, season)
    pay = re.search(r'href="([^"]*/roster/_payload\.json[^"]*)"', html)
    if len(parsed.players) < MIN_PLAYERS and pay and stamp:
        # Nuxt sites that ship the page data as a separate _payload.json (same host,
        # same data the page renders): one extra request
        from cbb_edge.rosters.parsers import wmt

        r_page = d._last  # type: ignore[attr-defined]
        js = _get(d, urljoin(url, unescape(pay.group(1))), stamp)
        if js is not None:
            emb = wmt.payload_players(js, url)
            if len(emb) >= MIN_PLAYERS:
                parsed.players, parsed.platform = emb, "wmt"
        d._last = r_page  # type: ignore[attr-defined]
    if len(parsed.players) < MIN_PLAYERS:
        d.attempts[-1]["players"] = len(parsed.players)
        return False
    r = d._last  # type: ignore[attr-defined]
    d.roster_url = r.meta.get("final_url") or url
    d.method, d.players, d.season_label = method, parsed.players, parsed.season_label
    d.platform = parsed.platform
    d.page_path, d.page_meta = str(r.path), r.meta
    return True


def discover(
    team_id: str,
    base_url: str,
    season: int,
    stamp: str,
    known_url: str | None = None,
    team_hosts: frozenset[str] = frozenset(),
) -> Discovery:
    """``known_url``: the roster URL found by an earlier run (tried first: a normal daily
    run costs one page request per site, plus robots.txt). ``team_hosts``: the team's
    other registered hosts (redirect / linked evidence in the registry)."""
    host = (urlsplit(base_url).hostname or "").lower().removeprefix("www.")
    d = Discovery(team_id, base_url, host, stamp=stamp)
    if known_url:
        page = _get(d, known_url, stamp)
        if page is not None:
            d.platform = detect_platform(page)
            if _try_roster(d, known_url, page, "known_url", season, stamp):
                return d
    home = _get(d, base_url, stamp)
    if home is None and (urlsplit(base_url).hostname or "").lower().startswith("www."):
        # Wave 8 (C4): the www. name of the registered host answers 404 (e.g.
        # www.mutigers.com while mutigers.com serves the site): try the bare host once
        if d.attempts and d.attempts[-1].get("result") == "404":
            apex = base_url.replace("://www.", "://", 1)
            home = _get(d, apex, stamp)
            if home is not None:
                base_url = apex
    if home is None:
        d.error = "home_unreachable"
        # the conventional routes may still work when only the home page is blocked
        home = ""
    else:
        # an official link that redirected (e.g. wofford.edu/athletics ->
        # woffordterriers.com): the site's own routes live on the final host
        final = (d._last.meta.get("final_url") if hasattr(d, "_last") else None) or base_url  # type: ignore[attr-defined]
        fh = (urlsplit(final).hostname or "").lower().removeprefix("www.")
        if fh and fh != host:
            base_url, host = final, fh
    d.platform = detect_platform(home) if home else "unknown"
    tried: set[str] = set()
    cands = [(u, "home_link") for u in roster_links(home, base_url, host, team_hosts)[:2]]
    if home and not cands:
        from cbb_edge.rosters.ncaa_directory import linked_host_ok

        for u in offsite_roster_links(home, base_url, host):
            lh = (urlsplit(u).hostname or "").lower().removeprefix("www.")
            if lh in team_hosts or not linked_host_ok(host, lh) or d.linked_to:
                continue
            page = d._last.meta if hasattr(d, "_last") else {}  # type: ignore[attr-defined]
            d.linked_to = u
            d.linked_evidence = {"from": page.get("final_url") or base_url, "to": u,
                                 "observed_at": stamp, "page_sha256": page.get("sha256"),
                                 "kind": "official_home_page_roster_link"}  # fmt: skip
            d.attempts.append({"url": u, "result": "linked_unregistered"})
    cands += [(urljoin(base_url, p), "platform_route") for p in platform_paths(d.platform, season)]
    for u, how in cands:
        if u in tried:
            continue
        tried.add(u)
        if _try_roster(d, u, _get(d, u, stamp), how, season, stamp):
            return d
    for sp in sport_links(home, base_url, host):
        page = _get(d, sp, stamp)
        if page is None:
            continue
        for u in roster_links(page, sp, host)[:1]:
            if u not in tried and _try_roster(
                d, u, _get(d, u, stamp), "sport_page_link", season, stamp
            ):
                return d
    d.error = d.error or "roster_not_found"
    return d
