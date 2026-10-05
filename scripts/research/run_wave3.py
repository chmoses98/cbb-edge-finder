"""Wave-3 PURE_BASKETBALL research: early-season team strength (preseason priors, roster
transformation, transfer translation, box-score priors, garbage time, network anchoring).

Season roles are unchanged from wave 2 (see run_wave2.py): DEV 2006-2014 (all fitting of
new prior components happens on DEV, 2012-2014, or walk-forward on strictly earlier
seasons), VALIDATION 2015-2024 (promotion decisions, preregistered in
research/hypotheses/WAVE3.md), HISTORICAL 2025-2026 (supporting evidence only).

Stages (each cached under data/research/wave3, so they can run in parallel):

    python scripts/research/run_wave3.py engine <b10|b10d|b13|b14|b15>
    python scripts/research/run_wave3.py pf <b11|b12|b15>
    python scripts/research/run_wave3.py arms
    python scripts/research/run_wave3.py freeze     # only if B15 is promoted

All arms are PURE_BASKETBALL. Market data is never read here; the market scorecard and
convergence curves are computed downstream by wave3_market.py from the persisted
predictions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.backtest.config import tuned_config
from cbb_edge.backtest.residuals import actual_side_stats
from cbb_edge.backtest.walkforward import run
from cbb_edge.data.http import data_dir
from cbb_edge.features.context import rest_days, season_phase, team_home_effect
from cbb_edge.features.garbage import GARBAGE_WEIGHT, garbage_weighted_tg
from cbb_edge.features.shot_profile import enrich_team_games
from cbb_edge.model import arms
from cbb_edge.model.families import ARM_FAMILY
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players import box_prior, preseason, team_prior
from cbb_edge.players.rapm import player_team_features
from cbb_edge.ratings.adjusted import BASE_STATS, SHOT_STATS
from cbb_edge.research import blocks, scorecard

sys.path.insert(0, str(Path(__file__).parent))
import run_wave2 as w2  # noqa: E402

SEASONS = w2.SEASONS
VALID, HIST = w2.VALID, w2.HIST
DEV_FIT = [2012, 2013, 2014]
OUT = Path("research/wave3")
WORK = data_dir() / "research" / "wave3"
W2 = data_dir() / "research" / "wave2"
B15_FILE = OUT / "b15_components.json"


def cached(name: str, fn):
    p = WORK / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    WORK.mkdir(parents=True, exist_ok=True)
    df = fn()
    df.to_parquet(p, index=False)
    return df


# ---------------------------------------------------------------- shared inputs ------
class Ctx:
    def __init__(self) -> None:
        self.games, self.tg = load_pure_silver()
        self.tg_e = enrich_team_games(self.tg)
        self.cfg = tuned_config(stats=BASE_STATS + SHOT_STATS)
        self.st9 = pd.read_parquet(W2 / "states_shot.parquet")
        self.pf9 = pd.read_parquet(W2 / "player_features.parquet")
        self.ps = preseason.load_player_seasons()
        self.finals9 = team_prior.season_final_ratings(self.st9, self.games)
        self.team_net = self.finals9.assign(net=self.finals9["o"] - self.finals9["d"])

    def pre(self) -> pd.DataFrame:
        return cached(
            "preseason_features",
            lambda: preseason.all_seasons(self.ps, list(range(2012, 2027))),
        )


def decay_lambda(cfg) -> dict[str, float]:
    """Per-stat λ multipliers chosen on DEV one-step error (tune_stat_decay_dev.py)."""
    t = pd.read_csv(OUT / "stat_decay_dev.csv")
    best = t.sort_values("wrmse").groupby("stat").head(1).set_index("stat")["mult"]
    lam = dict(cfg.lam)
    for s, m in best.items():
        if s in lam:
            lam[s] = cfg.lam[s] * float(m)
    return lam


def roster_hook(ctx: Ctx, pf: pd.DataFrame, conf: bool, roster: bool = True):
    strength = team_prior.team_day_strength(pf, ctx.games) if roster else None
    pre = ctx.pre() if roster else None
    ca = team_prior.conference_anchor(ctx.finals9, ctx.games) if conf else None
    coefs = team_prior.fit_prior_coefficients(
        ctx.finals9, ctx.cfg.prior_regress, DEV_FIT, strength=strength, preseason=pre, conf=ca
    )
    # conference anchor for the hook must use the hooked engine's own previous-season
    # finals in principle; the DEV-fitted B9 finals are used for both (they are
    # end-of-season ratings of completed seasons, known before the next season)
    return team_prior.TeamPriorHook(coefs, strength, pre, ca), coefs


def b15_components() -> dict[str, object]:
    """B15 composition, fixed before B15 was run (research/hypotheses/WAVE3.md)."""
    if B15_FILE.exists():
        return json.loads(B15_FILE.read_text())
    return {
        "roster_pf": "rot_b11",
        "conf": True,
        "decay": False,
        "garbage": False,
        "pf": "b11",
        "extra": ["mismatch"],
    }


def engine_stage(name: str) -> None:
    ctx = Ctx()
    cfg, tg, hook = ctx.cfg, ctx.tg_e, None
    info: dict[str, object] = {"variant": name}
    if name == "b10":
        hook, coefs = roster_hook(ctx, ctx.pf9, conf=False)
        info["coefs"] = coefs.__dict__
    elif name == "b10r":
        pf = pf_variant(ctx, "rot")
        hook, coefs = roster_hook(ctx, pf, conf=False)
        info["coefs"] = coefs.__dict__
    elif name == "b10d":
        cfg = tuned_config(stats=BASE_STATS + SHOT_STATS, lam=decay_lambda(ctx.cfg))
        info["lam"] = cfg.lam
    elif name == "b13":
        tg = garbage_weighted_tg(tg, ctx.games, GARBAGE_WEIGHT)
    elif name == "b14":
        hook, coefs = roster_hook(ctx, ctx.pf9, conf=True, roster=False)
        info["coefs"] = coefs.__dict__
    elif name == "b15":
        comp = b15_components()
        info["components"] = comp
        if comp.get("decay"):
            cfg = tuned_config(stats=BASE_STATS + SHOT_STATS, lam=decay_lambda(ctx.cfg))
        if comp.get("garbage"):
            tg = garbage_weighted_tg(tg, ctx.games, GARBAGE_WEIGHT)
        rp = comp.get("roster_pf")
        if rp or comp.get("conf"):
            pf = pf_variant(ctx, str(rp)) if rp else ctx.pf9
            hook, coefs = roster_hook(ctx, pf, conf=bool(comp.get("conf")), roster=bool(rp))
            info["coefs"] = coefs.__dict__
    else:
        raise SystemExit(f"unknown engine variant {name}")
    print(f"engine {name} ...", flush=True)
    st = run(ctx.games, tg, SEASONS, cfg, prior_hook=hook)
    WORK.mkdir(parents=True, exist_ok=True)
    st.to_parquet(WORK / f"states_{name}.parquet", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"engine_{name}.json").write_text(json.dumps(info, indent=1, default=str))


PF_VARIANTS: dict[str, dict] = {
    "b11": {"provider": dict(kind="rapm", box_update=False, translate=True)},
    # chosen on DEV (research/wave3/player_prior_dev.csv): RAPM start prior + transfer
    # translation + in-season box-score (SPM) update
    "b12": {"provider": dict(kind="rapm", box_update=True, translate=True)},
    # roster composition x season-start player ratings (no in-season RAPM updates)
    "rot": {"provider": None, "update": False},
    "rot_b11": {"provider": dict(kind="rapm", box_update=False, translate=True), "update": False},
}


def pf_variant(ctx: Ctx, name: str) -> pd.DataFrame:
    if name == "w2":
        return ctx.pf9
    p = WORK / f"pf_{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    raise SystemExit(f"run `pf {name}` first")


def pf_stage(name: str) -> None:
    ctx = Ctx()
    spec = PF_VARIANTS.get(name)
    if spec is None:
        raise SystemExit(f"unknown pf variant {name}")
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    kw = spec.get("provider")
    prov = box_prior.PlayerPriorProvider(ctx.ps, pg, ctx.team_net, **kw) if kw else None
    pf = player_team_features(
        list(range(2011, 2027)),
        ctx.games,
        pg[["season", "game_id", "team_id", "player_id", "min"]],
        w2.rapm_cfg(),
        prior_provider=prov,
        update_ratings=spec.get("update", True),
    )
    WORK.mkdir(parents=True, exist_ok=True)
    pf.to_parquet(WORK / f"pf_{name}.parquet", index=False)
    if prov is not None:
        models = {s: dict(m.__dict__) for s, m in prov.models.items() if m is not None}
        (OUT / f"pf_{name}_models.json").write_text(json.dumps(models, indent=1, default=float))


# ---------------------------------------------------------------- arms ---------------
def frame(ctx: Ctx, st: pd.DataFrame, pf: pd.DataFrame) -> pd.DataFrame:
    df = arms.attach_games(st[st["season"] >= 2011], ctx.games)
    df = df.merge(ctx.games[["game_id", "venue_city", "venue_state"]], on="game_id", how="left")
    df = df.merge(pf.drop(columns=["season"]), on="game_id", how="left")
    df = df.merge(rest_days(ctx.games), on="game_id", how="left")
    act = actual_side_stats(ctx.tg, ctx.games)
    df = df.merge(act[["game_id", "act_poss"]], on="game_id", how="left")
    return df[df["h_p_off"].notna()].reset_index(drop=True)


def arm_predictions(df: pd.DataFrame, extra: list[pd.DataFrame] | None = None):
    """Exactly the wave-2 B9 recipe (B3 -> team HCA -> B9 blocks) + optional blocks."""
    Xb = blocks.base_block(df)
    p3 = w2.make_pred(df, Xb)
    hca = team_home_effect(df, df["margin"] - p3["margin"])
    ctx_cols = df[["h_rest", "a_rest", "rest_diff", "h_b2b", "a_b2b"]].fillna(7.0)
    c = pd.concat([ctx_cols, season_phase(df), hca.rename("team_hca")], axis=1)
    X = blocks.combine(
        Xb,
        blocks.player_block(df),
        blocks.shot_block(df),
        blocks.context_block(df, c),
        *(extra or []),
    )
    return w2.make_pred(df, X), X


def compare(df, p, base, mask) -> dict[str, object]:
    m = mask & p["margin"].notna() & base["margin"].notna() & df["margin"].notna()
    mon = scorecard.buckets(df)["month"]
    early = m & mon.isin([11, 12])
    late = m & mon.isin([1, 2, 3, 4])

    def r(pp, mm):
        return float(np.sqrt(np.mean((pp.loc[mm, "margin"] - df.loc[mm, "margin"]) ** 2)))

    def ll(pp, mm):
        q = pp.loc[mm, "home_wp"].clip(1e-4, 1 - 1e-4)
        y = df.loc[mm, "home_win"]
        return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))

    seasons = sorted(df.loc[m, "season"].unique())
    wins = sum(r(p, m & (df["season"] == s)) < r(base, m & (df["season"] == s)) for s in seasons)
    return {
        "n": int(m.sum()),
        "rmse": r(p, m),
        "d_rmse": r(p, m) - r(base, m),
        "d_rmse_nov_dec": r(p, early) - r(base, early),
        "d_rmse_jan_mar": r(p, late) - r(base, late),
        "d_log_loss": ll(p, m) - ll(base, m),
        "seasons_better": int(wins),
        "n_seasons": len(seasons),
        "total_rmse": float(np.sqrt(np.mean((p.loc[m, "total"] - df.loc[m, "total"]) ** 2))),
        "by_season": {
            int(s): r(p, m & (df["season"] == s)) - r(base, m & (df["season"] == s))
            for s in seasons
        },
    }


def verdict(name: str, v: dict[str, float]) -> str:
    """Preregistered thresholds (research/hypotheses/WAVE3.md)."""
    if name.startswith("B15_"):
        return "REPORTED (not eligible for promotion)"
    if name == "B15":
        ok = (
            v["d_rmse"] <= -0.010
            and v["seasons_better"] >= 8
            and v["d_rmse_nov_dec"] <= -0.030
            and v["d_rmse_jan_mar"] <= 0.005
            and v["d_log_loss"] <= 0
        )
    else:
        ok = (
            v["d_rmse"] < 0
            and v["seasons_better"] >= 7
            and v["d_rmse_nov_dec"] < 0
            and v["d_rmse_jan_mar"] <= 0.005
            and v["d_log_loss"] <= 0
        )
    return "PROMOTE" if ok else "REJECT"


ARM_SPECS = {
    # name: (engine states, player features, extra blocks)
    "B9": ("b9", "w2", ()),
    "B10": ("b10", "w2", ("preseason",)),
    "B10_engine_only": ("b10", "w2", ()),
    "B10d": ("b10d", "w2", ()),
    "B10r": ("b10r", "w2", ("preseason",)),
    "B10r_engine_only": ("b10r", "w2", ()),
    "B11": ("b9", "b11", ()),
    "B12": ("b9", "b12", ()),
    "B13": ("b13", "w2", ("mismatch",)),
    "B13_garbage_only": ("b13", "w2", ()),
    "B13_mismatch_only": ("b9", "w2", ("mismatch",)),
    "B14": ("b14", "w2", ()),
    "B14v": ("b9", "w2", ("venue",)),
    "B15": ("b15", "B15_PF", "B15_EXTRA"),
    "B15_with_preseason": ("b15", "B15_PF", "B15_EXTRA+preseason"),
}


def arms_stage(only: list[str] | None = None) -> None:
    ctx = Ctx()
    pre = ctx.pre()
    preds: dict[str, pd.DataFrame] = {}
    frames: dict[str, pd.DataFrame] = {}
    comp = b15_components()
    for name, (eng, pfn, extra) in ARM_SPECS.items():
        if only and name not in only and name != "B9":
            continue
        if pfn == "B15_PF":
            pfn = str(comp["pf"])
        if isinstance(extra, str):
            extra = tuple(comp["extra"]) + (("preseason",) if extra.endswith("preseason") else ())
        sp = W2 / "states_shot.parquet" if eng == "b9" else WORK / f"states_{eng}.parquet"
        pp = W2 / "player_features.parquet" if pfn == "w2" else WORK / f"pf_{pfn}.parquet"
        if not sp.exists() or not pp.exists():
            print(f"skip {name}: missing {sp.name if not sp.exists() else pp.name}", flush=True)
            continue
        df = frame(ctx, pd.read_parquet(sp), pd.read_parquet(pp))
        ex = []
        if "preseason" in extra:
            ex.append(blocks.preseason_block(df, pre))
        if "mismatch" in extra:
            ex.append(blocks.mismatch_block(df))
        if "venue" in extra:
            ex.append(blocks.venue_block(df, ctx.games))
        p, _ = arm_predictions(df, ex)
        p.index = df["game_id"].to_numpy()
        preds[name] = p
        frames[name] = df.set_index("game_id", drop=False)
        print(f"arm {name} done", flush=True)
    # align every arm on the common set of games (the B9 frame)
    base_df = frames["B9"]
    ids = base_df.index
    for p in preds.values():
        ids = ids.intersection(p.index[p["margin"].notna()])
    df = base_df.loc[ids].reset_index(drop=True)
    al = {k: v.loc[ids].reset_index(drop=True) for k, v in preds.items()}
    report: dict[str, object] = {
        "note": "PURE_BASKETBALL only; thresholds preregistered in research/hypotheses/WAVE3.md",
        "n_common": len(ids),
        "arms": {},
    }
    for split, seasons in (("validation", VALID), ("historical", HIST)):
        mask = df["season"].isin(seasons)
        for name, p in al.items():
            if name == "B9":
                continue
            v = compare(df, p, al["B9"], mask)
            entry = report["arms"].setdefault(
                name, {"family": str(ARM_FAMILY.get(name, "PURE_BASKETBALL"))}
            )
            entry[split] = v
            if split == "validation":
                entry["verdict"] = verdict(name, v)
            print(
                name,
                split,
                {
                    k: (round(x, 4) if isinstance(x, float) else x)
                    for k, x in v.items()
                    if k != "by_season"
                },
                flush=True,
            )
    # scorecard (pure only) and convergence curves
    sc = []
    for split, seasons in (("validation", VALID), ("historical", HIST)):
        s = scorecard.scorecard(df, al, df["season"].isin(seasons))
        sc.append(s.assign(split=split))
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(sc).to_csv(OUT / "scorecard_pure.csv", index=False)
    allp = pd.DataFrame({"game_id": df["game_id"], "season": df["season"]})
    for c in ("start_time_utc", "h_games_seen", "a_games_seen", "home_team_id", "away_team_id"):
        allp[c] = df[c]
    for name, p in al.items():
        for c in ("margin", "total", "home_wp"):
            allp[f"{name}_{c}"] = p[c].to_numpy()
    WORK.mkdir(parents=True, exist_ok=True)
    allp.to_parquet(WORK / "pure_predictions.parquet", index=False)
    (OUT / "metrics.json").write_text(json.dumps(report, indent=1, default=float))


# ---------------------------------------------------------------- freeze -------------
NEW_VERSION = "pure-0.3.0"


def _prov_spec(name: object) -> dict | None:
    """Live provider spec for a PF variant (None = wave-2 carry priors, no provider)."""
    if not name or name == "w2":
        return None
    kw = PF_VARIANTS[str(name)]["provider"]
    if kw is None:
        return None
    return {**kw, "half_minutes": box_prior.BOX_HALF_MINUTES, "carry": 0.95}


def freeze_stage() -> None:
    """Freeze B15 as ``pure-0.3.0`` — only if B15's preregistered verdict is PROMOTE.
    Writes a NEW artifact; refuses to overwrite any existing one (pure-0.2.0 untouched)."""
    import hashlib

    from sklearn.linear_model import LogisticRegression, Ridge

    rep = json.loads((OUT / "metrics.json").read_text())
    if rep["arms"].get("B15", {}).get("verdict") != "PROMOTE":
        raise SystemExit("B15 not promoted: nothing frozen; pure-0.2.0 stays production")
    path = Path("models/pure") / f"{NEW_VERSION}.json"
    if path.exists():
        raise SystemExit(f"{path} exists: frozen artifacts are immutable")
    ctx = Ctx()
    comp = b15_components()
    df = frame(
        ctx,
        pd.read_parquet(WORK / "states_b15.parquet"),
        pf_variant(ctx, str(comp["pf"])),
    )
    ex = [blocks.mismatch_block(df)] if "mismatch" in comp["extra"] else []
    p3 = w2.make_pred(df, blocks.base_block(df))
    hca_resid = df["margin"] - p3["margin"]
    _, X = arm_predictions(df, ex)
    eng = json.loads((OUT / "engine_b15.json").read_text())
    pf_models: dict[str, object] = {}
    pspec = _prov_spec(comp.get("pf"))
    if pspec is not None:
        pf_models = json.loads((OUT / f"pf_{comp['pf']}_models.json").read_text())
        pairs = box_prior.pair_table(ctx.ps, ctx.team_net, 2026)
        pf_models["2027"] = dict(box_prior.fit_prior_model(pairs, pspec["kind"], 2026).__dict__)
    cfg = ctx.cfg
    ok = X.notna().all(axis=1) & df["margin"].notna() & (df["season"] >= w2.FIRST_TRAIN)
    spec: dict[str, object] = {
        "name": "cbb-edge-pure",
        "version": NEW_VERSION,
        "arm": "B15",
        "family": "PURE_BASKETBALL",
        "market_inputs": "NONE",
        "trained_seasons": [w2.FIRST_TRAIN, int(df["season"].max())],
        "engine_config": {
            "lam": cfg.lam,
            "prior_regress": cfg.prior_regress,
            "recency_tau_days": cfg.recency_tau_days,
            "stats": list(cfg.stats),
        },
        "rapm_config": w2.rapm_cfg().__dict__,
        "team_prior_hook": {**eng["coefs"], "stats": ["eff"], "fit_seasons": DEV_FIT},
        "player_prior": {
            "roster_strength": _prov_spec(comp.get("roster_pf")),
            "player_features": _prov_spec(comp.get("pf")),
            "models": pf_models,
        },
        "extra_blocks": list(comp["extra"]),
        "b15_components": comp,
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
        str(int(k)): float(v) for k, v in res.groupby(mg.astype(int)).std().items()
    }
    tf = Ridge(alpha=10.0).fit(Z, df.loc[ok, "total"]).predict(Z)
    spec["sigma_total"] = float((df.loc[ok, "total"] - tf).std())
    last3 = (df["season"] > df["season"].max() - 3) & (df["L"] == 1) & hca_resid.notna()
    agg = hca_resid[last3].groupby(df.loc[last3, "home_team_id"]).agg(["sum", "count"])
    spec["team_hca"] = {t: float(v) for t, v in (agg["sum"] / (agg["count"] + 40.0)).items()}
    blob = json.dumps(spec, sort_keys=True, default=float)
    spec = json.loads(blob)
    spec["sha256"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps(spec, indent=1, sort_keys=True))
    print(f"frozen {path} sha256={spec['sha256']}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "arms"
    if stage == "engine":
        engine_stage(sys.argv[2])
    elif stage == "pf":
        pf_stage(sys.argv[2])
    elif stage == "freeze":
        freeze_stage()
    else:
        arms_stage(sys.argv[2:] or None)
