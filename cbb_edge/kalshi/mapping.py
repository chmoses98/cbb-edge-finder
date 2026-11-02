"""Map Kalshi game-level markets to canonical games — exact keys only, never fuzzy.

Kalshi game event tickers look like ``<SERIES>-<YY><MON><DD><CODES>`` (e.g.
``KXNCAAMBGAME-26NOV04DUKEUNC``) and titles like ``"Duke at North Carolina Winner?"``.

Resolution:
1. the event date comes from the ticker;
2. team names come from the title (``A at B`` / ``A vs B``) and are resolved with
   ``teams.resolve`` (exact, source-scoped; misses logged);
3. the canonical game is the unique scheduled game on that ET date (±1 day for late
   tips) between those two canonical teams.

Anything ambiguous returns ``None`` with a reason and is logged for manual mapping.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

from cbb_edge.data.ids import teams

MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}
EVENT_RE = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})([A-Z0-9]*)$")
TITLE_RE = re.compile(
    r"^\s*(?P<a>.+?)\s+(?:at|@|vs\.?|v\.?)\s+(?P<b>.+?)(?:\s+winner\??|\?|:.*)?\s*$", re.I
)


def event_date(event_ticker: str) -> date | None:
    m = EVENT_RE.match(event_ticker.upper())
    if not m or m.group(2) not in MONTHS:
        return None
    try:
        return date(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))
    except ValueError:
        return None


def title_teams(title: str) -> tuple[str, str] | None:
    m = TITLE_RE.match(title or "")
    if not m:
        return None
    return m.group("a").strip(), m.group("b").strip()


@lru_cache(maxsize=1)
def _codes() -> dict[str, frozenset[str]]:
    """Known, canonical team ticker codes only. No guessed or fuzzy abbreviations."""
    out: dict[str, frozenset[str]] = {}
    for row in teams._registry().to_dict("records"):
        codes = set()
        for field in ("kalshi_code", "espn_abbreviation"):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                code = re.sub(r"[^A-Z0-9]", "", value.upper())
                if code:
                    codes.add(code)
        out[str(row["team_id"])] = frozenset(codes)
    return out


def _unique_game(rows: pd.DataFrame) -> tuple[int | None, str]:
    if len(rows) == 1:
        return int(rows["game_id"].iloc[0]), "ok"
    return None, "ambiguous_game" if len(rows) > 1 else "no_game"


def map_market(
    market: dict[str, Any],
    games: pd.DataFrame,
    event: dict[str, Any] | None = None,
) -> tuple[int | None, str]:
    """Match an individual contract to exactly one scheduled game, otherwise fail closed.

    Event title identifies BOTH teams even when a contract title only names one side.
    Older captures without event metadata can match an exact *pair* of known ticker
    codes to the scheduled opponents on the event's date. No fuzzy joins or odds-based
    guesses. Returns the reason for every unmatched contract for coverage audits.
    """
    ev = str(market.get("event_ticker", ""))
    d = event_date(ev)
    if d is None:
        return None, "unparsed_event_ticker"
    days = {d - timedelta(days=1), d, d + timedelta(days=1)}
    nearby = games[games["game_date_et"].isin(days)]
    if nearby.empty:
        return None, "no_game_on_date"

    source = event or {}
    title_found = False
    for title in (
        source.get("title"),
        source.get("sub_title"),
        market.get("title"),
    ):
        pair = title_teams(str(title or ""))
        if pair is None:
            continue
        title_found = True
        a = teams.resolve(pair[0], "kalshi", log=False)
        b = teams.resolve(pair[1], "kalshi", log=False)
        if a is None or b is None or a == b:
            continue
        rows = nearby[
            ((nearby["home_team_id"] == a) & (nearby["away_team_id"] == b))
            | ((nearby["home_team_id"] == b) & (nearby["away_team_id"] == a))
        ]
        if len(rows):
            return _unique_game(rows)

    match = EVENT_RE.match(ev.upper())
    suffix = match.group(4) if match else ""
    if suffix:
        codes = _codes()
        matches: list[int] = []
        for row in nearby.to_dict("records"):
            home = codes.get(str(row["home_team_id"]), frozenset())
            away = codes.get(str(row["away_team_id"]), frozenset())
            if any(h + a == suffix or a + h == suffix for h in home for a in away):
                matches.append(int(row["game_id"]))
        if len(matches) == 1:
            return matches[0], "ok"
        if len(matches) > 1:
            return None, "ambiguous_game"

    reason = "unresolved_team" if title_found else "unresolved_event_identity"
    teams.log_unresolved("game", ev, "kalshi", reason, date=str(d))
    return None, reason
