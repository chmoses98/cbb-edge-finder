"""Hierarchical, team-game-number-aware scoring-level adaptation of a FROZEN projection (SHADOW ONLY).

Protocol: research/hypotheses/WAVE13.md (fixed before any result). Compared with Wave 12
(``level_adapt``: one pooled shift) this lets the level differ by team game number but only through a
strongly shrunk hierarchy, so a thinly observed group cannot drive an aggressive separate correction:

    r_j = lambda0 + delta_g(j) + e_j,   lambda0 ~ N(0, s^2/n0),   delta_g ~ N(0, s^2/n_tau)

with ``r = (actual_total - projected_total) / projected_possessions`` and groups from the team game
number known pregame (G1: min games seen 0, G2: 1, G3: >= 2). Because both prior variances scale with the
residual variance ``s^2``, the posterior mean is the ridge solution ``(X'X + diag(n0, n_tau x3))^-1 X'r``
and does not depend on ``s^2``. No SD rescale, no margin change, no market input; same as-of rule and
minimum history as Wave 12 (a game's state uses only finals first visible at or before its ``as_of``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

VERSION = "wf13-hier-level-0.5.0-v1"
N_GROUPS = 3


@dataclass(frozen=True)
class Params:
    n0: float = 30.0  # pseudo-games on "pooled level = 0" (Wave 12 k_level)
    n_tau: float = 100.0  # pseudo-games on "group deviation = 0"
    min_games: int = 30
    hierarchical: bool = True  # False = independent per-group corrections (ablation only)


def group_of(min_games_seen: int | float | None) -> int:
    """0, 1, 2 for team game 1, 2, 3+ (min of the two teams' games already seen)."""
    m = 0 if min_games_seen is None else int(min_games_seen)
    return min(max(m, 0), N_GROUPS - 1)


def fit(history: Sequence[dict[str, float]], params: Params | None = None) -> dict[str, Any] | None:
    """``history``: finished games with ``poss``, ``total_err`` (actual - projected) and ``group``."""
    params = params or Params()
    n = len(history)
    if n < params.min_games:
        return None
    r = np.array([h["total_err"] / h["poss"] for h in history], dtype=float)
    grp = np.array([int(h["group"]) for h in history])
    if params.hierarchical:
        X = np.zeros((n, 1 + N_GROUPS))
        X[:, 0] = 1.0
        X[np.arange(n), 1 + grp] = 1.0
        prior = np.array([params.n0] + [params.n_tau] * N_GROUPS)
    else:
        X = np.zeros((n, N_GROUPS))
        X[np.arange(n), grp] = 1.0
        prior = np.full(N_GROUPS, params.n0)
    theta = np.linalg.solve(X.T @ X + np.diag(prior), X.T @ r)
    if params.hierarchical:
        lam = [float(theta[0] + theta[1 + g]) for g in range(N_GROUPS)]
        pooled, dev = float(theta[0]), [float(theta[1 + g]) for g in range(N_GROUPS)]
    else:
        lam = [float(t) for t in theta]
        pooled, dev = None, None
    counts = [int((grp == g).sum()) for g in range(N_GROUPS)]
    return {
        "n_games": n, "group_counts": counts, "lambda_per_poss_by_group": lam,
        "pooled": pooled, "group_deviation": dev,
        "raw_group_mean_per_poss": [float(r[grp == g].mean()) if counts[g] else None for g in range(N_GROUPS)],
        "params": params.__dict__,
    }  # fmt: skip


def adapt(proj: dict[str, float], state: dict[str, Any], group: int) -> dict[str, float]:
    add = state["lambda_per_poss_by_group"][group] * proj["poss"]
    return {
        "home_score": proj["home_score"] + add / 2.0,
        "away_score": proj["away_score"] + add / 2.0,
        "total": proj["total"] + add,
        "margin": proj["margin"],
        "margin_sd": proj["margin_sd"],  # untouched: no SD rescale in Wave 13
        "total_sd": proj["total_sd"],
        "poss": proj["poss"],
    }


def walk_forward(
    games: Sequence[dict[str, Any]],
    finals: dict[int, dict[str, Any]],
    params: Params | None = None,
) -> dict[int, dict[str, Any] | None]:
    """Per game, the state built ONLY from games whose final was available at or before its ``as_of``.

    ``games``: frozen projections of ONE base version (``wave1.load_frozen`` values); ``finals`` must be
    in the PROJECTION's home/away frame (``wave13.load_finals_oriented``)."""
    params = params or Params()
    hist = []
    for g in games:
        f = finals.get(g["game_id"])
        if f is None or f.get("available_at") is None:
            continue
        hist.append(
            (
                f["available_at"],
                {
                    "poss": g["poss"], "total_err": (f["home"] + f["away"]) - g["total"],
                    "group": group_of(min(g["home_games_seen"] or 0, g["away_games_seen"] or 0)),
                },
            )
        )  # fmt: skip
    hist.sort(key=lambda t: t[0])
    out: dict[int, dict[str, Any] | None] = {}
    for g in games:
        out[g["game_id"]] = fit([h for at, h in hist if at <= g["as_of"]], params)
    return out
