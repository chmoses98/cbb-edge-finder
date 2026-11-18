"""Phase 15 CBB evaluation: calibration/SD layers, 1H/2H period models, Kalshi-strike scoring (research only).

Run after cbb_p15_data.py and the walk-forward (cbb_p15_run.py).  All layer parameters are fitted on TRAIN seasons only
(full game 2010-2025, periods 2023-2025; ESPN season = end year) and frozen before the holdout (2026 = 2025-26, and
2027 = 2026-27 to date, reported separately) is scored once.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/sift-alpha/research/phase15")
import p15eval as E  # noqa: E402

FG_TRAIN = list(range(2010, 2026))
P_TRAIN = [2023, 2024, 2025]
HOLD = [2026, 2027]
EARLY = 10   # early-season slice: either team has played < EARLY games


def _ols(X, y, w=None):
    w = np.ones(len(y)) if w is None else w
    return np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]


# ----------------------------------------------------------------------------------------------- full game layers
def fg_design(d: pd.DataFrame, variant: str):
    rm, rt = d.raw_h - d.raw_a, d.raw_h + d.raw_a
    one = np.ones(len(d))
    nmin = np.minimum(d.n_before_h, d.n_before_a).values
    e = 1.0 / (1.0 + nmin)
    if variant == "base":
        return np.c_[one, rm], np.c_[one, rt], np.c_[one], np.c_[one], e
    rest = np.clip(d.rest_h - d.rest_a, -4, 4).values
    b2b = (d.rest_h <= 1).astype(float).values - (d.rest_a <= 1).astype(float).values
    Xm = np.c_[one, rm, d.hca_team.values, rest, b2b]
    Xt = np.c_[one, rt, e, rt * e]
    Vm = np.c_[one, e, np.abs(rm)]
    Vt = np.c_[one, e, rt]
    return Xm, Xt, Vm, Vt, e


def fit_fg(d: pd.DataFrame, variant: str) -> dict:
    Xm, Xt, Vm, Vt, _ = fg_design(d, variant)
    m, t = (d.home_pts - d.away_pts).values, (d.home_pts + d.away_pts).values
    bm, bt = _ols(Xm, m), _ols(Xt, t)
    rm, rt = m - Xm @ bm, t - Xt @ bt
    vm, vt = _ols(Vm, rm ** 2), _ols(Vt, rt ** 2)
    return {"bm": bm.tolist(), "bt": bt.tolist(), "vm": vm.tolist(), "vt": vt.tolist(),
            "rho": float(np.corrcoef(rm, rt)[0, 1]), "n": len(d)}


def apply_fg(d: pd.DataFrame, variant: str, P: dict) -> pd.DataFrame:
    Xm, Xt, Vm, Vt, _ = fg_design(d, variant)
    return pd.DataFrame({"game_id": d.game_id.values, "mu_m": Xm @ P["bm"], "mu_t": Xt @ P["bt"],
                         "sd_m": np.sqrt(np.maximum(Vm @ P["vm"], 25.0)), "sd_t": np.sqrt(np.maximum(Vt @ P["vt"], 36.0)),
                         "rho": P["rho"]})


# ----------------------------------------------------------------------------------------------- period layers
def team_share_lookup(games: pd.DataFrame, halves: pd.DataFrame, s_lg: float, k: float = 10.0):
    """Date-strict team 1H-share tendencies for ANY game: (sum 1H - s_lg * sum FG) / (sum FG + k * 70) over the team's
    earlier regulation games of the season (strictly earlier dates) plus half-weighted previous-season games, for points
    scored (dev_off) and allowed (dev_def)."""
    # state after each team's games, keyed by date; a game uses the latest state strictly before its date
    h = halves[halves.n_ot == 0].merge(games[["game_id", "season", "date", "home_id", "away_id", "home_pts", "away_pts"]],
                                       on=["game_id", "season"])
    rows = []
    for side, o1, of, d1, df in (("home_id", "home_1h", "home_pts", "away_1h", "away_pts"),
                                 ("away_id", "away_1h", "away_pts", "home_1h", "home_pts")):
        rows.append(pd.DataFrame({"season": h.season, "date": h.date, "team": h[side], "o1": h[o1], "of": h[of],
                                  "d1": h[d1], "df": h[df]}))
    L = pd.concat(rows).groupby(["season", "team", "date"]).sum().groupby(level=[0, 1]).cumsum().reset_index()
    end = L.groupby(["season", "team"]).tail(1).drop(columns="date").assign(season=lambda x: x.season + 1)
    out = []
    g = games[["game_id", "season", "date", "home_id", "away_id"]]
    for side in ("home_id", "away_id"):
        q = g.rename(columns={side: "team"})[["game_id", "season", "date", "team"]].sort_values("date")
        q = pd.merge_asof(q, L.sort_values("date").rename(columns={"date": "sdate"}), left_on="date", right_on="sdate",
                          by=["season", "team"], allow_exact_matches=False)
        q = q.merge(end.add_prefix("p_").rename(columns={"p_season": "season", "p_team": "team"}), on=["season", "team"], how="left")
        q = q.fillna(0.0)
        t = {c: q[c] + 0.5 * q["p_" + c] for c in ("o1", "of", "d1", "df")}
        pre = "h_" if side == "home_id" else "a_"
        out.append(pd.DataFrame({"game_id": q.game_id, pre + "dev_off": (t["o1"] - s_lg * t["of"]) / (t["of"] + k * 70),
                                 pre + "dev_def": (t["d1"] - s_lg * t["df"]) / (t["df"] + k * 70)}))
    return out[0].merge(out[1], on="game_id")


def period_design(d: pd.DataFrame, s_lg: float, half: str):
    """d has FG forecasts (mu_m, mu_t, sd_m, sd_t) and share devs.  half = '1h' or '2h' (2H incl. OT)."""
    fh, fa = (d.mu_t + d.mu_m) / 2, (d.mu_t - d.mu_m) / 2
    sgn = 1.0 if half == "1h" else -1.0
    th = fh * (d.h_dev_off + d.a_dev_def) * sgn
    ta = fa * (d.a_dev_off + d.h_dev_def) * sgn
    one = np.ones(len(d))
    Xm = np.c_[one, d.mu_m, th - ta, (~d.neutral).astype(float)]
    Xt = np.c_[one, d.mu_t, th + ta]
    Vm = np.c_[one, d.sd_m ** 2]
    Vt = np.c_[one, d.sd_t ** 2]
    return Xm, Xt, Vm, Vt


def fit_period(d: pd.DataFrame, s_lg: float, half: str) -> dict:
    Xm, Xt, Vm, Vt = period_design(d, s_lg, half)
    m, t = d["y_m"].values, d["y_t"].values
    bm, bt = _ols(Xm, m), _ols(Xt, t)
    rm, rt = m - Xm @ bm, t - Xt @ bt
    return {"bm": bm.tolist(), "bt": bt.tolist(), "vm": _ols(Vm, rm ** 2).tolist(), "vt": _ols(Vt, rt ** 2).tolist(),
            "rho": float(np.corrcoef(rm, rt)[0, 1]), "n": len(d)}


def apply_period(d: pd.DataFrame, s_lg: float, half: str, P: dict) -> pd.DataFrame:
    Xm, Xt, Vm, Vt = period_design(d, s_lg, half)
    return pd.DataFrame({"game_id": d.game_id.values, "mu_m": Xm @ P["bm"], "mu_t": Xt @ P["bt"],
                         "sd_m": np.sqrt(np.maximum(Vm @ P["vm"], 9.0)), "sd_t": np.sqrt(np.maximum(Vt @ P["vt"], 16.0)),
                         "rho": P["rho"]})


def proportional(d: pd.DataFrame, share: float, rho: float) -> pd.DataFrame:
    """Baseline: mechanical split of the full-game forecast (means x share, SDs x sqrt(share))."""
    return pd.DataFrame({"game_id": d.game_id.values, "mu_m": share * d.mu_m.values, "mu_t": share * d.mu_t.values,
                         "sd_m": np.sqrt(share) * d.sd_m.values, "sd_t": np.sqrt(share) * d.sd_t.values, "rho": rho})


# ----------------------------------------------------------------------------------------------- scoring
class GamePMF:
    """Margin / total / team-score marginals of p15eval's discretised bivariate-normal score PMF."""

    def __init__(self, mu_m, sd_m, mu_t, sd_t, rho, n):
        pm = E.pmf_from_margin_total(mu_m, sd_m, mu_t, sd_t, rho, n=n)
        self.lo, self.mp = pm.margin_pmf()
        _, self.tp = pm.total_pmf()
        self.hp, self.ap = pm.p.sum(axis=1), pm.p.sum(axis=0)
        self.mk = self.lo + np.arange(len(self.mp))

    def margin_gt(self, x):
        return float(self.mp[self.mk > x].sum())

    def total_gt(self, x):
        return float(self.tp[np.arange(len(self.tp)) > x].sum())

    def team_gt(self, side, x):
        v = self.hp if side == "home" else self.ap
        return float(v[np.arange(len(v)) > x].sum())

    def tie(self):
        return float(self.mp[self.mk == 0].sum())

    def crps_margin(self, y):
        return E.crps_pmf(self.lo, self.mp, y)

    def crps_total(self, y):
        return E.crps_pmf(0, self.tp, y)


def contract_p(pmf: GamePMF, kind: str, side, strike):
    """Kalshi convention: '<side> wins by more than k', totals/team totals 'more than k', winner incl. 'tie'."""
    if kind == "spread":
        return pmf.margin_gt(strike) if side == "home" else float(pmf.mp[pmf.mk < -strike].sum())
    if kind == "total":
        return pmf.total_gt(strike)
    if kind == "team_total":
        return pmf.team_gt(side, strike)
    if kind == "winner":
        if side == "tie":
            return pmf.tie()
        return pmf.margin_gt(0.5) if side == "home" else float(pmf.mp[pmf.mk < -0.5].sum())
    raise ValueError(kind)


def summarize(p_new, p_old, y, clusters, label_new="model", label_old="baseline") -> dict:
    p_new, p_old, y = (np.asarray(v, float) for v in (p_new, p_old, y))
    bn, bo = E.brier(p_new, y), E.brier(p_old, y)
    ln, lo = E.logloss(p_new, y), E.logloss(p_old, y)
    return {"n_rows": int(len(y)), "n_games": int(len(np.unique(clusters))),
            "brier": E.cluster_ci(bn, clusters), "logloss": E.cluster_ci(ln, clusters),
            "brier_" + label_old: round(float(bo.mean()), 5), "logloss_" + label_old: round(float(lo.mean()), 5),
            "d_brier": E.paired_delta(bn, bo, clusters), "d_logloss": E.paired_delta(ln, lo, clusters),
            "p_d_logloss": E.boot_p(ln - lo, clusters),
            "slope": round(E.calibration_slope(p_new, y), 3), "slope_" + label_old: round(E.calibration_slope(p_old, y), 3),
            "bias_p_minus_y": round(float(p_new.mean() - y.mean()), 4),
            "reliability": E.reliability(p_new, y)}
