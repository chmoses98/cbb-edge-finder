"""Evaluation metrics for projections (margin, total, win probability)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def point_metrics(pred: pd.Series, actual: pd.Series) -> dict[str, float]:
    ok = pred.notna() & actual.notna()
    e = (pred[ok] - actual[ok]).to_numpy(dtype=float)
    if not len(e):
        return {"n": 0}
    return {
        "n": int(len(e)),
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e**2))),
        "bias": float(np.mean(e)),
    }


def prob_metrics(p: pd.Series, y: pd.Series) -> dict[str, float]:
    ok = p.notna() & y.notna()
    pp = np.clip(p[ok].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    yy = y[ok].to_numpy(dtype=float)
    if not len(yy):
        return {"n": 0}
    return {
        "n": int(len(yy)),
        "log_loss": float(-np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp))),
        "brier": float(np.mean((pp - yy) ** 2)),
        "accuracy": float(np.mean((pp > 0.5) == (yy == 1))),
    }


def calibration_table(p: pd.Series, y: pd.Series, bins: int = 10) -> pd.DataFrame:
    ok = p.notna() & y.notna()
    d = pd.DataFrame({"p": p[ok], "y": y[ok]})
    d["bin"] = pd.cut(d.p, np.linspace(0, 1, bins + 1), include_lowest=True)
    t = d.groupby("bin", observed=True).agg(
        n=("y", "size"), mean_pred=("p", "mean"), observed=("y", "mean")
    )
    return t.reset_index()


def ece(p: pd.Series, y: pd.Series, bins: int = 10) -> float:
    t = calibration_table(p, y, bins)
    return float((t.n * (t.mean_pred - t.observed).abs()).sum() / t.n.sum())


def wilson_ci(wins: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    ph = wins / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (float(c - h), float(c + h))
