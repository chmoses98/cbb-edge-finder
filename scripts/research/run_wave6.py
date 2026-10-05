"""Wave-6 PURE_BASKETBALL research harness (preregistered in research/hypotheses/WAVE6.md).

Reference: B25 = pure-0.5.0. Blocked folds F1–F5 (2015–2024), day-clustered bootstrap,
gates fixed in WAVE6.md. 2025–26 evidence only (veto for B29).

    python scripts/research/run_wave6.py continuity     # B27 / B28 / ORACLE features
    python scripts/research/run_wave6.py dev            # B26 development offsets (DEV)
    python scripts/research/run_wave6.py devchain       # B26 player chain (slow)
    python scripts/research/run_wave6.py arms [ARM ...]
    python scripts/research/run_wave6.py rotation       # expected-rotation model
    python scripts/research/run_wave6.py oracle         # ORACLE upper bound + P-ROSTER-1 (b) fit

No market data is read here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.research import blocks

sys.path.insert(0, str(Path(__file__).parent))
import run_wave2 as w2  # noqa: E402
import run_wave3 as w3  # noqa: E402
import run_wave4 as w4  # noqa: E402
import run_wave5 as w5  # noqa: E402

OUT = Path("research/wave6")
WORK = data_dir() / "research" / "wave6"
FIRST5 = 5


def decay(gs: pd.Series | np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.asarray(gs, float) / 3.0)


# ------------------------------------------------------------------ continuity -------
def team_game_order(ctx: w3.Ctx) -> pd.DataFrame:
    """One row per (team, game) of D-I games with the pregame cutoff (first tip of the
    day, ET) and the team's game index in the season."""
    g = ctx.games[ctx.games["home_is_d1"] & ctx.games["away_is_d1"]]
    g = g[~g["status"].isin(["STATUS_CANCELED", "STATUS_POSTPONED"])]
    first = g.groupby("game_date_et")["start_time_utc"].transform("min")
    rows = []
    for col in ("home_team_id", "away_team_id"):
        rows.append(
            pd.DataFrame(
                {
                    "game_id": g["game_id"],
                    "season": g["season"],
                    "team_id": g[col],
                    "start_time_utc": g["start_time_utc"],
                    "cutoff": first,
                }
            )
        )
    t = pd.concat(rows, ignore_index=True).sort_values(["team_id", "start_time_utc"])
    t["game_no"] = t.groupby(["team_id", "season"]).cumcount()
    return t.reset_index(drop=True)


def continuity_stage() -> None:
    ctx = w3.Ctx()
    ps = ctx.ps
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min", "available_at"],
    )
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0) & (pg["season"] >= 2010)]
    tgo = team_game_order(ctx)
    pre = ctx.pre()[["team_id", "season", "ret_min"]]
    fin = ctx.finals9.assign(prev_net=lambda f: f["o"] - f["d"])[["team_id", "season", "prev_net"]]
    fin = fin.assign(season=fin["season"] + 1)
    # D-I history before each season (observed participation)
    first_season = pg.groupby("player_id")["season"].min()
    last_team = (
        pg.sort_values(["season", "available_at"])
        .groupby(["player_id", "season"])
        .tail(1)
        .set_index(["player_id", "season"])["team_id"]
    )
    seasons_by = pg.groupby("player_id")["season"].agg(lambda v: sorted(set(v))).to_dict()
    out = []
    for (team, s), tg in tgo[tgo["season"].between(2012, 2026)].groupby(["team_id", "season"]):
        prev = ps[(ps["season"] == s - 1) & (ps["team_id"] == team)].set_index("player_id")
        prev_sh = prev["min_share"].clip(lower=0)
        tot_prev = float(prev_sh.sum())
        cur = pg[(pg["season"] == s) & (pg["team_id"] == team)]
        cur = cur.merge(
            tgo[["game_id", "team_id", "game_no"]], on=["game_id", "team_id"], how="left"
        )
        # player classes from history BEFORE the season
        pid = cur["player_id"].unique()
        newb = {p: first_season.get(p, s) >= s for p in pid}
        tr = {}
        for p in pid:
            prior = [x for x in seasons_by.get(p, []) if x < s]
            tr[p] = bool(prior) and last_team.get((p, prior[-1]), team) != team
        cur = cur.assign(new=cur["player_id"].map(newb), tr=cur["player_id"].map(tr))
        # ORACLE membership: appears in the team's first five games
        orc = set(cur.loc[cur["game_no"] < FIRST5, "player_id"])
        o_cont = (
            float(prev_sh[prev_sh.index.isin(orc)].sum() / tot_prev) if tot_prev > 0 else np.nan
        )
        tr_prev = ps[(ps["season"] == s - 1) & ps["player_id"].isin([p for p in orc if tr.get(p)])]
        o_tr = float(tr_prev["min_share"].sum())
        o_new = int(sum(1 for p in orc if newb.get(p)))
        av = cur[["available_at", "player_id", "min", "new", "tr"]].sort_values("available_at")
        avt = pd.to_datetime(av["available_at"], utc=True).astype("int64").to_numpy()
        for r in tg.itertuples(index=False):
            k = int(np.searchsorted(avt, pd.Timestamp(r.cutoff).value, side="left"))
            seen = av.iloc[:k]
            gs = int(r.game_no)
            if gs == 0 or seen.empty:
                rev_cont = np.nan
                rev_new = rev_tr = 0.0
            else:
                appeared = set(seen["player_id"])
                rev_cont = (
                    float(prev_sh[prev_sh.index.isin(appeared)].sum() / tot_prev)
                    if tot_prev > 0
                    else np.nan
                )
                m = seen["min"].sum()
                rev_new = float(seen.loc[seen["new"], "min"].sum() / m) if m > 0 else 0.0
                rev_tr = float(seen.loc[seen["tr"], "min"].sum() / m) if m > 0 else 0.0
            out.append(
                {
                    "game_id": r.game_id, "team_id": team, "season": s, "gs": gs,
                    "rev_cont": rev_cont, "rev_new": rev_new, "rev_tr": rev_tr,
                    "oracle_cont": o_cont, "oracle_tr_prev_share": o_tr, "oracle_first_d1": o_new,
                }
            )  # fmt: skip
    c = (
        pd.DataFrame(out)
        .merge(pre, on=["team_id", "season"], how="left")
        .merge(fin, on=["team_id", "season"], how="left")
    )
    WORK.mkdir(parents=True, exist_ok=True)
    c.to_parquet(WORK / "continuity.parquet", index=False)
    print(c.describe().T.round(3).to_string(), flush=True)


# ------------------------------------------------------------------ arms -------------
COMPONENTS = ("B26", "B27", "B28")


def _side_cont(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    c = pd.read_parquet(WORK / "continuity.parquet")
    out = {}
    for side, col in (("h", "home_team_id"), ("a", "away_team_id")):
        x = df[["game_id", col]].merge(
            c.rename(columns={"team_id": col}), on=["game_id", col], how="left"
        )
        x.index = df.index
        out[side] = x
    return out


def b27_block(df: pd.DataFrame) -> pd.DataFrame:
    """B27: continuity-dependent carryover from PRESEASON-known continuity (P(return))."""
    sc = _side_cont(df)
    X = pd.DataFrame(index=df.index)
    for side in ("h", "a"):
        x = sc[side]
        d = decay(df[f"{side}_games_seen"])
        rm = x["ret_min"].fillna(DEV_RET_MIN)
        X[f"carry_{side}"] = x["prev_net"].fillna(0.0) * (1 - rm) * d
        X[f"cont_{side}"] = rm * d
    return X


def b28_block(df: pd.DataFrame) -> pd.DataFrame:
    """B28: continuity REVEALED by games already played (gs >= 1; expectation at gs 0)."""
    sc = _side_cont(df)
    X = pd.DataFrame(index=df.index)
    for side in ("h", "a"):
        x = sc[side]
        gs = df[f"{side}_games_seen"]
        d = decay(gs)
        rm = x["ret_min"].fillna(DEV_RET_MIN)
        rc = np.where((gs >= 1) & x["rev_cont"].notna(), x["rev_cont"], rm)
        X[f"rcont_{side}"] = rc * d
        X[f"rnew_{side}"] = np.where(gs >= 1, x["rev_new"].fillna(0.0), 0.0) * d
        X[f"rtr_{side}"] = np.where(gs >= 1, x["rev_tr"].fillna(0.0), 0.0) * d
        X[f"rcarry_{side}"] = x["prev_net"].fillna(0.0) * (1 - rc) * d
    return X


DEV_RET_MIN = 0.513  # mean expected returning-minute share (fill for missing tables)


def evaluate(df: pd.DataFrame, p: pd.DataFrame, base: pd.DataFrame) -> dict:
    v = w5.evaluate(df, p, base)
    m = p["margin"].notna() & base["margin"].notna() & df["margin"].notna()
    val = df["season"].isin(w2.VALID)
    gs = np.minimum(df["h_games_seen"], df["a_games_seen"])
    for k, mask in (("first_game", gs == 0), ("games_2_5", gs.between(1, 4)),
                    ("games_6_10", gs.between(5, 9))):  # fmt: skip
        mm = (m & val & mask).to_numpy()
        ea = (p["margin"] - df["margin"]).to_numpy()[mm]
        eb = (base["margin"] - df["margin"]).to_numpy()[mm]
        v[f"d_{k}"] = w4._rmse(ea) - w4._rmse(eb)
    return v


def gate(name: str, v: dict) -> str:
    bl = list(v["blocks"].values())
    if name == "B29":
        ok = (
            v["d_rmse"] <= -0.008
            and sum(x < 0 for x in bl) >= 4
            and sum(x < 0 for x in v["seasons"].values()) >= 8
            and v["boot_p_better"] >= 0.95
            and v["d_first_game"] <= -0.03
            and v["d_games_2_5"] <= 0
            and v["d_nov_dec"] < 0
            and v["d_jan_mar"] <= 0.005
            and v["d_log_loss"] <= 0
            and v["d_total_rmse"] <= 0.010
            and v["hist_d_rmse"] <= 0.010
        )
        return "FREEZE" if ok else "REJECT"
    ok = (
        v["d_rmse"] < 0
        and sum(x < 0 for x in bl) >= 4
        and max(bl) <= 0.005
        and v["boot_p_better"] >= 0.90
        and v["d_log_loss"] <= 0
        and v["d_nov_dec"] <= 0.005
        and v["d_jan_mar"] <= 0.005
    )
    return "USEFUL" if ok else "NOT USEFUL"


def b25_X(ctx: w3.Ctx, df: pd.DataFrame) -> pd.DataFrame:
    comp = json.loads((w5.OUT / "b25_components.json").read_text())["components"]
    return w5.b25_X(ctx, df, comp)


def arms_stage(only: list[str] | None = None) -> None:
    ctx = w3.Ctx()
    df = w5.b20_frame(ctx)
    X25 = b25_X(ctx, df)
    preds = {"B25": w4.make_pred(df, X25)}
    ref = pd.read_parquet(w5.WORK / "pure_predictions.parquet").set_index("game_id")
    chk = float(np.nanmax(np.abs(preds["B25"]["margin"].to_numpy()
                                 - ref.loc[df["game_id"], "B25_margin"].to_numpy())))  # fmt: skip
    print({"B25_recomputed_vs_wave5_max_abs": chk}, flush=True)
    want = (lambda a: True) if only is None else (lambda a: a in only)
    extra = {"B27": lambda: b27_block(df), "B28": lambda: b28_block(df)}
    if (WORK / "pf_b26.parquet").exists():
        extra["B26"] = None  # player chain variant, handled below
    for a in COMPONENTS:
        if not want(a) or a not in extra:
            continue
        if a == "B26":
            preds[a] = b26_pred(ctx, df)
        else:
            preds[a] = w4.make_pred(df, pd.concat([X25, extra[a]()], axis=1))
    comp_file = OUT / "b29_components.json"
    if want("B29") and comp_file.exists():
        comp = json.loads(comp_file.read_text())["components"]
        if comp:
            preds["B29"] = b29_pred(ctx, df, comp)
    report: dict[str, object] = {"reference": "B25 (pure-0.5.0)", "arms": {}}
    for name, p in preds.items():
        if name == "B25":
            continue
        v = evaluate(df, p, preds["B25"])
        v["verdict"] = gate(name, v)
        report["arms"][name] = v
        print(name, {k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()
                     if k not in ("seasons", "subgroups")}, flush=True)  # fmt: skip
    report["useful_components"] = [a for a, v in report["arms"].items() if v["verdict"] == "USEFUL"]
    allp = df[["game_id", "season", "start_time_utc", "h_games_seen", "a_games_seen",
               "home_team_id", "away_team_id"]].copy()  # fmt: skip
    for name, p in preds.items():
        for c in ("margin", "total", "home_wp"):
            allp[f"{name}_{c}"] = p[c].to_numpy()
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "" if only is None else "_" + "_".join(only)
    allp.to_parquet(WORK / f"pure_predictions{tag}.parquet", index=False)
    (OUT / f"metrics{tag}.json").write_text(json.dumps(report, indent=1, default=float))


def b26_pred(ctx: w3.Ctx, df: pd.DataFrame) -> pd.DataFrame:
    d2 = w3.frame(ctx, pd.read_parquet(w4.WORK / "states_b16b.parquet"),
                  pd.read_parquet(WORK / "pf_b26.parquet"))  # fmt: skip
    d2["game_date_et"] = d2["game_id"].map(ctx.games.set_index("game_id")["game_date_et"])
    p = w4.make_pred(d2, b25_X(ctx, d2))
    keyed = df.set_index("game_id")
    return p.set_index(d2["game_id"].to_numpy()).reindex(keyed.index).reset_index(drop=True)


def b29_pred(ctx: w3.Ctx, df: pd.DataFrame, comp: list[str]) -> pd.DataFrame:
    base = df
    if "B26" in comp:
        base = w3.frame(ctx, pd.read_parquet(w4.WORK / "states_b16b.parquet"),
                        pd.read_parquet(WORK / "pf_b26.parquet"))  # fmt: skip
        base["game_date_et"] = base["game_id"].map(ctx.games.set_index("game_id")["game_date_et"])
    parts = [b25_X(ctx, base)]
    if "B27" in comp:
        parts.append(b27_block(base))
    if "B28" in comp:
        parts.append(b28_block(base))
    p = w4.make_pred(base, blocks.combine(*parts))
    keyed = df.set_index("game_id")
    return p.set_index(base["game_id"].to_numpy()).reindex(keyed.index).reset_index(drop=True)


# ------------------------------------------------------------------ B26 development --
EXP_CELLS = (1, 2, 3, 4)  # D-I seasons completed at the end of the earlier season (4 = 4+)


def _cell(exp: np.ndarray, msh: np.ndarray) -> list[tuple[int, int]]:
    e = np.clip(np.nan_to_num(exp, nan=1).astype(int), 1, 4)
    m = (np.nan_to_num(msh) >= 0.3).astype(int)
    return list(zip(e.tolist(), m.tolist(), strict=True))


def dev_stage() -> None:
    """DEV-only development offsets: mean(next weak-RAPM - 0.95 x current weak-RAPM)
    by (experience x minutes) cell, weighted by next-season possessions; cells with
    n < 200 pool to their experience row; shrunk x0.5 (survivor selection)."""
    from cbb_edge.players import box_prior

    ctx = w3.Ctx()
    pairs = box_prior.pair_table(ctx.ps, ctx.team_net, 2014)
    pairs = pairs[pairs["next_season"] <= 2014]
    exp = pairs["seasons_prior"].fillna(0).to_numpy() + 1
    cells = _cell(exp, pairs["min_share"].to_numpy())
    pairs = pairs.assign(cell=cells, r_o=pairs["n_o"] - 0.95 * pairs["c_o"],
                         r_d=pairs["n_d"] - 0.95 * pairs["c_d"])  # fmt: skip
    w = pairs["n_poss"].clip(upper=3000)
    off: dict[str, dict[str, float]] = {}
    rows = {}
    for e in EXP_CELLS:
        re = pairs[[c[0] == e for c in pairs["cell"]]]
        for m in (0, 1):
            x = pairs[[c == (e, m) for c in pairs["cell"]]]
            src = x if len(x) >= 200 else re
            ww = w[src.index]
            o = float(np.average(src["r_o"], weights=ww)) if len(src) else 0.0
            d = float(np.average(src["r_d"], weights=ww)) if len(src) else 0.0
            off[f"{e}|{m}"] = {"o": 0.5 * o, "d": 0.5 * d}
            rows[f"{e}|{m}"] = {"n": len(x), "pooled": len(x) < 200, "raw_o": o, "raw_d": d}
    rep = {"offsets": off, "cells": rows, "n_pairs": len(pairs), "fit": "DEV pairs, next <= 2014"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b26_development.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1), flush=True)


def devchain_stage() -> None:
    """B19h player chain with B26 development offsets on season-start priors."""
    from cbb_edge.players import availability_model as am
    from cbb_edge.players import box_prior
    from cbb_edge.players.rapm import player_team_features

    off = json.loads((OUT / "b26_development.json").read_text())["offsets"]
    ctx = w3.Ctx()
    ps = ctx.ps
    last = ps.sort_values("season").groupby(["player_id", "season"]).tail(1)
    info = {
        (p_, int(s_)): (float(sp) + 1, float(ms))
        for p_, s_, sp, ms in zip(
            last["player_id"], last["season"], last["seasons_prior"].fillna(0),
            last["min_share"].fillna(0), strict=True,
        )
    }  # fmt: skip

    class DevProvider(box_prior.PlayerPriorProvider):
        def start(self, season, players, prev, cfg):  # type: ignore[override]
            po, pd_ = super().start(season, players, prev, cfg)
            oo = np.zeros(len(players))
            dd = np.zeros(len(players))
            for i, q in enumerate(players):
                v = info.get((q, season - 1))
                if v is None:
                    continue
                ((e, m),) = _cell(np.array([v[0]]), np.array([v[1]]))
                oo[i] = off[f"{e}|{m}"]["o"]
                dd[i] = off[f"{e}|{m}"]["d"]
            po = po + oo
            pd_ = pd_ + dd
            if getattr(self, "_base", None) is not None and self._pm is not None:
                self._base = (self._base[0] + oo, self._base[1] + dd)
            return po, pd_

    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    t = pd.read_parquet(w4.WORK / "absence_table.parquet")
    rep = json.loads((w4.OUT / "absence_study.json").read_text())["replacement"]
    pos = pg.sort_values("season").drop_duplicates("player_id", keep="last")
    positions = {p_: am._pos(x) for p_, x in zip(pos["player_id"], pos["position"], strict=True)}
    adj = am.AvailabilityAdjuster(
        w4.persistence_models(t), positions, rep["gamma"], rep["beta"], mode="persistence"
    )
    prov = DevProvider(ctx.ps, pg, ctx.team_net, **w3.PF_VARIANTS["b12"]["provider"])
    pf = player_team_features(
        list(range(2011, 2027)),
        ctx.games,
        pg[["season", "game_id", "team_id", "player_id", "min"]],
        w2.rapm_cfg(),
        prior_provider=prov,
        share_adjust=adj,
        verbose=False,
    )
    WORK.mkdir(parents=True, exist_ok=True)
    pf.to_parquet(WORK / "pf_b26.parquet", index=False)
    print("pf_b26 written", len(pf), flush=True)


# ------------------------------------------------------------------ rotation ---------
ROT_FEATURES = [
    "prev_min_share", "prev_start_rate", "prev_usage", "prev_net", "d1_seasons",
    "pos_g", "pos_c", "transfer", "origin_net", "first_d1", "depth_same_pos",
    "team_prev_net",
]  # fmt: skip


def rotation_rows(ps: pd.DataFrame, pg: pd.DataFrame, roster: pd.DataFrame,
                  finals: pd.DataFrame) -> pd.DataFrame:  # fmt: skip
    """Feature rows for (season, team, player) roster entries, from seasons < season."""
    from cbb_edge.players.availability_model import _pos

    last = ps.sort_values(["season", "minutes"]).groupby(["player_id", "season"]).tail(1)
    prev = last[["player_id", "season", "team_id", "min_share", "start_rate", "usage_share",
                 "rapm_net", "seasons_prior", "position"]].rename(
        columns={"season": "h_season", "team_id": "h_team"})  # fmt: skip
    x = roster.merge(prev, on="player_id", how="left")
    x = x[x["h_season"].isna() | (x["h_season"] < x["season"])]
    x = x.sort_values("h_season", na_position="first").groupby(
        ["season", "team_id", "player_id"]).tail(1)  # fmt: skip
    x = x.rename(columns={"h_season": "prev_season", "h_team": "prev_team"})
    hist = x["prev_season"].notna()
    out = x[["season", "team_id", "player_id"]].copy()
    out["first_d1"] = (~hist).astype(float)
    out["prev_min_share"] = np.where(hist, x["min_share"].fillna(0), 0.0)
    out["prev_start_rate"] = np.where(hist, x["start_rate"].fillna(0), 0.0)
    out["prev_usage"] = np.where(hist, x["usage_share"].fillna(0), 0.0)
    out["prev_net"] = np.where(hist, x["rapm_net"].fillna(-2.0), -2.0)
    out["d1_seasons"] = np.where(hist, x["seasons_prior"].fillna(0) + 1, 0.0)
    out["transfer"] = (hist & (x["prev_team"] != x["team_id"])).astype(float)
    pos = x["position"].map(_pos) if "position" in x else "F"
    if pos is not None and hasattr(pos, "where"):
        pos = pos.where(hist, "F")
    out["pos_g"] = (pos == "G").astype(float)
    out["pos_c"] = (pos == "C").astype(float)
    fn = finals.assign(net=finals["o"] - finals["d"]).set_index(["team_id", "season"])["net"]
    out["origin_net"] = np.where(
        out["transfer"] > 0,
        fn.reindex(pd.MultiIndex.from_arrays([x["prev_team"], x["prev_season"]])).to_numpy(),
        0.0,
    )
    out["origin_net"] = out["origin_net"].fillna(0.0)
    out["team_prev_net"] = (
        fn.reindex(pd.MultiIndex.from_arrays([out["team_id"], out["season"] - 1]))
        .fillna(0.0)
        .to_numpy()
    )
    out["pos_key"] = np.select([out["pos_g"] > 0, out["pos_c"] > 0], ["G", "C"], "F")
    tot = out.groupby(["season", "team_id", "pos_key"])["prev_min_share"].transform("sum")
    out["depth_same_pos"] = tot - out["prev_min_share"]
    return out.drop(columns=["pos_key"])


def first5_targets(pg: pd.DataFrame, tgo: pd.DataFrame) -> pd.DataFrame:
    x = pg.merge(
        tgo[["game_id", "team_id", "game_no", "season"]], on=["game_id", "team_id", "season"]
    )
    x = x[x["game_no"] < FIRST5]
    tm = x.groupby(["season", "team_id"])["min"].transform("sum")
    x = x.assign(share=5 * x["min"] / tm)
    t = x.groupby(["season", "team_id", "player_id"]).agg(
        target=("share", "sum"),
        started_g1=("starter", lambda v: bool(v.iloc[0]) if len(v) else False),
    )
    g1 = x[x["game_no"] == 0].groupby(["season", "team_id", "player_id"])["starter"].first()
    t["started_g1"] = g1.reindex(t.index).fillna(False).astype(bool)
    return t.reset_index()


def rotation_stage() -> None:
    from sklearn.ensemble import HistGradientBoostingRegressor

    ctx = w3.Ctx()
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min", "starter", "available_at"],
    )
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0) & pg["season"].between(2010, 2026)]
    tgo = team_game_order(ctx)
    tg = first5_targets(pg, tgo)
    roster = tg[["season", "team_id", "player_id"]]
    feats = rotation_rows(ctx.ps, pg, roster, ctx.finals9)
    d = feats.merge(tg, on=["season", "team_id", "player_id"], how="inner")
    preds = []
    for s in range(2013, 2027):
        tr = d[d["season"].between(2011, s - 1)]
        te = d[d["season"] == s].copy()
        m = HistGradientBoostingRegressor(max_depth=3, max_iter=200, learning_rate=0.05,
                                          random_state=0)  # fmt: skip
        m.fit(tr[ROT_FEATURES], tr["target"])
        te["pred_raw"] = np.clip(m.predict(te[ROT_FEATURES]), 0.0, 1.0)
        tot = te.groupby("team_id")["pred_raw"].transform("sum")
        te["pred"] = (5 * te["pred_raw"] / tot.replace(0, np.nan)).clip(upper=1.0)
        # naive baseline: previous minute share (first-D-I 0.15), normalised to 5
        nv = np.where(te["first_d1"] > 0, 0.15, te["prev_min_share"])
        te["naive"] = 5 * nv / pd.Series(nv, index=te.index).groupby(te["team_id"]).transform("sum")
        preds.append(te)
    P = pd.concat(preds)
    WORK.mkdir(parents=True, exist_ok=True)
    P.to_parquet(WORK / "rotation_oos.parquet", index=False)
    rep = {"note": "conditional on roster membership (players in the first five games); "
                   "PROSPECTIVE input = roster truth", "validation": {}, "2025_26": {}}  # fmt: skip
    for lab, ss in (("validation", range(2015, 2025)), ("2025_26", [2026])):
        v = P[P["season"].isin(ss)]
        rep[lab] = {k: rotation_metrics(v, k) for k in ("pred", "naive")}
    (OUT / "rotation.json").write_text(json.dumps(rep, indent=1, default=float))
    print(json.dumps(rep, indent=1, default=float), flush=True)


def rotation_metrics(v: pd.DataFrame, col: str) -> dict:
    mae = float((v[col] - v["target"]).abs().mean() * 40)
    top5, top8, start, prec, rec = [], [], [], [], []
    for _, x in v.groupby(["season", "team_id"]):
        a5 = set(x.nlargest(5, "target")["player_id"])
        p5 = set(x.nlargest(5, col)["player_id"])
        a8 = set(x.nlargest(8, "target")["player_id"])
        p8 = set(x.nlargest(8, col)["player_id"])
        top5.append(len(a5 & p5) / 5)
        top8.append(len(a8 & p8) / 8)
        st = set(x.loc[x["started_g1"], "player_id"])
        if len(st) == 5:
            start.append(len(st & p5) / 5)
        ar = set(x.loc[x["target"] >= 0.25, "player_id"])
        pr = set(x.loc[x[col] >= 0.25, "player_id"])
        if pr:
            prec.append(len(ar & pr) / len(pr))
        if ar:
            rec.append(len(ar & pr) / len(ar))
    return {"minutes_mae": mae, "top5_identification": float(np.mean(top5)),
            "top8_identification": float(np.mean(top8)),
            "starter_accuracy_game1": float(np.mean(start)) if start else None,
            "rotation_precision": float(np.mean(prec)), "rotation_recall": float(np.mean(rec)),
            "n_team_seasons": int(v.groupby(["season", "team_id"]).ngroups)}  # fmt: skip


# ------------------------------------------------------------------ ORACLE / P-ROSTER-1
ROSTER_B_FEATURES = ("dcont", "tr_prev", "first_d1")


def roster_b_features(df: pd.DataFrame, cont_col: str, tr_col: str, new_col: str,
                      sc: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:  # fmt: skip
    """P-ROSTER-1 (b) inputs, home minus away, each x d(gs) (WAVE6.md):
    (truth - expected) returning share, transfers' previous minute share, first-D-I count."""
    sc = sc or _side_cont(df)
    X = pd.DataFrame(index=df.index)
    parts = {}
    for side in ("h", "a"):
        x = sc[side]
        d = decay(df[f"{side}_games_seen"])
        rm = x["ret_min"].fillna(DEV_RET_MIN)
        parts[side] = {
            "dcont": (x[cont_col].fillna(rm) - rm) * d,
            "tr_prev": x[tr_col].fillna(0.0) * d,
            "first_d1": x[new_col].fillna(0.0) * d,
        }
    for f in ROSTER_B_FEATURES:
        X[f] = parts["h"][f] - parts["a"][f]
    return X


def oracle_stage() -> None:
    """ORACLE upper bound of P-ROSTER-1 (b): ridge on B25 residuals (games seen <= 10),
    expanding window over 2015..s-1, ORACLE membership. Then the final fit on 2015-2026
    for prospective use (models/overlays/p-roster-1.json)."""
    from sklearn.linear_model import Ridge

    ctx = w3.Ctx()
    df = w5.b20_frame(ctx)
    pp = pd.read_parquet(w5.WORK / "pure_predictions.parquet").set_index("game_id")
    b25 = pp.loc[df["game_id"], "B25_margin"].to_numpy()
    X = roster_b_features(df, "oracle_cont", "oracle_tr_prev_share", "oracle_first_d1")
    resid = df["margin"].to_numpy() - b25
    gs = np.minimum(df["h_games_seen"], df["a_games_seen"]).to_numpy()
    early = gs <= 10
    corr = np.zeros(len(df))
    coefs = {}
    for s in range(2016, 2027):
        tr = (df["season"].between(2015, s - 1) & early & np.isfinite(resid)).to_numpy()
        te = ((df["season"] == s) & early).to_numpy()
        m = Ridge(alpha=10.0).fit(X[tr], resid[tr])
        corr[te] = m.predict(X[te])
        coefs[s] = dict(zip(ROSTER_B_FEATURES, map(float, m.coef_), strict=True))
    p_or = pd.DataFrame({"margin": b25 + corr, "total": pp.loc[df["game_id"], "B25_total"].to_numpy()},
                        index=df.index)  # fmt: skip
    p_or["home_wp"] = w2.logistic_wp(df, p_or["margin"])
    base = pd.DataFrame({"margin": b25, "total": p_or["total"],
                         "home_wp": pp.loc[df["game_id"], "B25_home_wp"].to_numpy()}, index=df.index)  # fmt: skip
    mask = df["season"] >= 2016
    v = evaluate(df[mask], p_or[mask], base[mask])
    full = (df["season"].between(2015, 2026) & early & np.isfinite(resid)).to_numpy()
    mf = Ridge(alpha=10.0).fit(X[full], resid[full])
    spec = {
        "name": "P-ROSTER-1",
        "role": "PROSPECTIVE_ONLY overlay on pure-0.5.0 (never a frozen version)",
        "base_version": "pure-0.5.0",
        "component_b": {
            "features": list(ROSTER_B_FEATURES),
            "coef": list(map(float, mf.coef_)),
            "intercept": float(mf.intercept_),
            "applies_games_seen_max": 10,
            "decay": "1 / (1 + games_seen / 3)",
            "fit": "ridge alpha 10 on pure-0.5.0 OOS residuals 2015-2026, ORACLE membership "
            "(players appearing in a team's first five games)",
        },
        "oracle_eval_expanding_window": {k: v[k] for k in v if k not in ("seasons",)},
        "coef_by_season": coefs,
        "market_inputs": "NONE",
    }
    Path("models/overlays").mkdir(parents=True, exist_ok=True)
    path = Path("models/overlays/p-roster-1.json")
    if path.exists():
        raise SystemExit(f"{path} exists: overlay specs are immutable once written")
    import hashlib

    spec = json.loads(json.dumps(spec, sort_keys=True, default=float))
    spec["sha256"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps(spec, indent=1, sort_keys=True))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "oracle_b.json").write_text(json.dumps(v, indent=1, default=float))
    print({k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()
           if k not in ("seasons", "subgroups")}, flush=True)  # fmt: skip
    print("final coef", dict(zip(ROSTER_B_FEATURES, mf.coef_, strict=True)), flush=True)


def oracle_a_chain_stage() -> None:
    """ORACLE (a): B19h player chain where, before each team's first game, the player
    block uses the OOS expected rotation over the ORACLE roster (players appearing in the
    first five games) instead of last season's full roster. Diagnostic upper bound."""
    from cbb_edge.players import availability_model as am
    from cbb_edge.players import box_prior
    from cbb_edge.players.rapm import player_team_features

    ctx = w3.Ctx()
    rot = pd.read_parquet(WORK / "rotation_oos.parquet")
    shares = {
        (t, int(s_)): (x["player_id"].to_numpy(), x["pred"].fillna(0).to_numpy())
        for (s_, t), x in rot.groupby(["season", "team_id"])
    }
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    t = pd.read_parquet(w4.WORK / "absence_table.parquet")
    rep = json.loads((w4.OUT / "absence_study.json").read_text())["replacement"]
    pos = pg.sort_values("season").drop_duplicates("player_id", keep="last")
    positions = {p_: am._pos(x) for p_, x in zip(pos["player_id"], pos["position"], strict=True)}
    adj = am.AvailabilityAdjuster(
        w4.persistence_models(t), positions, rep["gamma"], rep["beta"], mode="persistence"
    )
    prov = box_prior.PlayerPriorProvider(
        ctx.ps, pg, ctx.team_net, **w3.PF_VARIANTS["b12"]["provider"]
    )
    pf = player_team_features(
        list(range(2011, 2027)), ctx.games,
        pg[["season", "game_id", "team_id", "player_id", "min"]], w2.rapm_cfg(),
        prior_provider=prov, share_adjust=adj, verbose=False, preseason_shares=shares,
    )  # fmt: skip
    pf.to_parquet(WORK / "pf_oracle_a.parquet", index=False)
    print("pf_oracle_a written", len(pf), flush=True)


def oracle_a_stage() -> None:
    ctx = w3.Ctx()
    df = w5.b20_frame(ctx)
    base = w4.make_pred(df, b25_X(ctx, df))
    d2 = w3.frame(ctx, pd.read_parquet(w4.WORK / "states_b16b.parquet"),
                  pd.read_parquet(WORK / "pf_oracle_a.parquet"))  # fmt: skip
    d2["game_date_et"] = d2["game_id"].map(ctx.games.set_index("game_id")["game_date_et"])
    p = w4.make_pred(d2, b25_X(ctx, d2))
    p = p.set_index(d2["game_id"].to_numpy()).reindex(df["game_id"]).reset_index(drop=True)
    v = evaluate(df, p, base)
    (OUT / "oracle_a.json").write_text(json.dumps(v, indent=1, default=float))
    print({k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()
           if k not in ("seasons", "subgroups")}, flush=True)  # fmt: skip


if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "continuity":
        continuity_stage()
    elif stage == "dev":
        dev_stage()
    elif stage == "devchain":
        devchain_stage()
    elif stage == "rotation":
        rotation_stage()
    elif stage == "oracle_a_chain":
        oracle_a_chain_stage()
    elif stage == "oracle_a":
        oracle_a_stage()
    elif stage == "oracle":
        oracle_stage()
    elif stage == "arms":
        arms_stage(sys.argv[2:] or None)
    else:
        raise SystemExit(stage)
