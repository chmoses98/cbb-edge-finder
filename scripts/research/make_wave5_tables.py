"""Full historical table for the Wave-5 report: margin RMSE / log loss / total RMSE per
season for B15 (pure-0.3.0), B20 (pure-0.4.0) and the Wave-5 arms. Writes
research/wave5/full_table.csv and prints a markdown table."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir

sys.path.insert(0, str(Path(__file__).parent))
import run_wave4 as w4  # noqa: E402
import run_wave5 as w5  # noqa: E402

ARMS = ["B15", "B20", "B21", "B22", "B23", "B24", "B25"]


def main() -> None:
    p5 = pd.read_parquet(w5.WORK / "pure_predictions.parquet")
    p4 = pd.read_parquet(w4.WORK / "pure_predictions.parquet")[
        ["game_id", "B15_margin", "B15_total", "B15_home_wp"]
    ]
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")[
        ["game_id", "home_score", "away_score"]
    ]
    d = p5.merge(p4, on="game_id", how="left").merge(g, on="game_id")
    d["margin"] = d["home_score"] - d["away_score"]
    d["total"] = d["home_score"] + d["away_score"]
    d["hw"] = (d["margin"] > 0).astype(float)
    rows = []
    groups = [(str(s), d["season"] == s) for s in range(2015, 2027)]
    groups += [("2015-2024", d["season"].between(2015, 2024)), ("2025-26", d["season"] == 2026)]
    for lab, m in groups:
        r = {"season": lab, "n": int(m.sum())}
        for a in ARMS:
            x = d[m & d[f"{a}_margin"].notna()]
            q = x[f"{a}_home_wp"].clip(1e-4, 1 - 1e-4)
            r[f"{a}_rmse"] = float(np.sqrt(((x[f"{a}_margin"] - x["margin"]) ** 2).mean()))
            r[f"{a}_logloss"] = float(-(x["hw"] * np.log(q) + (1 - x["hw"]) * np.log(1 - q)).mean())
            r[f"{a}_total_rmse"] = float(np.sqrt(((x[f"{a}_total"] - x["total"]) ** 2).mean()))
        rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(w5.OUT / "full_table.csv", index=False)
    cols = ["season", "n"] + [f"{a}_rmse" for a in ARMS]
    print(t[cols].round(4).to_string(index=False))
    cols = (
        ["season"]
        + [f"{a}_logloss" for a in ("B20", "B25")]
        + [f"{a}_total_rmse" for a in ("B20", "B25")]
    )
    print(t[cols].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
