"""MARKET_BENCHMARK step for Wave 4 (downstream only).

Reads the persisted Wave-4 PURE predictions (written by run_wave4.py arms) and the free
ESPN closing lines and writes research/wave4/{market_scorecard.csv, convergence.csv,
market.json}. market.json also tests the Wave-3 "game-20 bump": gap at games-seen 18–22
vs the surrounding windows 12–17 and 23–28, with a day-clustered bootstrap, and the gap
by game type (non-conference / first conference meeting / conference rematch) for
games-seen 15–25. Nothing here can influence the PURE predictions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.research import scorecard

sys.path.insert(0, str(Path(__file__).parent))
from market_benchmark import load_lines  # noqa: E402

OUT = Path("research/wave4")
WORK = data_dir() / "research" / "wave4"
VALID = list(range(2015, 2025))
HIST = [2025, 2026]
ARMS = ("B15", "B17", "B20")


def _gap(x: pd.DataFrame, arm: str) -> float:
    return float(
        np.sqrt(((x[f"{arm}_margin"] - x["margin"]) ** 2).mean())
        - np.sqrt(((x["mkt"] - x["margin"]) ** 2).mean())
    )


def bump_test(d: pd.DataFrame, arm: str, n_boot: int = 2000, seed: int = 0) -> dict:
    v = d[d["season"].isin(VALID)].copy()
    v["gs"] = np.minimum(v["h_games_seen"], v["a_games_seen"])
    inner = v[v["gs"].between(18, 22)]
    outer = v[v["gs"].between(12, 17) | v["gs"].between(23, 28)]
    obs = _gap(inner, arm) - _gap(outer, arm)
    rng = np.random.default_rng(seed)
    days_i = inner["game_date_et"].unique()
    days_o = outer["game_date_et"].unique()
    gi = {k: x for k, x in inner.groupby("game_date_et")}
    go = {k: x for k, x in outer.groupby("game_date_et")}
    diffs = []
    for _ in range(n_boot):
        a = pd.concat([gi[k] for k in rng.choice(days_i, len(days_i))])
        b = pd.concat([go[k] for k in rng.choice(days_o, len(days_o))])
        diffs.append(_gap(a, arm) - _gap(b, arm))
    diffs = np.asarray(diffs)
    return {
        "gap_18_22": _gap(inner, arm),
        "gap_12_17_and_23_28": _gap(outer, arm),
        "excess": obs,
        "ci90": [float(np.quantile(diffs, 0.05)), float(np.quantile(diffs, 0.95))],
        "n_inner": len(inner),
        "n_outer": len(outer),
    }


def main() -> None:
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pp = pd.read_parquet(WORK / "pure_predictions.parquet")
    lines = load_lines(games)
    d = pp.merge(lines, on="game_id", how="inner").merge(
        games[["game_id", "home_score", "away_score", "game_date_et", "conference_game"]],
        on="game_id",
    )
    d["margin"] = (d["home_score"] - d["away_score"]).astype(float)
    d["home_win"] = (d["margin"] > 0).astype(float)
    d["mkt"] = -d["home_spread_close"]
    preds = {
        a: pd.DataFrame({"margin": d[f"{a}_margin"], "home_wp": d[f"{a}_home_wp"]}) for a in ARMS
    }
    sc, curves, par = [], [], {}
    for split, seasons in (("validation", VALID), ("historical", HIST)):
        mask = d["season"].isin(seasons)
        sc.append(scorecard.scorecard(d, preds, mask, d["mkt"], "MARKET").assign(split=split))
        for a in ARMS:
            c = scorecard.convergence_curve(d, d[f"{a}_margin"], mask, d["mkt"], max_games=30)
            curves.append(c.assign(arm=a, split=split))
            par[f"{split}|{a}"] = scorecard.time_to_parity(c)
    # game type within the conference-play transition window (games seen 15-25)
    d["pair"] = [tuple(sorted(x)) for x in zip(d["home_team_id"], d["away_team_id"], strict=True)]
    d = d.sort_values("start_time_utc")
    d["meeting"] = d.groupby(["season", "pair"]).cumcount() + 1
    v = d[d["season"].isin(VALID)].copy()
    v["gs"] = np.minimum(v["h_games_seen"], v["a_games_seen"])
    w = v[v["gs"].between(15, 25)]
    gtype = np.where(
        w["conference_game"].astype(bool),
        np.where(w["meeting"] > 1, "conf_rematch", "conf_first"),
        "nonconf",
    )
    by_type = {}
    for t in ("nonconf", "conf_first", "conf_rematch"):
        x = w[gtype == t]
        if len(x) >= 200:
            by_type[t] = {
                "n": len(x),
                **{f"gap_{a}": _gap(x, a) for a in ARMS},
                "market_rmse": float(np.sqrt(((x["mkt"] - x["margin"]) ** 2).mean())),
            }
    rep = {
        "note": "MARKET is a benchmark only; PURE arms use no market data",
        "time_to_parity_games_seen": par,
        "game20_bump_test": {a: bump_test(d, a) for a in ("B15", "B20")},
        "gap_by_game_type_games_seen_15_25": by_type,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(sc).to_csv(OUT / "market_scorecard.csv", index=False)
    pd.concat(curves).to_csv(OUT / "convergence.csv", index=False)
    (OUT / "market.json").write_text(json.dumps(rep, indent=1, default=float))
    s = pd.concat(sc)
    print(s[s["arm"].isin(["B15", "B20"])].round(3).to_string())
    print(
        json.dumps(
            {k: rep[k] for k in ("game20_bump_test", "gap_by_game_type_games_seen_15_25")},
            indent=1,
            default=float,
        )
    )


if __name__ == "__main__":
    main()
