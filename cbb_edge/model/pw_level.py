"""Wave 14 challenger: prior-weight-proportional scoring-level correction of a FROZEN projection.

Protocol: research/hypotheses/WAVE14.md; immutable spec: research/wave14/spec.json (SHADOW, RESEARCH ONLY).

    adjusted_total = base_total + beta * pbar * projected_possessions

``pbar`` is the mean of the four prior weights the record itself exported in ``model_inputs``
(home/away x pace/efficiency, ``ridge_diagonal_approx``). ``beta`` is ONE walk-forward ridge slope on
games whose final was visible at the projection's ``as_of``, shrunk toward 0 with fixed pseudo-games.
The shift is split evenly between the teams: margin, margin SD, win probability are untouched.
Missing/invalid inputs fail closed (no adjustment is defined; the game is not eligible).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

VERSION = "pw-level-0.5.0-v1"
BASE_VERSION = "pure-0.5.0"
INPUTS_VERSION = "cbb-model-inputs-1"
BASIS = "ridge_diagonal_approx"
_BLOCKS = (("home", "pace_weighting"), ("away", "pace_weighting"),
           ("home", "efficiency_weighting"), ("away", "efficiency_weighting"))  # fmt: skip


@dataclass(frozen=True)
class Params:
    """Fixed a priori (spec.json); never tuned on any outcome."""

    k_beta: float = 30.0  # pseudo-games shrinking beta toward 0
    x_ref: float = 40.0  # reference regressor (pbar 0.6 x ~67 possessions), a constant, not fitted
    min_games: int = 30  # fewer finished games WITH valid inputs: no adjustment (explicit gap)


class InputsInvalid(ValueError):
    """Essential model_inputs absent or inconsistent: the game cannot be adjusted (fail closed)."""


def validate_inputs(mi: Any, *, as_of: Any, possessions: float) -> list[str]:
    """Reasons the record's ``model_inputs`` are unusable (empty list = usable). Point-in-time:
    ``info_cutoff_utc`` must not be after the record's ``as_of``."""
    if not isinstance(mi, dict):
        return ["model_inputs_absent"]
    why: list[str] = []
    if mi.get("version") != INPUTS_VERSION:
        why.append(f"inputs_version:{mi.get('version')}")
    for side, blk in _BLOCKS:
        w = ((mi.get(side) or {}).get(blk)) or {}
        pw, cw, ess, ps = (w.get(k) for k in ("prior_weight", "current_weight", "effective_sample", "prior_strength"))  # fmt: skip
        tag = f"{side}.{blk}"
        if w.get("basis") != BASIS:
            why.append(f"{tag}:basis")
        vals = (pw, cw, ess, ps)
        if any(
            not isinstance(v, int | float) or isinstance(v, bool) or not math.isfinite(v)
            for v in vals
        ):
            why.append(f"{tag}:missing_or_nonfinite")
            continue
        if not (0.0 <= pw <= 1.0):
            why.append(f"{tag}:prior_weight_out_of_bounds")
        if abs(pw + cw - 1.0) > 1e-6:
            why.append(f"{tag}:weights_do_not_sum_to_1")
        if ess <= 0 or abs(ps / ess - pw) > 1e-6:
            why.append(f"{tag}:prior_weight_inconsistent_with_ess")
    ep = ((mi.get("expected_possessions")) or {}).get("value")
    if not isinstance(ep, int | float) or not math.isfinite(ep) or abs(ep - possessions) > 1e-6 * max(1.0, possessions):  # fmt: skip
        why.append("possessions_mismatch")
    cut = mi.get("info_cutoff_utc")
    try:
        from datetime import datetime

        c = datetime.fromisoformat(str(cut).replace("Z", "+00:00"))
        if c > as_of:
            why.append("info_cutoff_after_as_of")
    except (TypeError, ValueError):
        why.append("info_cutoff_unparseable")
    return why


def pbar(mi: dict[str, Any]) -> float:
    """Mean of the four prior weights. Caller must have validated ``mi``."""
    return sum(float(mi[s][b]["prior_weight"]) for s, b in _BLOCKS) / 4.0


def fit(history: Sequence[dict[str, float]], params: Params | None = None) -> dict[str, Any] | None:
    """``history``: FINISHED games with ``x`` (= pbar * possessions) and ``total_err`` (actual -
    projected total). Ridge slope through the origin, shrunk by ``k_beta`` pseudo-games at ``x_ref``."""
    params = params or Params()
    n = len(history)
    if n < params.min_games:
        return None
    sxx = sum(h["x"] ** 2 for h in history)
    sxy = sum(h["x"] * h["total_err"] for h in history)
    beta = sxy / (sxx + params.k_beta * params.x_ref**2)
    return {"n_games": n, "beta": beta, "raw_beta": sxy / sxx if sxx > 0 else None, "params": params.__dict__}  # fmt: skip


def adapt(proj: dict[str, float], state: dict[str, Any], p_bar: float) -> dict[str, float]:
    """Adjusted score distribution; margin and its SD are unchanged by construction."""
    add = state["beta"] * p_bar * proj["poss"]
    return {
        "home_score": proj["home_score"] + add / 2.0,
        "away_score": proj["away_score"] + add / 2.0,
        "total": proj["total"] + add,
        "margin": proj["margin"],
        "margin_sd": proj["margin_sd"],
        "total_sd": proj["total_sd"],
        "poss": proj["poss"],
    }


def walk_forward(
    games: Sequence[dict[str, Any]],
    finals: dict[int, dict[str, Any]],
    params: Params | None = None,
) -> dict[int, dict[str, Any] | None]:
    """Per game, the state from ONLY games with valid inputs whose final was available at or before
    this game's ``as_of``. ``games``: frozen pure-0.5.0 projections carrying ``pbar`` (None = invalid
    inputs, excluded from both fitting and adjustment)."""
    params = params or Params()
    hist = []
    for g in games:
        f = finals.get(g["game_id"])
        if g.get("pbar") is None or f is None or f.get("available_at") is None:
            continue
        hist.append((f["available_at"], {"x": g["pbar"] * g["poss"], "total_err": (f["home"] + f["away"]) - g["total"]}))  # fmt: skip
    hist.sort(key=lambda t: t[0])
    return {g["game_id"]: fit([h for at, h in hist if at <= g["as_of"]], params) for g in games}
