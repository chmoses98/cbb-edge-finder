"""Official school athletics roster pages: the roster-truth fallback (Wave 6).

Only for teams whose structured sources are stale or in conflict, and only for domains
on the explicit allowlist below (also ``cost_policy.SCHOOL_HOSTS``). Requests go through
the network chokepoint (``school_athletics``: cached, >= 5 s between requests).

Parser: SIDEARM "nextgen" roster pages (``s-person-card`` list view), the most common
D-I athletics platform. Fields: name, jersey, position, academic year (class), height,
last school. The page's season label ("2026-27 Men's Basketball Roster") is the
source-native season. Names are matched to ESPN ids only by exact normalized name
within the same team (``truth.match_official``).
"""

from __future__ import annotations

import html as _html
import re
from typing import Any

# ESPN team id -> roster URL. Verified by the source probe (scripts/data/probe_rosters.py).
# Extend only with a team's official athletics domain, and add the host to
# cost_policy.SCHOOL_HOSTS in the same change.
SCHOOL_ROSTERS: dict[int, str] = {
    150: "https://goduke.com/sports/mens-basketball/roster",
    103: "https://bceagles.com/sports/mens-basketball/roster",
    120: "https://umterps.com/sports/mens-basketball/roster",
}

_SPLIT = 'class="s-person-card s-person-card--'


def _cards(page: str) -> list[str]:
    """List-view person cards, each bounded by the next person card of any view."""
    return [c[len("list") :] for c in page.split(_SPLIT)[1:] if c.startswith("list")]


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _field(card: str, label: str) -> str | None:
    m = re.search(
        r'<span[^>]*class="sr-only"[^>]*>\s*' + re.escape(label) + r"\s*</span>(.*?)</span>",
        card,
        flags=re.S,
    )
    return _txt(m.group(1)) or None if m else None


def _height_in(h: str | None) -> float | None:
    if not h:
        return None
    m = re.match(r"(\d+)\s*'\s*(\d+)", h.replace("’", "'"))
    return float(int(m.group(1)) * 12 + int(m.group(2))) if m else None


def season_label(page: str) -> int | None:
    """End year of the page's roster season ("2026-27 ... Roster" -> 2027)."""
    m = re.search(r"(20\d\d)-(\d\d)\s+Men'?s Basketball Roster", _html.unescape(page))
    if not m:
        m = re.search(r"(20\d\d)-(\d\d)[^<]{0,40}[Rr]oster", _html.unescape(page))
    return int(m.group(1)) + 1 if m else None


def parse_sidearm(page: str) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for c in _cards(page):
        name = re.search(r"<h3>(.*?)</h3>", c, flags=re.S)
        if not name:
            continue
        nm = _txt(name.group(1))
        jersey = _field(c, "Jersey Number")
        key = (nm, jersey)
        if key in seen:
            continue
        seen.add(key)
        pos, cls = _field(c, "Position"), _field(c, "Academic Year")
        if pos is None and cls is None:  # staff cards carry neither
            continue
        out.append(
            {
                "name": nm,
                "jersey": jersey,
                "position": pos,
                "class_label": cls,
                "height_in": _height_in(_field(c, "Height")),
                "previous_school": _field(c, "Last School") or _field(c, "Previous School"),
            }
        )
    return out
