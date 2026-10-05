"""Opponent-adjusted team ratings via prior-anchored ridge regression.

For a statistic observed once per team-game (offense perspective), e.g. points per 100
possessions, we fit simultaneously

    y_k = mu + a[t_k] + b[o_k] + eta * loc_k + e_k,      weight w_k

where ``t_k`` is the team on offense, ``o_k`` its opponent (on defense), ``loc_k`` is
+1 home / 0 neutral / -1 away for the offense, ``a`` = adjusted offense, ``b`` =
adjusted defense (positive = allows more), ``eta`` = home-court effect for this stat.
Opponent strength therefore lives INSIDE the fit: every team's offense is estimated
net of the defenses it faced, which are themselves estimated net of the offenses they
faced (a single linear system, not an after-the-fact SOS correction).

Shrinkage: the objective adds

    lam_a * sum_i (a_i - pa_i)^2 + lam_b * sum_j (b_j - pb_j)^2
    + lam_mu * (mu - p_mu)^2 + lam_eta * (eta - p_eta)^2

where ``pa``/``pb`` are pre-season priors (e.g. regressed last-season ratings, or a
roster-continuity prior). ``lam`` is measured in units of the observation weight (e.g.
possessions), so a team's estimate moves from its prior to its data as current-season
possessions accumulate: with n possessions the data weight is ~n/(n+lam). The prior
strength is a tuned hyperparameter (research: prior decay rate).

Pace uses the symmetric additive form ``tempo_g = mu + p[t] + p[o]`` (one parameter
per team, both teams contribute) with the same prior anchoring.

``adjust=False`` drops the opponent term (and solves offense/defense independently),
which yields the *raw rolling* benchmark B1 under identical shrinkage, so B1 vs B2
isolates the value of opponent adjustment.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp
import scipy.sparse.linalg as spla


@dataclass(frozen=True)
class StatSpec:
    name: str
    value_col: str
    weight_col: str | None
    scale: float = 1.0
    use_loc: bool = True
    pace: bool = False


# Offensive-perspective stats on team_games rows. Defense = same stat for the opponent.
STATS: dict[str, StatSpec] = {
    s.name: s
    for s in (
        StatSpec("eff", "ppp", "poss", scale=100.0),
        StatSpec("tempo", "tempo", None, pace=True, use_loc=False),
        StatSpec("efg", "efg", "fga", scale=100.0),
        StatSpec("to", "to_rate", "poss", scale=100.0),
        StatSpec("orb", "orb_rate", "orb_chances", scale=100.0),
        StatSpec("ftr", "ftr", "fga", scale=100.0),
        StatSpec("fg2", "fg2_pct", "fg2a", scale=100.0),
        StatSpec("fg3", "fg3_pct", "fg3a", scale=100.0),
        StatSpec("fg3a_rate", "fg3a_rate", "fga", scale=100.0),
    )
}


@dataclass
class Fit:
    mu: float
    eta: float
    off: np.ndarray  # a, length n_teams (or pace p for pace stats)
    deff: np.ndarray  # b, length n_teams (zeros for pace stats)
    n_obs: np.ndarray  # summed weight per team (offense side)
    raw: np.ndarray | None = None  # full solution vector (warm start for the next day)


def solve(
    t_idx: np.ndarray,
    o_idx: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    loc: np.ndarray,
    n_teams: int,
    prior_off: np.ndarray,
    prior_def: np.ndarray,
    lam: float,
    *,
    prior_mu: float,
    prior_eta: float,
    lam_mu: float = 1.0,
    lam_eta: float = 1.0,
    pace: bool = False,
    use_loc: bool = True,
    adjust: bool = True,
    x0: np.ndarray | None = None,
) -> Fit:
    """Solve the prior-anchored weighted ridge system (dense normal equations)."""
    n = n_teams
    if pace:
        k = 1 + n  # mu, p
    else:
        k = 2 + 2 * n  # mu, eta, a, b
    A = sp.csr_matrix((k, k))
    rhs = np.zeros(k)
    if len(y):
        if pace:
            cols = [np.zeros_like(t_idx), 1 + t_idx, 1 + o_idx]
            vals = [np.ones_like(y), np.ones_like(y), np.ones_like(y)]
            if not adjust:
                cols, vals = cols[:2], vals[:2]
        else:
            cols = [np.zeros_like(t_idx), np.ones_like(t_idx), 2 + t_idx, 2 + n + o_idx]
            vals = [
                np.ones_like(y),
                loc.astype(float) if use_loc else np.zeros_like(y),
                np.ones_like(y),
                np.ones_like(y),
            ]
        m = len(y)
        rows = np.concatenate([np.arange(m)] * len(cols))
        X = sp.csr_matrix((np.concatenate(vals), (rows, np.concatenate(cols))), shape=(m, k))
        Xw = X.multiply(w[:, None]).tocsr()
        A = (X.T @ Xw).tocsr()
        rhs += Xw.T @ y
    # priors (diagonal ridge terms anchored at the prior values)
    diag = np.zeros(k)
    diag[0] = lam_mu
    rhs[0] += lam_mu * prior_mu
    if pace:
        diag[1:] = lam
        rhs[1:] += lam * prior_off
    else:
        diag[1] = lam_eta if use_loc else 1e6
        rhs[1] += (lam_eta * prior_eta) if use_loc else 0.0
        diag[2 : 2 + n] = lam
        rhs[2 : 2 + n] += lam * prior_off
        diag[2 + n :] = lam
        rhs[2 + n :] += lam * prior_def
    A = (A + sp.diags(diag)).tocsr()
    if not adjust and not pace:
        # Raw benchmark: decouple offense and defense from each other (no opponent
        # adjustment). Each team's offense is its own weighted mean deviation.
        A = A.tolil()
        A[2 : 2 + n, 2 + n :] = 0.0
        A[2 + n :, 2 : 2 + n] = 0.0
        A = A.tocsr()
    if x0 is not None and len(x0) == k:
        # Warm-started conjugate gradient (A is SPD); converges in few iterations
        # because consecutive days differ by one day of games.
        sol, info = spla.cg(A, rhs, x0=x0, rtol=1e-10, atol=0.0, maxiter=2000)
        if info != 0:
            sol = spla.spsolve(A.tocsc(), rhs)
    else:
        sol = spla.spsolve(A.tocsc(), rhs)
    nobs = np.bincount(t_idx, weights=w, minlength=n) if len(y) else np.zeros(n)
    if pace:
        return Fit(sol[0], 0.0, sol[1:], np.zeros(n), nobs, sol)
    return Fit(sol[0], sol[1] if use_loc else 0.0, sol[2 : 2 + n], sol[2 + n :], nobs, sol)


def fit_stat(
    tg: pd.DataFrame,
    spec: StatSpec,
    team_index: dict[str, int],
    prior_off: np.ndarray,
    prior_def: np.ndarray,
    lam: float,
    prior_mu: float,
    prior_eta: float,
    *,
    adjust: bool = True,
    recency_tau_days: float | None = None,
    as_of: pd.Timestamp | None = None,
    x0: np.ndarray | None = None,
) -> Fit:
    """Fit one stat from team-game rows (already filtered to the information set)."""
    if "t_idx" in tg:
        t_idx, o_idx = tg["t_idx"].to_numpy(), tg["o_idx"].to_numpy()
    else:
        t_idx = tg["team_id"].map(team_index).to_numpy()
        o_idx = tg["opp_id"].map(team_index).to_numpy()
    y = tg[spec.value_col].to_numpy(dtype=float) * spec.scale
    w = np.ones(len(tg)) if spec.weight_col is None else tg[spec.weight_col].to_numpy(dtype=float)
    ok = np.isfinite(y) & np.isfinite(w) & (w > 0)
    if recency_tau_days and as_of is not None and len(tg):
        age = (as_of - pd.to_datetime(tg["start_time_utc"])).dt.total_seconds().to_numpy()
        w = w * np.exp(-np.clip(age, 0, None) / (86400.0 * recency_tau_days))
    loc = tg["loc"].to_numpy()
    return solve(
        t_idx[ok].astype(int),
        o_idx[ok].astype(int),
        y[ok],
        w[ok],
        loc[ok],
        len(team_index),
        prior_off,
        prior_def,
        lam,
        prior_mu=prior_mu,
        prior_eta=prior_eta,
        pace=spec.pace,
        use_loc=spec.use_loc,
        adjust=adjust,
        x0=x0,
    )
