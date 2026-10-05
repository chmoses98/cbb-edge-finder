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
from cbb_edge.features.shot_profile import enrich_team_games
from cbb_edge.model import arms
from cbb_edge.model.families import ARM_FAMILY, assert_pure_frame
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players import box_prior, preseason, team_prior
from cbb_edge.players.rapm import player_team_features
from cbb_edge.players.stints import stints_path
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
GARBAGE_WEIGHT = 0.3  # same fixed constant as the wave-2 RAPM (not tuned)
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


def garbage_weighted_tg(tg: pd.DataFrame, games: pd.DataFrame, w: float) -> pd.DataFrame:
    """Team-game points per possession with garbage-time possessions down-weighted.

    Uses the game's own NCAA possession data (flag ``is_garbage_time``), available only
    after the game — the same timestamp as the box score it replaces. Applied when the
    stint possessions match the box-score possession estimate within 15%; otherwise
    the raw box value is kept.
    """
    parts = []
    for s in sorted(tg["season"].unique()):
        p = stints_path(int(s))
        if not p.exists():
            continue
        st = pd.read_parquet(p, columns=["game_id", "off_home", "poss", "pts", "garbage"])
        g = st.groupby(["game_id", "off_home"]).agg(
            poss=("poss", "sum"), pts=("pts", "sum"), garb=("garbage", "sum")
        )
        # points in garbage time: stint points pro rata to garbage possessions
        st["gpts"] = st["pts"] * st["garbage"] / st["poss"].clip(lower=1)
        g["gpts"] = st.groupby(["game_id", "off_home"])["gpts"].sum()
        parts.append(g.reset_index())
    if not parts:
        return tg
    g = pd.concat(parts)
    g["ppp_c"] = (g["pts"] - (1 - w) * g["gpts"]) / (g["poss"] - (1 - w) * g["garb"]).clip(lower=1)
    hm = games[["game_id", "home_espn_id"]]
    out = tg.merge(hm, on="game_id", how="left")
    out["off_home"] = out["team_espn_id"] == out["home_espn_id"]
    own = g[["game_id", "off_home", "ppp_c", "poss"]].rename(columns={"poss": "st_poss"})
    out = out.merge(own, on=["game_id", "off_home"], how="left")
    opp = g[["game_id", "off_home", "ppp_c"]].rename(columns={"ppp_c": "opp_ppp_c"})
    opp["off_home"] = ~opp["off_home"]
    out = out.merge(opp, on=["game_id", "off_home"], how="left")
    ok = out["ppp_c"].notna() & out["opp_ppp_c"].notna()
    ok &= (out["st_poss"] / out["poss"]).between(0.85, 1.15)
    out.loc[ok, "ppp"] = out.loc[ok, "ppp_c"]
    out.loc[ok, "opp_ppp"] = out.loc[ok, "opp_ppp_c"]
    print(f"  garbage weighting applied to {ok.mean():.1%} of team-games", flush=True)
    return out.drop(columns=["home_espn_id", "off_home", "ppp_c", "opp_ppp_c", "st_poss"])


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


def b15_components() -> dict[str, bool]:
    if B15_FILE.exists():
        return json.loads(B15_FILE.read_text())
    return {"roster": True, "decay": True, "garbage": True, "conf": True, "pf": "b12"}


def engine_stage(name: str) -> None:
    ctx = Ctx()
    cfg, tg, hook = ctx.cfg, ctx.tg_e, None
    info: dict[str, object] = {"variant": name}
    if name == "b10":
        hook, coefs = roster_hook(ctx, ctx.pf9, conf=False)
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
        if comp.get("roster") or comp.get("conf"):
            pf = pf_variant(ctx, comp.get("pf") or "w2")
            hook, coefs = roster_hook(
                ctx, pf, conf=bool(comp.get("conf")), roster=bool(comp.get("roster"))
            )
            info["coefs"] = coefs.__dict__
    else:
        raise SystemExit(f"unknown engine variant {name}")
    print(f"engine {name} ...", flush=True)
    st = run(ctx.games, tg, SEASONS, cfg, prior_hook=hook)
    WORK.mkdir(parents=True, exist_ok=True)
    st.to_parquet(WORK / f"states_{name}.parquet", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"engine_{name}.json").write_text(json.dumps(info, indent=1, default=str))


PF_VARIANTS = {
    "b11": dict(kind="rapm", box_update=False, translate=True),
    "b12": dict(kind="both", box_update=True, translate=True),
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
    kw = PF_VARIANTS.get(name)
    if name == "b15":
        kw = PF_VARIANTS[b15_components().get("pf") or "b12"]
    if kw is None:
        raise SystemExit(f"unknown pf variant {name}")
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    prov = box_prior.PlayerPriorProvider(ctx.ps, pg, ctx.team_net, **kw)
    pf = player_team_features(
        list(range(2011, 2027)),
        ctx.games,
        pg[["season", "game_id", "team_id", "player_id", "min"]],
        w2.rapm_cfg(),
        prior_provider=prov,
    )
    WORK.mkdir(parents=True, exist_ok=True)
    pf.to_parquet(WORK / f"pf_{name}.parquet", index=False)
    models = {
        s: {k: v for k, v in m.__dict__.items()} for s, m in prov.models.items() if m is not None
    }
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
    m = arms.matchup_features(df)["margin_an"]
    X["L_x_margin_an"] = df["L"] * m
    return assert_pure_frame(X, "venue_block")


def mismatch_block(df: pd.DataFrame) -> pd.DataFrame:
    """B13: piecewise-linear extension of the analytic margin beyond +-15 points."""
    m = arms.matchup_features(df)["margin_an"]
    X = pd.DataFrame(index=df.index)
    X["margin_ext_pos"] = np.maximum(m - 15.0, 0.0)
    X["margin_ext_neg"] = np.minimum(m + 15.0, 0.0)
    return assert_pure_frame(X, "mismatch_block")


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
    "B11": ("b9", "b11", ()),
    "B12": ("b9", "b12", ()),
    "B13": ("b13", "w2", ("mismatch",)),
    "B13_garbage_only": ("b13", "w2", ()),
    "B13_mismatch_only": ("b9", "w2", ("mismatch",)),
    "B14": ("b14", "w2", ()),
    "B14v": ("b9", "w2", ("venue",)),
    "B15": ("b15", "b15", ("preseason", "mismatch", "venue")),
}


def arms_stage(only: list[str] | None = None) -> None:
    ctx = Ctx()
    pre = ctx.pre()
    preds: dict[str, pd.DataFrame] = {}
    frames: dict[str, pd.DataFrame] = {}
    for name, (eng, pfn, extra) in ARM_SPECS.items():
        if only and name not in only and name != "B9":
            continue
        sp = W2 / "states_shot.parquet" if eng == "b9" else WORK / f"states_{eng}.parquet"
        pp = W2 / "player_features.parquet" if pfn == "w2" else WORK / f"pf_{pfn}.parquet"
        if not sp.exists() or not pp.exists():
            print(f"skip {name}: missing {sp.name if not sp.exists() else pp.name}", flush=True)
            continue
        df = frame(ctx, pd.read_parquet(sp), pd.read_parquet(pp))
        ex = []
        if "preseason" in extra:
            ex.append(preseason_block(df, pre))
        if "mismatch" in extra:
            ex.append(mismatch_block(df))
        if "venue" in extra:
            ex.append(venue_block(df, ctx.games))
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


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "arms"
    if stage == "engine":
        engine_stage(sys.argv[2])
    elif stage == "pf":
        pf_stage(sys.argv[2])
    else:
        arms_stage(sys.argv[2:] or None)
