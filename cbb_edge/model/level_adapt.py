"""Walk-forward scoring-level and uncertainty adaptation of a FROZEN PURE projection (SHADOW ONLY).

Evidence (research/reports/WAVE12_SCORING_LEVEL.md): in the first nine days of 2026-27 the frozen
pure-0.5.0 total is ~3 points too low (about 40% possessions, 60% points per possession) while the
margin is unbiased; the margin standard deviation is too narrow in lopsided games. The challenger
changes ONLY those two things and nothing else:

* ``level``: add ``lambda * projected_possessions`` to the game total (split evenly between the two
  teams, so the margin mean is untouched). ``lambda`` is the possession-weighted mean total residual
  of games already FINISHED at the projection's ``as_of``, shrunk toward 0 with the weight of
  ``k_level`` games.
* ``sd``: multiply ``total_sd`` and ``margin_sd`` by shrunk RMS standardised residuals of those same
  games (margin by three |projected margin| bins, each shrunk toward the pooled scale).

Everything is estimated from games whose result was available before ``as_of`` - the model is never
"frozen before" games it was fitted on; it is a rule applied pregame with a growing information set.
No market price, line or quote is an input (the PURE/market separation is untouched). The frozen
archive records are never edited.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

VERSION = "wf-level-0.5.0-v1"
BASE_VERSION = "pure-0.5.0"


@dataclass(frozen=True)
class Params:
    """Fixed a priori (research/hypotheses/WAVE12.md section 3); never tuned on evaluation games."""

    k_level: float = 30.0  # prior weight, in games, on "the frozen level is right"
    k_sd: float = 40.0  # prior weight, in games, on "the frozen SD is right"
    min_games: int = 30  # fewer finished games than this: no adaptation is defined (explicit gap)
    margin_bins: tuple[float, float] = (6.0, 14.0)  # |projected margin| bin edges (points)
    level: bool = True
    sd: bool = True


def _bin(abs_margin: float, edges: tuple[float, float]) -> int:
    return 0 if abs_margin < edges[0] else 1 if abs_margin < edges[1] else 2


def fit(history: Sequence[dict[str, float]], params: Params = Params()) -> dict[str, Any] | None:
    """``history``: one dict per FINISHED game with the frozen projection's ``poss``, ``margin``,
    ``margin_sd``, ``total``, ``total_sd`` and the realised ``margin_err`` / ``total_err``
    (actual - projected). Returns the adaptation state, or None below ``min_games``."""
    n = len(history)
    if n < params.min_games:
        return None
    sum_poss = sum(h["poss"] for h in history)
    ref = sum_poss / n
    lam = 0.0
    if params.level:
        lam = sum(h["total_err"] for h in history) / (sum_poss + params.k_level * ref)
    out: dict[str, Any] = {
        "n_games": n,
        "lambda_per_poss": lam,
        "total_sd_scale": 1.0,
        "margin_sd_scale": [1.0, 1.0, 1.0],
        "params": params.__dict__,
    }
    if params.sd:
        zt = [((h["total_err"] - lam * h["poss"]) / h["total_sd"]) ** 2 for h in history]
        out["total_sd_scale"] = math.sqrt((sum(zt) + params.k_sd) / (n + params.k_sd))
        zm = [(h["margin_err"] / h["margin_sd"]) ** 2 for h in history]
        pooled = (sum(zm) + params.k_sd) / (n + params.k_sd)
        scales = []
        for b in range(3):
            zb = [z for z, h in zip(zm, history, strict=True)
                  if _bin(abs(h["margin"]), params.margin_bins) == b]  # fmt: skip
            scales.append(math.sqrt((sum(zb) + params.k_sd * pooled) / (len(zb) + params.k_sd)))
        out["margin_sd_scale"] = scales
        out["margin_pooled_scale"] = math.sqrt(pooled)
    return out


def adapt(proj: dict[str, float], state: dict[str, Any]) -> dict[str, float]:
    """Adapted score distribution for one game (same keys the contract pricer reads)."""
    p = Params(**{**state["params"], "margin_bins": tuple(state["params"]["margin_bins"])})
    add = state["lambda_per_poss"] * proj["poss"]
    scale_m = state["margin_sd_scale"][_bin(abs(proj["margin"]), p.margin_bins)]
    margin_sd = proj["margin_sd"] * scale_m
    return {
        "home_score": proj["home_score"] + add / 2.0,
        "away_score": proj["away_score"] + add / 2.0,
        "total": proj["total"] + add,
        "margin": proj["margin"],
        "margin_sd": margin_sd,
        "total_sd": proj["total_sd"] * state["total_sd_scale"],
        "poss": proj["poss"],
    }


def win_prob(adapted: dict[str, float]) -> float:
    return 0.5 * (1.0 + math.erf(adapted["margin"] / adapted["margin_sd"] / math.sqrt(2.0)))


def walk_forward(
    games: Sequence[dict[str, Any]],
    finals: dict[int, dict[str, Any]],
    params: Params = Params(),
) -> dict[int, dict[str, Any] | None]:
    """For each game, the adaptation state built ONLY from other games whose final was recorded
    (``finals[gid]['available_at']``) at or before this game's projection ``as_of``.

    ``games``: the frozen projections of ONE base version (``cbb_edge.research.wave1.load_frozen``
    values). Returns {game_id: state or None}; None means fewer than ``min_games`` were finished."""
    hist: list[tuple[Any, dict[str, float]]] = []
    for g in games:
        f = finals.get(g["game_id"])
        if f is None or f.get("available_at") is None:
            continue
        hist.append(
            (
                f["available_at"],
                {
                    "poss": g["poss"], "margin": g["margin"], "margin_sd": g["margin_sd"],
                    "total": g["total"], "total_sd": g["total_sd"],
                    "margin_err": (f["home"] - f["away"]) - g["margin"],
                    "total_err": (f["home"] + f["away"]) - g["total"],
                },
            )
        )  # fmt: skip
    hist.sort(key=lambda t: t[0])
    out: dict[int, dict[str, Any] | None] = {}
    for g in games:
        known = [h for at, h in hist if at <= g["as_of"]]
        out[g["game_id"]] = fit(known, params)
    return out
