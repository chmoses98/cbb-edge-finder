"""As-of first-half scoring MEAN baseline from verified independent period scores.

This is a shadow research forecast, not a 1H line probability. The model estimates
historical first-half shares of FINAL game points (including the normal OT mix) and
applies them to each team's frozen full-game projected score. It is deliberately
simple and requires separately validated distribution models before pricing markets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

VERSION = "cbb-first-half-share-0.1.0-shadow"


def _time(x: Any) -> pd.Timestamp:
    t = pd.Timestamp(x)
    if t.tzinfo is None:
        raise ValueError("timestamp must contain a timezone")
    return t.tz_convert("UTC")


def _points(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        n = float(x)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


@dataclass(frozen=True)
class HalfShareFit:
    version: str
    as_of: str
    games: int
    home_share: float
    away_share: float


def fit_half_share(
    period_scores: list[dict[str, Any]],
    *,
    as_of: Any,
    min_games: int = 75,
) -> HalfShareFit | None:
    """Fit on unique, verified, already archived finals known strictly before as_of."""
    at = _time(as_of)
    unique: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    conflicts: set[str] = set()
    for rec in period_scores:
        if not rec.get("verified") or rec.get("flags") or rec.get("superseded_by_conflict"):
            continue
        observed = rec.get("observed_at")
        gid = rec.get("espn_game_id")
        if observed is None or gid is None or _time(observed) >= at:
            continue
        h, a = rec.get("home_periods"), rec.get("away_periods")
        if (
            not isinstance(h, list)
            or not isinstance(a, list)
            or len(h) != len(a)
            or len(h) < 2
            or any(type(q) is not int or q < 0 for q in [*h, *a])
        ):
            continue
        if sum(h) != rec.get("final_home") or sum(a) != rec.get("final_away"):
            continue
        game = str(gid)
        scores = tuple(h), tuple(a)
        if game in unique and unique[game] != scores:
            conflicts.add(game)
        else:
            unique[game] = scores
    records = [scores for gid, scores in unique.items() if gid not in conflicts]
    if len(records) < min_games:
        return None
    home_total = sum(sum(h) for h, _ in records)
    away_total = sum(sum(a) for _, a in records)
    if home_total <= 0 or away_total <= 0:
        return None
    return HalfShareFit(
        version=VERSION,
        as_of=at.isoformat(),
        games=len(records),
        home_share=sum(h[0] for h, _ in records) / home_total,
        away_share=sum(a[0] for _, a in records) / away_total,
    )


def forecast_half_means(
    frozen: dict[str, Any],
    fit: HalfShareFit | None,
    *,
    forecast_as_of: Any,
    tip: Any,
) -> dict[str, Any]:
    """Produce only mean 1H scores, with explicit inability to price any line."""
    at, start = _time(forecast_as_of), _time(tip)
    if at >= start:
        raise ValueError("first-half forecast cannot be created after tip")
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "model_version": None if fit is None else fit.version,
        "model_as_of": None if fit is None else fit.as_of,
        "forecast_as_of": at.isoformat(),
        "trained_games": 0 if fit is None else fit.games,
        "home_points_mean": None,
        "away_points_mean": None,
        "total_mean": None,
        "home_margin_mean": None,
        "line_probability": None,
        "authorized_bet": False,
        "reason": "no_verified_asof_half_share_fit",
    }
    if fit is None:
        return result
    if _time(fit.as_of) > at:
        raise ValueError("period-share fit includes future information")
    home = _points(frozen.get("home_score"))
    away = _points(frozen.get("away_score"))
    if home is None or away is None:
        result["reason"] = "missing_frozen_full_game_team_points"
        return result
    hp, ap = home * fit.home_share, away * fit.away_share
    result.update(
        {
            "status": "EXPLORATORY_MEANS_ONLY",
            "home_points_mean": round(hp, 2),
            "away_points_mean": round(ap, 2),
            "total_mean": round(hp + ap, 2),
            "home_margin_mean": round(hp - ap, 2),
            "reason": "first_half_distribution_not_calibrated",
        }
    )
    return result
