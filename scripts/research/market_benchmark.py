"""MARKET_BENCHMARK step (downstream only).

Reads the already-persisted PURE_BASKETBALL predictions and the free closing lines and
reports ``market_gap = PURE RMSE - MARKET RMSE`` on games that have a usable line.
Nothing here can influence the PURE predictions: they were written before this step
runs, and the PURE pipeline cannot import ``cbb_edge.market`` (CI test).

A MARKET_ENSEMBLE diagnostic (PURE + market) is reported separately and is never a
default projection.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from cbb_edge.backtest.evaluate import point_metrics, prob_metrics
from cbb_edge.data.http import data_dir
from cbb_edge.market.espn_lines import orient_to_games

OUT = Path("research/wave2/market_benchmark.json")
WORK = data_dir() / "research" / "wave2"
VALID = list(range(2015, 2025))
HIST = [2025, 2026]


def load_lines(games: pd.DataFrame) -> pd.DataFrame:
    parts = sorted((data_dir() / "bronze" / "github_raw" / "espn_lines").glob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = orient_to_games(df.drop_duplicates("game_id"), games)
    return df[df["line_usable"]][["game_id", "home_spread_close", "total_close", "provider"]]


def main() -> None:
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pp = pd.read_parquet(WORK / "pure_predictions.parquet")
    lines = load_lines(games)
    d = pp.merge(lines, on="game_id", how="inner").merge(
        games[["game_id", "home_score", "away_score"]], on="game_id"
    )
    d["margin"] = (d["home_score"] - d["away_score"]).astype(float)
    d["total"] = (d["home_score"] + d["away_score"]).astype(float)
    d["home_win"] = (d["margin"] > 0).astype(float)
    d["mkt_margin"] = -d["home_spread_close"]
    arm_names = sorted(
        {
            c.split("_")[0]
            for c in pp.columns
            if c.endswith("_margin") and not c.endswith("sigma_margin")
        }
    )
    out: dict[str, object] = {"note": "MARKET is a benchmark only; PURE arms use no market data"}
    for split, seasons in (("validation", VALID), ("historical", HIST)):
        sm = d["season"].isin(seasons) & d["mkt_margin"].notna() & d["margin"].notna()
        for a in arm_names:
            sm &= d[f"{a}_margin"].notna()
        x = d[sm]
        mk_m = point_metrics(x["mkt_margin"], x["margin"])
        mk_t = point_metrics(x["total_close"], x["total"])
        res: dict[str, object] = {"n": len(x), "MARKET": {"margin": mk_m, "total": mk_t}}
        for a in arm_names:
            am = point_metrics(x[f"{a}_margin"], x["margin"])
            at = point_metrics(x[f"{a}_total"], x["total"])
            res[a] = {
                "margin": am,
                "total": at,
                "wp": prob_metrics(x[f"{a}_home_wp"], x["home_win"]),
                "market_gap_margin_rmse": am["rmse"] - mk_m["rmse"],
                "market_gap_total_rmse": at["rmse"] - mk_t["rmse"],
                "corr_with_market_margin": float(
                    np.corrcoef(x[f"{a}_margin"], x["mkt_margin"])[0, 1]
                ),
            }
        by = {}
        for s in sorted(x["season"].unique()):
            xs = x[x["season"] == s]
            by[int(s)] = {
                "n": len(xs),
                "MARKET": point_metrics(xs["mkt_margin"], xs["margin"])["rmse"],
                **{a: point_metrics(xs[f"{a}_margin"], xs["margin"])["rmse"] for a in arm_names},
            }
        res["by_season_margin_rmse"] = by
        mon = (
            pd.to_datetime(
                x.merge(games[["game_id", "start_time_utc"]], on="game_id")[
                    "start_time_utc"
                ].to_numpy(),
                utc=True,
            )
            .tz_convert("America/New_York")
            .month
        )
        bym = {}
        for mo in (11, 12, 1, 2, 3, 4):
            xm = x[mon == mo]
            if len(xm) < 50:
                continue
            mk = point_metrics(xm["mkt_margin"], xm["margin"])["rmse"]
            bym[int(mo)] = {
                "n": len(xm),
                "MARKET": mk,
                **{
                    a: point_metrics(xm[f"{a}_margin"], xm["margin"])["rmse"] - mk
                    for a in arm_names
                },
            }
        res["market_gap_by_month"] = bym
        # MARKET_ENSEMBLE diagnostic for the best PURE arm (expanding window, lines only)
        best = min(arm_names, key=lambda a: res[a]["margin"]["rmse"])  # type: ignore[index]
        ens = pd.Series(np.nan, index=d.index)
        for s in sorted(d["season"].unique()):
            tr = (d["season"] < s) & d[[f"{best}_margin", "mkt_margin", "margin"]].notna().all(
                axis=1
            )
            cur = (d["season"] == s) & d[[f"{best}_margin", "mkt_margin"]].notna().all(axis=1)
            if tr.sum() < 2000 or not cur.any():
                continue
            r = Ridge(alpha=1.0).fit(
                d.loc[tr, [f"{best}_margin", "mkt_margin"]], d.loc[tr, "margin"]
            )
            ens[cur] = r.predict(d.loc[cur, [f"{best}_margin", "mkt_margin"]])
        em = sm & ens.notna()
        res["MARKET_ENSEMBLE_diagnostic"] = {
            "pure_arm": best,
            "n": int(em.sum()),
            "margin": point_metrics(ens[em], d.loc[em, "margin"]),
        }
        out[split] = res
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print(
        json.dumps(
            {
                k: (
                    v
                    if k == "note"
                    else {
                        a: (
                            v[a]["market_gap_margin_rmse"]
                            if isinstance(v.get(a), dict) and "market_gap_margin_rmse" in v[a]
                            else None
                        )
                        for a in arm_names
                    }
                )
                for k, v in out.items()
            },
            indent=1,
            default=float,
        )
    )


if __name__ == "__main__":
    main()
