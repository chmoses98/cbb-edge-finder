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
from datetime import date, datetime, timedelta
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
    return date(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))


def title_teams(title: str) -> tuple[str, str] | None:
    m = TITLE_RE.match(title or "")
    if not m:
        return None
    return m.group("a").strip(), m.group("b").strip()


def map_market(market: dict[str, Any], games: pd.DataFrame) -> tuple[int | None, str]:
    """Return (espn game_id, reason). ``games`` = silver games table."""
    ev = str(market.get("event_ticker", ""))
    d = event_date(ev)
    if d is None:
        return None, "unparsed_event_ticker"
    tt = title_teams(str(market.get("title", "")))
    if tt is None:
        return None, "unparsed_title"
    a = teams.resolve(tt[0], "kalshi")
    b = teams.resolve(tt[1], "kalshi")
    if a is None or b is None:
        return None, "unresolved_team"
    days = {d - timedelta(days=1), d, d + timedelta(days=1)}
    g = games[
        games["game_date_et"].isin(days)
        & (
            ((games["home_team_id"] == a) & (games["away_team_id"] == b))
            | ((games["home_team_id"] == b) & (games["away_team_id"] == a))
        )
    ]
    if len(g) == 1:
        return int(g["game_id"].iloc[0]), "ok"
    teams.log_unresolved(
        "game",
        ev,
        "kalshi",
        "ambiguous" if len(g) > 1 else "missing",
        teams=[a, b],
        date=str(d),
        at=datetime.now().isoformat(),
    )
    return None, "ambiguous_game" if len(g) > 1 else "no_game"
