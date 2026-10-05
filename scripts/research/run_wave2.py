"""Wave-2 PURE_BASKETBALL research: player/lineup (B6), shot profile (B7), context (B8),
combined (B9), possession models, heteroscedastic uncertainty, residuals.

Season roles:
    2006-2010  engine seed / warm-up (team ratings); 2011 seeds player ratings
    2012-2014  first training window for every stacked arm (identical for all arms)
    2015-2024  VALIDATION (expanding-window, walk-forward) — promotion decisions
    2025-2026  HISTORICAL (the PR #1 holdout; already observed — reported as evidence,
               not used for any decision)
    2026-27    the clean prospective test (archive in cbb_edge.app.prospective)

All arms are PURE_BASKETBALL. Market data is read only at the very end, by the
separate MARKET_BENCHMARK step, to compute market_gap — never as a model input.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression, Ridge

from cbb_edge.backtest.config import tuned_config
from cbb_edge.backtest.evaluate import ece, point_metrics, prob_metrics
from cbb_edge.backtest.residuals import (
    actual_side_stats,
    error_decomposition,
    residual_table,
    standard_slices,
)
from cbb_edge.backtest.walkforward import run
from cbb_edge.data.http import data_dir
from cbb_edge.features.context import rest_days, season_phase, team_home_effect
from cbb_edge.features.shot_profile import enrich_team_games
from cbb_edge.model import arms, pace, uncertainty
from cbb_edge.model.families import ARM_FAMILY, assert_pure_frame
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players.rapm import RapmConfig, player_team_features
from cbb_edge.ratings.adjusted import BASE_STATS, SHOT_STATS
from cbb_edge.research import blocks

SEASONS = list(range(2006, 2027))
FIRST_TRAIN = 2012
VALID = list(range(2015, 2025))
HIST = [2025, 2026]
OUT = Path("research/wave2")
WORK = data_dir() / "research" / "wave2"
MODEL_VERSION = "pure-0.2.0"


def cached(name: str, fn):
    p = WORK / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    WORK.mkdir(parents=True, exist_ok=True)
    df = fn()
    df.to_parquet(p, index=False)
    return df


def rapm_cfg() -> RapmConfig:
    p = OUT / "rapm_dev_tuning.csv"
    if not p.exists():
        return RapmConfig()
    t = pd.read_csv(p).sort_values("rmse").iloc[0]
    return RapmConfig(
        lam_o=float(t["lam"]),
        lam_d=float(t["lam"]),
        carry=float(t["carry"]),
        new_o=float(t["new_o"]),
        new_d=float(t["new_d"]),
    )


def stack(df: pd.DataFrame, X: pd.DataFrame, y: pd.Series, alpha: float = 10.0) -> pd.Series:
    """Expanding-window ridge: season s is predicted by a model trained on
    FIRST_TRAIN..s-1 only. Features standardized on the training window."""
    out = pd.Series(np.nan, index=df.index)
    ok = X.notna().all(axis=1)
    for s in sorted(df["season"].unique()):
        tr = ok & y.notna() & df["season"].between(FIRST_TRAIN, s - 1)
        cur = ok & (df["season"] == s)
        if df.loc[tr, "season"].nunique() < 3 or not cur.any():
            continue
        mu, sd = X[tr].mean(), X[tr].std().replace(0, 1.0)
        m = Ridge(alpha=alpha).fit((X[tr] - mu) / sd, y[tr])
        out[cur] = m.predict((X[cur] - mu) / sd)
    return out


def logistic_wp(df: pd.DataFrame, margin: pd.Series) -> pd.Series:
    """P(home win) = logistic(a + b * margin), fit on earlier seasons that have
    walk-forward predictions. The first predicted season has none, so it uses a fixed
    Normal(margin, 11) link (documented fallback, no fitting on its own outcomes)."""
    p = pd.Series(np.nan, index=df.index)
    for s in sorted(df["season"].unique()):
        tr = df["season"].between(FIRST_TRAIN, s - 1) & df["home_win"].notna() & margin.notna()
        cur = (df["season"] == s) & margin.notna()
        if not cur.any():
            continue
        if tr.sum() < 500:
            p[cur] = norm.cdf(margin[cur] / 11.0)
            continue
        lr = LogisticRegression(C=1e6).fit(margin[tr].to_frame(), df.loc[tr, "home_win"])
        p[cur] = lr.predict_proba(margin[cur].to_frame())[:, 1]
    return p.clip(1e-4, 1 - 1e-4)


def arm_metrics(df: pd.DataFrame, pred: pd.DataFrame, mask: pd.Series) -> dict[str, object]:
    m = mask & pred["margin"].notna() & df["margin"].notna()
    out: dict[str, object] = {"n": int(m.sum())}
    out["margin"] = point_metrics(pred.loc[m, "margin"], df.loc[m, "margin"])
    out["total"] = point_metrics(pred.loc[m, "total"], df.loc[m, "total"])
    out["home_pts"] = point_metrics(pred.loc[m, "home_pts"], df.loc[m, "home_score"].astype(float))
    out["away_pts"] = point_metrics(pred.loc[m, "away_pts"], df.loc[m, "away_score"].astype(float))
    out["wp"] = prob_metrics(pred.loc[m, "home_wp"], df.loc[m, "home_win"])
    out["ece"] = ece(pred.loc[m, "home_wp"], df.loc[m, "home_win"])
    if "poss" in pred and pred["poss"].notna().any():
        out["poss"] = point_metrics(pred.loc[m, "poss"], df.loc[m, "act_poss"])
    by = {}
    for s in sorted(df.loc[m, "season"].unique()):
        ms = m & (df["season"] == s)
        by[int(s)] = {
            "n": int(ms.sum()),
            "margin_rmse": point_metrics(pred.loc[ms, "margin"], df.loc[ms, "margin"])["rmse"],
            "total_rmse": point_metrics(pred.loc[ms, "total"], df.loc[ms, "total"])["rmse"],
            "log_loss": prob_metrics(pred.loc[ms, "home_wp"], df.loc[ms, "home_win"])["log_loss"],
        }
    out["by_season"] = by
    early = m & (
        pd.to_datetime(df["start_time_utc"], utc=True)
        .dt.tz_convert("America/New_York")
        .dt.month.isin([11, 12])
    )
    out["nov_dec"] = {
        "n": int(early.sum()),
        "margin": point_metrics(pred.loc[early, "margin"], df.loc[early, "margin"]),
        "total": point_metrics(pred.loc[early, "total"], df.loc[early, "total"]),
        "wp": prob_metrics(pred.loc[early, "home_wp"], df.loc[early, "home_win"]),
    }
    return out


def make_pred(df: pd.DataFrame, X: pd.DataFrame, poss: pd.Series | None = None) -> pd.DataFrame:
    assert_pure_frame(X, "arm features")
    margin = stack(df, X, df["margin"])
    total = stack(df, X, df["total"])
    p = pd.DataFrame({"margin": margin, "total": total}, index=df.index)
    p["home_pts"] = (total + margin) / 2
    p["away_pts"] = (total - margin) / 2
    p["home_wp"] = logistic_wp(df, margin)
    p["poss"] = (
        poss if poss is not None else (df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"])
    )
    return p


def freeze_model(
    df: pd.DataFrame, X: pd.DataFrame, arm: str, cfg, rc: RapmConfig, hca_resid: pd.Series
) -> Path:
    """Fit the promoted PURE arm on all seasons FIRST_TRAIN..2026 and write the frozen
    artifact used by the prospective archive (models/pure/<version>.json)."""
    import hashlib

    ok = X.notna().all(axis=1) & df["margin"].notna() & (df["season"] >= FIRST_TRAIN)
    spec: dict[str, object] = {
        "name": "cbb-edge-pure",
        "version": MODEL_VERSION,
        "arm": arm,
        "family": "PURE_BASKETBALL",
        "market_inputs": "NONE",
        "trained_seasons": [FIRST_TRAIN, int(df["season"].max())],
        "engine_config": {
            "lam": cfg.lam,
            "prior_regress": cfg.prior_regress,
            "recency_tau_days": cfg.recency_tau_days,
            "stats": list(cfg.stats),
        },
        "rapm_config": rc.__dict__,
        "sources": ["sportsdataverse_releases (ESPN + stats.ncaa.org bulk)"],
    }
    mu, sd = X[ok].mean(), X[ok].std().replace(0, 1.0)
    for target in ("margin", "total"):
        m = Ridge(alpha=10.0).fit((X[ok] - mu) / sd, df.loc[ok, target])
        spec[target] = {
            "features": list(X.columns),
            "mean": mu.tolist(),
            "sd": sd.tolist(),
            "coef": m.coef_.tolist(),
            "intercept": float(m.intercept_),
        }
    fitted = (
        Ridge(alpha=10.0).fit((X[ok] - mu) / sd, df.loc[ok, "margin"]).predict((X[ok] - mu) / sd)
    )
    lr = LogisticRegression(C=1e6).fit(fitted.reshape(-1, 1), df.loc[ok, "home_win"])
    spec["wp_logit"] = [float(lr.intercept_[0]), float(lr.coef_[0][0])]
    res = df.loc[ok, "margin"] - fitted
    mg = (
        np.minimum(df.loc[ok, "h_games_seen"], df.loc[ok, "a_games_seen"])
        .clip(upper=11)
        .astype(int)
    )
    spec["sigma_margin"] = float(res.std())
    spec["sigma_margin_by_games"] = {str(k): float(v) for k, v in res.groupby(mg).std().items()}
    tf = Ridge(alpha=10.0).fit((X[ok] - mu) / sd, df.loc[ok, "total"]).predict((X[ok] - mu) / sd)
    spec["sigma_total"] = float((df.loc[ok, "total"] - tf).std())
    # team home-court effect for the NEXT season: shrunk mean B3 home residual over the
    # last 3 completed seasons (same estimator as context.team_home_effect)
    last3 = (df["season"] > df["season"].max() - 3) & (df["L"] == 1) & hca_resid.notna()
    agg = hca_resid[last3].groupby(df.loc[last3, "home_team_id"]).agg(["sum", "count"])
    spec["team_hca"] = {t: float(v) for t, v in (agg["sum"] / (agg["count"] + 40.0)).items()}
    blob = json.dumps(spec, sort_keys=True)
    spec["sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    path = Path("models/pure") / f"{MODEL_VERSION}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=1, sort_keys=True))
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    games, tg = load_pure_silver()
    tg_e = enrich_team_games(tg)
    cfg = tuned_config(stats=BASE_STATS + SHOT_STATS)
    print("engine (base + shot stats)...", flush=True)
    st = cached("states_shot", lambda: run(games, tg_e, SEASONS, cfg))
    print("rapm player features...", flush=True)
    rc = rapm_cfg()
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min"],
    )
    pf = cached(
        "player_features",
        lambda: player_team_features(list(range(2011, 2027)), games, pg, rc, save=True),
    )
    df = arms.attach_games(st[st["season"] >= 2011], games)
    df = df.merge(pf.drop(columns=["season"]), on="game_id", how="left")
    df = df.merge(rest_days(games), on="game_id", how="left")
    act = actual_side_stats(tg, games)
    df = df.merge(act[["game_id", "act_poss"]], on="game_id", how="left")
    df = df[df["h_p_off"].notna()].reset_index(drop=True)
    phase = season_phase(df)

    Xb = blocks.base_block(df)
    Xp = blocks.player_block(df)
    Xs = blocks.shot_block(df)
    preds: dict[str, pd.DataFrame] = {}
    preds["B3"] = make_pred(df, Xb)
    # team-specific home court from PRIOR-season B3 home residuals (hierarchical shrink)
    hca = team_home_effect(df, df["margin"] - preds["B3"]["margin"])
    ctx = pd.concat(
        [
            df[["h_rest", "a_rest", "rest_diff", "h_b2b", "a_b2b"]].fillna(7.0),
            phase,
            hca.rename("team_hca"),
        ],
        axis=1,
    )
    Xc = blocks.context_block(df, ctx)
    preds["B6"] = make_pred(df, blocks.combine(Xb, Xp))
    preds["B7"] = make_pred(df, blocks.combine(Xb, Xs))
    preds["B8"] = make_pred(df, blocks.combine(Xb, Xc))
    preds["B9"] = make_pred(df, blocks.combine(Xb, Xp, Xs, Xc))

    # ---- possession models (P0 additive vs P1 ridge) -------------------------------
    pX = pace.pace_features(df, ctx[["h_rest", "a_rest", "ph_nov", "ph_post"]])
    poss_p1 = pace.ridge_by_season(df, pX, df["act_poss"], first_train=FIRST_TRAIN)
    poss_p0 = df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"]
    # P0 is a per-40 tempo; calibrate its level on prior seasons for a fair comparison
    poss_p0c = pace.ridge_by_season(df, pX[["add"]], df["act_poss"], first_train=FIRST_TRAIN)
    poss_summary = {}
    for name, ser in (
        ("P0_additive_raw", poss_p0),
        ("P0_additive_calibrated", poss_p0c),
        ("P1_ridge", poss_p1),
    ):
        for split, sm in (
            ("validation", df["season"].isin(VALID)),
            ("historical", df["season"].isin(HIST)),
        ):
            mm = sm & ser.notna() & df["act_poss"].notna()
            poss_summary[f"{name}|{split}"] = point_metrics(ser[mm], df.loc[mm, "act_poss"])

    # ---- metrics per arm -------------------------------------------------------------
    report: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "engine_config": {
            "lam": cfg.lam,
            "prior_regress": cfg.prior_regress,
            "recency_tau_days": cfg.recency_tau_days,
            "stats": list(cfg.stats),
        },
        "rapm_config": rc.__dict__,
        "first_train": FIRST_TRAIN,
        "validation": VALID,
        "historical": HIST,
        "possession_models": poss_summary,
        "arms": {},
    }
    common = pd.Series(True, index=df.index)
    for p in preds.values():
        common &= p["margin"].notna()
    feature_sets = {
        "B3": list(Xb.columns),
        "B6": list(Xb.columns) + list(Xp.columns),
        "B7": list(Xb.columns) + list(Xs.columns),
        "B8": list(Xb.columns) + list(Xc.columns),
        "B9": list(blocks.combine(Xb, Xp, Xs, Xc).columns),
    }
    for name, p in preds.items():
        report["arms"][name] = {
            "family": str(ARM_FAMILY[name]),
            "market_inputs": "NONE",
            "features": feature_sets[name],
            "validation": arm_metrics(df, p, common & df["season"].isin(VALID)),
            "historical": arm_metrics(df, p, common & df["season"].isin(HIST)),
        }

    # ---- promotion rule (decided before results): validation margin RMSE better than B3
    # overall AND in >= 7 of 10 validation seasons AND log loss not worse ----------------
    base = report["arms"]["B3"]["validation"]
    for name in preds:
        if name == "B3":
            continue
        v = report["arms"][name]["validation"]
        wins = sum(
            v["by_season"][s]["margin_rmse"] < base["by_season"][s]["margin_rmse"]
            for s in v["by_season"]
        )
        d_rmse = v["margin"]["rmse"] - base["margin"]["rmse"]
        d_ll = v["wp"]["log_loss"] - base["wp"]["log_loss"]
        promote = d_rmse < 0 and wins >= 7 and d_ll <= 0
        report["arms"][name]["vs_B3"] = {
            "d_margin_rmse": d_rmse,
            "d_total_rmse": v["total"]["rmse"] - base["total"]["rmse"],
            "d_log_loss": d_ll,
            "seasons_better": wins,
            "verdict": "PROMOTE" if promote else "REJECT",
        }
        print(name, report["arms"][name]["vs_B3"], flush=True)

    # ---- uncertainty: heteroscedastic sigma for the best arm ---------------------------
    best = min(preds, key=lambda a: report["arms"][a]["validation"]["margin"]["rmse"])
    bp = preds[best]
    sx = uncertainty.sigma_features(
        df, bp["margin"], bp["total"], extra=pd.DataFrame({"roster_known": Xp["roster_known"]})
    )
    sig_m = uncertainty.hetero_sigma(df, bp["margin"], "margin", sx, first_train=FIRST_TRAIN)
    sig_t = uncertainty.hetero_sigma(df, bp["total"], "total", sx, first_train=FIRST_TRAIN)
    const_m = arms.residual_sd(df.assign(season=df["season"]), bp["margin"], "margin")
    unc = {}
    for split, sm in (
        ("validation", df["season"].isin(VALID)),
        ("historical", df["season"].isin(HIST)),
    ):
        mm = sm & sig_m.notna() & bp["margin"].notna() & df["margin"].notna()
        wp_h = uncertainty.normal_wp(bp["margin"][mm], sig_m[mm])
        unc[split] = {
            "n": int(mm.sum()),
            "logistic_wp": prob_metrics(bp.loc[mm, "home_wp"], df.loc[mm, "home_win"]),
            "hetero_normal_wp": prob_metrics(wp_h, df.loc[mm, "home_win"]),
            "bucket_sd_normal_wp": prob_metrics(
                pd.Series(
                    np.clip(norm.cdf(bp["margin"][mm] / const_m[mm]), 1e-4, 1 - 1e-4),
                    index=bp["margin"][mm].index,
                ),
                df.loc[mm, "home_win"],
            ),
            "margin_coverage_hetero": uncertainty.coverage(
                bp["margin"][mm], sig_m[mm], df.loc[mm, "margin"]
            ),
            "margin_coverage_bucket": uncertainty.coverage(
                bp["margin"][mm], const_m[mm], df.loc[mm, "margin"]
            ),
            "margin_pit_dev_hetero": uncertainty.pit_calibration(
                bp["margin"][mm], sig_m[mm], df.loc[mm, "margin"]
            ),
            "margin_pit_dev_bucket": uncertainty.pit_calibration(
                bp["margin"][mm], const_m[mm], df.loc[mm, "margin"]
            ),
            "total_coverage_hetero": uncertainty.coverage(
                bp["total"][mm], sig_t[mm], df.loc[mm, "total"]
            ),
            "sigma_margin_range": [
                float(sig_m[mm].quantile(0.05)),
                float(sig_m[mm].quantile(0.95)),
            ],
        }
    report["uncertainty"] = {"arm": best, **unc}

    # ---- residuals / error decomposition for best arm ----------------------------------
    fac = pd.DataFrame(index=df.index)
    mf = arms.matchup_features(df)
    for f in ("efg", "to", "orb", "ftr"):
        fac[f"{f}_h"], fac[f"{f}_a"] = mf[f"{f}_h"], mf[f"{f}_a"]
    pred_b = bp.copy()
    pred_b["poss"] = poss_p1.where(poss_p1.notna(), bp["poss"])
    r = residual_table(df, pred_b, act, fac)
    r.to_parquet(WORK / "residuals_best.parquet", index=False)
    val = r[r["season"].isin(VALID)]
    tr_fit = r[r["season"].between(FIRST_TRAIN, 2014)]
    report["error_decomposition"] = {
        "validation": error_decomposition(val, tr_fit),
        "historical": error_decomposition(r[r["season"].isin(HIST)], tr_fit),
    }
    sl = standard_slices(val)
    report["residual_slices_validation"] = {
        k: v.astype(str).to_dict("records") for k, v in sl.items()
    }
    # ---- persist PURE predictions (immutable research artefact) ------------------------
    allp = pd.DataFrame({"game_id": df["game_id"], "season": df["season"]})
    for name, p in preds.items():
        for c in ("margin", "total", "home_pts", "away_pts", "home_wp"):
            allp[f"{name}_{c}"] = p[c]
    allp["poss_p1"] = poss_p1
    allp[f"{best}_sigma_margin"] = sig_m
    allp[f"{best}_sigma_total"] = sig_t
    allp.to_parquet(WORK / "pure_predictions.parquet", index=False)
    # ---- freeze the production PURE arm: best validation arm among B3 + PROMOTED arms --
    promoted = ["B3"] + [
        a for a in preds if a != "B3" and report["arms"][a]["vs_B3"]["verdict"] == "PROMOTE"
    ]
    prod = min(promoted, key=lambda a: report["arms"][a]["validation"]["margin"]["rmse"])
    X_by = {
        "B3": Xb,
        "B6": blocks.combine(Xb, Xp),
        "B7": blocks.combine(Xb, Xs),
        "B8": blocks.combine(Xb, Xc),
        "B9": blocks.combine(Xb, Xp, Xs, Xc),
    }
    report["production_arm"] = prod
    report["frozen_model"] = str(
        freeze_model(df, X_by[prod], prod, cfg, rc, df["margin"] - preds["B3"]["margin"])
    )
    (OUT / "metrics.json").write_text(json.dumps(report, indent=1, default=float))
    print("best arm:", best, "production arm:", prod, flush=True)


if __name__ == "__main__":
    main()
