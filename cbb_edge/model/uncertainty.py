"""Heteroscedastic predictive uncertainty (basketball-only, prior seasons only).

log(residual^2) ~ context features (early-season sample size, projected total, pace,
3PA rates, mismatch size, neutral site, roster uncertainty) fitted by ridge on earlier
seasons; sigma = sqrt(exp(fit) * c) with c calibrated so mean sigma^2 matches the
training residual variance (log-normal bias correction). Win probability is then
Phi(margin / sigma_margin). Optimized for calibration (log loss, interval coverage),
never for betting payoff.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import Ridge


def sigma_features(
    df: pd.DataFrame, margin: pd.Series, total: pd.Series, extra: pd.DataFrame | None = None
) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    mg = np.minimum(df["h_games_seen"], df["a_games_seen"])
    X["early"] = 1.0 / (1.0 + mg)
    X["total"] = total
    X["abs_margin"] = margin.abs()
    X["poss"] = df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"]
    if "h_off_fg3a_rate" in df:
        X["three_rate"] = (
            df["mu_fg3a_rate"] * 2
            + df["h_off_fg3a_rate"]
            + df["a_def_fg3a_rate"]
            + df["a_off_fg3a_rate"]
            + df["h_def_fg3a_rate"]
        )
    X["neutral"] = 1.0 - df["L"]
    if extra is not None:
        for c in extra.columns:
            X[c] = extra[c]
    return X


def hetero_sigma(
    df: pd.DataFrame,
    pred: pd.Series,
    target: str,
    X: pd.DataFrame,
    first_train: int = 2012,
    min_train_seasons: int = 3,
) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    res = df[target] - pred
    ok = X.notna().all(axis=1) & pred.notna()
    for s in sorted(df["season"].unique()):
        tr = ok & res.notna() & df["season"].between(first_train, s - 1)
        cur = ok & (df["season"] == s)
        if df.loc[tr, "season"].nunique() < min_train_seasons or not cur.any():
            continue
        z = np.log(res[tr] ** 2 + 1.0)
        m = Ridge(alpha=10.0).fit(X[tr], z)
        fit_tr = np.exp(m.predict(X[tr]))
        c = float((res[tr] ** 2).mean() / fit_tr.mean())
        out[cur] = np.sqrt(np.exp(m.predict(X[cur])) * c)
    return out


def normal_wp(margin: pd.Series, sigma: pd.Series) -> pd.Series:
    return pd.Series(np.clip(norm.cdf(margin / sigma), 1e-4, 1 - 1e-4), index=margin.index)


def coverage(
    pred: pd.Series,
    sigma: pd.Series,
    actual: pd.Series,
    levels: tuple[float, ...] = (0.5, 0.8, 0.95),
) -> dict[str, float]:
    ok = pred.notna() & sigma.notna() & actual.notna()
    z = ((actual - pred) / sigma)[ok].abs()
    return {f"cov{int(lv * 100)}": float((z <= norm.ppf(0.5 + lv / 2)).mean()) for lv in levels}


def pit_calibration(pred: pd.Series, sigma: pd.Series, actual: pd.Series) -> float:
    """Mean |empirical CDF - uniform| of PIT values (0 = perfectly calibrated)."""
    ok = pred.notna() & sigma.notna() & actual.notna()
    u = np.sort(norm.cdf(((actual - pred) / sigma)[ok]))
    if not len(u):
        return float("nan")
    grid = (np.arange(1, len(u) + 1) - 0.5) / len(u)
    return float(np.mean(np.abs(u - grid)))
