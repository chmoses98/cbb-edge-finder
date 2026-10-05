"""Residual store, slicing and error decomposition (PURE_BASKETBALL diagnostics).

``residual_table`` stores, for every historical projection: predicted/actual scores,
margin, total, possessions, PPP per side, projected Four Factors per side, and the
actual box-score factors, so persistent residual structure can be studied.

``error_decomposition`` attributes total-points error to pace vs efficiency, and
per-side PPP error to shooting / turnovers / offensive rebounding / free throws using a
linear PPP ≈ f(eFG, TO, ORB, FTR) map fitted on actual games (prior seasons only).
Residual findings generate *hypotheses*; they are never fitted on the evaluation data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

FACTOR_COLS = {"efg": "efg", "to": "to_rate", "orb": "orb_rate", "ftr": "ftr"}

POWER_CONF_NAMES = ("Atlantic Coast", "Big Ten", "Big 12", "Southeastern", "Big East", "Pac-12")


def actual_side_stats(tg: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Actual possessions and per-side PPP / factors keyed by game_id (h_/a_ prefixes)."""
    g = games[["game_id", "home_espn_id"]]
    t = tg.merge(g, on="game_id")
    home = t[t["team_espn_id"] == t["home_espn_id"]]
    away = t[t["team_espn_id"] != t["home_espn_id"]]
    cols = ["ppp", "efg", "to_rate", "orb_rate", "ftr", "fg3a_rate", "fg3_pct"]
    h = home[["game_id", "poss", *cols]].rename(columns={c: f"act_h_{c}" for c in cols})
    a = away[["game_id", *cols]].rename(columns={c: f"act_a_{c}" for c in cols})
    out = h.merge(a, on="game_id").rename(columns={"poss": "act_poss"})
    return out.drop_duplicates("game_id")


def residual_table(
    df: pd.DataFrame, pred: pd.DataFrame, actual: pd.DataFrame, factors: pd.DataFrame | None = None
) -> pd.DataFrame:
    """df = attached pregame states; pred has margin/total/poss/home_pts/away_pts."""
    r = pd.DataFrame(
        {"game_id": df["game_id"].to_numpy(), "season": df["season"].to_numpy()}, index=df.index
    )
    for c in ("margin", "total", "poss", "home_pts", "away_pts", "home_wp"):
        if c in pred:
            r[f"pred_{c}"] = pred[c].to_numpy()
    r["act_margin"] = df["margin"].to_numpy()
    r["act_total"] = df["total"].to_numpy()
    r["act_home_pts"] = df["home_score"].astype(float).to_numpy()
    r["act_away_pts"] = df["away_score"].astype(float).to_numpy()
    r["home_win"] = df["home_win"].to_numpy()
    r["res_margin"] = r["act_margin"] - r["pred_margin"]
    r["res_total"] = r["act_total"] - r["pred_total"]
    r["res_home_pts"] = r["act_home_pts"] - r["pred_home_pts"]
    r["res_away_pts"] = r["act_away_pts"] - r["pred_away_pts"]
    r = r.merge(actual, on="game_id", how="left")
    r.index = df.index
    if factors is not None:
        for c in factors.columns:
            r[f"pred_{c}"] = factors[c].to_numpy()
    # context for slicing
    t = pd.to_datetime(df["start_time_utc"], utc=True).dt.tz_convert("America/New_York")
    r["month"] = t.dt.month.to_numpy()
    r["site"] = np.where(df["L"].to_numpy() == 1, "home", "neutral")
    post = (df["season_type"].fillna(2) == 3) | df["tournament_id"].notna()
    r["phase"] = np.where(
        post,
        "postseason",
        np.where(
            df["conference_game"].astype(bool),
            "conference",
            np.where(t.dt.month.isin([11, 12]), "nonconf_nov_dec", "nonconf_other"),
        ),
    )
    net_h = (df["h_off_eff"] - df["h_def_eff"]).to_numpy()
    net_a = (df["a_off_eff"] - df["a_def_eff"]).to_numpy()
    r["strength_avg"] = (net_h + net_a) / 2
    r["min_games"] = np.minimum(df["h_games_seen"], df["a_games_seen"]).to_numpy()
    return r


def slice_metrics(r: pd.DataFrame, by: str | pd.Series, name: str | None = None) -> pd.DataFrame:
    key = r[by] if isinstance(by, str) else by
    g = r.assign(_k=key).groupby("_k", observed=True)
    out = g.apply(
        lambda x: pd.Series(
            {
                "n": len(x),
                "margin_rmse": float(np.sqrt(np.nanmean(x.res_margin**2))),
                "margin_bias": float(np.nanmean(-x.res_margin)),
                "total_rmse": float(np.sqrt(np.nanmean(x.res_total**2))),
                "total_bias": float(np.nanmean(-x.res_total)),
                "home_pts_mae": float(np.nanmean(np.abs(x.res_home_pts))),
                "away_pts_mae": float(np.nanmean(np.abs(x.res_away_pts))),
                "poss_mae": float(np.nanmean(np.abs(x.act_poss - x.pred_poss)))
                if "pred_poss" in x
                else np.nan,
            }
        ),
        include_groups=False,
    )
    out.index.name = name or (by if isinstance(by, str) else "slice")
    return out.reset_index()


def standard_slices(
    r: pd.DataFrame, conf_of_home: pd.Series | None = None
) -> dict[str, pd.DataFrame]:
    out = {
        "season": slice_metrics(r, "season"),
        "month": slice_metrics(r, "month"),
        "site": slice_metrics(r, "site"),
        "phase": slice_metrics(r, "phase"),
        "strength": slice_metrics(
            r,
            pd.qcut(r["strength_avg"], 5, labels=["q1_weak", "q2", "q3", "q4", "q5_strong"]),
            "strength_quintile",
        ),
        "spread_bucket": slice_metrics(
            r,
            pd.cut(r["pred_margin"].abs(), [0, 3, 6, 10, 15, 25, 99], right=False),
            "abs_proj_margin",
        ),
        "pace_bucket": slice_metrics(
            r,
            pd.qcut(r["pred_poss"], 5, labels=["slowest", "slow", "mid", "fast", "fastest"]),
            "proj_pace",
        ),
        "games_seen": slice_metrics(
            r, pd.cut(r["min_games"], [0, 1, 3, 6, 11, 99], right=False), "min_games_seen"
        ),
    }
    if conf_of_home is not None:
        out["conference_tier"] = slice_metrics(r, conf_of_home, "home_conference_tier")
    return out


def error_decomposition(r: pd.DataFrame, train: pd.DataFrame | None = None) -> dict[str, float]:
    """Variance attribution of total and margin errors.

    Total: actual - pred = poss_act*ppp_sum_act - poss_pred*ppp_sum_pred
         = (poss_act - poss_pred)*ppp_sum_pred  [pace]  + poss_act*(ppp_sum_act - ppp_sum_pred) [eff]
    Margin efficiency error per side is split into factor contributions with a linear PPP
    model fitted on ``train`` (actual factor -> actual PPP).
    """
    ok = r[["act_poss", "pred_poss", "act_h_ppp", "act_a_ppp"]].notna().all(axis=1)
    x = r[ok]
    ppp_sum_pred = x["pred_total"] / x["pred_poss"]
    ppp_sum_act = x["act_h_ppp"] + x["act_a_ppp"]
    pace = (x["act_poss"] - x["pred_poss"]) * ppp_sum_pred
    eff = x["act_poss"] * (ppp_sum_act - ppp_sum_pred)
    err = x["act_total"] - x["pred_total"]
    out = {
        "n": int(len(x)),
        "total_rmse": float(np.sqrt((err**2).mean())),
        "total_err_var": float(err.var()),
        "pace_component_var": float(pace.var()),
        "efficiency_component_var": float(eff.var()),
        "pace_eff_cov": float(2 * np.cov(pace, eff)[0, 1]),
        "poss_mae": float((x["act_poss"] - x["pred_poss"]).abs().mean()),
        "poss_bias": float((x["pred_poss"] - x["act_poss"]).mean()),
    }
    # factor attribution of per-side PPP error
    tr = train if train is not None else x
    rows = []
    for side in ("h", "a"):
        cols = [f"act_{side}_{FACTOR_COLS[f]}" for f in FACTOR_COLS]
        rows.append(tr[cols + [f"act_{side}_ppp"]].set_axis(list(FACTOR_COLS) + ["ppp"], axis=1))
    fit = pd.concat(rows).dropna()
    lin = LinearRegression().fit(fit[list(FACTOR_COLS)], fit["ppp"])
    coef = dict(zip(FACTOR_COLS, lin.coef_, strict=True))
    out["ppp_factor_r2"] = float(lin.score(fit[list(FACTOR_COLS)], fit["ppp"]))
    for f, c in coef.items():
        comps = []
        for side in ("h", "a"):
            pc = f"pred_{f}_{side}"
            if pc not in x:
                continue
            # projected factors are in percent units; actuals are fractions
            comps.append(c * (x[f"act_{side}_{FACTOR_COLS[f]}"] - x[pc] / 100.0))
        if comps:
            v = pd.concat(comps)
            out[f"ppp_err_from_{f}_var"] = float(v.var())
            out[f"ppp_err_from_{f}_mean"] = float(v.mean())
    return out
