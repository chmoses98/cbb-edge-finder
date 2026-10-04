"""Baseline walk-forward study: arms B0-B5, ELO, MARKET, ENSEMBLE, ESPN benchmark.

Season roles (fixed in research/REGISTRY.md before any validation result was seen):
    2006        seed season (priors only)
    2007-2014   DEV: hyperparameter tuning (scripts/research/tune_dev.py)
    2015-2024   VALIDATION: arm comparison, walk-forward
    2025-2026   HOLDOUT: opened once, config frozen

Outputs (committed, small): research/baseline/metrics.json, research/reports/BASELINE.md
Outputs (data lake): data/research/states_*.parquet, data/research/predictions.parquet
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from cbb_edge.backtest.config import tuned_config
from cbb_edge.backtest.evaluate import (
    calibration_table,
    ece,
    point_metrics,
    prob_metrics,
    wilson_ci,
)
from cbb_edge.backtest.walkforward import EngineConfig, run
from cbb_edge.data.http import data_dir
from cbb_edge.market import espn_lines, espn_pregame
from cbb_edge.model import arms
from cbb_edge.model.elo import elo_projections

SEASONS = list(range(2006, 2027))
VALID = list(range(2015, 2025))
HOLDOUT = [2025, 2026]
OUT_JSON = Path("research/baseline/metrics.json")
OUT_MD = Path("research/reports/BASELINE.md")
LINE_AUDIT = Path("research/baseline/line_orientation_audit.json")


def load_lines(games: pd.DataFrame) -> pd.DataFrame:
    """Free closing lines oriented to our home team; unusable lines dropped."""
    parts = sorted((data_dir() / "bronze" / "github_raw" / "espn_lines").glob("*.parquet"))
    if not parts:
        return pd.DataFrame(columns=["game_id"])
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = espn_lines.orient_to_games(df.drop_duplicates("game_id"), games)
    audit = df.groupby("season").agg(
        n=("game_id", "size"),
        flipped=("orientation", lambda x: int((x == "flipped").sum())),
        unknown=("orientation", lambda x: int((x == "unknown").sum())),
        suspect=("line_suspect", "sum"),
        usable=("line_usable", "sum"),
    )
    print("line orientation audit:\n", audit.to_string(), flush=True)
    LINE_AUDIT.write_text(audit.reset_index().to_json(orient="records", indent=1))
    return df[df["line_usable"]]


def states_for(
    name: str, cfg: EngineConfig, g: pd.DataFrame, tg: pd.DataFrame, pg: pd.DataFrame | None = None
) -> pd.DataFrame:
    path = data_dir() / "research" / f"states_{name}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    print(f"[engine] {name}", flush=True)
    st = run(g, tg, SEASONS, cfg, pg=pg)
    path.parent.mkdir(parents=True, exist_ok=True)
    st.to_parquet(path, index=False)
    return st


def ats_table(df: pd.DataFrame, model_margin: pd.Series) -> list[dict[str, float]]:
    """Against-the-spread study vs the closing line at -110 (research only)."""
    mk = -df["home_spread_close"]
    ok = model_margin.notna() & mk.notna() & df.margin.notna()
    edge = (model_margin - mk)[ok]
    res = (df.margin - mk)[ok]  # >0 home covers
    rows = []
    for thr in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):
        pick = edge.abs() >= thr
        side = np.sign(edge[pick])
        outcome = np.sign(res[pick]) * side
        wins, losses = float((outcome > 0).sum()), float((outcome < 0).sum())
        n = wins + losses
        lo, hi = wilson_ci(wins, n)
        rows.append(
            {
                "edge_ge": thr,
                "bets": int(n),
                "win_pct": wins / n if n else np.nan,
                "ci95_lo": lo,
                "ci95_hi": hi,
                "roi_at_-110": (wins * (100 / 110) - losses) / n if n else np.nan,
            }
        )
    return rows


def totals_table(df: pd.DataFrame, model_total: pd.Series) -> list[dict[str, float]]:
    mk = df["total_close"]
    ok = model_total.notna() & mk.notna() & df.total.notna()
    edge = (model_total - mk)[ok]
    res = (df.total - mk)[ok]
    rows = []
    for thr in (0.0, 2.0, 4.0, 6.0, 8.0):
        pick = edge.abs() >= thr
        outcome = np.sign(res[pick]) * np.sign(edge[pick])
        wins, losses = float((outcome > 0).sum()), float((outcome < 0).sum())
        n = wins + losses
        lo, hi = wilson_ci(wins, n)
        rows.append(
            {
                "edge_ge": thr,
                "bets": int(n),
                "win_pct": wins / n if n else np.nan,
                "ci95_lo": lo,
                "ci95_hi": hi,
                "roi_at_-110": (wins * (100 / 110) - losses) / n if n else np.nan,
            }
        )
    return rows


def ensemble(df: pd.DataFrame, model: pd.Series, market: pd.Series, target: str) -> pd.Series:
    """Expanding-window ridge on [model, market] trained on prior seasons with lines."""
    out = pd.Series(np.nan, index=df.index)
    X = pd.DataFrame({"m": model, "k": market})
    for s in sorted(df.season.unique()):
        tr = (df.season < s) & X.notna().all(axis=1) & df[target].notna()
        if tr.sum() < 2000:
            continue
        r = Ridge(alpha=1.0).fit(X[tr], df.loc[tr, target])
        cur = (df.season == s) & X.notna().all(axis=1)
        if cur.any():
            out[cur] = r.predict(X[cur])
    return out


def main() -> None:
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    tg = pd.read_parquet(data_dir() / "silver" / "team_games.parquet")
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min", "available_at"],
    )
    pg = pg[pg["team_id"].notna() & pg["min"].fillna(0).gt(0)]
    cfg = tuned_config()
    print("tuned config:", cfg, flush=True)

    st_adj = states_for("adjusted", cfg, g, tg)
    raw_cfg = EngineConfig(
        lam=cfg.lam,
        prior_regress=cfg.prior_regress,
        recency_tau_days=cfg.recency_tau_days,
        adjust=False,
        stats=("eff", "tempo"),
    )
    st_raw = states_for("raw", raw_cfg, g, tg)
    ros_cfg = EngineConfig(
        lam=cfg.lam,
        prior_regress=cfg.prior_regress,
        recency_tau_days=cfg.recency_tau_days,
        roster_prior=True,
    )
    st_ros = states_for("roster", ros_cfg, g, tg, pg)

    adj = arms.attach_games(st_adj, g)
    raw = arms.attach_games(st_raw, g).set_index("game_id").reindex(adj.game_id).reset_index()
    ros = arms.attach_games(st_ros, g).set_index("game_id").reindex(adj.game_id).reset_index()
    raw.index = adj.index
    ros.index = adj.index

    proj: dict[str, arms.Projection] = {
        "B0": arms.b0_naive(adj),
        "B1": arms.analytic(raw),
        "B2": arms.analytic(adj),
        "B3": arms.stacked(adj),
        "B4": arms.stacked(ros),
        "B5": arms.stacked(ros, interactions=True),
    }
    elo = elo_projections(g, SEASONS).set_index("game_id")["elo_margin"]
    elo_m = adj.game_id.map(elo)
    proj["ELO"] = arms.Projection(elo_m, proj["B0"].total)

    lines = load_lines(g)
    df = adj.merge(
        lines[
            [
                "game_id",
                "home_spread_close",
                "total_close",
                "home_spread_open",
                "total_open",
                "has_open_close",
                "provider",
            ]
        ],
        on="game_id",
        how="left",
    )
    df.index = adj.index
    for c in ("home_spread_close", "total_close", "home_spread_open", "total_open"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    proj["MARKET"] = arms.Projection(-df["home_spread_close"], df["total_close"])
    best_basketball = "B3"
    proj["ENSEMBLE"] = arms.Projection(
        ensemble(df, proj[best_basketball].margin, proj["MARKET"].margin, "margin"),
        ensemble(df, proj[best_basketball].total, proj["MARKET"].total, "total"),
    )

    espn = espn_pregame.build(SEASONS).set_index("game_id")["pregame_home_prob"]
    df["espn_wp"] = df.game_id.map(espn)

    preds = pd.DataFrame({"game_id": df.game_id, "season": df.season})
    for name, p in proj.items():
        preds[f"{name}_margin"] = p.margin
        preds[f"{name}_total"] = p.total
        preds[f"{name}_wp"] = arms.win_prob(df, p.margin)
        preds[f"{name}_margin_sd"] = arms.residual_sd(df, p.margin, "margin")
        preds[f"{name}_total_sd"] = arms.residual_sd(df, p.total, "total")
    preds["ESPN_wp"] = df["espn_wp"]
    (data_dir() / "research").mkdir(parents=True, exist_ok=True)
    preds.to_parquet(data_dir() / "research" / "predictions.parquet", index=False)

    metrics: dict[str, object] = {
        "config": {
            "lam": cfg.lam,
            "prior_regress": cfg.prior_regress,
            "recency_tau_days": cfg.recency_tau_days,
        }
    }
    splits = {
        "validation_2015_2024": df.season.isin(VALID),
        "holdout_2025_2026": df.season.isin(HOLDOUT),
    }
    names = list(proj) + ["ESPN"]
    for split, mask in splits.items():
        done = mask & df.margin.notna()
        # common sample: every arm has a projection (apples-to-apples)
        common = done.copy()
        for name in proj:
            if name in ("MARKET", "ENSEMBLE"):
                continue
            common &= preds[f"{name}_margin"].notna()
        with_lines = common & df.home_spread_close.notna()
        res: dict[str, object] = {
            "n_games": int(done.sum()),
            "n_common": int(common.sum()),
            "n_with_lines": int(with_lines.sum()),
        }
        for sample_name, smask in (("all", common), ("with_lines", with_lines)):
            arm_res = {}
            for name in names:
                if name == "ESPN":
                    wp = preds["ESPN_wp"]
                    sm = smask & wp.notna()
                    arm_res[name] = {
                        "wp": prob_metrics(wp[sm], df.home_win[sm]),
                        "ece": ece(wp[sm], df.home_win[sm]) if sm.any() else None,
                    }
                    continue
                if name in ("MARKET", "ENSEMBLE") and sample_name == "all":
                    continue
                sm = smask & preds[f"{name}_margin"].notna()
                arm_res[name] = {
                    "margin": point_metrics(preds.loc[sm, f"{name}_margin"], df.margin[sm]),
                    "total": point_metrics(preds.loc[sm, f"{name}_total"], df.total[sm]),
                    "wp": prob_metrics(preds.loc[sm, f"{name}_wp"], df.home_win[sm]),
                    "ece": ece(preds.loc[sm, f"{name}_wp"], df.home_win[sm]),
                }
            res[sample_name] = arm_res
        # by season, best basketball arm + market
        by_season = {}
        for s in sorted(df[mask].season.unique()):
            sm = common & (df.season == s)
            row = {}
            for name in ("B0", "B1", "B2", "B3", "B4", "B5", "ELO"):
                row[name] = point_metrics(preds.loc[sm, f"{name}_margin"], df.margin[sm])["mae"]
            lm = sm & df.home_spread_close.notna()
            row["n"] = int(sm.sum())
            row["n_lines"] = int(lm.sum())
            if lm.any():
                row["B3_on_lines"] = point_metrics(preds.loc[lm, "B3_margin"], df.margin[lm])["mae"]
                row["MARKET"] = point_metrics(-df.home_spread_close[lm], df.margin[lm])["mae"]
            by_season[int(s)] = row
        res["by_season_margin_mae"] = by_season
        # betting-market research on games with lines
        lm = with_lines
        res["ats_vs_close"] = {
            a: ats_table(df[lm], preds.loc[lm, f"{a}_margin"]) for a in ("B2", "B3", "B4", "B5")
        }
        res["totals_vs_close"] = {
            a: totals_table(df[lm], preds.loc[lm, f"{a}_total"]) for a in ("B2", "B3", "B4", "B5")
        }
        oc = lm & df.has_open_close.fillna(False).astype(bool)
        if oc.any():
            # CLV-style check where open AND close exist: does model edge vs OPEN
            # predict the open->close line move?
            sp_open = pd.to_numeric(df.home_spread_open, errors="coerce")
            sp_close = pd.to_numeric(df.home_spread_close, errors="coerce")
            mv = (sp_open - sp_close)[oc]  # + = line moved toward home
            ed = preds.loc[oc, "B3_margin"] + sp_open[oc]  # + = model likes home vs open
            ok = mv.notna() & ed.notna()
            mv, ed = mv[ok].astype(float), ed[ok].astype(float)
            big = ed.abs() >= 2
            moved = big & (mv != 0)
            res["clv_open_to_close"] = {
                "n": int(ok.sum()),
                "corr_edge_vs_move": float(np.corrcoef(ed, mv)[0, 1]) if len(ed) > 2 else None,
                "share_move_toward_model_when_edge_ge_2": float(
                    (np.sign(mv[moved]) == np.sign(ed[moved])).mean()
                )
                if moved.any()
                else None,
                "n_edge_ge_2": int(big.sum()),
                "n_edge_ge_2_line_moved": int(moved.sum()),
            }
        res["calibration_B3"] = (
            calibration_table(preds.loc[common, "B3_wp"], df.home_win[common])
            .astype(str)
            .to_dict("records")
        )
        metrics[split] = res
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(metrics, indent=1, default=float))
    print(
        json.dumps({k: v for k, v in metrics.items() if k != "config"}, indent=1, default=float)[
            :6000
        ]
    )


if __name__ == "__main__":
    main()
