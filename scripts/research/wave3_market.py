"""MARKET_BENCHMARK step for wave 3 (downstream only).

Reads the persisted wave-3 PURE predictions (written by run_wave3.py before this step
runs) and the free ESPN closing lines, and produces:

* research/wave3/market_scorecard.csv – Nov / Dec / Jan-Mar and games-played slices:
  N, PURE RMSE / MAE / log loss, MARKET RMSE, market_gap (validation + historical)
* research/wave3/convergence.csv       – RMSE by games seen (less-informed team),
  PURE arms vs MARKET, pooled +-1 game
* research/wave3/market.json           – time to market parity (+0.50 ... +0.05) per arm

Nothing here can influence the PURE predictions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.research import scorecard

sys.path.insert(0, str(Path(__file__).parent))
from market_benchmark import load_lines  # noqa: E402

OUT = Path("research/wave3")
WORK = data_dir() / "research" / "wave3"
VALID = list(range(2015, 2025))
HIST = [2025, 2026]


def main() -> None:
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pp = pd.read_parquet(WORK / "pure_predictions.parquet")
    lines = load_lines(games)
    d = pp.merge(lines, on="game_id", how="inner").merge(
        games[["game_id", "home_score", "away_score"]], on="game_id"
    )
    d["margin"] = (d["home_score"] - d["away_score"]).astype(float)
    d["home_win"] = (d["margin"] > 0).astype(float)
    ref = -d["home_spread_close"]
    arms = sorted({c[: -len("_margin")] for c in pp.columns if c.endswith("_margin")})
    preds = {
        a: pd.DataFrame({"margin": d[f"{a}_margin"], "home_wp": d[f"{a}_home_wp"]}) for a in arms
    }
    sc, curves, parity = [], [], {}
    for split, seasons in (("validation", VALID), ("historical", HIST)):
        mask = d["season"].isin(seasons)
        sc.append(scorecard.scorecard(d, preds, mask, ref, "MARKET").assign(split=split))
        for a in arms:
            c = scorecard.convergence_curve(d, d[f"{a}_margin"], mask, ref, max_games=30)
            curves.append(c.assign(arm=a, split=split))
            parity[f"{split}|{a}"] = scorecard.time_to_parity(c)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(sc).to_csv(OUT / "market_scorecard.csv", index=False)
    pd.concat(curves).to_csv(OUT / "convergence.csv", index=False)
    (OUT / "market.json").write_text(
        json.dumps(
            {
                "note": "MARKET is a benchmark only; PURE arms use no market data",
                "time_to_parity_games_seen": parity,
            },
            indent=1,
        )
    )
    s = pd.concat(sc)
    print(s[s["slice"].isin(["all", "Nov", "Dec", "Jan-Mar"])].round(3).to_string())


if __name__ == "__main__":
    main()
