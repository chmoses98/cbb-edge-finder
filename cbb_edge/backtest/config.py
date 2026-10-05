"""Frozen engine configuration chosen on DEV seasons (research/baseline/dev_tuning.csv)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cbb_edge.backtest.walkforward import DEFAULT_LAMBDA, EngineConfig

REPO = Path(__file__).resolve().parents[2]
TUNING_CSV = REPO / "research" / "baseline" / "dev_tuning.csv"


def tuned_config(**overrides: object) -> EngineConfig:
    if not TUNING_CSV.exists():
        return EngineConfig(**overrides)  # type: ignore[arg-type]
    t = pd.read_csv(TUNING_CSV).sort_values("margin_rmse").iloc[0]
    tau = None if pd.isna(t["tau"]) else float(t["tau"])
    kw: dict[str, object] = {
        "lam": {k: v * float(t["lam_scale"]) for k, v in DEFAULT_LAMBDA.items()},
        "prior_regress": float(t["prior_regress"]),
        "recency_tau_days": tau,
    }
    kw.update(overrides)
    return EngineConfig(**kw)  # type: ignore[arg-type]
