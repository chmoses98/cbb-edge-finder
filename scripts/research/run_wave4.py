"""Wave-4 PURE_BASKETBALL research harness (preregistered in research/hypotheses/WAVE4.md).

Reference: B15 = pure-0.3.0 (states_b15, player features pf_b12, mismatch block).
Evaluation: blocked rolling-origin folds F1..F5 (2 validation seasons each), day-
clustered bootstrap, gates fixed in WAVE4.md. 2025-26 reported as evidence only.

Stages (cached under data/research/wave4):

    python scripts/research/run_wave4.py pf <b19h|b19oracle>
    python scripts/research/run_wave4.py engine <b16b>
    python scripts/research/run_wave4.py arms [ARM ...]
    python scripts/research/run_wave4.py freeze      # only if B20 passes

No market data is read here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.players import availability_model as am
from cbb_edge.players import box_prior
from cbb_edge.players.rapm import player_team_features
from cbb_edge.research import blocks

sys.path.insert(0, str(Path(__file__).parent))
import run_wave2 as w2  # noqa: E402
import run_wave3 as w3  # noqa: E402

OUT = Path("research/wave4")
WORK = data_dir() / "research" / "wave4"
W3 = data_dir() / "research" / "wave3"
VALID, HIST = w2.VALID, w2.HIST
BLOCKS = {
    "F1": [2015, 2016],
    "F2": [2017, 2018],
    "F3": [2019, 2020],
    "F4": [2021, 2022],
    "F5": [2023, 2024],
}


def persistence_models(t: pd.DataFrame) -> dict[int, am.Persistence]:
    """P(plays) model for season s fitted on absence rows of seasons < s only."""
    out = {}
    for s in range(2012, 2028):
        tr = t[t["season"] < s]
        if tr["season"].nunique() >= 1 and len(tr) > 10000:
            out[s] = am.fit_persistence(tr)
    return out


def pf_stage(name: str) -> None:
    ctx = w3.Ctx()
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    t = pd.read_parquet(WORK / "absence_table.parquet")
    rep = json.loads((OUT / "absence_study.json").read_text())["replacement"]
    pos = pg.sort_values("season").drop_duplicates("player_id", keep="last")
    positions = {p: am._pos(x) for p, x in zip(pos["player_id"], pos["position"], strict=True)}
    actual = None
    mode = "persistence"
    if name == "b19oracle":
        mode = "oracle"
        actual = pg.groupby("game_id")["player_id"].agg(set).to_dict()
    adj = am.AvailabilityAdjuster(
        persistence_models(t), positions, rep["gamma"], rep["beta"], mode=mode, actual=actual
    )
    prov = box_prior.PlayerPriorProvider(
        ctx.ps, pg, ctx.team_net, **w3.PF_VARIANTS["b12"]["provider"]
    )
    pf = player_team_features(
        list(range(2011, 2027)),
        ctx.games,
        pg[["season", "game_id", "team_id", "player_id", "min"]],
        w2.rapm_cfg(),
        prior_provider=prov,
        share_adjust=adj,
    )
    WORK.mkdir(parents=True, exist_ok=True)
    pf.to_parquet(WORK / f"pf_{name}.parquet", index=False)


# ---------------------------------------------------------------- evaluation ---------
def _rmse(e: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(e))))


def blocked_compare(
    df: pd.DataFrame, p: pd.DataFrame, base: pd.DataFrame, n_boot: int = 2000, seed: int = 0
) -> dict[str, object]:
    """Δ vs base on validation 2015-2024 by block, season, month; day-clustered
    bootstrap (stratified by block) of pooled Δ RMSE; 2025-26 evidence."""
    m = p["margin"].notna() & base["margin"].notna() & df["margin"].notna()
    y = df["margin"].to_numpy()
    ea = (p["margin"] - df["margin"]).to_numpy()
    eb = (base["margin"] - df["margin"]).to_numpy()
    mon = pd.to_datetime(df["start_time_utc"], utc=True).dt.tz_convert("America/New_York").dt.month

    def d(mask) -> float:
        mm = (m & mask).to_numpy()
        return _rmse(ea[mm]) - _rmse(eb[mm]) if mm.any() else float("nan")

    def ll(pp, mask) -> float:
        mm = m & mask
        q = pp.loc[mm, "home_wp"].clip(1e-4, 1 - 1e-4)
        yy = df.loc[mm, "home_win"]
        return float(-np.mean(yy * np.log(q) + (1 - yy) * np.log(1 - q)))

    val = df["season"].isin(VALID)
    out: dict[str, object] = {
        "n_val": int((m & val).sum()),
        "rmse_val": _rmse(ea[(m & val).to_numpy()]),
        "d_rmse": d(val),
        "d_nov_dec": d(val & mon.isin([11, 12])),
        "d_jan_mar": d(val & mon.isin([1, 2, 3, 4])),
        "d_log_loss": ll(p, val) - ll(base, val),
        "blocks": {b: d(df["season"].isin(s)) for b, s in BLOCKS.items()},
        "seasons": {int(s): d(df["season"] == s) for s in VALID},
        "hist_d_rmse": d(df["season"].isin(HIST)),
        "hist_d_nov_dec": d(df["season"].isin(HIST) & mon.isin([11, 12])),
        "d_total_rmse": _rmse((p["total"] - df["total"]).to_numpy()[(m & val).to_numpy()])
        - _rmse((base["total"] - df["total"]).to_numpy()[(m & val).to_numpy()]),
    }
    del y
    # day-clustered bootstrap stratified by block
    rng = np.random.default_rng(seed)
    v = (m & val).to_numpy()
    days = df["game_date_et"].astype(str).to_numpy()
    blk = df["season"].map({s: b for b, ss in BLOCKS.items() for s in ss}).to_numpy()
    sa, sb = ea**2, eb**2
    frame = pd.DataFrame({"day": days[v], "blk": blk[v], "a": sa[v], "b": sb[v]})
    g = frame.groupby(["blk", "day"]).agg(a=("a", "sum"), b=("b", "sum"), n=("a", "size"))
    g = g.reset_index()
    groups = [x for _, x in g.groupby("blk")]
    deltas = []
    for _ in range(n_boot):
        A = B = N = 0.0
        for x in groups:
            i = rng.integers(0, len(x), len(x))
            A += x["a"].to_numpy()[i].sum()
            B += x["b"].to_numpy()[i].sum()
            N += x["n"].to_numpy()[i].sum()
        deltas.append(np.sqrt(A / N) - np.sqrt(B / N))
    deltas = np.asarray(deltas)
    out["boot_p_better"] = float((deltas < 0).mean())
    out["boot_ci90"] = [float(np.quantile(deltas, 0.05)), float(np.quantile(deltas, 0.95))]
    return out


def gate(name: str, v: dict[str, object]) -> str:
    """Preregistered gates (WAVE4.md)."""
    blocks = list(v["blocks"].values())
    if name == "B20":
        seasons_better = sum(x < 0 for x in v["seasons"].values())
        ok = (
            v["d_rmse"] <= -0.005
            and all(x < 0 for x in blocks)
            and seasons_better >= 8
            and v["boot_p_better"] >= 0.975
            and v["d_log_loss"] <= 0
            and v["d_nov_dec"] <= 0.003
            and v["d_jan_mar"] <= 0.003
            and v["hist_d_rmse"] <= 0.010
        )
        return "FREEZE" if ok else "REJECT"
    ok = (
        v["d_rmse"] < 0
        and sum(x < 0 for x in blocks) >= 4
        and max(blocks) <= 0.005
        and v["boot_p_better"] >= 0.90
        and v["d_log_loss"] <= 0
        and v["d_nov_dec"] <= 0.005
        and v["d_jan_mar"] <= 0.005
    )
    return "USEFUL" if ok else "NOT USEFUL"


# ---------------------------------------------------------------- B16b engine --------
def b16b_hook(ctx, k: float):
    from cbb_edge.players import team_prior

    eng = json.loads((w3.OUT / "engine_b15.json").read_text())["coefs"]
    coefs = team_prior.PriorCoefficients(
        components=tuple(eng["components"]), pre=eng["pre"], obs=eng["obs"], n=eng["n"]
    )
    pf_rot = w3.pf_variant(ctx, "rot")
    strength = team_prior.team_day_strength(pf_rot, ctx.games)
    ca = team_prior.conference_anchor(ctx.finals9, ctx.games)
    return team_prior.DynamicConferenceHook(coefs, ctx.games, k, strength, ctx.pre(), ca)


def _margin_an_rmse(st: pd.DataFrame, games: pd.DataFrame, seasons: list[int]) -> float:
    from cbb_edge.model import arms

    df = arms.attach_games(st[st["season"].isin(seasons)], games)
    m = arms.matchup_features(df)["margin_an"]
    ok = m.notna() & df["margin"].notna()
    return _rmse((m - df["margin"])[ok].to_numpy())


def engine_stage(name: str) -> None:
    from cbb_edge.backtest.walkforward import run

    ctx = w3.Ctx()
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if name == "b16b_dev":
        dev = [2012, 2013, 2014]
        base = pd.read_parquet(W3 / "states_b15.parquet")
        rows = [{"k": "static (B15)", "dev_margin_an_rmse": _margin_an_rmse(base, ctx.games, dev)}]
        for k in (25.0, 100.0, 400.0):
            st = run(
                ctx.games,
                ctx.tg_e,
                list(range(2006, 2015)),
                ctx.cfg,
                verbose=False,
                prior_hook=b16b_hook(ctx, k),
            )
            rows.append({"k": k, "dev_margin_an_rmse": _margin_an_rmse(st, ctx.games, dev)})
            print(rows[-1], flush=True)
        pd.DataFrame(rows).to_csv(OUT / "b16b_k_dev.csv", index=False)
        return
    if name == "b16b":
        t = pd.read_csv(OUT / "b16b_k_dev.csv")
        t = t[t["k"] != "static (B15)"].sort_values("dev_margin_an_rmse")
        k = float(t.iloc[0]["k"])
        st = run(ctx.games, ctx.tg_e, w2.SEASONS, ctx.cfg, prior_hook=b16b_hook(ctx, k))
        st.to_parquet(WORK / "states_b16b.parquet", index=False)
        (OUT / "engine_b16b.json").write_text(json.dumps({"k": k}))
        return
    raise SystemExit(f"unknown engine {name}")


# ---------------------------------------------------------------- B17 shooting -------
def shoot_stage() -> None:
    from dataclasses import asdict

    from cbb_edge.model.pure import load_pure_silver
    from cbb_edge.players import shooting

    games, _ = load_pure_silver()
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna()]
    x = shooting.player_games(pg)
    cb = shooting.career_before(x)
    sp = shooting.fit_prior(cb, list(range(2008, 2015)))
    print("kappa", sp.kappa, "b3", sp.b3, flush=True)
    tf = shooting.team_features(x, games, sp)
    WORK.mkdir(parents=True, exist_ok=True)
    tf.to_parquet(WORK / "shooting_features.parquet", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "shooting_prior.json").write_text(json.dumps(asdict(sp), indent=1, default=float))


# ---------------------------------------------------------------- arms ---------------
def make_pred(
    df: pd.DataFrame,
    X: pd.DataFrame,
    margin_target: pd.Series | None = None,
    X_total: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Wave-2/3 stacking (expanding window, logistic WP) with optional separate margin
    target (B18r) and extra total-only features (B18t)."""
    from cbb_edge.model.families import assert_pure_frame

    assert_pure_frame(X, "wave4 features")
    margin = w2.stack(df, X, df["margin"] if margin_target is None else margin_target)
    Xt = X if X_total is None else pd.concat([X, X_total], axis=1)
    total = w2.stack(df, Xt, df["total"])
    out = pd.DataFrame({"margin": margin, "total": total}, index=df.index)
    out["home_pts"] = (total + margin) / 2
    out["away_pts"] = (total - margin) / 2
    out["home_wp"] = w2.logistic_wp(df, margin)
    return out


def base_X(df: pd.DataFrame, extra: list[pd.DataFrame]) -> pd.DataFrame:
    from cbb_edge.features.context import season_phase, team_home_effect
    from cbb_edge.research import blocks

    Xb = blocks.base_block(df)
    p3 = w2.make_pred(df, Xb)
    hca = team_home_effect(df, df["margin"] - p3["margin"])
    c = pd.concat(
        [
            df[["h_rest", "a_rest", "rest_diff", "h_b2b", "a_b2b"]].fillna(7.0),
            season_phase(df),
            hca.rename("team_hca"),
        ],
        axis=1,
    )
    return blocks.combine(
        Xb,
        blocks.player_block(df),
        blocks.shot_block(df),
        blocks.context_block(df, c),
        blocks.mismatch_block(df),
        *extra,
    )


def rematch_block(df: pd.DataFrame, p15: pd.DataFrame) -> pd.DataFrame:
    """B16a: earlier meetings this season (tip < current tip only), B15 OOS residuals."""
    from cbb_edge.model.families import assert_pure_frame

    d = df[
        [
            "game_id",
            "season",
            "start_time_utc",
            "home_team_id",
            "away_team_id",
            "margin",
            "total",
            "act_poss",
            "mu_tempo",
            "h_off_tempo",
            "a_off_tempo",
        ]
    ].copy()
    d["r_m"] = d["margin"] - p15["margin"]
    d["r_t"] = d["total"] - p15["total"]
    d["r_p"] = d["act_poss"] - (d["mu_tempo"] + d["h_off_tempo"] + d["a_off_tempo"])
    d["pair"] = [tuple(sorted(x)) for x in zip(d["home_team_id"], d["away_team_id"], strict=True)]
    d = d.sort_values("start_time_utc")
    g = d.groupby(["season", "pair"])
    prev_home = g["home_team_id"].shift(1)
    same = (prev_home == d["home_team_id"]).astype(float)
    sign = np.where(prev_home.isna(), 0.0, np.where(same == 1, 1.0, -1.0))
    X = pd.DataFrame(index=d.index)
    X["rm_n"] = g.cumcount().clip(upper=2).astype(float)
    X["rm_flag"] = (X["rm_n"] > 0).astype(float)
    X["rm_margin_resid"] = (g["r_m"].shift(1) * sign).fillna(0.0)
    X["rm_total_resid"] = g["r_t"].shift(1).fillna(0.0)
    X["rm_poss_resid"] = g["r_p"].shift(1).fillna(0.0)
    X["rm_venue_swap"] = (prev_home.notna() & (prev_home != d["home_team_id"])).astype(float)
    return assert_pure_frame(X.reindex(df.index), "rematch_block")


def calibrate(df: pd.DataFrame, pm: pd.Series) -> pd.Series:
    """B18: spline-ridge calibration of OOS margin, fitted on earlier predicted seasons."""
    from sklearn.linear_model import Ridge

    knots = (-25, -20, -15, -10, -5, 5, 10, 15, 20, 25)

    def basis(v: pd.Series) -> np.ndarray:
        return np.column_stack([v] + [np.maximum(v - k, 0) for k in knots])

    out = pm.copy()
    for s in sorted(df["season"].unique()):
        tr = (df["season"] < s) & (df["season"] >= 2015) & pm.notna() & df["margin"].notna()
        cur = (df["season"] == s) & pm.notna()
        if df.loc[tr, "season"].nunique() < 1 or not cur.any():
            continue
        m = Ridge(alpha=10.0).fit(basis(pm[tr]), df.loc[tr, "margin"])
        out[cur] = m.predict(basis(pm[cur]))
    return out


def arms_stage(only: list[str] | None = None) -> None:
    ctx = w3.Ctx()
    pf12 = pd.read_parquet(W3 / "pf_b12.parquet")
    st15 = pd.read_parquet(W3 / "states_b15.parquet")
    df = w3.frame(ctx, st15, pf12)
    df["game_date_et"] = df["game_id"].map(ctx.games.set_index("game_id")["game_date_et"])
    X15 = base_X(df, [])
    preds: dict[str, pd.DataFrame] = {"B15": make_pred(df, X15)}
    keyed = df.set_index("game_id")

    def realign(other: pd.DataFrame, p: pd.DataFrame) -> pd.DataFrame:
        return p.set_index(other["game_id"].to_numpy()).reindex(keyed.index).reset_index(drop=True)

    def want(a: str) -> bool:
        return only is None or a in only

    if want("B16a") or want("B20"):
        preds["B16a"] = make_pred(df, pd.concat([X15, rematch_block(df, preds["B15"])], axis=1))
    if (want("B16b") or want("B20")) and (WORK / "states_b16b.parquet").exists():
        d2 = w3.frame(ctx, pd.read_parquet(WORK / "states_b16b.parquet"), pf12)
        preds["B16b"] = realign(d2, make_pred(d2, base_X(d2, [])))
    if want("B17") or want("B20"):
        sf = pd.read_parquet(WORK / "shooting_features.parquet")
        preds["B17"] = make_pred(df, pd.concat([X15, blocks.shooting_block(df, sf)], axis=1))
    if want("B18") or want("B20"):
        b18 = preds["B15"].copy()
        b18["margin"] = calibrate(df, preds["B15"]["margin"])
        b18["home_wp"] = w2.logistic_wp(df, b18["margin"])
        preds["B18"] = b18
        reg = df["margin"].where(df["n_ot"].fillna(0) == 0, 0.0) if "n_ot" in df else None
        if reg is None:
            nt = df["game_id"].map(ctx.games.set_index("game_id")["n_ot"]).fillna(0)
            reg = df["margin"].where(nt == 0, 0.0)
        preds["B18r"] = make_pred(df, X15, margin_target=reg)
        from cbb_edge.model import arms as _arms

        ma = _arms.matchup_features(df)["margin_an"].abs()
        preds["B18t"] = make_pred(
            df,
            X15,
            X_total=pd.DataFrame(
                {"abs_margin_an": ma, "close_sq": np.minimum(ma, 10.0) ** 2}, index=df.index
            ),
        )
    for nm in ("b19h", "b19oracle"):
        arm = "B19h" if nm == "b19h" else "B19oracle"
        if (want(arm) or (arm == "B19h" and want("B20"))) and (WORK / f"pf_{nm}.parquet").exists():
            d2 = w3.frame(ctx, st15, pd.read_parquet(WORK / f"pf_{nm}.parquet"))
            preds[arm] = realign(d2, make_pred(d2, base_X(d2, [])))
    if want("B20"):
        comp = json.loads((OUT / "b20_components.json").read_text())["components"]
        st = pd.read_parquet(WORK / "states_b16b.parquet") if "B16b" in comp else st15
        pf = pd.read_parquet(WORK / "pf_b19h.parquet") if "B19h" in comp else pf12
        d2 = w3.frame(ctx, st, pf)
        ex = (
            [blocks.shooting_block(d2, pd.read_parquet(WORK / "shooting_features.parquet"))]
            if "B17" in comp
            else []
        )
        preds["B20"] = realign(d2, make_pred(d2, base_X(d2, ex)))
    report: dict[str, object] = {"reference": "B15 (pure-0.3.0)", "arms": {}}
    eligible = {"B16a", "B16b", "B17", "B18", "B18r", "B19h", "B20"}
    for name, p in preds.items():
        if name == "B15":
            continue
        v = blocked_compare(df, p, preds["B15"])
        v["verdict"] = gate(name, v) if name in eligible else "DIAGNOSTIC / EXPLORATORY"
        report["arms"][name] = v
        print(
            name,
            {
                k: (round(x, 4) if isinstance(x, float) else x)
                for k, x in v.items()
                if k not in ("seasons",)
            },
            flush=True,
        )
    useful = [a for a, v in report["arms"].items() if v["verdict"] == "USEFUL"]
    report["useful_components"] = useful
    OUT.mkdir(parents=True, exist_ok=True)
    allp = pd.DataFrame({"game_id": df["game_id"], "season": df["season"]})
    for c in ("start_time_utc", "h_games_seen", "a_games_seen", "home_team_id", "away_team_id"):
        allp[c] = df[c]
    for name, p in preds.items():
        for c in ("margin", "total", "home_wp"):
            allp[f"{name}_{c}"] = p[c].to_numpy()
    WORK.mkdir(parents=True, exist_ok=True)
    allp.to_parquet(
        WORK / ("pure_predictions.parquet" if only is None else "pure_predictions_partial.parquet"),
        index=False,
    )
    fn = "metrics.json" if only is None else "metrics_partial.json"
    (OUT / fn).write_text(json.dumps(report, indent=1, default=float))


# ---------------------------------------------------------------- freeze -------------
NEW_VERSION = "pure-0.4.0"


def freeze_stage() -> None:
    """Freeze B20 as pure-0.4.0 — only if its preregistered gate says FREEZE. Writes a
    NEW artifact and refuses to overwrite any existing one."""
    import hashlib
    from dataclasses import asdict

    from sklearn.linear_model import LogisticRegression, Ridge

    rep = json.loads((OUT / "metrics.json").read_text())
    if rep["arms"].get("B20", {}).get("verdict") != "FREEZE":
        raise SystemExit("B20 not frozen by the gate: nothing written")
    path = Path("models/pure") / f"{NEW_VERSION}.json"
    if path.exists():
        raise SystemExit(f"{path} exists: frozen artifacts are immutable")
    ctx = w3.Ctx()
    comp = json.loads((OUT / "b20_components.json").read_text())["components"]
    df = w3.frame(
        ctx,
        pd.read_parquet(WORK / "states_b16b.parquet"),
        pd.read_parquet(WORK / "pf_b19h.parquet"),
    )
    sf = pd.read_parquet(WORK / "shooting_features.parquet")
    X = base_X(df, [blocks.shooting_block(df, sf)])
    p3 = w2.make_pred(df, blocks.base_block(df))
    hca_resid = df["margin"] - p3["margin"]
    eng = json.loads((w3.OUT / "engine_b15.json").read_text())["coefs"]
    k = json.loads((OUT / "engine_b16b.json").read_text())["k"]
    pf_models = json.loads((w3.OUT / "pf_b12_models.json").read_text())
    pairs = box_prior.pair_table(ctx.ps, ctx.team_net, 2026)
    pf_models["2027"] = dict(box_prior.fit_prior_model(pairs, "rapm", 2026).__dict__)
    t = pd.read_parquet(WORK / "absence_table.parquet")
    pers = {str(s_): asdict(m) for s_, m in persistence_models(t).items()}
    rep_ab = json.loads((OUT / "absence_study.json").read_text())["replacement"]
    sp = json.loads((OUT / "shooting_prior.json").read_text())
    sp.pop("fit", None)
    cfg = ctx.cfg
    ok = X.notna().all(axis=1) & df["margin"].notna() & (df["season"] >= w2.FIRST_TRAIN)
    spec: dict[str, object] = {
        "name": "cbb-edge-pure",
        "version": NEW_VERSION,
        "arm": "B20",
        "family": "PURE_BASKETBALL",
        "market_inputs": "NONE",
        "trained_seasons": [w2.FIRST_TRAIN, int(df["season"].max())],
        "components": comp,
        "engine_config": {
            "lam": cfg.lam,
            "prior_regress": cfg.prior_regress,
            "recency_tau_days": cfg.recency_tau_days,
            "stats": list(cfg.stats),
        },
        "rapm_config": w2.rapm_cfg().__dict__,
        "team_prior_hook": {**eng, "stats": ["eff"], "fit_seasons": w3.DEV_FIT, "dynamic_k": k},
        "player_prior": {
            "roster_strength": None,
            "player_features": {
                **w3.PF_VARIANTS["b12"]["provider"],
                "half_minutes": box_prior.BOX_HALF_MINUTES,
                "carry": 0.95,
            },
            "models": pf_models,
        },
        "availability_model": {
            "gamma": rep_ab["gamma"],
            "beta": rep_ab["beta"],
            "persistence": pers,
            "mode": "persistence",
        },
        "shooting_prior": sp,
        "extra_blocks": ["mismatch", "shooting"],
        "sources": ["sportsdataverse_releases (ESPN + stats.ncaa.org bulk)"],
    }
    mu, sd = X[ok].mean(), X[ok].std().replace(0, 1.0)
    Z = (X[ok] - mu) / sd
    for target in ("margin", "total"):
        m = Ridge(alpha=10.0).fit(Z, df.loc[ok, target])
        spec[target] = {
            "features": list(X.columns),
            "mean": mu.tolist(),
            "sd": sd.tolist(),
            "coef": m.coef_.tolist(),
            "intercept": float(m.intercept_),
        }
    fitted = Ridge(alpha=10.0).fit(Z, df.loc[ok, "margin"]).predict(Z)
    lr = LogisticRegression(C=1e6).fit(fitted.reshape(-1, 1), df.loc[ok, "home_win"])
    spec["wp_logit"] = [float(lr.intercept_[0]), float(lr.coef_[0][0])]
    res = df.loc[ok, "margin"] - fitted
    mg = np.minimum(df.loc[ok, "h_games_seen"], df.loc[ok, "a_games_seen"]).clip(upper=11)
    spec["sigma_margin"] = float(res.std())
    spec["sigma_margin_by_games"] = {
        str(int(a)): float(b) for a, b in res.groupby(mg.astype(int)).std().items()
    }
    tf = Ridge(alpha=10.0).fit(Z, df.loc[ok, "total"]).predict(Z)
    spec["sigma_total"] = float((df.loc[ok, "total"] - tf).std())
    last3 = (df["season"] > df["season"].max() - 3) & (df["L"] == 1) & hca_resid.notna()
    agg = hca_resid[last3].groupby(df.loc[last3, "home_team_id"]).agg(["sum", "count"])
    spec["team_hca"] = {a: float(b) for a, b in (agg["sum"] / (agg["count"] + 40.0)).items()}
    spec = json.loads(json.dumps(spec, sort_keys=True, default=float))
    spec["sha256"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps(spec, indent=1, sort_keys=True))
    print(f"frozen {path} sha256={spec['sha256']}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "arms"
    if stage == "pf":
        pf_stage(sys.argv[2])
    elif stage == "engine":
        engine_stage(sys.argv[2])
    elif stage == "shoot":
        shoot_stage()
    elif stage == "freeze":
        freeze_stage()
    else:
        arms_stage(sys.argv[2:] or None)
