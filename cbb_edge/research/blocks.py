"""PURE_BASKETBALL feature blocks for the wave-2 stacked arms.

Every block is a function of pregame state rows (and pure silver tables) only. All
blocks pass ``assert_pure_frame``. Sign conventions: ``*_off`` = points scored added,
``*_def`` = points ALLOWED added (positive = worse defense).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.model.arms import FACTORS, matchup_features
from cbb_edge.model.families import assert_pure_frame
from cbb_edge.ratings.adjusted import SHOT_STATS


def base_block(df: pd.DataFrame) -> pd.DataFrame:
    """B3 feature set (analytic projection + adjusted Four Factors / shot rates)."""
    f = matchup_features(df)
    X = f[["margin_an", "total_an", "poss", "L"]].copy()
    for x in FACTORS:
        if f"{x}_h" in f:
            X[f"{x}_h"] = f[f"{x}_h"]
            X[f"{x}_a"] = f[f"{x}_a"]
            X[f"{x}_diff_poss"] = (f[f"{x}_h"] - f[f"{x}_a"]) * f.poss / 100
            X[f"{x}_sum_poss"] = (f[f"{x}_h"] + f[f"{x}_a"]) * f.poss / 100
    return assert_pure_frame(X, "base_block")


def player_block(df: pd.DataFrame) -> pd.DataFrame:
    """B6: player-impact (RAPM) team strength for the expected rotation."""
    poss = df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"]
    X = pd.DataFrame(index=df.index)
    h_net = df["h_p_off"] - df["h_p_def"]
    a_net = df["a_p_off"] - df["a_p_def"]
    X["p_margin"] = poss / 100 * ((df["h_p_off"] + df["a_p_def"]) - (df["a_p_off"] + df["h_p_def"]))
    X["p_total"] = poss / 100 * ((df["h_p_off"] + df["a_p_def"]) + (df["a_p_off"] + df["h_p_def"]))
    known = (df["h_roster_known"] * df["a_roster_known"]).astype(float)
    X["p_margin_known"] = X["p_margin"] * known
    X["p_net_gap"] = h_net - a_net
    # disagreement between player-based and team-based strength (availability signal)
    team_net = (df["h_off_eff"] - df["h_def_eff"]) - (df["a_off_eff"] - df["a_def_eff"])
    X["p_minus_team"] = (h_net - a_net) - team_net
    X["roster_known"] = known
    X["depth_h"] = df["h_p_top5_share"].fillna(0.72)
    X["depth_a"] = df["a_p_top5_share"].fillna(0.72)
    return assert_pure_frame(X, "player_block")


def shot_block(df: pd.DataFrame) -> pd.DataFrame:
    """B7: opponent-adjusted shot-profile matchup (expected zone rates and accuracy)."""
    X = pd.DataFrame(index=df.index)
    L = df["L"]
    exp = {}
    for x in SHOT_STATS:
        if f"mu_{x}" not in df:
            continue
        for side, o, d, sgn in (("h", "h", "a", 1.0), ("a", "a", "h", -1.0)):
            exp[f"{x}_{side}"] = (
                df[f"mu_{x}"] + df[f"{o}_off_{x}"] + df[f"{d}_def_{x}"] + sgn * df[f"eta_{x}"] * L
            )
    for k, v in exp.items():
        X[k] = v
    # expected rim / mid points per 100 FGA, combining frequency and accuracy matchups
    for side in ("h", "a"):
        if f"rim_rate_{side}" in exp:
            X[f"rim_pts_{side}"] = 2 * exp[f"rim_rate_{side}"] * exp[f"rim_pct_{side}"] / 100
            X[f"mid_pts_{side}"] = 2 * exp[f"mid_rate_{side}"] * exp[f"mid_pct_{side}"] / 100
    if "rim_pts_h" in X:
        X["rim_pts_diff"] = X["rim_pts_h"] - X["rim_pts_a"]
        X["mid_pts_diff"] = X["mid_pts_h"] - X["mid_pts_a"]
        # rim offense vs rim defense interaction (regularized through the ridge layer)
        X["rim_mismatch_h"] = df["h_off_rim_rate"] * df["a_def_rim_pct"] / 100
        X["rim_mismatch_a"] = df["a_off_rim_rate"] * df["h_def_rim_pct"] / 100
    return assert_pure_frame(X, "shot_block")


def context_block(df: pd.DataFrame, ctx: pd.DataFrame) -> pd.DataFrame:
    """B8: rest, season phase, team-specific home court (prior seasons, shrunk)."""
    X = ctx.copy()
    X.index = df.index
    return assert_pure_frame(X, "context_block")


def combine(*blocks: pd.DataFrame) -> pd.DataFrame:
    X = pd.concat(blocks, axis=1)
    X = X.loc[:, ~X.columns.duplicated()]
    return X.replace([np.inf, -np.inf], np.nan)
