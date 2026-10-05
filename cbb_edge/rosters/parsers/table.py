"""Header-driven HTML roster tables (PrestoSports and many custom sites).

A table qualifies only if its header row names the player column and at least one of
position / height / class; columns are mapped by header text, never by position."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from cbb_edge.rosters.parsers.base import ParsedRoster, clean, height_in, season_label, txt

COLS = {
    "jersey": r"^(?:no\.?|#|num(?:ber)?|jersey)$",
    "name": r"^(?:name|player|full name)$",
    "position": r"^(?:pos\.?|position)$",
    "height": r"^(?:ht\.?|height)$",
    "class_label": r"^(?:cl\.?|class|yr\.?|year|academic year|elig\.?)$",
    "hometown": r"^(?:hometown.*|home ?town.*)$",
    "previous_school": r"^(?:previous school|last school|prev\.? school|high school.*|"
    r"hometown ?/ ?(?:high school|previous school).*)$",
}


def _cells(row: str) -> list[str]:
    return re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, flags=re.S | re.I)


def _map(header: list[str]) -> dict[str, int]:
    m: dict[str, int] = {}
    for i, h in enumerate(header):
        t = txt(h).lower().strip(":")
        for k, pat in COLS.items():
            if k not in m and re.match(pat, t):
                m[k] = i
                break
    return m


def parse(page: str, url: str, platform: str = "table") -> ParsedRoster:
    best: list[dict] = []
    for tab in re.findall(r"<table\b.*?</table>", page, flags=re.S | re.I):
        rows = re.findall(r"<tr\b.*?</tr>", tab, flags=re.S | re.I)
        if len(rows) < 2:
            continue
        cm = _map(_cells(rows[0]))
        if "name" not in cm or not ({"position", "height", "class_label"} & cm.keys()):
            continue
        out = []
        for r in rows[1:]:
            c = _cells(r)
            if len(c) <= cm["name"]:
                continue

            def g(k: str, c: list[str] = c, cm: dict = cm) -> str | None:
                i = cm.get(k)
                return (txt(c[i]) or None) if i is not None and i < len(c) else None

            prof = re.search(r'href="([^"]+)"', c[cm["name"]])
            out.append({
                "name": g("name"), "jersey": g("jersey"), "position": g("position"),
                "height_in": height_in(g("height")), "class_label": g("class_label"),
                "hometown": g("hometown"), "previous_school": g("previous_school"),
                "profile_url": urljoin(url, prof.group(1)) if prof else None,
            })  # fmt: skip
        if len(out) > len(best):
            best = out
    return ParsedRoster(platform, clean(best), season_label(page, url))
