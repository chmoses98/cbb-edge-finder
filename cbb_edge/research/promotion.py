"""Prospective promotion rule (fixed 2026-10-05 in research/hypotheses/WAVE4.md).

``evaluate(df)`` takes one row per completed game with the incumbent's and a
challenger's latest pre-tip projections from the same run, and returns every criterion
plus the verdict. Run ONCE after the national championship game; earlier calls are
monitoring only (``final=False`` never returns PROMOTE).

Columns: game_id, game_date (ET date), month, margin, total, home_win,
inc_margin, inc_total, inc_wp, ch_margin, ch_total, ch_wp, conference_game, neutral,
less_informed_games, conf_tier_home, conf_tier_away, and optionally mkt_margin (latest
captured pre-tip line — benchmark only).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_GAMES = 4000
N_BOOT = 10000


def _rmse(e) -> float:
    return float(np.sqrt(np.mean(np.square(e))))


def _ll(p, y) -> float:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _ece(p, y, bins: int = 10) -> float:
    p, y = np.asarray(p), np.asarray(y)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(
        sum(
            abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean()
            for b in range(bins)
            if (idx == b).any()
        )
    )


def evaluate(
    df: pd.DataFrame, final: bool = False, n_boot: int = N_BOOT, seed: int = 0
) -> dict[str, object]:
    d = df.dropna(subset=["margin", "inc_margin", "ch_margin"])
    e_i, e_c = d["inc_margin"] - d["margin"], d["ch_margin"] - d["margin"]
    c: dict[str, object] = {"n_games": len(d)}
    c["1_sample"] = len(d) >= MIN_GAMES
    c["rmse_inc"], c["rmse_ch"] = _rmse(e_i), _rmse(e_c)
    # day-clustered bootstrap of Δ RMSE
    rng = np.random.default_rng(seed)
    g = (
        d.assign(a=e_c**2, b=e_i**2)
        .groupby("game_date")
        .agg(a=("a", "sum"), b=("b", "sum"), n=("a", "size"))
    )
    A, B, N = g["a"].to_numpy(), g["b"].to_numpy(), g["n"].to_numpy()
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    delta = np.sqrt(A[idx].sum(1) / N[idx].sum(1)) - np.sqrt(B[idx].sum(1) / N[idx].sum(1))
    c["p_better"] = float((delta < 0).mean())
    c["2_margin_rmse"] = c["rmse_ch"] < c["rmse_inc"] and c["p_better"] >= 0.95
    c["3_mae"] = float(e_c.abs().mean()) <= float(e_i.abs().mean()) + 0.01
    c["4_total_rmse"] = (
        _rmse(d["ch_total"] - d["total"]) <= _rmse(d["inc_total"] - d["total"]) + 0.05
    )
    c["5_log_loss"] = _ll(d["ch_wp"], d["home_win"]) <= _ll(d["inc_wp"], d["home_win"]) + 0.0005
    ece_c, ece_i = _ece(d["ch_wp"], d["home_win"]), _ece(d["inc_wp"], d["home_win"])
    c["ece_ch"], c["ece_inc"] = ece_c, ece_i
    c["6_calibration"] = ece_c <= 0.020 and ece_c <= ece_i + 0.005
    if "mkt_margin" in d and d["mkt_margin"].notna().any():
        m = d["mkt_margin"].notna()
        gm = _rmse(d.loc[m, "mkt_margin"] - d.loc[m, "margin"])
        c["gap_ch"] = _rmse(e_c[m]) - gm
        c["gap_inc"] = _rmse(e_i[m]) - gm
        c["7_market_gap"] = c["gap_ch"] <= c["gap_inc"]
    else:
        c["7_market_gap"] = False
    months = {}
    for mo, x in d.groupby("month"):
        if len(x) >= 300:
            months[int(mo)] = _rmse(x["ch_margin"] - x["margin"]) - _rmse(
                x["inc_margin"] - x["margin"]
            )
    c["by_month_delta"] = months
    c["8_by_month"] = all(v <= 0.05 for v in months.values())
    subs = {
        "conference": d["conference_game"].astype(bool),
        "non_conference": ~d["conference_game"].astype(bool),
        "neutral": d["neutral"].astype(bool),
        "true_home": ~d["neutral"].astype(bool),
        "big_projection": d["inc_margin"].abs() >= 15,
        "early_info": d["less_informed_games"] <= 5,
        "same_tier": d["conf_tier_home"] == d["conf_tier_away"],
    }
    sub = {k: _rmse(e_c[m]) - _rmse(e_i[m]) for k, m in subs.items() if m.sum() >= 100}
    c["subgroup_delta"] = sub
    c["9_no_catastrophic_subgroup"] = all(v <= 0.10 for v in sub.values())
    d2 = d.assign(day=pd.to_datetime(d["game_date"]))
    start = d2["day"].min()
    blk = ((d2["day"] - start).dt.days // 14).to_numpy()
    wins = [(_rmse(e_c[blk == b]) < _rmse(e_i[blk == b])) for b in np.unique(blk)]
    c["share_14d_blocks_better"] = float(np.mean(wins)) if wins else 0.0
    c["10_consistency"] = c["share_14d_blocks_better"] >= 0.60
    keys = [k for k in c if k[:2].rstrip("_").isdigit()]
    ok = all(bool(c[k]) for k in keys)
    c["verdict"] = (
        ("PROMOTE" if ok else "KEEP INCUMBENT") if final else ("MONITORING ONLY (not final)")
    )
    return c
