"""SIDEARM Sports roster pages (nextgen person cards, and the classic list/table)."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from cbb_edge.rosters.parsers.base import ParsedRoster, clean, height_in, season_label, txt

_SPLIT = 'class="s-person-card s-person-card--'


def _field(card: str, label: str) -> str | None:
    m = re.search(r'<span[^>]*class="sr-only"[^>]*>\s*' + re.escape(label)
                  + r"\s*</span>(.*?)</span>", card, flags=re.S)  # fmt: skip
    v = (txt(m.group(1)) or None) if m else None
    return re.sub(r"^" + re.escape(label) + r"\s*:\s*", "", v, flags=re.I) or None if v else None


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


def _embedded(page: str, url: str) -> list[dict]:
    """Client-rendered SIDEARM pages embed the roster as JSON (``"players":[{...}]``,
    fields first_name / last_name / jersey_number / position_short / height_feet /
    height_inches / academic_year_short / hometown / previous_school). The largest such
    array with person names wins."""
    best: list[dict] = []
    dec = json.JSONDecoder()
    for m in re.finditer(r'"players"\s*:\s*\[', page):
        try:
            arr, _ = dec.raw_decode(page, m.end() - 1)
        except ValueError:
            continue
        if (
            isinstance(arr, list)
            and len(arr) > len(best)
            and all(isinstance(x, dict) and "last_name" in x for x in arr)
        ):
            best = arr
    out = []
    slug = re.search(r"/sports/([^/]+)/", url)
    for x in best:
        ft, inch = x.get("height_feet"), x.get("height_inches")
        prof = None
        if x.get("rp_id") and slug:
            nm = re.sub(r"[^a-z0-9]+", "-", f"{x.get('first_name', '')} {x.get('last_name', '')}"
                        .lower()).strip("-")  # fmt: skip
            prof = urljoin(url, f"/sports/{slug.group(1)}/roster/{nm}/{x['rp_id']}")
        out.append({
            "name": f"{x.get('first_name') or ''} {x.get('last_name') or ''}".strip(),
            "jersey": str(x.get("jersey_number")) if x.get("jersey_number") not in (None, "")
            else None,
            "position": x.get("position_short") or x.get("position_long"),
            "height_in": float(int(ft) * 12 + int(inch or 0)) if ft else None,
            "class_label": x.get("academic_year_short") or x.get("academic_year_long"),
            "hometown": x.get("hometown"), "previous_school": x.get("previous_school"),
            "profile_url": prof,
        })  # fmt: skip
    return out


def parse(page: str, url: str) -> ParsedRoster:
    players = _nextgen(page, url) or _classic(page, url) or _embedded(page, url)
    return ParsedRoster("sidearm", clean(players), season_label(page, url))
