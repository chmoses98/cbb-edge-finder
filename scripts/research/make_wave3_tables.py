"""Markdown tables for research/reports/WAVE3.md from the wave-3 artefacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir

OUT = Path("research/wave3")


def main() -> None:
    m = json.loads((OUT / "metrics.json").read_text())["arms"]
    pp = pd.read_parquet(data_dir() / "research" / "wave3" / "pure_predictions.parquet")
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")[
        ["game_id", "home_score", "away_score"]
    ]
    d = pp.merge(g, on="game_id")
    y = (d["home_score"] - d["away_score"]).astype(float)
    lines = [
        "## Arms vs B9 (validation 2015-2024 | historical 2025-2026)\n",
        "| arm | val RMSE | Δ | Δ Nov–Dec | Δ Jan–Mar | Δ log loss | seasons better | verdict"
        " | hist Δ | hist Δ Nov–Dec |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a, e in m.items():
        v, h = e["validation"], e["historical"]
        lines.append(
            f"| {a} | {v['rmse']:.4f} | {v['d_rmse']:+.4f} | {v['d_rmse_nov_dec']:+.4f} | "
            f"{v['d_rmse_jan_mar']:+.4f} | {v['d_log_loss']:+.4f} | {v['seasons_better']}/10 | "
            f"{e['verdict']} | {h['d_rmse']:+.4f} | {h['d_rmse_nov_dec']:+.4f} |"
        )
    lines += [
        "",
        "## B9 vs B15 by season (margin RMSE)\n",
        "| season | n | B9 | B15 | Δ |",
        "|---|---|---|---|---|",
    ]
    for s, x in d.groupby("season"):
        if s < 2015:
            continue
        yy = y[x.index]
        r9 = float(np.sqrt(np.mean((x["B9_margin"] - yy) ** 2)))
        r15 = float(np.sqrt(np.mean((x["B15_margin"] - yy) ** 2)))
        lines.append(f"| {s} | {len(x)} | {r9:.3f} | {r15:.3f} | {r15 - r9:+.3f} |")
    sc = pd.read_csv(OUT / "market_scorecard.csv")
    lines += [
        "",
        "## Early-season scorecard vs MARKET (closing line; benchmark only)\n",
        "| split | slice | n | B9 RMSE | B15 RMSE | B9 MAE | B15 MAE | B9 LL | B15 LL | "
        "MARKET RMSE | B9 gap | B15 gap |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (split, sl), x in sc[sc["arm"].isin(["B9", "B15"])].groupby(["split", "slice"], sort=False):
        b9, b15 = x[x["arm"] == "B9"].iloc[0], x[x["arm"] == "B15"].iloc[0]
        if b9["n"] == 0:
            continue
        lines.append(
            f"| {split} | {sl} | {b9['n']} | {b9['margin_rmse']:.3f} | {b15['margin_rmse']:.3f} | "
            f"{b9['margin_mae']:.3f} | {b15['margin_mae']:.3f} | {b9['log_loss']:.4f} | "
            f"{b15['log_loss']:.4f} | {b9['MARKET_rmse']:.3f} | {b9['gap_vs_MARKET']:+.3f} | "
            f"{b15['gap_vs_MARKET']:+.3f} |"
        )
    c = pd.read_csv(OUT / "convergence.csv")
    c = c[(c["split"] == "validation") & c["arm"].isin(["B9", "B15"])]
    pv = c.pivot(index="games_seen", columns="arm", values="gap")
    n = c[c["arm"] == "B9"].set_index("games_seen")["n"]
    lines += [
        "",
        "## Convergence (validation; gap = PURE RMSE − MARKET RMSE, pooled ±1 game)\n",
        "| games seen | n | B9 gap | B15 gap |",
        "|---|---|---|---|",
    ]
    for k in (0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30):
        lines.append(f"| {k} | {n[k]} | {pv.loc[k, 'B9']:+.3f} | {pv.loc[k, 'B15']:+.3f} |")
    par = json.loads((OUT / "market.json").read_text())["time_to_parity_games_seen"]
    lines += [
        "",
        "## Time to market parity (games seen by the less-informed team)\n",
        "| split | arm | kind | +0.50 | +0.25 | +0.15 | +0.10 | +0.05 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key in ("validation|B9", "validation|B15", "historical|B9", "historical|B15"):
        for kind in ("first", "sustained"):
            t = par[key][kind]
            sp, arm = key.split("|")
            lines.append(
                f"| {sp} | {arm} | {kind} | "
                + " | ".join("—" if t[k] is None else str(t[k]) for k in t)
                + " |"
            )
    (OUT / "tables.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
