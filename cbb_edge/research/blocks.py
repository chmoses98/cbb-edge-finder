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


# ---- wave 3 ---------------------------------------------------------------------
def preseason_block(df: pd.DataFrame, pre: pd.DataFrame) -> pd.DataFrame:
    """Roster-transformation features, faded out as each team's games accumulate."""
    cols = ["ret_min", "ret_impact", "lost_impact", "ret_top3", "pre_net"]
    p = pre[["team_id", "season", *cols]]
    h = df[["home_team_id", "season"]].merge(
        p, left_on=["home_team_id", "season"], right_on=["team_id", "season"], how="left"
    )
    a = df[["away_team_id", "season"]].merge(
        p, left_on=["away_team_id", "season"], right_on=["team_id", "season"], how="left"
    )
    wh = np.exp(-df["h_games_seen"].to_numpy() / 6.0)
    wa = np.exp(-df["a_games_seen"].to_numpy() / 6.0)
    X = pd.DataFrame(index=df.index)
    for c in cols:
        hv = h[c].fillna(h[c].mean()).to_numpy()
        av = a[c].fillna(a[c].mean()).to_numpy()
        X[f"pre_{c}_diff_w"] = hv * wh - av * wa
    X["pre_ret_min_h_w"] = h["ret_min"].fillna(0.5).to_numpy() * wh
    X["pre_ret_min_a_w"] = a["ret_min"].fillna(0.5).to_numpy() * wa
    return assert_pure_frame(X, "preseason_block")


def venue_block(df: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """B14v: measurable venue context. Each team's home city/state = modal venue of its
    true home games in the previous three seasons (prior seasons only). A neutral-site
    game in the designated home (away) team's home state is +1 (-1); same for city.
    Plus a home-court x strength-gap interaction (strong-team x venue)."""
    home = games[~games["neutral_site"].astype(bool)].dropna(subset=["venue_state"])
    X = pd.DataFrame(0.0, index=df.index, columns=["semi_state", "semi_city"])
    for s in sorted(df["season"].unique()):
        past = home[home["season"].between(s - 3, s - 1)]
        if past.empty:
            continue
        loc = past.groupby("home_team_id").agg(
            st=("venue_state", lambda v: v.value_counts().index[0]),
            ct=("venue_city", lambda v: v.value_counts().index[0]),
        )
        cur = (df["season"] == s) & (df["L"] == 0)
        x = df.loc[cur]
        hs = x["home_team_id"].map(loc["st"])
        as_ = x["away_team_id"].map(loc["st"])
        hc = x["home_team_id"].map(loc["ct"])
        ac = x["away_team_id"].map(loc["ct"])
        vs, vc = x["venue_state"], x["venue_city"]
        X.loc[cur, "semi_state"] = (vs == hs).astype(float) - (vs == as_).astype(float)
        X.loc[cur, "semi_city"] = (vc == hc).astype(float) - (vc == ac).astype(float)
    m = matchup_features(df)["margin_an"]
    X["L_x_margin_an"] = df["L"] * m
    return assert_pure_frame(X, "venue_block")


def mismatch_block(df: pd.DataFrame) -> pd.DataFrame:
    """B13: piecewise-linear extension of the analytic margin beyond +-15 points."""
    m = matchup_features(df)["margin_an"]
    X = pd.DataFrame(index=df.index)
    X["margin_ext_pos"] = np.maximum(m - 15.0, 0.0)
    X["margin_ext_neg"] = np.minimum(m + 15.0, 0.0)
    return assert_pure_frame(X, "mismatch_block")


def shooting_block(
    df: pd.DataFrame, sf: pd.DataFrame, fill: dict[str, float] | None = None
) -> pd.DataFrame:
    """B17: player-skill expected shooting (heavily shrunk) + realized-minus-skill gap.

    Missing skills (a team with no earlier D-I history) get ``fill[<side>_sk<t>]``
    (pure-0.5.0+: fixed DEV means, reproducible live) or, by default (pure-0.4.0), the
    mean of the frame."""
    x = df[["game_id"]].merge(sf, on="game_id", how="left")
    X = pd.DataFrame(index=df.index)
    L = df["L"]
    for side, o, dd, sgn in (("h", "h", "a", 1.0), ("a", "a", "h", -1.0)):
        for t in ("3", "ft", "2"):
            v = x[f"{side}_sk{t}"].to_numpy(dtype=float)
            fv = np.nanmean(v) if fill is None else fill[f"{side}_sk{t}"]
            X[f"sk{t}_{side}"] = np.where(np.isfinite(v), v, fv) * 100
        rate = df["mu_fg3a_rate"] + df[f"{o}_off_fg3a_rate"] + df[f"{dd}_def_fg3a_rate"]
        X[f"exp3pts_{side}"] = 3 * rate / 100 * X[f"sk3_{side}"]
        eng3 = df["mu_fg3"] + df[f"{o}_off_fg3"] + df[f"{dd}_def_fg3"] + sgn * df["eta_fg3"] * L
        X[f"luck3_{side}"] = eng3 - X[f"sk3_{side}"]
    X["sk3_diff"] = X["sk3_h"] - X["sk3_a"]
    X["exp3pts_diff"] = X["exp3pts_h"] - X["exp3pts_a"]
    return assert_pure_frame(X, "shooting_block")


# ------------------------------------------------------------------ Wave 5 -----------
def possession_frame(
    df: pd.DataFrame,
    prof: pd.DataFrame,
    de: pd.DataFrame,
    lg: pd.DataFrame,
    fill: dict[str, float],
) -> pd.DataFrame:
    """Join pregame player-derived team profiles (``possession.team_profiles``), each
    side's defensive allowed excess as DEFENDER (``possession.defense_excess``) and the
    league season-to-date zone means onto the game rows. Missing values -> ``fill``
    (DEV league means, fixed)."""
    pcols = [c for c in prof.columns if c not in ("game_id", "team_id", "season")]
    dcols = [c for c in de.columns if c.startswith("def_") and c != "def_id"]
    out = df[["game_id", "home_team_id", "away_team_id", "game_date_et", "season"]].copy()
    for side, col in (("h", "home_team_id"), ("a", "away_team_id")):
        pp = prof[["game_id", "team_id", *pcols]].rename(
            columns={"team_id": col, **{c: f"{side}_{c}" for c in pcols}}
        )
        out = out.merge(pp, on=["game_id", col], how="left")
        dd = de[["game_id", "def_id", *dcols]].rename(
            columns={"def_id": col, **{c: f"{side}_{c}" for c in dcols}}
        )
        out = out.merge(dd, on=["game_id", col], how="left")
    out = out.merge(lg, on=["season", "game_date_et"], how="left")
    for c in out.columns:
        if c[:2] in ("h_", "a_") and c not in ("home_team_id", "away_team_id"):
            out[c] = out[c].fillna(fill.get(c[2:], 0.0))
    for c in ("lg_rim", "lg_t3"):
        out[c] = out[c].fillna(fill.get(c[3:], 0.0) if c[3:] in fill else out[c].mean())
    out.index = df.index
    return out


def _matchup_mix(pf: pd.DataFrame, side: str, opp: str) -> dict[str, pd.Series]:
    rim = (pf[f"{side}_x_rim"] + pf[f"{opp}_def_rim"]).clip(0.02, 0.9)
    t3 = (pf[f"{side}_x_t3"] + pf[f"{opp}_def_t3"]).clip(0.02, 0.9)
    j2 = pf[f"{side}_x_j2"].clip(0.02, 0.9)
    z = rim + t3 + j2
    return {"rim": rim / z, "t3": t3 / z, "j2": j2 / z}


def b21_block(df: pd.DataFrame, pf: pd.DataFrame) -> pd.DataFrame:
    """B21: player shot selection x finishing skill x opponent suppression (WAVE5.md)."""
    X = pd.DataFrame(index=df.index)
    poss = df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"]
    mix = {}
    for side, opp in (("h", "a"), ("a", "h")):
        m = _matchup_mix(pf, side, opp)
        mix[side] = m
        k_rim = pf[f"{side}_xk_rim"] + pf[f"{opp}_def_rimpct"]
        X[f"xpps_{side}"] = (
            2 * m["rim"] * k_rim
            + 2 * m["j2"] * pf[f"{side}_xk_j2"]
            + 3 * m["t3"] * pf[f"{side}_xk_t3"]
        )
        X[f"xrim_{side}"] = m["rim"] - pf["lg_rim"]
        X[f"x3r_{side}"] = m["t3"] - pf["lg_t3"]
        X[f"xftr_{side}"] = pf[f"{side}_x_ftr"] + pf[f"{opp}_def_ftr"]
        X[f"def_rimpct_ex_{side}"] = pf[f"{side}_def_rimpct"]
    X["d_xpps_poss"] = poss / 100 * (X["xpps_h"] - X["xpps_a"])
    X["s_xpps_poss"] = poss / 100 * (X["xpps_h"] + X["xpps_a"])
    X["c_rim"] = (mix["h"]["rim"] + mix["a"]["rim"]) / 2 - pf["lg_rim"]
    X["c_t3"] = (mix["h"]["t3"] + mix["a"]["t3"]) / 2 - pf["lg_t3"]
    return assert_pure_frame(X, "b21_block")


def b22_block(df: pd.DataFrame, pf: pd.DataFrame) -> pd.DataFrame:
    """B22: player possession-component profile (WAVE5.md, the enumerated 11 features)."""
    X = pd.DataFrame(index=df.index)
    for side in ("h", "a"):
        for c in ("to", "orb", "drb"):
            X[f"x{c}_{side}"] = pf[f"{side}_x_{c}"]
    X["orb_edge_h"] = pf["h_x_orb"] - pf["a_x_drb"]
    X["orb_edge_a"] = pf["a_x_orb"] - pf["h_x_drb"]
    X["to_edge_h"] = pf["h_x_to"] + pf["a_x_stl"]
    X["to_edge_a"] = pf["a_x_to"] + pf["h_x_stl"]
    X["foul_edge"] = pf["a_x_pf"] - pf["h_x_pf"]
    return assert_pure_frame(X, "b22_block")


def b24_block(df: pd.DataFrame, pf: pd.DataFrame) -> pd.DataFrame:
    """B24: B21 + B22 + five preregistered interactions per side."""
    X = pd.concat([b21_block(df, pf), b22_block(df, pf)], axis=1)
    for side in ("h", "a"):
        for c in ("spacing", "handler", "rimprot", "orbsize", "hhi"):
            X[f"i_{c}_{side}"] = pf[f"{side}_i_{c}"]
    return assert_pure_frame(X, "b24_block")


def b23_block(df_b19h: pd.DataFrame, df_b12: pd.DataFrame) -> pd.DataFrame:
    """B23: absence-driven part of the player signal (B19h minus B12 player margin)."""
    a = player_block(df_b19h)
    b = player_block(df_b12).set_axis(df_b12["game_id"].to_numpy())
    b = b.reindex(df_b19h["game_id"].to_numpy()).set_axis(df_b19h.index)
    X = pd.DataFrame(index=df_b19h.index)
    X["avail_delta"] = (a["p_margin"] - b["p_margin"]).fillna(0.0)
    X["avail_delta_total"] = (a["p_total"] - b["p_total"]).fillna(0.0)
    return assert_pure_frame(X, "b23_block")


def combine(*blocks: pd.DataFrame) -> pd.DataFrame:
    X = pd.concat(blocks, axis=1)
    X = X.loc[:, ~X.columns.duplicated()]
    return X.replace([np.inf, -np.inf], np.nan)
