"""Quote-freshness classification for published Kalshi markets (read-only, no pricing).

SIFT must never present a stale, settled or empty-book quote as a live market view. The raw
bid/ask stay published (they are evidence, with ``captured_at``); the derived
``market_probability`` is kept ONLY for a live, fresh, two-sided book.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

STALE_AFTER_MINUTES = 45.0  # capture cadence is 15 min; three missed ticks = not "live"


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def two_sided(yes_bid: Any, yes_ask: Any) -> bool:
    b, a = _num(yes_bid), _num(yes_ask)
    return b is not None and a is not None and b > 0.0 and a < 1.0 and a >= b


def classify_quote(
    market_status: str,
    yes_bid: Any,
    yes_ask: Any,
    captured_at: datetime | None,
    now: datetime,
    stale_after_minutes: float = STALE_AFTER_MINUTES,
) -> dict[str, Any]:
    """State is one of SETTLED | CLOSED | UNOPENED | UNKNOWN_STATUS | NO_CAPTURE_TIME |
    EMPTY_BOOK | STALE | LIVE. ``live_probability_ok`` gates ``market_probability``."""
    age = None if captured_at is None else (now - captured_at).total_seconds() / 60.0
    if market_status in ("SETTLED", "CLOSED", "UNOPENED"):
        state = market_status
    elif market_status != "OPEN":
        state = "UNKNOWN_STATUS"
    elif age is None:
        state = "NO_CAPTURE_TIME"
    elif not two_sided(yes_bid, yes_ask):
        state = "EMPTY_BOOK"
    elif age > stale_after_minutes:
        state = "STALE"
    else:
        state = "LIVE"
    return {
        "state": state,
        "age_minutes": None if age is None else round(age, 1),
        "stale_after_minutes": stale_after_minutes,
        "live_probability_ok": state == "LIVE",
        "captured_at": None if captured_at is None else captured_at.isoformat(),
        "note": "last captured quote, not a current price"
        if state in ("STALE", "SETTLED", "CLOSED", "EMPTY_BOOK")
        else None,
    }
