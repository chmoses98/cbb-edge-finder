"""Downstream model-vs-market comparison (Kalshi / free lines). NEVER feeds PURE.

Flow: PURE projection (frozen, archived before tip) -> probability distribution
(Normal(margin, margin_sd), Normal(total, total_sd)) -> Kalshi contract mapping ->
market implied probability -> disagreement. The projection is read from the archive and
is never recomputed here, so a market change cannot alter it.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from scipy.stats import norm

from cbb_edge.kalshi.taxonomy import yes_mid_cents

STRIKE = re.compile(r"(\d+(?:\.\d+)?)")


def model_probability(
    proj: dict[str, Any], family: str, market: dict[str, Any], home_is_yes_team: bool | None
) -> float | None:
    """Model probability that a Kalshi contract settles YES.

    GAME_WINNER: P(yes-team wins). SPREAD: P(yes-team margin > strike).
    TOTAL: P(total > strike). Returns None when the contract cannot be mapped exactly.
    """
    p = proj["projection"]
    m, sm = p["margin"], p.get("margin_sd") or 11.0
    t, st = p["total"], p.get("total_sd") or 17.0
    strike = market.get("floor_strike")
    if family == "GAME_WINNER" and home_is_yes_team is not None:
        ph = float(norm.cdf(m / sm))
        return ph if home_is_yes_team else 1 - ph
    if family == "SPREAD" and home_is_yes_team is not None and strike is not None:
        mm = m if home_is_yes_team else -m
        return float(1 - norm.cdf((float(strike) - mm) / sm))
    if family == "TOTAL" and strike is not None:
        return float(1 - norm.cdf((float(strike) - t) / st))
    return None


def disagreement(
    proj: dict[str, Any], family: str, market: dict[str, Any], home_is_yes_team: bool | None
) -> dict[str, Any] | None:
    mp = model_probability(proj, family, market, home_is_yes_team)
    mid = yes_mid_cents(market)
    if mp is None or mid is None:
        return None
    return {
        "ticker": market.get("ticker"),
        "family": family,
        "model_prob": mp,
        "market_prob": mid / 100.0,
        "diff": mp - mid / 100.0,
        "projection_as_of": proj.get("prospective", {}).get("as_of"),
        "model_version": proj["model"]["version"],
        "log_odds_diff": float(np.log(mp / (1 - mp)) - np.log((mid / 100) / (1 - mid / 100)))
        if 0 < mid < 100 and 0 < mp < 1
        else None,
    }
