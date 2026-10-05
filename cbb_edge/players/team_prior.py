"""Roster- and conference-aware team priors that participate in the team rating solve.

Default engine prior: ``prior_off_t = rho * last_season_off_t`` (fixed all season).
With a :class:`TeamPriorHook` the prior for team t on day D becomes a fitted linear
combination of whatever components are enabled:

    prior_off_t(D) = c0 + c_base * rho * last_off_t + c_S * S_off_t(D) + c_conf * C_off_t

* ``S`` (B10, roster): player-derived team offense known before D's first tip —
  before the team's first game the probabilistic preseason estimate
  (``preseason.pre_o``: expected returners' carried impact + newcomer fill); afterwards
  the rotation actually observed so far (EW minute shares of players who have appeared,
  transfers included) × walk-forward player impact (``rapm.player_team_features``).
* ``C`` (B14, network anchor): last season's mean end-of-season rating of the other
  members of t's CURRENT conference (schedules / conference membership are public
  before the season). Early in the season, when few cross-conference games link the
  network, this anchors a team's level to its conference's.

Same for defense. Coefficients are fitted on DEV seasons only (2012–2014) against each
team's end-of-season engine rating, separately for the preseason state (no game seen
yet) and the observed-roster state (``fit_prior_coefficients``). The ridge solve then
propagates these priors through the opponent network. A component that is missing for
a team (NaN) leaves that team's default prior unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from cbb_edge.backtest.walkforward import SeasonPriors


def team_day_strength(pf: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Long table: team, season, cutoff (first tip of the game day), s_off, s_def, known."""
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
    """Each team's last pregame eff rating of the season (team_id, season, o, d)."""
    g = games[["game_id", "home_team_id", "away_team_id", "start_time_utc"]]
    d = states.merge(g, on="game_id")
    cols = ["season", "t", "team_id", "o", "d"]
    long = pd.concat(
        [
            d[["season", "start_time_utc", "home_team_id", "h_off_eff", "h_def_eff"]].set_axis(
                cols, axis=1
            ),
            d[["season", "start_time_utc", "away_team_id", "a_off_eff", "a_def_eff"]].set_axis(
                cols, axis=1
            ),
        ]
    )
    last = long.sort_values("t").groupby(["team_id", "season"]).tail(1)
    return last[["team_id", "season", "o", "d"]].reset_index(drop=True)


def conference_of(games: pd.DataFrame) -> pd.DataFrame:
    """Team's modal conference id in each season (from the published schedule)."""
    x = pd.concat(
        [
            games[["season", "home_team_id", "home_conference_id"]].set_axis(
                ["season", "team_id", "conf"], axis=1
            ),
            games[["season", "away_team_id", "away_conference_id"]].set_axis(
                ["season", "team_id", "conf"], axis=1
            ),
        ]
    ).dropna()
    return (
        x.groupby(["season", "team_id"])["conf"]
        .agg(lambda s: s.value_counts().index[0])
        .reset_index()
    )


def conference_anchor(finals: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """C_off / C_def for season s: mean season s-1 final rating of the OTHER teams in the
    team's season-s conference (leave-one-out; NaN for conferences of one)."""
    conf = conference_of(games)
    last = finals.assign(season=finals["season"] + 1)
    x = conf.merge(last, on=["team_id", "season"], how="left")
    g = x.groupby(["season", "conf"])
    n = g["o"].transform("count")
    so, sd = g["o"].transform("sum"), g["d"].transform("sum")
    has = x["o"].notna().astype(float)
    k = n - has
    x["conf_o"] = (so - x["o"].fillna(0)) / k.where(k > 0)
    x["conf_d"] = (sd - x["d"].fillna(0)) / k.where(k > 0)
    return x[["team_id", "season", "conf", "conf_o", "conf_d"]]


@dataclass
class PriorCoefficients:
    """state ('pre' | 'obs') -> side ('off' | 'def') -> {'c0', 'base', 'S', 'conf'}."""

    components: tuple[str, ...] = ("S",)
    pre: dict[str, dict[str, float]] = field(default_factory=dict)
    obs: dict[str, dict[str, float]] = field(default_factory=dict)
    n: dict[str, int] = field(default_factory=dict)


def fit_prior_coefficients(
    finals: pd.DataFrame,
    rho: float,
    seasons: list[int],
    strength: pd.DataFrame | None = None,
    preseason: pd.DataFrame | None = None,
    conf: pd.DataFrame | None = None,
    max_games: int = 10,
) -> PriorCoefficients:
    """Regress each team's end-of-season rating on [rho*last, components] (DEV only)."""
    comps = tuple(c for c, v in (("S", strength), ("conf", conf)) if v is not None)
    last = finals.assign(season=finals["season"] + 1).rename(columns={"o": "last_o", "d": "last_d"})
    base = finals.merge(last, on=["team_id", "season"], how="inner")
    base = base[base["season"].isin(seasons)]
    if conf is not None:
        base = base.merge(conf[["team_id", "season", "conf_o", "conf_d"]], on=["team_id", "season"])
    out = PriorCoefficients(components=comps)
    states: dict[str, pd.DataFrame] = {}
    if strength is not None:
        assert preseason is not None
        states["pre"] = base.merge(
            preseason[["team_id", "season", "pre_o", "pre_d"]], on=["team_id", "season"]
        ).rename(columns={"pre_o": "s_off", "pre_d": "s_def"})
        obs = strength[strength["known"].astype(bool) & (strength["games_seen"] <= max_games)]
        states["obs"] = base.merge(
            obs[["team_id", "season", "s_off", "s_def"]], on=["team_id", "season"]
        )
    else:
        states["pre"] = base
        states["obs"] = base
    for state, x in states.items():
        x = x.dropna()
        out.n[state] = len(x)
        coefs: dict[str, dict[str, float]] = {}
        for side, lc, sc, cc, tgt in (
            ("off", "last_o", "s_off", "conf_o", "o"),
            ("def", "last_d", "s_def", "conf_d", "d"),
        ):
            F = {"base": rho * x[lc]}
            if "S" in comps:
                F["S"] = x[sc]
            if "conf" in comps:
                F["conf"] = x[cc]
            Xf = pd.DataFrame(F)
            m = LinearRegression().fit(Xf, x[tgt])
            coefs[side] = {
                "c0": float(m.intercept_),
                **dict(zip(Xf.columns, map(float, m.coef_), strict=True)),
            }
        setattr(out, state, coefs)
    return out


class TeamPriorHook:
    """Callable for ``walkforward.replay_season``: day-specific priors for ``stats``."""

    def __init__(
        self,
        coefs: PriorCoefficients,
        strength: pd.DataFrame | None = None,
        preseason: pd.DataFrame | None = None,
        conf: pd.DataFrame | None = None,
        stats: tuple[str, ...] = ("eff",),
    ):
        self.coefs = coefs
        self.stats = stats
        self.pre = (
            preseason.set_index(["season", "team_id"])[["pre_o", "pre_d"]]
            if preseason is not None
            else None
        )
        self.conf = (
            conf.set_index(["season", "team_id"])[["conf_o", "conf_d"]]
            if conf is not None
            else None
        )
        self.strength = (
            {s: x for s, x in strength.groupby("season")} if strength is not None else {}
        )
        self._season_cache: dict[int, tuple[np.ndarray, ...]] = {}
        self._cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def _season_arrays(self, season: int, team_ids: list[str]) -> tuple[np.ndarray, ...]:
        if season not in self._season_cache:
            n = len(team_ids)
            po, pd_, co, cd = (np.full(n, np.nan) for _ in range(4))
            for src, a, b, c1, c2 in (
                (self.pre, po, pd_, "pre_o", "pre_d"),
                (self.conf, co, cd, "conf_o", "conf_d"),
            ):
                if src is not None and season in src.index.get_level_values(0):
                    p = src.loc[season].reindex(team_ids)
                    a[:], b[:] = p[c1].to_numpy(), p[c2].to_numpy()
            self._season_cache[season] = (po, pd_, co, cd)
        return self._season_cache[season]

    def _roster(self, season: int, cutoff: pd.Timestamp, team_ids: list[str]):
        key = (season, int(pd.Timestamp(cutoff).value))
        if key not in self._cache:
            n = len(team_ids)
            so, sd, known = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
            st = self.strength.get(season)
            if st is not None:
                cur = st[st["cutoff"] <= cutoff].drop_duplicates("team_id", keep="last")
                cur = cur[cur["known"].astype(bool)].set_index("team_id").reindex(team_ids)
                ok = cur["s_off"].notna().to_numpy()
                so[ok], sd[ok], known[ok] = (
                    cur["s_off"].to_numpy()[ok],
                    cur["s_def"].to_numpy()[ok],
                    1.0,
                )
            self._cache[key] = (so, sd, known)
        return self._cache[key]

    def __call__(self, season: int, cutoff: pd.Timestamp, pri: SeasonPriors) -> SeasonPriors:
        po, pd_, co, cd = self._season_arrays(season, pri.team_ids)
        comps = self.coefs.components
        if "S" in comps:
            so, sd, known = self._roster(season, cutoff, pri.team_ids)
            s_off = np.where(known > 0, so, po)
            s_def = np.where(known > 0, sd, pd_)
        else:
            known = np.zeros(len(pri.team_ids))
            s_off = s_def = np.zeros(len(pri.team_ids))
        off, deff = dict(pri.off), dict(pri.deff)
        for stat in self.stats:
            for side, base, s, c, store in (
                ("off", pri.off[stat], s_off, co, off),
                ("def", pri.deff[stat], s_def, cd, deff),
            ):
                vals = []
                for state in ("pre", "obs"):
                    k = getattr(self.coefs, state)[side]
                    v = k["c0"] + k["base"] * base
                    if "S" in comps:
                        v = v + k["S"] * s
                    if "conf" in comps:
                        v = v + k["conf"] * c
                    vals.append(v)
                new = np.where(known > 0, vals[1], vals[0])
                store[stat] = np.where(np.isfinite(new), new, base)
        return SeasonPriors(pri.team_ids, off, deff, pri.mu, pri.eta, pri.last_off, pri.last_def)


class DynamicConferenceHook(TeamPriorHook):
    """B16b: conference anchor that moves from last season's conference strength to
    the conference's CURRENT strength as cross-conference evidence accumulates:

        C_t(D) = (1 - w_c) * C_last + w_c * C_cur(D),   w_c = n_c / (n_c + k)

    C_cur(D) = leave-one-out mean of conference-mates' current eff ratings from the
    previous day's fits (information < D); n_c = cross-conference D-I games the
    conference's members completed before D. Coefficients are B15's (DEV-fitted).
    """

    wants_fits = True

    def __init__(
        self,
        coefs: PriorCoefficients,
        games: pd.DataFrame,
        k: float,
        strength: pd.DataFrame | None = None,
        preseason: pd.DataFrame | None = None,
        conf: pd.DataFrame | None = None,
        stats: tuple[str, ...] = ("eff",),
    ):
        super().__init__(coefs, strength, preseason, conf, stats)
        self.k = float(k)
        g = games[
            games["home_is_d1"]
            & games["away_is_d1"]
            & games["home_conference_id"].notna()
            & games["away_conference_id"].notna()
            & (games["home_conference_id"] != games["away_conference_id"])
        ]
        g = g.assign(t=pd.to_datetime(g["available_at"], utc=True).astype("int64"))
        self.cross: dict[tuple[int, object], np.ndarray] = {}
        for (s, c), x in pd.concat(
            [
                g[["season", "home_conference_id", "t"]].set_axis(["season", "c", "t"], axis=1),
                g[["season", "away_conference_id", "t"]].set_axis(["season", "c", "t"], axis=1),
            ]
        ).groupby(["season", "c"]):
            self.cross[(int(s), c)] = np.sort(x["t"].to_numpy())
        self.member = conference_of(games).set_index(["season", "team_id"])["conf"]

    def __call__(self, season, cutoff, pri, fits=None):  # type: ignore[override]
        if fits is None or "eff" not in fits or self.conf is None:
            return super().__call__(season, cutoff, pri)
        po, pd_, co, cd = self._season_arrays(season, pri.team_ids)
        mem = self.member.reindex(pd.MultiIndex.from_product([[season], pri.team_ids]))
        conf_ids = mem.to_numpy()
        f = fits["eff"]
        seen = f.n_obs > 0
        cut = int(pd.Timestamp(cutoff).tz_convert("UTC").value)
        cur_o, cur_d, w = np.full(len(co), np.nan), np.full(len(co), np.nan), np.zeros(len(co))
        df = pd.DataFrame(
            {"c": conf_ids, "o": np.where(seen, f.off, np.nan), "d": np.where(seen, f.deff, np.nan)}
        )
        grp = df.groupby("c")
        so, sd_, n = (
            grp["o"].transform("sum"),
            grp["d"].transform("sum"),
            grp["o"].transform("count"),
        )
        has = df["o"].notna()
        k_ = n - has.astype(int)
        cur_o = ((so - df["o"].fillna(0)) / k_.where(k_ > 0)).to_numpy()
        cur_d = ((sd_ - df["d"].fillna(0)) / k_.where(k_ > 0)).to_numpy()
        for i, c in enumerate(conf_ids):
            arr = self.cross.get((season, c))
            nc = int(np.searchsorted(arr, cut, side="left")) if arr is not None else 0
            w[i] = nc / (nc + self.k)
        dyn_o = np.where(np.isfinite(cur_o) & np.isfinite(co), (1 - w) * co + w * cur_o, co)
        dyn_d = np.where(np.isfinite(cur_d) & np.isfinite(cd), (1 - w) * cd + w * cur_d, cd)
        saved = self._season_cache[season]
        self._season_cache[season] = (po, pd_, dyn_o, dyn_d)
        try:
            return super().__call__(season, cutoff, pri)
        finally:
            self._season_cache[season] = saved
