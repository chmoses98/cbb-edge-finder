"""Possession challenger ``poss-ch-v1`` (RESEARCH_ONLY; never imported by production paths).

Walk-forward, day by day, using only team-game rows whose ``available_at`` is strictly
before the first tip of the forecast day:

* efficiency: ``100*pts/poss = mu + O[off] + D[def] + h*loc`` (+ optional per-team home
  term), weighted by possessions x exp(age/tau), ridge-shrunk toward a preseason prior
  (``rho`` x last season's end-of-season rating);
* tempo: ``poss = mu_t + T[home] + T[away]``, same weighting/prior;
* combination is multiplicative: ``pts_h = poss * eff_h / 100``.

A season-level linear layer (margin / total stretch + intercept, probit win SD by games seen)
is fitted only on seasons strictly earlier than the forecast season.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm


@dataclass(frozen=True)
class Params:
    tau_days: float = 60.0  # recency time constant
    lam_eff: float = 900.0  # prior strength, possessions
    lam_tempo: float = 6.0  # prior strength, games
    lam_hca_team: float = 4000.0  # shrinkage of team-specific home term (possessions); 0 = off
    rho_eff: float = 0.75  # share of last season's efficiency rating kept in the prior
    rho_tempo: float = 0.8
    cal_seasons: int = 6  # calibration window (seasons strictly before target)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def d1_team_games(tg: pd.DataFrame) -> pd.DataFrame:
    m = tg.team_is_d1 & tg.opp_is_d1 & tg.team_id.notna() & tg.opp_id.notna() & (tg.poss > 40)
    if "box_ok" in tg:
        m &= tg.box_ok.astype(bool)
    return tg[m]


def d1_games(g: pd.DataFrame) -> pd.DataFrame:
    m = (
        g.home_is_d1.astype(bool)
        & g.away_is_d1.astype(bool)
        & g.home_team_id.notna()
        & g.away_team_id.notna()
        & g.completed.astype(bool)
        & g.home_score.notna()
        & g.away_score.notna()
    )
    return g[m]


def _ns(x: pd.Series) -> np.ndarray:
    return pd.to_datetime(x, utc=True).dt.as_unit("ns").astype("int64").to_numpy()


def _ns_one(t: pd.Timestamp) -> int:
    t = pd.Timestamp(t)
    return int((t.tz_convert("UTC") if t.tzinfo else t.tz_localize("UTC")).as_unit("ns").value)


class _Ridge:
    """Ridge with recency weights: data term scaled by exp(-(day - d0)/tau) at solve time,
    so normal equations accumulate incrementally (rows only ever added)."""

    def __init__(self, k: int, prior_mean: np.ndarray, prior_prec: np.ndarray, tau: float):
        self.A = np.zeros((k, k))
        self.b = np.zeros(k)
        self.m0, self.p0, self.tau = prior_mean, prior_prec, tau

    def add(self, idx: np.ndarray, val: np.ndarray, y: np.ndarray, w: np.ndarray) -> None:
        # idx/val: (rows, nnz) sparse design rows
        nz = idx.shape[1]
        for a in range(nz):
            np.add.at(self.b, idx[:, a], w * val[:, a] * y)
            for c in range(nz):
                np.add.at(self.A, (idx[:, a], idx[:, c]), w * val[:, a] * val[:, c])

    def solve(self, day: float) -> np.ndarray:
        s = np.exp(-day / self.tau)
        M = s * self.A
        M[np.diag_indices_from(M)] += self.p0
        return np.linalg.solve(M, s * self.b + self.p0 * self.m0)


def walk_season(
    tg_s: pd.DataFrame,
    g_s: pd.DataFrame,
    teams: list[str],
    prior: dict[str, np.ndarray | float],
    p: Params,
) -> tuple[pd.DataFrame, dict[str, np.ndarray | float]]:
    """Pregame raw projections for every game in ``g_s`` + end-of-season state."""
    n = len(teams)
    ix = {t: i for i, t in enumerate(teams)}
    d0 = pd.Timestamp(g_s.start_time_utc.min()).normalize()
    tg_s = tg_s[tg_s.team_id.isin(ix) & tg_s.opp_id.isin(ix)].sort_values("available_at")
    # efficiency: [mu, h, O(n), D(n), H(n)]
    k = 2 + 3 * n
    m0 = np.concatenate([[prior["mu"], prior["h"]], prior["O"], prior["D"], np.zeros(n)])
    p0 = np.concatenate(
        [
            [1e-2, 50.0],
            np.full(n, p.lam_eff),
            np.full(n, p.lam_eff),
            np.full(n, p.lam_hca_team if p.lam_hca_team > 0 else 1e12),
        ]
    )
    eff = _Ridge(k, m0, p0, p.tau_days)
    kt = 1 + n
    t0 = np.concatenate([[prior["mu_t"]], prior["T"]])
    tp = np.concatenate([[1e-3], np.full(n, p.lam_tempo)])
    tem = _Ridge(kt, t0, tp, p.tau_days)

    ti = tg_s.team_id.map(ix).to_numpy()
    oi = tg_s.opp_id.map(ix).to_numpy()
    loc = tg_s["loc"].to_numpy(float)
    age = ((tg_s.start_time_utc - d0).dt.total_seconds() / 86400).to_numpy()
    y_e = 100 * tg_s.pts.to_numpy(float) / tg_s.poss.to_numpy(float)
    w_e = tg_s.poss.to_numpy(float) * np.exp(age / p.tau_days)
    avail = _ns(tg_s.available_at)
    e_idx = np.stack([np.zeros_like(ti), np.ones_like(ti), 2 + ti, 2 + n + oi, 2 + 2 * n + ti], 1)
    e_val = np.stack(
        [np.ones_like(loc), loc, np.ones_like(loc), np.ones_like(loc), (loc > 0) * 1.0], 1
    )
    # tempo: one row per game (home-or-first side)
    first = ~tg_s.duplicated("game_id")
    t_idx = np.stack([np.zeros_like(ti), 1 + ti, 1 + oi], 1)
    t_val = np.ones((len(ti), 3))

    out = []
    g_s = g_s.sort_values("start_time_utc")
    days = g_s.game_date_et.unique()
    ptr = 0
    first_np = first.to_numpy()
    for day in days:
        gd = g_s[g_s.game_date_et == day]
        cut = gd.start_time_utc.min()
        j = ptr
        while j < len(avail) and avail[j] < _ns_one(cut):
            j += 1
        if j > ptr:
            sl = slice(ptr, j)
            eff.add(e_idx[sl], e_val[sl], y_e[sl], w_e[sl])
            fm = first_np[sl]
            tem.add(
                t_idx[sl][fm],
                t_val[sl][fm],
                tg_s.poss.to_numpy(float)[sl][fm],
                np.exp(age[sl][fm] / p.tau_days),
            )
            ptr = j
        dd = (cut - d0).total_seconds() / 86400
        be, bt = eff.solve(dd), tem.solve(dd)
        mu, h = be[0], be[1]
        off, dfn, hca = be[2 : 2 + n], be[2 + n : 2 + 2 * n], be[2 + 2 * n :]
        seen = np.bincount(ti[:ptr], minlength=n)
        for r in gd.itertuples():
            a, b = ix.get(r.home_team_id), ix.get(r.away_team_id)
            if a is None or b is None:
                continue
            L = 0.0 if r.neutral_site else 1.0
            poss = bt[0] + bt[1 + a] + bt[1 + b]
            eh = mu + off[a] + dfn[b] + L * (h + hca[a])
            ea = mu + off[b] + dfn[a] - L * h
            out.append(
                (r.game_id, poss, poss * eh / 100, poss * ea / 100, int(seen[a]), int(seen[b]))
            )
    res = pd.DataFrame(out, columns=["game_id", "c_poss", "c_hpts", "c_apts", "h_seen", "a_seen"])
    dd = (g_s.start_time_utc.max() - d0).total_seconds() / 86400 + 1
    be, bt = eff.solve(dd), tem.solve(dd)
    end = {
        "mu": be[0],
        "h": be[1],
        "O": be[2 : 2 + n],
        "D": be[2 + n : 2 + 2 * n],
        "mu_t": bt[0],
        "T": bt[1:],
        "teams": np.array(teams),
    }
    return res, end


def next_prior(end: dict | None, teams: list[str], p: Params) -> dict[str, np.ndarray | float]:
    n = len(teams)
    if end is None:
        return {
            "mu": 102.0,
            "h": 1.5,
            "O": np.zeros(n),
            "D": np.zeros(n),
            "mu_t": 68.0,
            "T": np.zeros(n),
        }
    pos = {t: i for i, t in enumerate(end["teams"])}
    take = np.array([pos.get(t, -1) for t in teams])
    has = take >= 0

    def carry(v: np.ndarray, rho: float) -> np.ndarray:
        x = np.zeros(n)
        x[has] = rho * (v[take[has]] - v.mean())
        return x

    return {
        "mu": end["mu"],
        "h": end["h"],
        "O": carry(end["O"], p.rho_eff),
        "D": carry(end["D"], p.rho_eff),
        "mu_t": end["mu_t"],
        "T": carry(end["T"], p.rho_tempo),
    }


def raw_walk_forward(
    games: pd.DataFrame, tg: pd.DataFrame, seasons: list[int], p: Params
) -> pd.DataFrame:
    """Raw walk-forward projections for every completed D-I game of ``seasons`` (chain starts
    at ``seasons[0]`` with a flat prior)."""
    tg = d1_team_games(tg)
    g = d1_games(games)
    end, parts = None, []
    for s in seasons:
        g_s, tg_s = g[g.season == s], tg[tg.season == s]
        if g_s.empty:
            continue
        teams = sorted(set(g_s.home_team_id) | set(g_s.away_team_id) | set(tg_s.team_id))
        res, end = walk_season(tg_s, g_s, teams, next_prior(end, teams, p), p)
        res["season"] = s
        parts.append(res)
    out = pd.concat(parts, ignore_index=True)
    out["c_margin_raw"] = out.c_hpts - out.c_apts
    out["c_total_raw"] = out.c_hpts + out.c_apts
    return out.merge(
        g[
            [
                "game_id",
                "home_score",
                "away_score",
                "neutral_site",
                "game_date_et",
                "start_time_utc",
            ]
        ],
        on="game_id",
    )


SD_BUCKETS = (0, 2, 4, 6, 9, 12)


def _bucket(gs: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.array(SD_BUCKETS), gs, side="right") - 1


def calibrate(raw: pd.DataFrame, target: int, p: Params) -> dict[str, object]:
    """Linear stretch for margin/total and probit SD by games seen, fitted only on seasons in
    [target - cal_seasons, target)."""
    tr = raw[(raw.season < target) & (raw.season >= target - p.cal_seasons)]
    if tr.empty:
        raise ValueError(f"no calibration seasons before {target}")
    ym = (tr.home_score - tr.away_score).to_numpy(float)
    yt = (tr.home_score + tr.away_score).to_numpy(float)
    Xm = np.c_[np.ones(len(tr)), tr.c_margin_raw]
    Xt = np.c_[np.ones(len(tr)), tr.c_total_raw]
    cm = np.linalg.lstsq(Xm, ym, rcond=None)[0]
    ct = np.linalg.lstsq(Xt, yt, rcond=None)[0]
    res = ym - Xm @ cm
    b = _bucket(np.minimum(tr.h_seen, tr.a_seen).to_numpy())
    sd = [
        float(np.sqrt(np.mean(res[b == i] ** 2))) if (b == i).sum() > 50 else float(res.std())
        for i in range(len(SD_BUCKETS))
    ]
    return {
        "margin": cm.tolist(),
        "total": ct.tolist(),
        "sd_by_bucket": sd,
        "fit_seasons": sorted(tr.season.unique().tolist()),
    }


def apply_calibration(raw: pd.DataFrame, cal: dict[str, object]) -> pd.DataFrame:
    out = raw.copy()
    cm, ct, sd = cal["margin"], cal["total"], np.array(cal["sd_by_bucket"])
    out["c_margin"] = cm[0] + cm[1] * out.c_margin_raw
    out["c_total"] = ct[0] + ct[1] * out.c_total_raw
    out["c_msd"] = sd[_bucket(np.minimum(out.h_seen, out.a_seen).to_numpy())]
    out["c_wp"] = np.clip(norm.cdf(out.c_margin / out.c_msd), 1e-4, 1 - 1e-4)
    out["c_hpts"] = (out.c_total + out.c_margin) / 2
    out["c_apts"] = (out.c_total - out.c_margin) / 2
    return out


def forecasts(raw: pd.DataFrame, seasons: list[int], p: Params) -> tuple[pd.DataFrame, dict]:
    parts, cals = [], {}
    for s in seasons:
        cal = calibrate(raw, s, p)
        cals[s] = cal
        parts.append(apply_calibration(raw[raw.season == s], cal))
    return pd.concat(parts, ignore_index=True), cals
