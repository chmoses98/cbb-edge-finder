"""Hyperparameter tuning on DEV seasons only (2007-2014; 2006 seeds priors).

Validation (2015-2024) and holdout (2025-2026) seasons are never touched here.
Output: research/baseline/dev_tuning.csv
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pandas as pd

from cbb_edge.backtest.evaluate import point_metrics
from cbb_edge.backtest.walkforward import DEFAULT_LAMBDA, EngineConfig, run
from cbb_edge.model.arms import analytic, attach_games

DEV = list(range(2006, 2015))
OUT = Path("research/baseline/dev_tuning.csv")


def _parse(grid: str) -> tuple[list[float], list[float], list[float | None]]:
    parts = dict(p.split("=") for p in grid.split(";"))
    tau = [None if v == "None" else float(v) for v in parts["tau"].split(",")]
    return (
        [float(v) for v in parts["lam"].split(",")],
        [float(v) for v in parts["rho"].split(",")],
        tau,
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="lam=0.5,1,2;rho=0.5,0.65,0.8;tau=None,45")
    ap.add_argument("--append", action="store_true")
    a = ap.parse_args()
    lams, rhos, taus = _parse(a.grid)
    g = pd.read_parquet("data/silver/games.parquet")
    tg = pd.read_parquet("data/silver/team_games.parquet")
    rows = []
    for scale, rho, tau in itertools.product(lams, rhos, taus):
        cfg = EngineConfig(
            lam={k: v * scale for k, v in DEFAULT_LAMBDA.items()},
            prior_regress=rho,
            recency_tau_days=tau,
            stats=("eff", "tempo"),
        )
        st = attach_games(run(g, tg, DEV, cfg, verbose=False), g)
        st = st[st.season >= 2008]
        pr = analytic(st)
        m, t = point_metrics(pr.margin, st.margin), point_metrics(pr.total, st.total)
        rows.append(
            {
                "lam_scale": scale,
                "prior_regress": rho,
                "tau": tau,
                "margin_mae": m["mae"],
                "margin_rmse": m["rmse"],
                "total_mae": t["mae"],
                "total_bias": t["bias"],
                "n": m["n"],
            }
        )
        print(rows[-1], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if a.append and OUT.exists():
        df = pd.concat([pd.read_csv(OUT), df], ignore_index=True)
    df.drop_duplicates(["lam_scale", "prior_regress", "tau"], keep="last").sort_values(
        "margin_rmse"
    ).to_csv(OUT, index=False)


if __name__ == "__main__":
    main()
