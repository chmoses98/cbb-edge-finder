"""SIDEARM Sports roster pages (nextgen person cards, and the classic list/table)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from cbb_edge.rosters.parsers.base import ParsedRoster, clean, height_in, season_label, txt

_SPLIT = 'class="s-person-card s-person-card--'


def _field(card: str, label: str) -> str | None:
    m = re.search(r'<span[^>]*class="sr-only"[^>]*>\s*' + re.escape(label)
                  + r"\s*</span>(.*?)</span>", card, flags=re.S)  # fmt: skip
    return (txt(m.group(1)) or None) if m else None


def _nextgen(page: str, url: str) -> list[dict]:
    out = []
    for c in page.split(_SPLIT)[1:]:
        if not c.startswith("list"):
            continue
        c = c[len("list") :]
        nm = re.search(r"<h3[^>]*>(.*?)</h3>", c, flags=re.S)
        if not nm:
            continue
        pos, cls = _field(c, "Position"), _field(c, "Academic Year")
        if pos is None and cls is None:  # staff cards carry neither
            continue
        prof = re.search(r'href="([^"]*/roster/[^"]+)"', c)
        out.append({
            "name": txt(nm.group(1)), "jersey": _field(c, "Jersey Number"), "position": pos,
            "class_label": cls, "height_in": height_in(_field(c, "Height")),
            "hometown": _field(c, "Hometown"),
            "previous_school": _field(c, "Previous School") or _field(c, "Last School"),
            "profile_url": urljoin(url, prof.group(1)) if prof else None,
        })  # fmt: skip
    return out


def _classic(page: str, url: str) -> list[dict]:
    out = []
    for li in re.findall(r'<li[^>]*class="[^"]*sidearm-roster-player[^"]*"[^>]*>(.*?)</li>',
                         page, flags=re.S):  # fmt: skip
        nm = re.search(r'sidearm-roster-player-name[^>]*>.*?<a[^>]*>(.*?)</a>', li, flags=re.S) \
            or re.search(r"<h3[^>]*>(.*?)</h3>", li, flags=re.S)  # fmt: skip
        if not nm:
            continue

        def f(cls: str, li: str = li) -> str | None:
            m = re.search(r'class="[^"]*' + cls + r'[^"]*"[^>]*>(.*?)</', li, flags=re.S)
            return (txt(m.group(1)) or None) if m else None

        prof = re.search(r'href="([^"]*/roster/[^"]+)"', li)
        out.append({
            "name": txt(nm.group(1)), "jersey": f("sidearm-roster-player-jersey-number"),
            "position": f("sidearm-roster-player-position-long-short") or f("sidearm-roster-player-position"),
            "class_label": f("sidearm-roster-player-academic-year"),
            "height_in": height_in(f("sidearm-roster-player-height")),
            "hometown": f("sidearm-roster-player-hometown"),
            "previous_school": f("sidearm-roster-player-previous-school")
            or f("sidearm-roster-player-highschool"),
            "profile_url": urljoin(url, prof.group(1)) if prof else None,
        })  # fmt: skip
    return out


def parse(page: str, url: str) -> ParsedRoster:
    players = _nextgen(page, url) or _classic(page, url)
    return ParsedRoster("sidearm", clean(players), season_label(page))
