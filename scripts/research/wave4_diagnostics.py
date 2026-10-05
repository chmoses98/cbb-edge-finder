"""Wave-4 PURE diagnostics on B15 (pure-0.3.0) walk-forward predictions. No market data.

Outputs research/wave4/diagnostics.json:

* conference transition: residual decomposition (margin / total / possessions / home pts
  / away pts bias, RMSE) by conference vs non-conference, first meeting vs rematch,
  conference game number, season game number, days since previous meeting, venue,
  current-season conference-network links, and by games-seen 15-25 x game type;
* rematch effects: second meeting vs first (pace, margin, home-court asymmetry,
  favourite performance) and whether the first meeting's residual predicts the second's;
* extreme pace: total error split into possession error, PPP error, interaction,
  overtime and last-two-minutes scoring, by projected-pace decile;
* overtime audit: target variance with / without OT, regulation vs final margin;
* late-game fouling: last-2-minute points vs projected closeness and FT skill;
* strength compression: realized vs projected margin slope by projected-strength tier;
* shooting luck: split-half reliability of team 3P%, opponent 3P%, FT%, 2P% and the
  attempts at which reliability reaches 0.5.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.backtest.residuals import actual_side_stats
from cbb_edge.data.http import data_dir
from cbb_edge.model.pure import load_pure_silver

OUT = Path("research/wave4/diagnostics.json")
W3 = data_dir() / "research" / "wave3"
VALID = list(range(2015, 2025))


def _r(e) -> float:
    e = np.asarray(e, dtype=float)
    return float(np.sqrt(np.mean(e**2))) if len(e) else float("nan")


def frame() -> pd.DataFrame:
    games, tg = load_pure_silver()
    pp = pd.read_parquet(W3 / "pure_predictions.parquet")[
        [
            "game_id",
            "season",
            "B15_margin",
            "B15_total",
            "B15_home_wp",
            "h_games_seen",
            "a_games_seen",
        ]
    ]
    st = pd.read_parquet(W3 / "states_b15.parquet")[
        [
            "game_id",
            "mu_tempo",
            "h_off_tempo",
            "a_off_tempo",
            "h_off_eff",
            "h_def_eff",
            "a_off_eff",
            "a_def_eff",
        ]
    ]
    d = pp.merge(st, on="game_id").merge(
        games[
            [
                "game_id",
                "start_time_utc",
                "game_date_et",
                "home_team_id",
                "away_team_id",
                "neutral_site",
                "conference_game",
                "home_conference_id",
                "away_conference_id",
                "home_score",
                "away_score",
                "n_ot",
                "season_type",
                "tournament_id",
                "venue_id",
            ]
        ],
        on="game_id",
    )
    act = actual_side_stats(tg, games)[["game_id", "act_poss"]]
    d = d.merge(act, on="game_id", how="left")
    d["margin"] = (d["home_score"] - d["away_score"]).astype(float)
    d["total"] = (d["home_score"] + d["away_score"]).astype(float)
    d["resid"] = d["margin"] - d["B15_margin"]
    d["tresid"] = d["total"] - d["B15_total"]
    d["pred_poss"] = d["mu_tempo"] + d["h_off_tempo"] + d["a_off_tempo"]
    d["presid"] = d["act_poss"] - d["pred_poss"]
    d["hresid"] = d["home_score"] - (d["B15_total"] + d["B15_margin"]) / 2
    d["aresid"] = d["away_score"] - (d["B15_total"] - d["B15_margin"]) / 2
    d["L"] = (~d["neutral_site"].astype(bool)).astype(int)
    d = d.sort_values("start_time_utc").reset_index(drop=True)
    # meeting index for the (unordered) pair within the season (earlier tips only)
    pair = [tuple(sorted(x)) for x in zip(d["home_team_id"], d["away_team_id"], strict=True)]
    d["pair"] = pair
    d["meeting_no"] = d.groupby(["season", "pair"]).cumcount() + 1
    prev_t = d.groupby(["season", "pair"])["start_time_utc"].shift(1)
    d["days_since_meeting"] = (pd.to_datetime(d["start_time_utc"]) - pd.to_datetime(prev_t)).dt.days
    prev_home = d.groupby(["season", "pair"])["home_team_id"].shift(1)
    d["venue_swap"] = (prev_home.notna() & (prev_home != d["home_team_id"])).astype(int)
    same = prev_home == d["home_team_id"]
    for c in ("resid", "tresid", "presid"):
        prev = d.groupby(["season", "pair"])[c].shift(1)
        # margin residual re-oriented to the current home team; totals need no orientation
        d[f"prev_{c}"] = np.where(same, prev, -prev) if c == "resid" else prev
    # team game numbers
    long = pd.concat(
        [
            d[["game_id", "season", "start_time_utc", "home_team_id", "conference_game"]]
            .rename(columns={"home_team_id": "team"})
            .assign(side="h"),
            d[["game_id", "season", "start_time_utc", "away_team_id", "conference_game"]]
            .rename(columns={"away_team_id": "team"})
            .assign(side="a"),
        ]
    ).sort_values("start_time_utc")
    long["game_no"] = long.groupby(["season", "team"]).cumcount() + 1
    long["conf_no"] = (
        long.groupby(["season", "team"])["conference_game"]
        .cumsum()
        .where(long["conference_game"].astype(bool), 0)
    )
    for side in ("h", "a"):
        x = long[long["side"] == side].set_index("game_id")
        d[f"{side}_game_no"] = d["game_id"].map(x["game_no"])
        d[f"{side}_conf_no"] = d["game_id"].map(x["conf_no"])
    d["season_game_no"] = d[["h_game_no", "a_game_no"]].min(axis=1)
    d["conf_game_no"] = d[["h_conf_no", "a_conf_no"]].min(axis=1)
    d["post"] = (d["season_type"].fillna(2) == 3) | d["tournament_id"].notna()
    return d[d["B15_margin"].notna() & d["margin"].notna()].reset_index(drop=True)


def slice_stats(x: pd.DataFrame) -> dict[str, float]:
    return {
        "n": len(x),
        "rmse": _r(x["resid"]),
        "margin_bias": float(x["resid"].mean()),
        "fav_bias": float((x["resid"] * np.sign(x["B15_margin"]).replace(0, 1)).mean()),
        "total_bias": float(x["tresid"].mean()),
        "poss_bias": float(x["presid"].mean()),
        "home_pts_bias": float(x["hresid"].mean()),
        "away_pts_bias": float(x["aresid"].mean()),
        "total_rmse": _r(x["tresid"]),
    }


def by(d: pd.DataFrame, key, min_n: int = 200) -> list[dict]:
    out = []
    for k, x in d.groupby(key, observed=True):
        if len(x) >= min_n:
            out.append(
                {
                    "slice": str(k),
                    **{
                        a: round(b, 3) if isinstance(b, float) else b
                        for a, b in slice_stats(x).items()
                    },
                }
            )
    return out


def conference_transition(d: pd.DataFrame) -> dict:
    v = d[d["season"].isin(VALID) & ~d["post"]].copy()
    v["gtype"] = np.where(
        v["conference_game"].astype(bool),
        np.where(v["meeting_no"] > 1, "conf_rematch", "conf_first"),
        "nonconf",
    )
    v["gs"] = np.minimum(v["h_games_seen"], v["a_games_seen"])
    v["gs_b"] = pd.cut(v["gs"], [-1, 5, 10, 14, 17, 20, 23, 26, 40])
    v["conf_no_b"] = pd.cut(v["conf_game_no"], [-1, 0, 1, 3, 6, 10, 14, 30])
    v["season_no_b"] = pd.cut(v["season_game_no"], [0, 5, 10, 15, 18, 21, 24, 28, 40])
    v["days_b"] = pd.cut(v["days_since_meeting"], [-1, 14, 28, 42, 60, 200])
    return {
        "by_game_type": by(v, "gtype"),
        "by_games_seen": by(v, "gs_b"),
        "by_games_seen_x_type": by(v, ["gs_b", "gtype"]),
        "by_conference_game_number": by(v, "conf_no_b"),
        "by_season_game_number": by(v, "season_no_b"),
        "by_days_since_previous_meeting": by(v[v["meeting_no"] > 1], "days_b"),
        "by_venue_x_type": by(v, ["L", "gtype"]),
        "share_conference_by_games_seen": v.groupby("gs_b", observed=True)["conference_game"]
        .mean()
        .round(3)
        .astype(str)
        .to_dict(),
    }


def rematch(d: pd.DataFrame) -> dict:
    v = d[d["season"].isin(VALID) & ~d["post"] & (d["meeting_no"] == 2)].dropna(
        subset=["prev_resid"]
    )
    out = {"n_second_meetings": len(v)}
    for c in ("resid", "tresid", "presid"):
        ok = v[f"prev_{c}"].notna() & v[c].notna()
        a, b = v.loc[ok, f"prev_{c}"], v.loc[ok, c]
        out[f"corr_prev_{c}"] = float(np.corrcoef(a, b)[0, 1])
        out[f"slope_prev_{c}"] = float(np.polyfit(a, b, 1)[0])
    out["second_meeting"] = slice_stats(v)
    out["second_meeting_venue_swap"] = slice_stats(v[v["venue_swap"] == 1])
    out["second_meeting_same_venue"] = slice_stats(v[v["venue_swap"] == 0])
    return out


def pace(d: pd.DataFrame, pbp: pd.DataFrame) -> dict:
    v = d[d["season"].isin(VALID) & d["act_poss"].notna()].merge(pbp, on="game_id", how="left")
    P, Ph = v["act_poss"], v["pred_poss"]
    r = v["total"] / P
    rh = v["B15_total"] / Ph
    v["e_poss"] = (P - Ph) * rh
    v["e_ppp"] = Ph * (r - rh)
    v["e_int"] = (P - Ph) * (r - rh)
    v["dec"] = pd.qcut(v["pred_poss"], 10, labels=False)
    rows = []
    for k, x in v.groupby("dec"):
        rows.append(
            {
                "decile": int(k),
                "n": len(x),
                "pred_poss": round(float(x["pred_poss"].mean()), 1),
                "total_rmse": round(_r(x["tresid"]), 3),
                "total_bias": round(float(x["tresid"].mean()), 3),
                "poss_bias": round(float(x["presid"].mean()), 3),
                "ms_poss": round(float((x["e_poss"] ** 2).mean()), 2),
                "ms_ppp": round(float((x["e_ppp"] ** 2).mean()), 2),
                "ot_share": round(float((x["n_ot"] > 0).mean()), 4),
                "ot_pts_mean": round(float((x["ot_home"] + x["ot_away"]).fillna(0).mean()), 3),
                "last2_mean": round(float(x["last2_pts"].mean()), 3),
            }
        )
    reg = v[v["n_ot"] == 0]
    return {
        "by_projected_pace_decile": rows,
        "total_rmse_all": _r(v["tresid"]),
        "total_rmse_regulation_games": _r(reg["tresid"]),
        "total_rmse_ot_games": _r(v.loc[v["n_ot"] > 0, "tresid"]),
        "share_ms_poss": float((v["e_poss"] ** 2).mean() / (v["tresid"] ** 2).mean()),
        "share_ms_ppp": float((v["e_ppp"] ** 2).mean() / (v["tresid"] ** 2).mean()),
        "corr_poss_err_ppp_err": float(np.corrcoef(P - Ph, r - rh)[0, 1]),
    }


def overtime(d: pd.DataFrame, pbp: pd.DataFrame) -> dict:
    v = d[d["season"].isin(VALID)].merge(pbp, on="game_id", how="inner")
    ok = (v["reg_home"] + v["ot_home"] == v["home_score"]) & (
        v["reg_away"] + v["ot_away"] == v["away_score"]
    )
    v = v[ok]
    v["reg_margin"] = (v["reg_home"] - v["reg_away"]).astype(float)
    ot = v["n_ot"] > 0
    return {
        "n": len(v),
        "ot_share": float(ot.mean()),
        "margin_var_final": float(v["margin"].var()),
        "margin_var_regulation": float(v["reg_margin"].var()),
        "rmse_vs_final": _r(v["resid"]),
        "rmse_vs_regulation": _r(v["reg_margin"] - v["B15_margin"]),
        "ot_games_mean_abs_final_margin": float(v.loc[ot, "margin"].abs().mean()),
        "ot_games_fav_wins": float(
            (np.sign(v.loc[ot, "margin"]) == np.sign(v.loc[ot, "B15_margin"])).mean()
        ),
        "ot_games_mean_total_added": float((v.loc[ot, "ot_home"] + v.loc[ot, "ot_away"]).mean()),
        "total_rmse_ot_games": _r(v.loc[ot, "tresid"]),
        "total_rmse_non_ot": _r(v.loc[~ot, "tresid"]),
    }


def late_fouling(d: pd.DataFrame, pbp: pd.DataFrame) -> dict:
    v = d[d["season"].isin(VALID)].merge(pbp, on="game_id", how="inner")
    v = v[v["last2_pts"].between(0, 40) & (v["n_ot"] == 0)]
    v["close2"] = (v["at2_home"] - v["at2_away"]).abs()
    v["proj_close"] = pd.cut(v["B15_margin"].abs(), [0, 3, 6, 10, 15, 60])
    v["close_b"] = pd.cut(v["close2"], [-1, 3, 6, 10, 20, 100])
    return {
        "last2_pts_by_score_gap_at_2min": v.groupby("close_b", observed=True)["last2_pts"]
        .agg(["mean", "size"])
        .round(2)
        .reset_index()
        .astype(str)
        .to_dict("records"),
        "last2_pts_by_projected_margin": v.groupby("proj_close", observed=True)["last2_pts"]
        .agg(["mean", "size"])
        .round(2)
        .reset_index()
        .astype(str)
        .to_dict("records"),
        "total_resid_by_projected_margin": v.groupby("proj_close", observed=True)["tresid"]
        .agg(["mean", "size"])
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records"),
        "corr_last2_with_total_resid": float(np.corrcoef(v["last2_pts"], v["tresid"])[0, 1]),
    }


def compression(d: pd.DataFrame) -> dict:
    v = d[d["season"].isin(VALID)].copy()
    v["h_net"] = v["h_off_eff"] - v["h_def_eff"]
    v["a_net"] = v["a_off_eff"] - v["a_def_eff"]
    q = pd.concat([v["h_net"], v["a_net"]]).quantile([0.05, 0.10, 0.90, 0.95]).to_dict()
    tiers = {
        "top5": v["h_net"] >= q[0.95],
        "top10": v["h_net"] >= q[0.90],
        "bottom10": v["h_net"] <= q[0.10],
        "bottom5": v["h_net"] <= q[0.05],
    }
    out = {}
    for name, m in tiers.items():
        x = v[m]
        out[f"home_{name}"] = {
            "n": int(m.sum()),
            "mean_resid": float(x["resid"].mean()),
            "slope_real_on_proj": float(np.polyfit(x["B15_margin"], x["margin"], 1)[0]),
        }
    sw = v[(v["h_net"] >= q[0.90]) & (v["a_net"] <= q[0.10])]
    ws = v[(v["h_net"] <= q[0.10]) & (v["a_net"] >= q[0.90])]
    out["strong_home_vs_weak"] = {"n": len(sw), "mean_resid": float(sw["resid"].mean())}
    out["weak_home_vs_strong"] = {"n": len(ws), "mean_resid": float(ws["resid"].mean())}
    v["pb"] = pd.cut(v["B15_margin"], [-80, -25, -15, -8, -3, 3, 8, 15, 25, 80])
    out["calibration_by_projected_margin"] = (
        v.groupby("pb", observed=True)
        .agg(
            n=("resid", "size"),
            proj=("B15_margin", "mean"),
            real=("margin", "mean"),
            resid=("resid", "mean"),
        )
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records")
    )
    out["overall_slope_real_on_proj"] = float(np.polyfit(v["B15_margin"], v["margin"], 1)[0])
    return out


def shooting_luck(tg: pd.DataFrame) -> dict:
    """Split-half (odd/even game) reliability of team shooting percentages."""
    x = tg[tg["season"].isin(VALID) & tg["team_is_d1"]].sort_values("start_time_utc").copy()
    x["k"] = x.groupby(["season", "team_id"]).cumcount() % 2
    out = {}
    specs = {
        "fg3": ("fg3m", "fg3a"),
        "opp_fg3": ("opp_fg3m", "opp_fg3a"),
        "ft": ("ftm", "fta"),
        "fg2": (None, None),
        "opp_fg2": (None, None),
    }
    x["fg2m"] = x["fgm"] - x["fg3m"]
    x["fg2a"] = x["fga"] - x["fg3a"]
    x["opp_fg2m"] = x["opp_fgm"] - x["opp_fg3m"]
    x["opp_fg2a"] = x["opp_fga"] - x["opp_fg3a"]
    specs["fg2"] = ("fg2m", "fg2a")
    specs["opp_fg2"] = ("opp_fg2m", "opp_fg2a")
    for name, (mk, at) in specs.items():
        h = x.groupby(["season", "team_id", "k"])[[mk, at]].sum().unstack("k")
        p0 = h[(mk, 0)] / h[(at, 0)]
        p1 = h[(mk, 1)] / h[(at, 1)]
        n_half = float(((h[(at, 0)] + h[(at, 1)]) / 2).mean())
        rel = float(np.corrcoef(p0, p1)[0, 1])
        # Spearman-Brown: reliability with n attempts r(n) = n/(n + k*), k* = n_half*(1-rel)/rel
        kstar = n_half * (1 - rel) / rel if rel > 0 else float("inf")
        out[name] = {
            "split_half_reliability": round(rel, 3),
            "attempts_per_half": round(n_half, 1),
            "attempts_for_reliability_0.5": round(kstar, 1),
        }
    return out


def _keys(x):
    if isinstance(x, dict):
        return {str(k): _keys(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_keys(v) for v in x]
    return x


def main() -> None:
    d = frame()
    pbp = pd.read_parquet(data_dir() / "silver" / "pbp_game.parquet")
    _, tg = load_pure_silver()
    rep = {
        "conference_transition": conference_transition(d),
        "rematch": rematch(d),
        "extreme_pace": pace(d, pbp),
        "overtime": overtime(d, pbp),
        "late_game_fouling": late_fouling(d, pbp),
        "strength_compression": compression(d),
        "shooting_luck": shooting_luck(tg),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rep = _keys(rep)
    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str)[:20000])


if __name__ == "__main__":
    main()
