"""Reusable official-roster parsers by platform (Wave 7).

``parse_roster`` tries the detected platform's parser first, then the others, and the
header-driven table parser last; the first one that yields players wins and records
which parser read the page."""

from __future__ import annotations

from cbb_edge.rosters.parsers import sidearm, table, wmt
from cbb_edge.rosters.parsers.base import ParsedRoster

PARSERS = {
    "sidearm": sidearm.parse,
    "wmt": wmt.parse,
    "presto": lambda p, u: table.parse(p, u, "presto"),
    "table": table.parse,
}


def parse_roster(page: str, platform: str, url: str, season: int) -> ParsedRoster:
    order = [platform] if platform in PARSERS else []
    order += [k for k in PARSERS if k not in order]
    best = ParsedRoster(platform)
    for k in order:
        try:
            r = PARSERS[k](page, url)
        except Exception:  # noqa: BLE001  a parser failure is a non-match
            continue
        if len(r.players) > len(best.players):
            best = r
        if len(r.players) >= 8:
            return r
    return best
