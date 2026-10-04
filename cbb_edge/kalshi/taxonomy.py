"""Kalshi market-family taxonomy for men's college basketball.

Discovery is rule-based on series metadata rather than a hard-coded ticker list, so
new CBB series are picked up automatically. Women's basketball series are excluded.
Rules are deliberately transparent; every snapshot stores the raw series/market
payload so families can be re-derived later if the rules change.
"""

from __future__ import annotations

import re
from typing import Any

# Men's college basketball series observed on Kalshi (free-source probe, 2026-10-04):
# KXNCAAMB* (games, spreads, totals, halves, conferences, awards, rankings), KXMARMAD*
# and KXMAKEMARMAD (tournament futures), legacy KXNCAAB* (GAME/ACC/SEC/IVY).
# Look-alikes that are NOT men's basketball: KXNCAABB* / KXNCAABASEBALL /
# KXTEAMSINNCAABBWS (college baseball), KXNCAAWB* / KXWMARMAD* (women's basketball).
# KXNCAAM<conf> (e.g. KXNCAAMACC, KXNCAAMSEC) are legacy men's basketball conference
# series; other KXNCAAM<sport> series are excluded below and by the title sport filter.
CBB_TICKER = re.compile(
    r"^KX(NCAAMB|MARMAD|MAKEMARMAD|NCAAB(?!B|ASEBALL)|NCAAM(?!LAX|SOCCER|WRESTLING|HOCKEY))",
    re.I,
)
NOT_CBB_TICKER = re.compile(
    r"^KX(NCAABB|NCAABASEBALL|NCAAWB|WMARMAD|TEAMSINNCAABB|NCAAMLAX|NCAAMSOCCER|"
    r"NCAAMWRESTLING)",
    re.I,
)
# Word rules require "basketball"-specific phrasing ("NCAA Men's" alone also matches
# wrestling, lacrosse, soccer ...).
CBB_WORDS = re.compile(
    r"(men'?s college basketball|college basketball|march madness|men'?s basketball|"
    r"ncaab\b)",
    re.I,
)
COLLEGE = re.compile(r"(college|ncaa|march madness|ncaab)", re.I)
WOMEN = re.compile(
    r"(women|wcbb|ncaaw|wncaa|ncaawb|baseball|lacrosse|soccer|wrestling|hockey|football|"
    r"volleyball|softball)",
    re.I,
)

FAMILIES = (
    "GAME_WINNER",
    "SPREAD",
    "TOTAL",
    "TEAM_TOTAL",
    "HALF",
    "PLAYER_PROP",
    "FUTURES_CHAMPION",
    "FUTURES_FINAL_FOUR",
    "FUTURES_CONFERENCE",
    "FUTURES_SEED",
    "FUTURES_OTHER",
    "OTHER",
)


def _text(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def is_cbb_series(series: dict[str, Any]) -> bool:
    ticker = str(series.get("ticker", ""))
    blob = _text(
        ticker, series.get("title"), " ".join(series.get("tags") or []), series.get("category")
    )
    if NOT_CBB_TICKER.search(ticker) or WOMEN.search(blob):
        return False
    if CBB_TICKER.search(ticker):
        return True
    # word rules: basketball AND a college marker (excludes USA Basketball, NBA, ...)
    return bool(CBB_WORDS.search(blob) and COLLEGE.search(blob))


def classify_market(series: dict[str, Any], market: dict[str, Any]) -> str:
    st = str(series.get("ticker", "")).upper()
    blob = _text(
        st,
        series.get("title"),
        market.get("title"),
        market.get("subtitle"),
        market.get("yes_sub_title"),
    ).lower()
    if re.search(r"(1h|2h|first half|second half|1st half|2nd half|halftime)", blob):
        return "HALF"
    # 1) series ticker is the most reliable signal
    if "SPREAD" in st:
        return "SPREAD"
    if "TEAMTOTAL" in st:
        return "TEAM_TOTAL"
    if "TOTAL" in st:
        return "TOTAL"
    if "GAME" in st:
        return "GAME_WINNER"
    # 2) text rules
    if re.search(r"(rebounds|assists|three-pointers|threes|player|\bpts\b)", blob):
        return "PLAYER_PROP"
    if re.search(r"\bwins? by\b|spread", blob):
        return "SPREAD"
    if re.search(r"team total", blob):
        return "TEAM_TOTAL"
    if re.search(r"total points|over/under|combined", blob):
        return "TOTAL"
    if re.search(r"final four", blob):
        return "FUTURES_FINAL_FOUR"
    if re.search(r"\bseed\b", blob):
        return "FUTURES_SEED"
    if re.search(r"conference|\bconf\b", blob):
        return "FUTURES_CONFERENCE"
    if "MARMAD" in st or re.search(r"champion|national title|win the ncaa", blob):
        return "FUTURES_CHAMPION"
    if re.search(r"(make the|tournament|bracket|ranked|ap poll)", blob):
        return "FUTURES_OTHER"
    if re.search(r"\bwinner\b| vs\.? | at ", blob):
        return "GAME_WINNER"
    return "OTHER"


def yes_mid_cents(market: dict[str, Any]) -> float | None:
    """Mid price in cents (0-100) from top-of-book, tolerant of both API price styles."""

    def _c(key: str) -> float | None:
        v = market.get(key)
        if v is None:
            d = market.get(f"{key}_dollars")
            return None if d is None or d == "" else float(d) * 100.0
        return float(v)

    bid, ask = _c("yes_bid"), _c("yes_ask")
    if bid is not None and ask is not None and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    last = _c("last_price")
    return last if last else None
