"""Possession (pace) models — basketball-only, expanding window over prior seasons.

P0 additive:   poss = mu + p_h + p_a                        (engine default)
P1 ridge:      poss ~ additive + p_h*p_a + |p_h-p_a| + recent-pace proxy + context
Target: actual game possessions (mean of both teams' estimates, per 40 minutes is NOT
used for totals — real game possessions including overtime).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


def pace_features(df: pd.DataFrame, ctx: pd.DataFrame | None = None) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["add"] = df["mu_tempo"] + df["h_off_tempo"] + df["a_off_tempo"]
    X["prod"] = df["h_off_tempo"] * df["a_off_tempo"]
    X["absdiff"] = (df["h_off_tempo"] - df["a_off_tempo"]).abs()
    X["slow_side"] = np.minimum(df["h_off_tempo"], df["a_off_tempo"])
    X["L"] = df["L"]
    X["min_games"] = np.minimum(df["h_games_seen"], df["a_games_seen"]).clip(upper=15)
    if ctx is not None:
        for c in ctx.columns:
            X[c] = ctx[c]
    return X


def ridge_by_season(
    df: pd.DataFrame,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    alpha: float = 10.0,
    first_train: int = 2012,
    min_train_seasons: int = 3,
) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    ok = X.notna().all(axis=1)
    for s in sorted(df["season"].unique()):
        tr = ok & y.notna() & df["season"].between(first_train, s - 1)
        cur = ok & (df["season"] == s)
        if df.loc[tr, "season"].nunique() < min_train_seasons or not cur.any():
            continue
        m = Ridge(alpha=alpha).fit(X[tr], y[tr])
        out[cur] = m.predict(X[cur])
    return out
