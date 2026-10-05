"""Wave-5 PURE_BASKETBALL research harness (preregistered in research/hypotheses/WAVE5.md).

Reference: B20 = pure-0.4.0 (states_b16b, pf_b19h, shooting block, mismatch block).
Evaluation: Wave-4 blocked rolling-origin folds, day-clustered bootstrap, gates fixed in
WAVE5.md. 2025-26 is evidence only (veto for B25).

Stages (cached under data/research/wave5):

    python scripts/research/run_wave5.py prior       # DEV (<= 2014) shrinkage constants
    python scripts/research/run_wave5.py features    # player-derived team profiles
    python scripts/research/run_wave5.py arms [ARM ...]
    python scripts/research/run_wave5.py freeze      # only if B25 passes

No market data is read here.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.players import possession as pos
from cbb_edge.players import preseason
from cbb_edge.research import blocks

sys.path.insert(0, str(Path(__file__).parent))
import run_wave2 as w2  # noqa: E402
import run_wave3 as w3  # noqa: E402
import run_wave4 as w4  # noqa: E402

OUT = Path("research/wave5")
WORK = data_dir() / "research" / "wave5"
DEV_FIT = [2011, 2012, 2013, 2014]
DEV_MEANS = [2010, 2011, 2012, 2013, 2014]
K_DEF_GRID = (250.0, 500.0, 1000.0)
FIRST = 2007


def load_rows() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sil = data_dir() / "silver"
    pg = pd.read_parquet(sil / "player_games.parquet")
    pg = pg[pg["season"] >= FIRST - 1]
    tg = pd.read_parquet(sil / "team_games.parquet")
    shots = pd.read_parquet(sil / "pbp_player_shots.parquet")
    x = pos.player_rows(pg, tg, shots)
    return x, tg, shots


def prior_stage() -> pos.PlayerPrior:
    x, _, _ = load_rows()
    cb = pos.career(x)
    pr = pos.fit_prior(cb, DEV_FIT, DEV_MEANS)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "player_prior.json").write_text(json.dumps(asdict(pr), indent=1))
    print(json.dumps(pr.kappa, indent=1), flush=True)
    return pr


def load_prior() -> pos.PlayerPrior:
    d = json.loads((OUT / "player_prior.json").read_text())
    return pos.PlayerPrior(**d)


def p_return(ps: pd.DataFrame, seasons: list[int]) -> dict[tuple[str, str, int], float]:
    out: dict[tuple[str, str, int], float] = {}
    for s in seasons:
        prev = ps[ps["season"] == s - 1]
        if prev.empty:
            continue
        p = preseason.return_probabilities(ps, s)
        for q, t, v in zip(prev["player_id"], prev["team_id"], p.to_numpy(), strict=True):
            out[(q, t, s)] = float(v)
    return out


def choose_k_def(act: pd.DataFrame, prof: pd.DataFrame) -> tuple[float, dict]:
    """k_def by DEV (2012-2014) next-game error of the opponents' rim / 3PA share and
    FT rate: actual - (offence expectation + defender's excess)."""
    res = {}
    base = act.merge(
        prof[["game_id", "team_id", "x_rim", "x_t3", "x_ftr"]], on=["game_id", "team_id"]
    )
    base = base[base["season"].isin([2012, 2013, 2014]) & (base["pbp_fga"] > 0)]
    for k in K_DEF_GRID:
        de = pos.defense_excess(act, prof, k)
        m = base.merge(
            de.rename(columns={"def_id": "opp_id"}), on=["game_id", "opp_id", "season"], how="left"
        )
        err = 0.0
        for share, x, e, w in (
            (m["rim_a"] / m["pbp_fga"], m["x_rim"], m["def_rim"], m["pbp_fga"]),
            (m["t3_a"] / m["pbp_fga"], m["x_t3"], m["def_t3"], m["pbp_fga"]),
            (m["fta"] / m["fga"], m["x_ftr"], m["def_ftr"], m["fga"]),
        ):
            e0 = float(np.average((share - x) ** 2, weights=w))
            e1 = float(np.average((share - x - e.fillna(0)) ** 2, weights=w))
            err += e1 / e0
        res[str(k)] = err / 3
    best = min(K_DEF_GRID, key=lambda k: res[str(k)])
    return best, res


def features_stage() -> None:
    pr = load_prior()
    x, tg, shots = load_rows()
    ctx = w3.Ctx()
    games = ctx.games
    pret = p_return(ctx.ps, list(range(FIRST, 2027)))
    prof = pos.team_profiles(x, pr, games, pret)
    act = pos.team_actuals(
        shots.merge(
            x[["game_id", "player_id", "team_id"]].drop_duplicates(),
            on=["game_id", "player_id"],
            suffixes=("_s", ""),
        ).drop(columns=["team_id_s"], errors="ignore"),
        tg,
    )
    k_def, kfit = choose_k_def(act, prof)
    de = pos.defense_excess(act, prof, k_def)
    lg = pos.league_running(act, games)
    WORK.mkdir(parents=True, exist_ok=True)
    prof.to_parquet(WORK / "team_profiles.parquet", index=False)
    de.to_parquet(WORK / "defense_excess.parquet", index=False)
    lg.to_parquet(WORK / "league_running.parquet", index=False)
    act.to_parquet(WORK / "team_actuals.parquet", index=False)
    (OUT / "k_def.json").write_text(json.dumps({"k_def": k_def, "dev_fit": kfit}, indent=1))
    print({"k_def": k_def, "fit": kfit, "profiles": len(prof)}, flush=True)


# ------------------------------------------------------------------ arms -------------
COMPONENTS = ("B21", "B22", "B23", "B24")


def subgroup_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    from cbb_edge.model import arms as _arms

    gs = np.minimum(df["h_games_seen"], df["a_games_seen"])
    poss = df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"]
    val = df["season"].isin(w2.VALID)
    return {
        "first_game": gs <= 1,
        "games_seen_2_10": gs.between(2, 10),
        "conference": df["conference_game"].astype(bool),
        "non_conference": ~df["conference_game"].astype(bool),
        "neutral": df["L"] == 0,
        "mismatch_gt15": _arms.matchup_features(df)["margin_an"].abs() > 15,
        "top_pace_decile": poss >= poss[val].quantile(0.9),
    }


def evaluate(df: pd.DataFrame, p: pd.DataFrame, base: pd.DataFrame) -> dict[str, object]:
    v = w4.blocked_compare(df, p, base)
    m = p["margin"].notna() & base["margin"].notna() & df["margin"].notna()
    val = df["season"].isin(w2.VALID)
    sub = {}
    for k, mask in subgroup_masks(df).items():
        mm = (m & val & mask).to_numpy()
        ea = (p["margin"] - df["margin"]).to_numpy()[mm]
        eb = (base["margin"] - df["margin"]).to_numpy()[mm]
        sub[k] = {"n": int(mm.sum()), "d_rmse": w4._rmse(ea) - w4._rmse(eb)}
    v["subgroups"] = sub
    return v


def gate(name: str, v: dict) -> str:
    """Preregistered gates (WAVE5.md)."""
    bl = list(v["blocks"].values())
    if name == "B25":
        ok = (
            v["d_rmse"] <= -0.008
            and sum(x < 0 for x in bl) >= 4
            and sum(x < 0 for x in v["seasons"].values()) >= 8
            and v["boot_p_better"] >= 0.95
            and v["d_nov_dec"] <= 0
            and v["d_jan_mar"] <= 0.005
            and v["d_log_loss"] <= 0
            and v["d_total_rmse"] <= 0.010
            and all(g["d_rmse"] <= 0.030 for g in v["subgroups"].values())
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


def b20_frame(ctx: w3.Ctx, pf_name: str = "pf_b19h") -> pd.DataFrame:
    src = w4.WORK if pf_name == "pf_b19h" else w3.WORK
    df = w3.frame(ctx, pd.read_parquet(w4.WORK / "states_b16b.parquet"),
                  pd.read_parquet(src / f"{pf_name}.parquet"))  # fmt: skip
    df["game_date_et"] = df["game_id"].map(ctx.games.set_index("game_id")["game_date_et"])
    return df


def load_possession(df: pd.DataFrame) -> pd.DataFrame:
    prof = pd.read_parquet(WORK / "team_profiles.parquet")
    de = pd.read_parquet(WORK / "defense_excess.parquet")
    lg = pd.read_parquet(WORK / "league_running.parquet")
    dev = prof[prof["season"].between(2010, 2014)]
    fill = {
        c: float(dev[c].mean()) for c in prof.columns if c not in ("game_id", "team_id", "season")
    }
    fill.update({c: 0.0 for c in de.columns if c.startswith("def_") and c != "def_id"})
    lgd = lg[lg["season"].between(2010, 2014)]
    fill.update({"rim": float(lgd["lg_rim"].mean()), "t3": float(lgd["lg_t3"].mean())})
    return blocks.possession_frame(df, prof, de, lg, fill)


def arms_stage(only: list[str] | None = None) -> None:
    ctx = w3.Ctx()
    df = b20_frame(ctx)
    sf = pd.read_parquet(w4.WORK / "shooting_features.parquet")
    X20 = w4.base_X(df, [blocks.shooting_block(df, sf)])
    preds = {"B20": w4.make_pred(df, X20)}
    ref = pd.read_parquet(w4.WORK / "pure_predictions.parquet").set_index("game_id")
    chk = float(np.nanmax(np.abs(preds["B20"]["margin"].to_numpy()
                                 - ref.loc[df["game_id"], "B20_margin"].to_numpy())))  # fmt: skip
    print({"B20_recomputed_vs_wave4_max_abs": chk}, flush=True)
    pf = load_possession(df)
    want = (lambda a: True) if only is None else (lambda a: a in only)
    extra = {
        "B21": lambda: blocks.b21_block(df, pf),
        "B22": lambda: blocks.b22_block(df, pf),
        "B24": lambda: blocks.b24_block(df, pf),
        "B23": lambda: blocks.b23_block(df, b20_frame(ctx, "pf_b12")),
    }
    for a in COMPONENTS:
        if want(a):
            preds[a] = w4.make_pred(df, pd.concat([X20, extra[a]()], axis=1))
    comp_file = OUT / "b25_components.json"
    if want("B25") and comp_file.exists():
        comp = json.loads(comp_file.read_text())["components"]
        if comp:
            parts = [extra[a]() for a in comp]
            preds["B25"] = w4.make_pred(df, blocks.combine(X20, *parts))
    report: dict[str, object] = {"reference": "B20 (pure-0.4.0)", "arms": {}}
    for name, p in preds.items():
        if name == "B20":
            continue
        v = evaluate(df, p, preds["B20"])
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
    tag = "" if only is None else "_" + "_".join(only)
    allp.to_parquet(WORK / f"pure_predictions{tag}.parquet", index=False)
    (OUT / f"metrics{tag}.json").write_text(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "prior":
        prior_stage()
    elif stage == "features":
        features_stage()
    elif stage == "arms":
        arms_stage(sys.argv[2:] or None)
    else:
        raise SystemExit(stage)
