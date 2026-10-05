"""Early-season scorecard and convergence curves (generic; knows nothing about markets).

``bucket`` columns are derived from pregame state: calendar month (ET) and the number of
games the LESS-informed team has played before tip (``min(h_games_seen, a_games_seen)``),
reported as "game n" = games seen + 1. A reference prediction (e.g. a benchmark computed
downstream) can be passed as ``ref`` to report gaps; the PURE pipeline never passes one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GAME_BUCKETS = (
    ("game 1", 0, 1),
    ("games 2-3", 1, 3),
    ("games 4-5", 3, 5),
    ("games 6-10", 5, 10),
    ("games 11+", 10, 999),
)
MONTHS = (("Nov", (11,)), ("Dec", (12,)), ("Jan-Mar", (1, 2, 3, 4)))


def buckets(df: pd.DataFrame) -> pd.DataFrame:
    mon = pd.to_datetime(df["start_time_utc"], utc=True).dt.tz_convert("America/New_York").dt.month
    mg = np.minimum(df["h_games_seen"], df["a_games_seen"])
    return pd.DataFrame({"month": mon.to_numpy(), "min_games": mg.to_numpy()}, index=df.index)


def _rmse(e: pd.Series) -> float:
    return float(np.sqrt(np.mean(np.square(e)))) if len(e) else float("nan")


def _ll(p: pd.Series, y: pd.Series) -> float:
    p = p.clip(1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(p) else float("nan")


def scorecard(
    df: pd.DataFrame,
    preds: dict[str, pd.DataFrame],
    mask: pd.Series,
    ref: pd.Series | None = None,
    ref_name: str = "REF",
) -> pd.DataFrame:
    """Rows: slice x arm with N, margin RMSE, MAE, log loss (+ ref RMSE and gap)."""
    b = buckets(df)
    slices: list[tuple[str, pd.Series]] = [("all", pd.Series(True, index=df.index))]
    for name, months in MONTHS:
        slices.append((name, b["month"].isin(months)))
    for name, lo, hi in GAME_BUCKETS:
        slices.append((name, (b["min_games"] >= lo) & (b["min_games"] < hi)))
    common = mask & df["margin"].notna()
    for p in preds.values():
        common &= p["margin"].notna()
    if ref is not None:
        common &= ref.notna()
    rows = []
    for sname, sm in slices:
        m = common & sm
        y = df.loc[m, "margin"]
        r_rmse = _rmse(ref[m] - y) if ref is not None else np.nan
        for arm, p in preds.items():
            e = p.loc[m, "margin"] - y
            rec = {
                "slice": sname,
                "arm": arm,
                "n": int(m.sum()),
                "margin_rmse": _rmse(e),
                "margin_mae": float(e.abs().mean()) if m.any() else np.nan,
                "log_loss": _ll(p.loc[m, "home_wp"], df.loc[m, "home_win"]),
            }
            if ref is not None:
                rec[f"{ref_name}_rmse"] = r_rmse
                rec[f"gap_vs_{ref_name}"] = rec["margin_rmse"] - r_rmse
            rows.append(rec)
    return pd.DataFrame(rows)


def convergence_curve(
    df: pd.DataFrame,
    pred: pd.Series,
    mask: pd.Series,
    ref: pd.Series | None = None,
    max_games: int = 30,
    window: int = 1,
) -> pd.DataFrame:
    """RMSE by games seen (less-informed team), pooled over +-``window`` games."""
    mg = buckets(df)["min_games"]
    ok = mask & pred.notna() & df["margin"].notna()
    if ref is not None:
        ok &= ref.notna()
    rows = []
    for k in range(max_games + 1):
        m = ok & (mg >= k - window) & (mg <= k + window)
        y = df.loc[m, "margin"]
        rec = {"games_seen": k, "n": int(m.sum()), "pure_rmse": _rmse(pred[m] - y)}
        if ref is not None:
            rec["ref_rmse"] = _rmse(ref[m] - y)
            rec["gap"] = rec["pure_rmse"] - rec["ref_rmse"]
        rows.append(rec)
    return pd.DataFrame(rows)


def time_to_parity(
    curve: pd.DataFrame, thresholds=(0.50, 0.25, 0.15, 0.10, 0.05), min_n: int = 200
) -> dict:
    """Games seen until the PURE-vs-reference gap reaches each threshold.

    ``sustained``: smallest k from which the gap stays <= threshold for every later k;
    ``first``: first k at which the (pooled +-1 game) gap is <= threshold.
    Points pooled from fewer than ``min_n`` games are ignored.
    """
    if "n" in curve:
        curve = curve[curve["n"] >= min_n]
    g = curve["gap"].to_numpy()
    ks = curve["games_seen"].to_numpy()
    sustained: dict[str, int | None] = {}
    first: dict[str, int | None] = {}
    for t in thresholds:
        key = f"+{t:.2f}"
        sustained[key] = next((int(ks[i]) for i in range(len(g)) if np.all(g[i:] <= t)), None)
        first[key] = next((int(ks[i]) for i in range(len(g)) if g[i] <= t), None)
    return {"sustained": sustained, "first": first}
