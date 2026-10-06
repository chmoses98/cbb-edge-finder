"""Wave 8 roster-gap probe (from Actions). Evidence only; nothing here changes a roster.

Every request goes through the chokepoint (registered hosts only, per-host spacing),
robots.txt is consulted first, no bot protection is bypassed (a block is recorded as a
block), and failures keep their status, server headers and the first bytes of the body.

* ESPN: the West Florida (2697) and Saint Francis (2598) team records + 2697 schedule;
* Missouri: why the NCAA Athletics Link answers 404 (status / headers / body);
* Alabama: the 2026-27 roster's own page state (players in the server data and payload);
* ASU: the official home page's roster link to another host, then (with that evidence
  applied to a probe-only registry, the rule in ``ncaa_directory.linked_host_ok``) the
  linked roster page itself;
* Jacksonville, LIU, LSU: today's player counts on the official pages;
* robots / bot protection (Little Rock, CCSU, Colgate, Omaha, Tennessee Tech): the
  robots.txt answer only.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path("samples/gaps")
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"


def _raw(source: str, url: str, key: str) -> dict:
    """One request; keeps status, headers and body head also when the answer is an error."""
    from cbb_edge.data.http import RedirectNotAuthorized, fetch
    from cbb_edge.rosters import robots

    stamp = os.environ["PROBE_STAMP"]
    if source == "school_athletics" and not robots.allowed(source, url, stamp):
        host = re.sub(r"^https?://([^/]+).*", r"\1", url).lower()
        return {"url": url, "result": "robots", "robots_status": robots.status.get(host)}
    try:
        r = fetch(source, url, dest=f"gaps/{stamp}/{key}", use_cache=False, timeout=30,
                  max_attempts=1)  # fmt: skip
        body = r.path.read_bytes()
        (OUT / f"{key}.gz").write_bytes(gzip.compress(body))
        return {"url": url, "result": "ok", "status": r.meta.get("status"),
                "final_url": r.meta.get("final_url"), "bytes": len(body),
                "sha256": r.meta.get("sha256")}  # fmt: skip
    except RedirectNotAuthorized as e:
        return {"url": url, "result": "redirect_unregistered", "to": e.target}
    except Exception as e:  # noqa: BLE001  an HTTP error keeps its answer as evidence
        resp = getattr(e, "response", None)
        if resp is None:
            return {"url": url, "result": f"error:{type(e).__name__}:{str(e)[:200]}"}
        body = resp.content[:65536] if resp is not None else b""
        (OUT / f"{key}.error.gz").write_bytes(gzip.compress(body))
        hdr = {k: v for k, v in (resp.headers if resp is not None else {}).items()
               if k.lower() in ("server", "content-type", "x-cache", "x-served-by", "via",
                                "cf-ray", "x-iinfo", "x-cdn", "location")}  # fmt: skip
        return {"url": url, "result": "http_error", "status": getattr(resp, "status_code", None),
                "headers": hdr, "body_head": body[:1500].decode(errors="replace")}  # fmt: skip


def espn() -> dict:
    out = {}
    for tid in (2697, 2598):
        r = _raw("espn_public", f"{SITE}/teams/{tid}", f"espn_team_{tid}.json")
        if r["result"] == "ok":
            t = json.loads(gzip.decompress((OUT / f"espn_team_{tid}.json.gz").read_bytes()))
            t = t.get("team", {})
            r |= {"displayName": t.get("displayName"), "isActive": t.get("isActive"),
                  "groups": t.get("groups"), "standingSummary": t.get("standingSummary")}  # fmt: skip
        out[str(tid)] = r
    r = _raw("espn_public", f"{SITE}/teams/2697/schedule", "espn_sched_2697.json")
    if r["result"] == "ok":
        s = json.loads(gzip.decompress((OUT / "espn_sched_2697.json.gz").read_bytes()))
        ev = s.get("events", [])
        r |= {"events": len(ev), "season": s.get("season"),
              "first": [e.get("shortName") for e in ev[:6]]}  # fmt: skip
    out["2697_schedule"] = r
    return out


def nuxt_counts(key: str) -> dict:
    from cbb_edge.rosters.parsers import wmt

    p = OUT / f"{key}.gz"
    if not p.exists():
        return {}
    h = gzip.decompress(p.read_bytes()).decode(errors="replace")
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        return {"nuxt": False}
    v = wmt.devalue(json.loads(m.group(1)))
    r = ((v.get("pinia") or {}).get("roster") or {}).get("roster") or {}
    return {k: {"title": x.get("displayTitle"), "players": len(x.get("players") or []),
                "coaches": len(x.get("coaches") or []), "support": len(x.get("support") or [])}
            for k, x in r.items()}  # fmt: skip


def main() -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    os.environ["PROBE_STAMP"] = stamp
    OUT.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--asu-linked":
        return asu_linked(stamp)
    rep: dict = {"stamp": stamp, "espn": espn()}
    rep["missouri"] = [
        _raw("school_athletics", u, f"mizzou_{i}.html")
        for i, u in enumerate(["https://www.mutigers.com", "https://www.mutigers.com/",
                               "https://mutigers.com/",
                               "https://mutigers.com/sports/mens-basketball/roster"])
    ]  # fmt: skip
    rep["alabama"] = {
        "page": _raw("school_athletics", "https://rolltide.com/sports/mens-basketball/roster",
                     "bama_roster.html"),
    }  # fmt: skip
    rep["alabama"]["server_state"] = nuxt_counts("bama_roster.html")
    from cbb_edge.rosters import discovery, official

    reg = {r["team_id"]: r for r in official.load_registry()["teams"] if r.get("team_id")}
    found = {}
    for t in ("T0006", "T0137", "T0334", "T0050", "T0155"):
        d = discovery.discover(t, reg[t]["athletics_url"], 2027, stamp)
        found[t] = {"roster_url": d.roster_url, "players": len(d.players), "error": d.error,
                    "linked_to": d.linked_to, "linked_evidence": d.linked_evidence,
                    "season_label": d.season_label, "attempts": d.attempts}  # fmt: skip
    rep["discovery"] = found
    from cbb_edge.rosters import robots

    rep["robots"] = {}
    for t, h in (("T0171", "lrtrojans.com"), ("T0184", "www.ccsubluedevils.com"),
                 ("T0190", "gocolgateraiders.com"), ("T0349", "www.omavs.com"),
                 ("T0305", "www.ttusports.com")):  # fmt: skip
        ok = robots.allowed("school_athletics", f"https://{h}/", stamp)  # robots.txt only
        rep["robots"][t] = {"host": h, "home_allowed": ok, "robots_status": robots.status.get(h)}
    ev = found["T0006"].get("linked_evidence")
    if ev:
        # probe-only registry with the ASU evidence applied by the production rule, then
        # a separate process (SCHOOL_HOSTS is read at import) fetches the linked page
        from cbb_edge.rosters import ncaa_directory as nd

        body = official.load_registry()
        for r in body["teams"]:
            if r.get("team_id") == "T0006" and nd.linked_host_ok(r["host"], ev["to"].split("/")[2]):
                r["linked_hosts"] = nd._hosts_of([ev], r["host"])
                r["linked_evidence"] = [ev]
        body.pop("sha256", None)
        import hashlib

        body["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        p = OUT / "probe_registry.json"
        p.write_text(json.dumps(body))
        env = dict(os.environ, CBB_DOMAIN_REGISTRY=str(p.resolve()))
        res = subprocess.run([sys.executable, __file__, "--asu-linked"], env=env,
                             capture_output=True, text=True, check=False)  # fmt: skip
        rep["asu_linked"] = res.stdout.strip().splitlines()[-1:] or res.stderr[-2000:]
    (OUT / "gaps_report.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str)[:20000])


def asu_linked(stamp: str) -> None:
    from cbb_edge.rosters import discovery, official

    reg = {r["team_id"]: r for r in official.load_registry()["teams"] if r.get("team_id")}
    r = reg["T0006"]
    d = discovery.discover("T0006", r["athletics_url"], 2027, stamp,
                           team_hosts=frozenset(r.get("linked_hosts", [])))  # fmt: skip
    print(json.dumps({"linked_hosts": r.get("linked_hosts"), "roster_url": d.roster_url,
                      "players": len(d.players), "season_label": d.season_label,
                      "platform": d.platform, "error": d.error, "attempts": d.attempts,
                      "names": [p["name"] for p in d.players][:30]}, default=str))  # fmt: skip


if __name__ == "__main__":
    main()
