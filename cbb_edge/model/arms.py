"""Research arms: turn pregame rating states into game projections.

Arms (see research/REGISTRY.md):

B0  naive: home court + league-average total (both learned from prior seasons only).
B1  raw rolling efficiency + tempo (same shrinkage engine, opponent adjustment OFF).
B2  opponent-adjusted efficiency + tempo, analytic projection (no fitted layer).
B3  B2 + opponent-adjusted Four Factors / shot profile through an expanding-window
    ridge layer (trained only on seasons strictly before the predicted season).
B4  B3 with roster-continuity priors (engine run with ``roster_prior=True``).
B5  B4 + preregistered matchup interactions.
ELO points-based Elo dynamic benchmark (``cbb_edge.model.elo``).
MARKET free historical closing line; ENSEMBLE basketball model + market prior.

All fitted layers (ridge, win-probability link, uncertainty SDs) use expanding windows
over *previous* seasons, so a season's projections never see its own outcomes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression, Ridge

FACTORS = ("efg", "to", "orb", "ftr", "fg2", "fg3", "fg3a_rate")


def attach_games(states: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "game_id",
        "home_team_id",
        "away_team_id",
        "neutral_site",
        "home_score",
        "away_score",
        "completed",
        "start_time_utc",
        "game_date_et",
        "season_type",
        "conference_game",
        "tournament_id",
    ]
    df = states.merge(games[cols], on="game_id", how="left")
    df["L"] = (~df["neutral_site"].astype(bool)).astype(float)
    df["margin"] = (df["home_score"] - df["away_score"]).astype(float)
    df["total"] = (df["home_score"] + df["away_score"]).astype(float)
    df["home_win"] = (df["margin"] > 0).astype(float)
    df.loc[~df["completed"].astype(bool), ["margin", "total", "home_win"]] = np.nan
    return df


def matchup_features(df: pd.DataFrame) -> pd.DataFrame:
    """Analytic matchup projections from opponent-adjusted ratings."""
    f = pd.DataFrame(index=df.index)
    L = df["L"]
    f["eff_h"] = df.mu_eff + df.h_off_eff + df.a_def_eff + df.eta_eff * L
    f["eff_a"] = df.mu_eff + df.a_off_eff + df.h_def_eff - df.eta_eff * L
    f["poss"] = df.mu_tempo + df.h_off_tempo + df.a_off_tempo
    f["pts_h"] = f.eff_h * f.poss / 100
    f["pts_a"] = f.eff_a * f.poss / 100
    f["margin_an"] = f.pts_h - f.pts_a
    f["total_an"] = f.pts_h + f.pts_a
    for x in FACTORS:
        if f"mu_{x}" not in df:
            continue
        f[f"{x}_h"] = df[f"mu_{x}"] + df[f"h_off_{x}"] + df[f"a_def_{x}"] + df[f"eta_{x}"] * L
        f[f"{x}_a"] = df[f"mu_{x}"] + df[f"a_off_{x}"] + df[f"h_def_{x}"] - df[f"eta_{x}"] * L
    f["min_games_seen"] = np.minimum(df.h_games_seen, df.a_games_seen)
    f["L"] = L
    return f


def interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """B5 preregistered matchup interactions (H-B5-*, research/hypotheses)."""
    f = pd.DataFrame(index=df.index)
    # 3PA-heavy offense vs defense that allows / suppresses 3PA
    f["i_3pa_h"] = df.h_off_fg3a_rate * df.a_def_fg3a_rate / 100
    f["i_3pa_a"] = df.a_off_fg3a_rate * df.h_def_fg3a_rate / 100
    # offensive rebounding vs defensive rebounding mismatch
    f["i_orb_h"] = df.h_off_orb * df.a_def_orb / 100
    f["i_orb_a"] = df.a_off_orb * df.h_def_orb / 100
    # turnover pressure vs ball security
    f["i_to_h"] = df.h_off_to * df.a_def_to / 100
    f["i_to_a"] = df.a_off_to * df.h_def_to / 100
    # foul generation vs foul susceptibility
    f["i_ftr_h"] = df.h_off_ftr * df.a_def_ftr / 100
    f["i_ftr_a"] = df.a_off_ftr * df.h_def_ftr / 100
    # pace control: slow-vs-fast clash
    f["i_pace"] = df.h_off_tempo * df.a_off_tempo
    # interior: 2P offense vs 2P defense
    f["i_2p_h"] = df.h_off_fg2 * df.a_def_fg2 / 100
    f["i_2p_a"] = df.a_off_fg2 * df.h_def_fg2 / 100
    return f


@dataclass
class Projection:
    """Point projections for one arm (index-aligned with the input frame)."""

    margin: pd.Series
    total: pd.Series
    poss: pd.Series | None = None


def b0_naive(df: pd.DataFrame) -> Projection:
    """Home-court + league total, both from prior seasons (expanding window)."""
    m = pd.Series(np.nan, index=df.index)
    t = pd.Series(np.nan, index=df.index)
    for s in sorted(df.season.unique()):
        prior = df[(df.season < s) & df.margin.notna()]
        if not len(prior):
            continue
        hca = prior.loc[prior.L == 1, "margin"].mean()
        tot = prior[prior.season == prior.season.max()]["total"].mean()
        cur = df.season == s
        m[cur] = hca * df.loc[cur, "L"]
        t[cur] = tot
    return Projection(m, t)


def analytic(df: pd.DataFrame) -> Projection:
    f = matchup_features(df)
    return Projection(f.margin_an, f.total_an, f.poss)


def _stack(
    df: pd.DataFrame, X: pd.DataFrame, target: str, alpha: float, min_train_seasons: int
) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    for s in sorted(df.season.unique()):
        tr = (df.season < s) & df[target].notna() & X.notna().all(axis=1)
        if df.loc[tr, "season"].nunique() < min_train_seasons:
            continue
        model = Ridge(alpha=alpha).fit(X[tr], df.loc[tr, target])
        cur = (df.season == s) & X.notna().all(axis=1)
        out[cur] = model.predict(X[cur])
    return out


def stacked(
    df: pd.DataFrame, *, interactions: bool = False, alpha: float = 10.0, min_train_seasons: int = 3
) -> Projection:
    f = matchup_features(df)
    base = ["margin_an", "total_an", "poss", "L"]
    fac = [c for c in f.columns if any(c.startswith(x + "_") for x in FACTORS)]
    X = f[base + fac].copy()
    # factor-driven margin/total components scaled by possessions
    for x in FACTORS:
        if f"{x}_h" in f:
            X[f"{x}_diff_poss"] = (f[f"{x}_h"] - f[f"{x}_a"]) * f.poss / 100
            X[f"{x}_sum_poss"] = (f[f"{x}_h"] + f[f"{x}_a"]) * f.poss / 100
    if interactions:
        X = pd.concat([X, interaction_features(df)], axis=1)
    m = _stack(df, X, "margin", alpha, min_train_seasons)
    t = _stack(df, X, "total", alpha, min_train_seasons)
    return Projection(m, t, f.poss)


def win_prob(df: pd.DataFrame, margin: pd.Series) -> pd.Series:
    """Logistic link P(home win) = sigma(b * margin + c), fitted on prior seasons."""
    p = pd.Series(np.nan, index=df.index)
    for s in sorted(df.season.unique()):
        tr = (df.season < s) & df.home_win.notna() & margin.notna()
        cur = (df.season == s) & margin.notna()
        if tr.sum() < 500:
            # fallback: normal with SD 11 (typical college margin SD)
            p[cur] = norm.cdf(margin[cur] / 11.0)
            continue
        lr = LogisticRegression(C=1e6).fit(margin[tr].to_frame(), df.loc[tr, "home_win"])
        p[cur] = lr.predict_proba(margin[cur].to_frame())[:, 1]
    return p.clip(1e-4, 1 - 1e-4)


def residual_sd(
    df: pd.DataFrame, pred: pd.Series, target: str, buckets: tuple[int, ...] = (0, 3, 6, 11, 99)
) -> pd.Series:
    """Predictive SD by early-season bucket (min games seen), from prior seasons."""
    sd = pd.Series(np.nan, index=df.index)
    mg = np.minimum(df.h_games_seen, df.a_games_seen)
    b = pd.cut(mg, list(buckets), right=False, labels=False)
    for s in sorted(df.season.unique()):
        tr = (df.season < s) & df[target].notna() & pred.notna()
        if tr.sum() < 500:
            continue
        res = df.loc[tr, target] - pred[tr]
        by = res.groupby(b[tr]).std()
        cur = df.season == s
        sd[cur] = b[cur].map(by).fillna(res.std())
    return sd


ARMS: dict[str, Callable[[pd.DataFrame], Projection]] = {
    "B0": b0_naive,
    "B1": analytic,  # applied to the adjust=False engine states
    "B2": analytic,
    "B3": stacked,
    "B4": stacked,  # applied to roster-prior engine states
    "B5": lambda df: stacked(df, interactions=True),
}
