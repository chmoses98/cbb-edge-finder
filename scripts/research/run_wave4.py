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


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "arms"
    if stage == "pf":
        pf_stage(sys.argv[2])
    else:
        raise SystemExit("stage not implemented yet")
