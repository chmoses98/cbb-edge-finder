"""WMT Digital roster pages (Nuxt; card and list layouts).

Each player is a ``roster-card-item`` / ``roster-list-item`` container holding a
``/roster/player/<slug>`` link; staff containers carry no player link and are skipped.
Fields are read from the container's own class names (``...jersey-number``,
``...position``, ``...--height``, ``...--class-level``, ``...--hometown``,
``...--previous-school``) or from labelled pairs (``label`` / ``value`` spans)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from cbb_edge.rosters.parsers.base import (
    CLASSES,
    ParsedRoster,
    clean,
    height_in,
    season_label,
    txt,
)

_ITEM = re.compile(r'<(?:li|div)\b[^>]*class="roster-(?:list|card)-item(?:\s[^"]*)?"')
_PLAYER = re.compile(r'href="([^"]*/roster/(?:season/[^"/]+/)?player/[^"/?#]+)/?"')


def _cls(chunk: str, pat: str) -> str | None:
    m = re.search(r'<(\w+)\b[^>]*class="[^"]*' + pat + r'[^"]*"[^>]*>(.*?)</\1>', chunk, re.S)
    return (txt(m.group(2)) or None) if m else None


def _labelled(chunk: str) -> dict[str, str]:
    out = {}
    for lab, val in re.findall(
        r'class="[^"]*profile-field__label[^"]*"[^>]*>(.*?)</\w+>\s*(?:<!--\[-->)?\s*'
        r'<\w+[^>]*class="[^"]*profile-field__value[^"]*"[^>]*>(.*?)</\w+>',
        chunk,
        re.S,
    ):
        out[txt(lab).lower()] = txt(val)
    return out


def _basic_values(chunk: str) -> list[str]:
    return [txt(v) for v in re.findall(
        r'class="[^"]*profile-field__value--basic[^"]*"[^>]*>(.*?)</span>', chunk, re.S)]  # fmt: skip


def parse(page: str, url: str) -> ParsedRoster:
    body = page[page.find("<body") :] if "<body" in page else page
    starts = [m.start() for m in _ITEM.finditer(body)]
    out = []
    for i, s in enumerate(starts):
        chunk = body[s : starts[i + 1] if i + 1 < len(starts) else s + 8000]
        hrefs = _PLAYER.findall(chunk)
        if not hrefs:
            continue
        name = None
        for m in re.finditer(
            r'<a\b[^>]*href="' + re.escape(hrefs[0]) + r'"[^>]*>(.*?)</a>', chunk, re.S
        ):
            name = txt(m.group(1)) or name
            if name:
                break
        if not name:
            h3 = re.search(r"<h3\b[^>]*>(.*?)</h3>", chunk, re.S)
            name = txt(h3.group(1)) if h3 else None
        lab = _labelled(chunk)
        basic = _basic_values(chunk)
        jersey = _cls(chunk, "jersey-number") or _cls(chunk, "item__number")
        cls = _cls(chunk, "--class-level") or lab.get("class") or lab.get("year") or next(
            (b for b in basic if CLASSES.match(b)), None)  # fmt: skip
        h = _cls(chunk, "--height") or lab.get("height") or next(
            (b for b in basic if height_in(b) is not None), None)  # fmt: skip
        out.append({
            "name": name,
            "jersey": jersey.lstrip("#").strip() if jersey else None,
            "position": _cls(chunk, "--position") or _cls(chunk, "item__position")
            or lab.get("position"),
            "height_in": height_in(h),
            "class_label": cls,
            "hometown": _cls(chunk, "--hometown") or lab.get("hometown"),
            "previous_school": _cls(chunk, "--previous-school") or lab.get("previous school")
            or lab.get("last school"),
            "profile_url": urljoin(url, hrefs[0]),
        })  # fmt: skip
    if len(out) < 8:  # client-rendered list: the page's own embedded payload
        emb = nuxt_players(page, url)
        if len(emb) > len(out):
            out = emb
    return ParsedRoster("wmt", clean(out), season_label(page, url))


_WRAP = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}


def devalue(arr: list) -> object:
    """Decode a Nuxt 3 ``__NUXT_DATA__`` payload (devalue format: a flat array whose
    objects hold indices into the array)."""
    memo: dict[int, object] = {}

    def r(i: object, depth: int = 0) -> object:
        if not isinstance(i, int) or i < 0 or i >= len(arr) or depth > 80:
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, dict):
            o: dict = {}
            memo[i] = o
            for k, x in v.items():
                o[k] = r(x, depth + 1)
            return o
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _WRAP:
                return r(v[1] if len(v) > 1 else None, depth + 1)
            lst: list = []
            memo[i] = lst
            lst.extend(r(x, depth + 1) for x in v)
            return lst
        return v

    return r(0)


def _player_entries(root: object) -> list[dict]:
    out, seen = [], set()
    stack = [root]
    while stack:
        o = stack.pop()
        if id(o) in seen:
            continue
        seen.add(id(o))
        if isinstance(o, dict):
            p = o.get("player")
            if isinstance(p, dict) and "first_name" in p and "roster_id" in o:
                out.append(o)
            stack.extend(reversed(list(o.values())))  # document order
        elif isinstance(o, list):
            stack.extend(reversed(o))
    uniq = {}
    for e in out:
        pid = e["player"].get("id") or e["player"].get("full_name") or id(e)
        uniq.setdefault((e.get("roster_id"), pid), e)
    return list(uniq.values())


def _name_of(x: object, *keys: str) -> str | None:
    if isinstance(x, dict):
        for k in keys:
            if x.get(k):
                return str(x[k])
    return str(x) if isinstance(x, str) else None


def payload_players(payload: str, url: str) -> list[dict]:
    """Players from a Nuxt ``_payload.json`` (the same devalue array, served apart)."""
    return nuxt_players(f'<script id="__NUXT_DATA__">{payload}</script>', url)


def nuxt_players(page: str, url: str) -> list[dict]:
    """Player entries from the page's own embedded Nuxt payload (same data the page
    renders): roster entries ``{player: {first_name, last_name, ...}, jersey_number,
    height_feet, height_inches, class_level, player_position, roster_id}``. The roster
    with the most entries wins (pages can embed other sports' rosters)."""
    import json

    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    try:
        root = devalue(json.loads(m.group(1)))
    except ValueError:
        return []
    ent = _player_entries(root)
    if not ent:
        return []
    by_roster: dict = {}
    for e in ent:
        by_roster.setdefault(e.get("roster_id"), []).append(e)
    best = max(by_roster.values(), key=len)
    out = []
    for e in best:
        p = e["player"]
        ft = e.get("height_feet") or p.get("height_feet")
        inch = e.get("height_inches") if e.get("height_feet") else p.get("height_inches")
        out.append({
            "name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}",
            "jersey": str(e.get("jersey_number") or p.get("jersey_number") or "") or None,
            "position": _name_of(e.get("player_position"), "abbreviation", "name"),
            "height_in": float(int(ft) * 12 + int(inch or 0)) if ft else None,
            "class_label": _name_of(e.get("class_level"), "abbreviation", "name"),
            "hometown": p.get("hometown"),
            "previous_school": p.get("previous_school"),
            "profile_url": urljoin(url, f"player/{p['slug']}") if p.get("slug") else None,
        })  # fmt: skip
    return out
