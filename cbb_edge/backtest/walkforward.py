"""Chronological walk-forward replay engine.

For every game day ``D`` of a season, in order:

1. information set = this season's team-game rows with ``available_at`` strictly before
   the first tip-off on ``D`` (plus pre-season priors built only from earlier seasons);
2. fit opponent-adjusted ratings for every stat on that information set;
3. emit one *pregame state row* per D-I vs D-I game on ``D`` (persisted);
4. only then do ``D``'s results become eligible for later days.

The engine never builds a season-wide table containing future information: every
fitted state is a function of ``info_set(D)`` only, and every emitted row records the
``info_max_available_at`` it was built from, which the leakage tests check against the
game's start time.

Pre-season priors for season ``s`` come from the end-of-season fit of ``s-1``
(regressed toward the mean) and, optionally (``roster_prior``), from returning-minutes
continuity measured leakage-safely: only players who have already appeared for the
team in season ``s`` *before* ``D`` count as returning.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from cbb_edge.ratings.adjusted import BASE_STATS, STATS, Fit, fit_stat

DEFAULT_LAMBDA = {
    # prior strength in units of the stat's observation weight
    "eff": 450.0,  # possessions
    "tempo": 6.0,  # games
    "efg": 350.0,  # FGA
    "to": 450.0,  # possessions
    "orb": 220.0,  # rebound chances
    "ftr": 350.0,  # FGA
    "fg2": 200.0,  # 2PA
    "fg3": 180.0,  # 3PA
    "fg3a_rate": 250.0,  # FGA
    "rim_rate": 250.0,  # lineup FGA
    "rim_pct": 150.0,  # rim attempts
    "mid_rate": 250.0,  # lineup FGA
    "mid_pct": 150.0,  # mid-range attempts
    "ast_share": 200.0,  # made FG
}


@dataclass
class EngineConfig:
    lam: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LAMBDA))
    prior_regress: float = 0.65  # share of last season's (centered) rating retained
    adjust: bool = True  # False => raw rolling benchmark (B1)
    recency_tau_days: float | None = None
    roster_prior: bool = False  # B4: continuity-scaled prior
    # rho_i = prior_regress * (c0 + c1 * share_i) / (c0 + c1 * league_share): continuity
    # re-weights the tuned regression team by team, keeping its league-average strength.
    # (c0, c1) estimated on DEV seasons: research/baseline/roster_prior_dev.json
    roster_coef: tuple[float, float] = (0.548, 0.358)
    stats: tuple[str, ...] = BASE_STATS
    lam_mu: float = 3000.0
    lam_eta: float = 3000.0


@dataclass
class SeasonPriors:
    team_ids: list[str]
    off: dict[str, np.ndarray]
    deff: dict[str, np.ndarray]
    mu: dict[str, float]
    eta: dict[str, float]
    last_off: dict[str, np.ndarray] | None = None  # unregressed (for roster prior)
    last_def: dict[str, np.ndarray] | None = None


def d1_rows(tg: pd.DataFrame) -> pd.DataFrame:
    return tg[
        tg["team_id"].notna()
        & tg["opp_id"].notna()
        & tg["team_is_d1"]
        & tg["opp_is_d1"]
        & tg["box_ok"]
    ]


# Fixed, data-independent league priors (typical D-I values). Used ONLY for the very
# first replayed season. They must not be computed from that season's data: doing so
# leaks the season-wide league mean into early-season states (caught by
# tests/test_leakage.py::test_future_results_cannot_change_past_states).
LEAGUE_PRIOR_MU = {
    "eff": 102.0,
    "tempo": 67.0,
    "efg": 49.5,
    "to": 19.5,
    "orb": 32.0,
    "ftr": 35.0,
    "fg2": 47.5,
    "fg3": 34.5,
    "fg3a_rate": 33.0,
    "rim_rate": 36.7,
    "rim_pct": 60.0,
    "mid_rate": 26.6,
    "mid_pct": 37.0,
    "ast_share": 52.0,
}
LEAGUE_PRIOR_ETA = {"eff": 1.5}


def default_priors(team_ids: list[str], tg_season: pd.DataFrame | None = None) -> SeasonPriors:
    """Uninformative priors for the first season: fixed league constants, zero team
    effects. ``tg_season`` is accepted for API compatibility and deliberately unused."""
    n = len(team_ids)
    off = {k: np.zeros(n) for k in STATS}
    deff = {k: np.zeros(n) for k in STATS}
    mu = {k: LEAGUE_PRIOR_MU[k] for k in STATS}
    eta = {k: LEAGUE_PRIOR_ETA.get(k, 0.0) for k in STATS}
    return SeasonPriors(team_ids, off, deff, mu, eta)


def priors_from_previous(
    team_ids: list[str], prev_ids: list[str], prev_end: dict[str, Fit], cfg: EngineConfig
) -> SeasonPriors:
    n = len(team_ids)
    pidx = {t: i for i, t in enumerate(prev_ids)}
    off, deff, mu, eta, lo, ld = {}, {}, {}, {}, {}, {}
    for name, fit in prev_end.items():
        po, pd_ = np.zeros(n), np.zeros(n)
        have = np.array([t in pidx for t in team_ids])
        prev_o = np.array([fit.off[pidx[t]] if t in pidx else np.nan for t in team_ids])
        prev_d = np.array([fit.deff[pidx[t]] if t in pidx else np.nan for t in team_ids])
        # Teams new to D-I start near the bottom of the previous distribution.
        new_o = np.nanquantile(fit.off, 0.15)
        new_d = np.nanquantile(fit.deff, 0.85) if name != "tempo" else 0.0
        if name in ("to",):  # higher TO% is worse for offense
            new_o = np.nanquantile(fit.off, 0.85)
            new_d = np.nanquantile(fit.deff, 0.15)
        prev_o = np.where(have, prev_o, new_o)
        prev_d = np.where(have, prev_d, new_d)
        lo[name], ld[name] = prev_o.copy(), prev_d.copy()
        po = cfg.prior_regress * prev_o
        pd_ = cfg.prior_regress * prev_d
        off[name], deff[name] = po, pd_
        mu[name], eta[name] = fit.mu, fit.eta
    return SeasonPriors(team_ids, off, deff, mu, eta, lo, ld)


def returning_share(
    pg_prev: pd.DataFrame, pg_cur_info: pd.DataFrame, team_ids: list[str]
) -> np.ndarray:
    """Share of each team's previous-season minutes played by players who have ALREADY
    appeared for that team in the current season's information set. NaN if the team
    has not played yet this season (prior then uses the league-average share)."""
    prev = pg_prev.groupby(["team_id", "player_id"])["min"].sum().rename("m").reset_index()
    tot = prev.groupby("team_id")["m"].sum()
    seen = pg_cur_info[["team_id", "player_id"]].drop_duplicates()
    ret = prev.merge(seen, on=["team_id", "player_id"]).groupby("team_id")["m"].sum()
    played = set(pg_cur_info["team_id"].unique())
    out = np.full(len(team_ids), np.nan)
    for i, t in enumerate(team_ids):
        if t in played and t in tot.index and tot[t] > 0:
            out[i] = float(ret.get(t, 0.0) / tot[t])
    return out


def _apply_roster_prior(
    pri: SeasonPriors, share: np.ndarray, cfg: EngineConfig, league_share: float
) -> SeasonPriors:
    if pri.last_off is None or pri.last_def is None:
        return pri
    s = np.where(np.isfinite(share), share, league_share)
    c0, c1 = cfg.roster_coef
    rho = np.clip(cfg.prior_regress * (c0 + c1 * s) / (c0 + c1 * league_share), 0.0, 1.0)
    off = {k: rho * pri.last_off[k] for k in pri.last_off}
    deff = {k: rho * pri.last_def[k] for k in pri.last_def}
    return SeasonPriors(pri.team_ids, off, deff, pri.mu, pri.eta, pri.last_off, pri.last_def)


def fit_all(
    tg_info: pd.DataFrame,
    pri: SeasonPriors,
    cfg: EngineConfig,
    as_of: pd.Timestamp | None,
    warm: dict[str, Fit] | None = None,
) -> dict[str, Fit]:
    index = {t: i for i, t in enumerate(pri.team_ids)}
    fits = {}
    for name in cfg.stats:
        spec = STATS[name]
        fits[name] = fit_stat(
            tg_info,
            spec,
            index,
            pri.off[name],
            pri.deff[name],
            cfg.lam[name],
            pri.mu[name],
            pri.eta[name],
            adjust=cfg.adjust,
            recency_tau_days=cfg.recency_tau_days,
            as_of=as_of,
            x0=warm[name].raw if warm and name in warm else None,
        )
        if spec.pace:
            fits[name].deff = fits[name].off.copy()
    return fits


def state_rows(
    games_day: pd.DataFrame,
    fits: dict[str, Fit],
    index: dict[str, int],
    poss_seen: np.ndarray,
    games_seen: np.ndarray,
) -> pd.DataFrame:
    hi = games_day["home_team_id"].map(index).to_numpy()
    ai = games_day["away_team_id"].map(index).to_numpy()
    out: dict[str, object] = {
        "game_id": games_day["game_id"].to_numpy(),
        "h_poss_seen": poss_seen[hi],
        "a_poss_seen": poss_seen[ai],
        "h_games_seen": games_seen[hi],
        "a_games_seen": games_seen[ai],
    }
    for name, f in fits.items():
        out[f"h_off_{name}"] = f.off[hi]
        out[f"h_def_{name}"] = f.deff[hi]
        out[f"a_off_{name}"] = f.off[ai]
        out[f"a_def_{name}"] = f.deff[ai]
        out[f"mu_{name}"] = np.full(len(hi), f.mu)
        out[f"eta_{name}"] = np.full(len(hi), f.eta)
    return pd.DataFrame(out)


def replay_season(
    season: int,
    games: pd.DataFrame,
    tg: pd.DataFrame,
    pri: SeasonPriors,
    cfg: EngineConfig,
    pg_prev: pd.DataFrame | None = None,
    pg_cur: pd.DataFrame | None = None,
    prior_hook: Callable[[int, pd.Timestamp, SeasonPriors], SeasonPriors] | None = None,
) -> tuple[pd.DataFrame, dict[str, Fit]]:
    """Replay one season day by day. Returns (pregame state rows, end-of-season fits).

    ``prior_hook(season, cutoff, priors)`` may return day-specific priors built from
    information available before ``cutoff`` (e.g. the observed rotation's player
    impact); ``None`` keeps the fixed season priors (pure-0.2.0 behaviour)."""
    index = {t: i for i, t in enumerate(pri.team_ids)}
    n = len(index)
    g = games[
        (games["season"] == season)
        & games["home_team_id"].notna()
        & games["away_team_id"].notna()
        & games["home_is_d1"]
        & games["away_is_d1"]
        & ~games["status"].isin(["STATUS_CANCELED", "STATUS_POSTPONED"])
    ]
    g = g.sort_values("start_time_utc")
    tgs = d1_rows(tg[tg["season"] == season]).copy()
    tgs["t_idx"] = tgs["team_id"].map(index).astype(int)
    tgs["o_idx"] = tgs["opp_id"].map(index).astype(int)
    league_share = np.nan
    fits: dict[str, Fit] | None = None
    if cfg.roster_prior and pg_prev is not None and pg_cur is not None:
        full = returning_share(pg_prev, pg_cur, pri.team_ids)
        league_share = float(np.nanmean(full)) if np.isfinite(full).any() else 0.5
    rows = []
    for _day, gd in g.groupby("game_date_et", sort=True):
        cutoff = gd["start_time_utc"].min()
        info = tgs[tgs["available_at"] < cutoff]
        p = pri
        if cfg.roster_prior and pg_prev is not None and pg_cur is not None:
            share = returning_share(pg_prev, pg_cur[pg_cur["available_at"] < cutoff], pri.team_ids)
            p = _apply_roster_prior(pri, share, cfg, league_share)
        if prior_hook is not None:
            if getattr(prior_hook, "wants_fits", False):
                # previous day's fits: information strictly before this cutoff
                p = prior_hook(season, cutoff, p, fits)  # type: ignore[call-arg]
            else:
                p = prior_hook(season, cutoff, p)
        fits = fit_all(info, p, cfg, cutoff, warm=fits)
        t_idx = info["t_idx"].to_numpy()
        poss_seen = np.bincount(t_idx, weights=info["poss"].to_numpy(), minlength=n)
        games_seen = np.bincount(t_idx, minlength=n).astype(float)
        sr = state_rows(gd, fits, index, poss_seen, games_seen)
        sr["info_max_available_at"] = info["available_at"].max() if len(info) else pd.NaT
        sr["cutoff"] = cutoff
        sr["info_rows"] = len(info)
        rows.append(sr)
    end_fits = fit_all(tgs, pri if not cfg.roster_prior else p, cfg, None) if len(tgs) else {}
    states = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return states, end_fits


def run(
    games: pd.DataFrame,
    tg: pd.DataFrame,
    seasons: list[int],
    cfg: EngineConfig,
    pg: pd.DataFrame | None = None,
    verbose: bool = True,
    prior_hook: Callable[[int, pd.Timestamp, SeasonPriors], SeasonPriors] | None = None,
) -> pd.DataFrame:
    """Replay consecutive seasons; the first season only seeds priors for the next."""
    from cbb_edge.data.ids.teams import _registry

    team_ids = sorted(_registry()["team_id"].tolist())
    prev_end: dict[str, Fit] | None = None
    all_states = []
    for season in seasons:
        tgs = d1_rows(tg[tg["season"] == season])
        if prev_end is None:
            pri = default_priors(team_ids, tgs)
        else:
            pri = priors_from_previous(team_ids, team_ids, prev_end, cfg)
        pg_prev = pg[pg["season"] == season - 1] if pg is not None else None
        pg_cur = pg[pg["season"] == season] if pg is not None else None
        states, end = replay_season(season, games, tg, pri, cfg, pg_prev, pg_cur, prior_hook)
        if len(states):
            states["season"] = season
            all_states.append(states)
        if end:
            prev_end = end
        if verbose:
            print(f"  replay {season}: {len(states)} pregame states", flush=True)
    return pd.concat(all_states, ignore_index=True)
