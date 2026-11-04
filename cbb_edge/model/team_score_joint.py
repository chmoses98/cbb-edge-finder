"""Frozen-as-of joint home/away score uncertainty challenger (SHADOW ONLY).

Calibrate marginal team scoring variances and home/away residual covariance from
independent, fully settled games. A score mean alone is not a cover probability.
All inputs must be pretip forecasts paired with scores known before training cutoff.
Even a mathematically valid probability is NOT authorized until prospective calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

VERSION = "cbb-joint-team-scores-0.1.0-shadow"


def _utc(x: Any) -> pd.Timestamp:
    t = pd.Timestamp(x)
    if t.tzinfo is None:
        raise ValueError("timestamps must be timezone aware")
    return t.tz_convert("UTC")


def _number(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        n = float(x)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


@dataclass(frozen=True)
class JointScoreFit:
    model_version: str
    as_of: str
    games: int
    sd_home: float
    sd_away: float
    cov_home_away: float
    status: str = "SHADOW_UNVALIDATED"


def fit_joint_scores(
    records: list[dict[str, Any]],
    *,
    as_of: Any,
    frozen_model_version: str,
    min_games: int = 100,
) -> JointScoreFit | None:
    """Fit residual covariance from unique games with verified completed final scores."""
    cut = _utc(as_of)
    unique: dict[str, tuple[pd.Timestamp, tuple[float, float]]] = {}
    for r in records:
        if r.get("verified") is not True or r.get("model_version") != frozen_model_version:
            continue
        gid = r.get("game_id")
        if gid is None:
            continue
        stamps = (r.get("prediction_as_of"), r.get("tip"), r.get("outcome_available_at"))
        if any(s is None for s in stamps):
            continue
        pred_at, tip, known = (_utc(s) for s in stamps)
        if not (pred_at < tip and pred_at <= cut and tip < known < cut):
            continue
        vals = [
            _number(r.get(k))
            for k in ("predicted_home", "predicted_away", "actual_home", "actual_away")
        ]
        if any(v is None for v in vals):
            continue
        h, a, ah, aa = (float(v) for v in vals if v is not None)
        residual = (ah - h, aa - a)
        key = str(gid)
        # One independent game per record. Prefer its latest valid pretip forecast,
        # not multiple lines/contracts or repeated archive snapshots of the same game.
        if key not in unique or pred_at > unique[key][0]:
            unique[key] = (pred_at, residual)
    if len(unique) < min_games or min_games < 30:
        return None
    x = np.asarray([item[1] for item in unique.values()], dtype=float)
    if len(x) < 2:
        return None
    cov = np.cov(x, rowvar=False, ddof=1)
    if not np.isfinite(cov).all() or cov.shape != (2, 2):
        return None
    # Fixed 5% diagonal shrinkage limits unstable covariance; learned from the
    # historical sample, not tuned to current games or market outcomes.
    var_h, var_a = float(cov[0, 0]), float(cov[1, 1])
    if var_h <= 1 or var_a <= 1:
        return None
    cross = float(cov[0, 1]) * 0.95
    if cross * cross >= var_h * var_a:
        return None
    return JointScoreFit(
        model_version=frozen_model_version,
        as_of=cut.isoformat(),
        games=len(unique),
        sd_home=math.sqrt(var_h),
        sd_away=math.sqrt(var_a),
        cov_home_away=cross,
    )


def shadow_probability(
    fit: JointScoreFit,
    projection: dict[str, Any],
    *,
    target: str,
    line: float,
    prediction_as_of: Any,
    tip: Any,
) -> dict[str, Any]:
    """P(points strictly > line), normal+integer continuity approximation.

    No prices, fees, bet-to thresholds or execution. This is a challenger only.
    """
    at, start = _utc(prediction_as_of), _utc(tip)
    if not (_utc(fit.as_of) <= at < start):
        raise ValueError("fit/forecast chronology invalid or after tip")
    if target not in ("home_total", "away_total", "game_total", "home_margin"):
        raise ValueError("unsupported score target")
    h, a = _number(projection.get("home_score")), _number(projection.get("away_score"))
    if h is None or a is None or not math.isfinite(line):
        return {
            "status": "UNAVAILABLE",
            "model_probability": None,
            "reason": "missing_score_mean_or_valid_line",
            "authorized_bet": False,
        }
    vh, va = fit.sd_home**2, fit.sd_away**2
    mu, variance = {
        "home_total": (h, vh),
        "away_total": (a, va),
        "game_total": (h + a, vh + va + 2 * fit.cov_home_away),
        "home_margin": (h - a, vh + va - 2 * fit.cov_home_away),
    }[target]
    if variance <= 0:
        raise ValueError("invalid fitted covariance")
    # Home/away scores, game total AND margin are integer, so '> 78.5' and
    # '> 78' both require at least 79; a normal approximation uses 78.5.
    cutoff = math.floor(line) + 0.5
    probability = 1 - NormalDist(mu, math.sqrt(variance)).cdf(cutoff)
    return {
        "status": "SHADOW_UNVALIDATED",
        "model_probability": float(max(0, min(1, probability))),
        "model_version": VERSION,
        "champion_version": fit.model_version,
        "as_of": at.isoformat(),
        "training_cutoff": fit.as_of,
        "independent_training_games": fit.games,
        "target": target,
        "line": line,
        "mean": mu,
        "sd": math.sqrt(variance),
        "method": "joint_normal_fitted_covariance_continuity_corrected",
        "authorized_bet": False,
        "reason": "no_prospective_validation",
    }
