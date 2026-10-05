"""Player-derived, roster-aware priors that participate directly in the team rating solve.

Default engine prior: ``prior_off_t = rho * last_season_off_t`` (fixed all season).
Here the prior for team t on day D becomes

    prior_off_t(D) = c0 + c1 * rho * last_off_t + c2 * S_off_t(D)

where ``S_off_t(D)`` is the player-derived team offense known before D's first tip:
* before the team's first game: the probabilistic preseason estimate
  (``preseason.pre_o``: expected returners' carried impact + newcomer fill);
* afterwards: the rotation actually observed so far (EW minute shares of players who
  have appeared, incl. transfers with carried ratings) × walk-forward player impact
  (``rapm.player_team_features``).
Same for defense. Coefficients are fitted on DEV seasons only (2012–2014), separately
for the preseason and observed-roster states, against each team's end-of-season engine
rating (``fit_prior_coefficients``). The ridge solve then propagates these
uncertainty-weighted priors through the opponent network, so early-season opponent
adjustment is anchored on roster information rather than only last season's team.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from cbb_edge.backtest.walkforward import SeasonPriors


def team_day_strength(pf: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Long table: team, season, cutoff (first tip of the game day), S_off, S_def, known."""
    g = games[["game_id", "game_date_et", "start_time_utc", "home_team_id", "away_team_id"]]
    cut = g.groupby("game_date_et")["start_time_utc"].transform("min")
    g = g.assign(cutoff=cut)
    d = pf.merge(g, on="game_id")
    parts = []
    for side, team in (("h", "home_team_id"), ("a", "away_team_id")):
        parts.append(
            pd.DataFrame(
                {
                    "team_id": d[team],
                    "season": d["season"],
                    "cutoff": d["cutoff"],
                    "s_off": d[f"{side}_p_off"],
                    "s_def": d[f"{side}_p_def"],
                    "known": d[f"{side}_roster_known"],
                    "games_seen": d[f"{side}_games_seen_p"],
                }
            )
        )
    out = pd.concat(parts).dropna(subset=["team_id"]).sort_values(["team_id", "cutoff"])
    return out.drop_duplicates(["team_id", "cutoff"], keep="last")


def season_final_ratings(states: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    g = games[["game_id", "home_team_id", "away_team_id", "start_time_utc"]]
    d = states.merge(g, on="game_id")
    long = pd.concat(
        [
            d[["season", "start_time_utc", "home_team_id", "h_off_eff", "h_def_eff"]].set_axis(
                ["season", "t", "team_id", "o", "d"], axis=1
            ),
            d[["season", "start_time_utc", "away_team_id", "a_off_eff", "a_def_eff"]].set_axis(
                ["season", "t", "team_id", "o", "d"], axis=1
            ),
        ]
    )
    return (
        long.sort_values("t")
        .groupby(["team_id", "season"])
        .tail(1)[["team_id", "season", "o", "d"]]
    )


@dataclass
class PriorCoefficients:
    pre: dict[str, list[float]] = field(default_factory=dict)  # side -> [c0, c1, c2]
    obs: dict[str, list[float]] = field(default_factory=dict)


def fit_prior_coefficients(
    strength: pd.DataFrame,
    preseason: pd.DataFrame,
    finals: pd.DataFrame,
    rho: float,
    seasons: list[int],
    max_games: int = 10,
) -> PriorCoefficients:
    """Regress each team's end-of-season rating on [rho*last, S] (DEV seasons only)."""
    last = finals.assign(season=finals["season"] + 1).rename(columns={"o": "last_o", "d": "last_d"})
    out = PriorCoefficients()
    base = finals.merge(last, on=["team_id", "season"], how="inner")
    base = base[base["season"].isin(seasons)]
    pre = base.merge(preseason[["team_id", "season", "pre_o", "pre_d"]], on=["team_id", "season"])
    obs = base.merge(
        strength[strength["known"].astype(bool) & (strength["games_seen"] <= max_games)],
        on=["team_id", "season"],
    )
    for side, last_c, pre_c, obs_c, tgt in (
        ("off", "last_o", "pre_o", "s_off", "o"),
        ("def", "last_d", "pre_d", "s_def", "d"),
    ):
        X = np.column_stack([rho * pre[last_c], pre[pre_c]])
        m = LinearRegression().fit(X, pre[tgt])
        out.pre[side] = [float(m.intercept_), *map(float, m.coef_)]
        X = np.column_stack([rho * obs[last_c], obs[obs_c]])
        m = LinearRegression().fit(X, obs[tgt])
        out.obs[side] = [float(m.intercept_), *map(float, m.coef_)]
    return out


class RosterPriorHook:
    """Callable used by ``replay_season``: returns day-specific priors for 'eff'."""

    def __init__(
        self,
        strength: pd.DataFrame,
        preseason: pd.DataFrame,
        coefs: PriorCoefficients,
        stats: tuple[str, ...] = ("eff",),
    ):
        self.coefs = coefs
        self.stats = stats
        self.pre = preseason.set_index(["season", "team_id"])[["pre_o", "pre_d"]]
        self.strength = {s: x for s, x in strength.groupby("season")}
        self._cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def _arrays(
        self, season: int, cutoff: pd.Timestamp, team_ids: list[str]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        key = (season, int(pd.Timestamp(cutoff).value))
        if key in self._cache:
            return self._cache[key]
        n = len(team_ids)
        so, sd, known = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
        st = self.strength.get(season)
        if st is not None:
            cur = st[st["cutoff"] <= cutoff].drop_duplicates("team_id", keep="last")
            m = cur.set_index("team_id")
            idx = {t: i for i, t in enumerate(team_ids)}
            for t, r in m.iterrows():
                i = idx.get(t)
                if i is not None and r["known"]:
                    so[i], sd[i], known[i] = r["s_off"], r["s_def"], 1.0
        if season in self.pre.index.get_level_values(0):
            p = self.pre.loc[season]
            for i, t in enumerate(team_ids):
                if not known[i] and t in p.index:
                    so[i], sd[i] = p.at[t, "pre_o"], p.at[t, "pre_d"]
        self._cache[key] = (so, sd, known)
        return so, sd, known

    def __call__(self, season: int, cutoff: pd.Timestamp, pri: SeasonPriors) -> SeasonPriors:
        so, sd, known = self._arrays(season, cutoff, pri.team_ids)
        off = dict(pri.off)
        deff = dict(pri.deff)
        for stat in self.stats:
            base_o, base_d = pri.off[stat], pri.deff[stat]
            new_o, new_d = base_o.copy(), base_d.copy()
            have = np.isfinite(so)
            for arr, base, s, side in ((new_o, base_o, so, "off"), (new_d, base_d, sd, "def")):
                cp = self.coefs.pre[side]
                cb = self.coefs.obs[side]
                pre_v = cp[0] + cp[1] * base + cp[2] * np.nan_to_num(s)
                obs_v = cb[0] + cb[1] * base + cb[2] * np.nan_to_num(s)
                arr[:] = np.where(have, np.where(known > 0, obs_v, pre_v), base)
            off[stat], deff[stat] = new_o, new_d
        return SeasonPriors(pri.team_ids, off, deff, pri.mu, pri.eta, pri.last_off, pri.last_def)
