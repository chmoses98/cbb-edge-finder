"""Research-only projected scoring target means from immutable CBB pretip forecasts.

A projected point total is NOT a market outcome probability. In particular, the frozen
full-game model has no marginal team-score SD/covariance, and no half-specific distribution.
These means can be displayed and evaluated as forecasts, but cannot authorize wagers.
"""

from __future__ import annotations

import math
from typing import Any


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def projected_target_mean(
    semantics: dict[str, Any], projection: dict[str, Any] | None
) -> dict[str, Any]:
    """Projected *mean*, never a probability, for a precisely mapped team total."""
    out: dict[str, Any] = {
        "value": None, "unit": "points", "basis": None, "status": "UNAVAILABLE",
        "reason": None, "probability_available": False,
    }
    if semantics.get("status") != "parsed":
        out["reason"] = f"contract_parse_{semantics.get('status', 'missing')}"
        return out
    if semantics.get("market_type") != "TEAM_TOTAL":
        out["reason"] = "not_team_total_market"
        return out
    if semantics.get("period") != "FULL":
        out["reason"] = "no_period_scoring_mean_in_frozen_model"
        return out
    if projection is None:
        out["reason"] = "no_pretip_frozen_projection_for_this_game"
        return out
    side = semantics.get("subject_side")
    if side not in ("home", "away"):
        out["reason"] = "team_side_not_resolved"
        return out
    mean = _finite(projection.get(f"{side}_score"))
    if mean is None:
        out["reason"] = "missing_frozen_team_score_mean"
        return out
    # Reject internally contradictory records instead of silently editing archived values.
    other = _finite(projection.get("away_score" if side == "home" else "home_score"))
    total = _finite(projection.get("total"))
    if other is not None and total is not None and abs((mean + other) - total) > 0.1:
        out["reason"] = "inconsistent_frozen_team_scores"
        return out
    out.update({
        "value": round(mean, 2),
        "basis": "frozen_pretip_projected_team_score",
        "status": "MEAN_ONLY",
        "reason": "team_score_distribution_not_calibrated",
    })
    return out
