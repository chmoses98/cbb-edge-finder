"""Wave-3 PURE diagnostics on the incumbent (B9 / pure-0.2.0) walk-forward predictions.

No market data. Outputs research/wave3/diagnostics.json with:

* rotation prior     – preseason expected returning minutes vs realized (team level) and
                       P(return) calibration (player level)
* returning prod.    – does preseason returning production explain the change in team
                       strength, and do B9's early-season residuals depend on it?
* transfers          – early-season residual by realized share of minutes from incoming
                       transfers (hindsight slice, diagnostic only)
* extreme mismatches – residual (favourite's perspective) by projected margin
* neutral sites      – true neutral vs semi-home (venue in one team's home state) vs
                       designated-home-in-own-city, from venue city/state (measurable)
* strong team x venue– home residual by home-team strength tercile
* network bridging   – early-season residual by how many earlier games this season link
                       the two teams' conferences, plus season connectivity curves
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players import preseason, team_prior

OUT = Path("research/wave3/diagnostics.json")
W2 = data_dir() / "research" / "wave2"
VALID = list(range(2015, 2025))


def _r(e: pd.Series) -> float:
    return float(np.sqrt(np.mean(np.square(e)))) if len(e) else float("nan")


def resid_frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    games, _ = load_pure_silver()
    pp = pd.read_parquet(W2 / "pure_predictions.parquet")[["game_id", "B9_margin"]]
    st = pd.read_parquet(W2 / "states_shot.parquet")[
        [
            "game_id",
            "season",
            "h_games_seen",
            "a_games_seen",
            "h_off_eff",
            "h_def_eff",
            "a_off_eff",
            "a_def_eff",
        ]
    ]
    d = pp.merge(st, on="game_id").merge(games, on=["game_id", "season"])
    d["margin"] = (d["home_score"] - d["away_score"]).astype(float)
    d["resid"] = d["margin"] - d["B9_margin"]
    d["month"] = (
        pd.to_datetime(d["start_time_utc"], utc=True).dt.tz_convert("America/New_York").dt.month
    )
    d["early"] = d["month"].isin([11, 12])
    return d[d["season"].isin(VALID) & d["margin"].notna()].reset_index(drop=True), games


def rotation_prior(ps: pd.DataFrame, pre: pd.DataFrame) -> dict:
    cur = ps[ps["returning"]].groupby(["team_id", "season"])["min_share"].sum() / 5.0
    real = cur.rename("real_ret_min").reset_index()
    x = pre.merge(real, on=["team_id", "season"], how="left").fillna({"real_ret_min": 0.0})
    out = {}
    for name, sub in (("2012-2020", x[x["season"] <= 2020]), ("2021-2026", x[x["season"] >= 2021])):
        out[name] = {
            "n_teams": len(sub),
            "corr": float(np.corrcoef(sub["ret_min"], sub["real_ret_min"])[0, 1]),
            "rmse": _r(sub["ret_min"] - sub["real_ret_min"]),
            "mean_pred": float(sub["ret_min"].mean()),
            "mean_real": float(sub["real_ret_min"].mean()),
        }
    by = x.groupby("season").apply(
        lambda s: pd.Series(
            {
                "pred": s["ret_min"].mean(),
                "real": s["real_ret_min"].mean(),
                "corr": np.corrcoef(s["ret_min"], s["real_ret_min"])[0, 1],
            }
        )
    )
    out["by_season"] = by.round(3).to_dict("index")
    # player-level calibration of P(return)
    cal = []
    for s in range(2012, 2027):
        p = preseason.return_probabilities(ps, s)
        prev = ps.loc[p.index]
        cal.append(
            pd.DataFrame(
                {
                    "p": p,
                    "y": prev["returns_next"].astype(float),
                    "rot": prev["min_share"] >= 0.25,
                    "season": s,
                }
            )
        )
    c = pd.concat(cal)
    c["bin"] = pd.cut(c["p"], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
    out["p_return_calibration_rotation"] = (
        c[c["rot"]]
        .groupby("bin", observed=True)
        .agg(n=("y", "size"), p=("p", "mean"), realized=("y", "mean"))
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records")
    )
    return out


def returning_production(d: pd.DataFrame, pre: pd.DataFrame, finals: pd.DataFrame) -> dict:
    last = finals.assign(season=finals["season"] + 1).rename(columns={"o": "lo", "d": "ld"})
    x = finals.merge(last, on=["team_id", "season"]).merge(pre, on=["team_id", "season"])
    x["dnet"] = (x["o"] - x["d"]) - (x["lo"] - x["ld"])
    out: dict[str, object] = {}
    for c in (
        "ret_min",
        "ret_usage",
        "ret_starts",
        "ret_rot_n",
        "ret_impact",
        "lost_impact",
        "ret_top1",
        "ret_top3",
        "ret_ast",
        "ret_orb",
        "ret_drb",
        "ret_stl",
        "ret_blk",
        "ret_pts",
        "pre_net",
    ):
        out[f"corr_dnet_{c}"] = float(np.corrcoef(x[c], x["dnet"])[0, 1])
    # B9 early-season residual by home - away returning minutes (home perspective)
    e = (
        d[d["early"]]
        .merge(
            pre[["team_id", "season", "ret_min", "pre_net"]].rename(
                columns={"team_id": "home_team_id", "ret_min": "h_ret", "pre_net": "h_pre"}
            ),
            on=["home_team_id", "season"],
            how="left",
        )
        .merge(
            pre[["team_id", "season", "ret_min", "pre_net"]].rename(
                columns={"team_id": "away_team_id", "ret_min": "a_ret", "pre_net": "a_pre"}
            ),
            on=["away_team_id", "season"],
            how="left",
        )
    )
    e["ret_diff"] = e["h_ret"] - e["a_ret"]
    e["q"] = pd.qcut(e["ret_diff"], 5, labels=False, duplicates="drop")
    out["nov_dec_resid_by_ret_diff_quintile"] = (
        e.groupby("q")
        .agg(n=("resid", "size"), mean_resid=("resid", "mean"), rmse=("resid", _r))
        .round(3)
        .reset_index()
        .to_dict("records")
    )
    return out


def transfers(d: pd.DataFrame, ps: pd.DataFrame) -> dict:
    sh = (
        ps.assign(tr_min=ps["min_share"] * ps["transfer_in"])
        .groupby(["team_id", "season"])["tr_min"]
        .sum()
        .div(5.0)
        .rename("tr_share")
        .reset_index()
    )
    e = (
        d[d["early"]]
        .merge(
            sh.rename(columns={"team_id": "home_team_id", "tr_share": "h_tr"}),
            on=["home_team_id", "season"],
            how="left",
        )
        .merge(
            sh.rename(columns={"team_id": "away_team_id", "tr_share": "a_tr"}),
            on=["away_team_id", "season"],
            how="left",
        )
    )
    e["max_tr"] = e[["h_tr", "a_tr"]].max(axis=1)
    e["b"] = pd.cut(e["max_tr"], [-0.01, 0.1, 0.25, 0.4, 1.0])
    return {
        "nov_dec_rmse_by_max_transfer_minute_share (hindsight)": e.groupby("b", observed=True)
        .agg(n=("resid", "size"), rmse=("resid", _r), mean_abs=("resid", lambda r: r.abs().mean()))
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records")
    }


def mismatches(d: pd.DataFrame) -> dict:
    fav = np.sign(d["B9_margin"]).replace(0, 1)
    x = d.assign(abs_proj=d["B9_margin"].abs(), fav_resid=d["resid"] * fav)
    x["b"] = pd.cut(x["abs_proj"], [0, 5, 10, 15, 20, 25, 30, 80], right=False)
    out = {
        "by_projected_margin": x.groupby("b", observed=True)
        .agg(
            n=("resid", "size"),
            fav_mean_resid=("fav_resid", "mean"),
            rmse=("resid", _r),
            nov_dec_share=("early", "mean"),
        )
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records")
    }
    big = x[x["abs_proj"] >= 25]
    out["proj_25plus"] = {
        "n": len(big),
        "fav_mean_resid": float(big["fav_resid"].mean()),
        "fav_mean_resid_nov_dec": float(big.loc[big["early"], "fav_resid"].mean()),
        "rmse": _r(big["resid"]),
    }
    return out


def neutral_sites(d: pd.DataFrame, games: pd.DataFrame) -> dict:
    home = games[~games["neutral_site"].astype(bool)].dropna(subset=["venue_state"])
    hs = home.groupby("home_team_id").agg(
        state=("venue_state", lambda s: s.value_counts().index[0]),
        city=("venue_city", lambda s: s.value_counts().index[0]),
    )
    n = d[d["neutral_site"].astype(bool)].copy()
    n = n.join(hs.add_prefix("h_"), on="home_team_id").join(hs.add_prefix("a_"), on="away_team_id")
    h_state = n["venue_state"] == n["h_state"]
    a_state = n["venue_state"] == n["a_state"]
    h_city = n["venue_city"] == n["h_city"]
    a_city = n["venue_city"] == n["a_city"]
    cls = np.select(
        [
            h_city & ~a_city,
            a_city & ~h_city,
            h_state & ~a_state,
            a_state & ~h_state,
            n["venue_state"].isna(),
        ],
        ["home_team_city", "away_team_city", "home_team_state", "away_team_state", "unknown"],
        "true_neutral",
    )
    n["cls"] = cls
    out = {
        "neutral_games": len(n),
        "classes": n.groupby("cls")
        .agg(n=("resid", "size"), mean_resid_home_designated=("resid", "mean"), rmse=("resid", _r))
        .round(3)
        .reset_index()
        .to_dict("records"),
    }
    nn = d[~d["neutral_site"].astype(bool)]
    out["true_home_mean_resid"] = float(nn["resid"].mean())
    return out


def strong_team_venue(d: pd.DataFrame) -> dict:
    h = d[~d["neutral_site"].astype(bool)].copy()
    h["h_net"] = h["h_off_eff"] - h["h_def_eff"]
    h["t"] = pd.qcut(h["h_net"], 3, labels=["weak", "mid", "strong"])
    return {
        "home_resid_by_home_strength_tercile": h.groupby("t", observed=True)
        .agg(n=("resid", "size"), mean_resid=("resid", "mean"), rmse=("resid", _r))
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records")
    }


def network(d: pd.DataFrame, games: pd.DataFrame) -> dict:
    g = games[games["home_is_d1"] & games["away_is_d1"] & games["completed"].astype(bool)]
    g = g.dropna(subset=["home_conference_id", "away_conference_id"]).sort_values("start_time_utc")
    rows = []
    for _s, x in g.groupby("season"):
        pair = [
            tuple(sorted(p))
            for p in zip(x["home_conference_id"], x["away_conference_id"], strict=True)
        ]
        x = x.assign(pair=pair, cross=x["home_conference_id"] != x["away_conference_id"])
        # number of EARLIER games this season between the two conferences (strictly before day)
        cnt: dict[tuple, int] = {}
        before = []
        for _day, gd in x.groupby("game_date_et", sort=True):
            before.extend(cnt.get(p, 0) for p in gd["pair"])
            for p in gd["pair"]:
                cnt[p] = cnt.get(p, 0) + 1
        x = x.assign(bridge=before)
        rows.append(x[["game_id", "bridge", "cross"]])
    b = pd.concat(rows)
    e = d.merge(b, on="game_id")
    e = e[e["cross"] & e["early"]]
    e["b"] = pd.cut(e["bridge"], [-1, 0, 2, 5, 10, 1000])
    out = {
        "nov_dec_cross_conf_resid_by_prior_bridge_games": e.groupby("b", observed=True)
        .agg(n=("resid", "size"), rmse=("resid", _r))
        .round(3)
        .reset_index()
        .astype(str)
        .to_dict("records")
    }
    # share of a season's eventual cross-conference games completed by date
    g["cross"] = g["home_conference_id"] != g["away_conference_id"]
    g["month"] = (
        pd.to_datetime(g["start_time_utc"], utc=True).dt.tz_convert("America/New_York").dt.month
    )
    out["cross_conf_share_by_month"] = g.groupby("month")["cross"].mean().round(3).to_dict()
    return out


def main() -> None:
    d, games = resid_frame()
    ps = preseason.load_player_seasons()
    pre = pd.read_parquet(data_dir() / "research" / "wave3" / "preseason_features.parquet")
    st = pd.read_parquet(W2 / "states_shot.parquet")
    finals = team_prior.season_final_ratings(st, games)
    rep = {
        "rotation_prior": rotation_prior(ps, pre),
        "returning_production": returning_production(d, pre, finals),
        "transfers": transfers(d, ps),
        "extreme_mismatches": mismatches(d),
        "neutral_sites": neutral_sites(d, games),
        "strong_team_x_venue": strong_team_venue(d),
        "network": network(d, games),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
