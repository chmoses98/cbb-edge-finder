"""Prospective promotion rule (WAVE4.md) — mechanics on synthetic seasons."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.research import promotion


def _season(n=5000, ch_noise=10.6, inc_noise=11.0, seed=0):
    rng = np.random.default_rng(seed)
    truth = rng.normal(0, 8, n)
    margin = truth + rng.normal(0, 10, n)
    days = pd.date_range("2026-11-03", periods=150, freq="D")
    d = pd.DataFrame(
        {
            "game_id": np.arange(n),
            "game_date": rng.choice(days, n),
            "margin": margin,
            "total": 140 + rng.normal(0, 17, n),
        }
    )
    d["month"] = pd.to_datetime(d["game_date"]).dt.month
    d["home_win"] = (d["margin"] > 0).astype(float)
    d["inc_margin"] = truth + rng.normal(0, np.sqrt(max(inc_noise**2 - 100, 0.01)), n)
    d["ch_margin"] = truth + rng.normal(0, np.sqrt(max(ch_noise**2 - 100, 0.01)), n)
    from scipy.stats import norm

    for k, sd in (("inc", inc_noise), ("ch", ch_noise)):
        vp = max(sd**2 - 100, 0.01)  # projection noise variance; truth variance 64
        mean = d[f"{k}_margin"] * 64 / (64 + vp)
        var = 64 * vp / (64 + vp) + 100
        d[f"{k}_total"] = 140.0
        d[f"{k}_wp"] = norm.cdf(mean / np.sqrt(var))  # calibrated by construction
    d["conference_game"] = rng.random(n) < 0.6
    d["neutral"] = rng.random(n) < 0.1
    d["less_informed_games"] = rng.integers(0, 30, n)
    d["conf_tier_home"] = rng.integers(0, 3, n)
    d["conf_tier_away"] = rng.integers(0, 3, n)
    d["mkt_margin"] = truth + rng.normal(0, 2, n)
    return d


def test_clearly_better_challenger_is_promoted_only_when_final():
    d = _season()
    assert promotion.evaluate(d, final=False, n_boot=500)["verdict"].startswith("MONITORING")
    r = promotion.evaluate(d, final=True, n_boot=500)
    assert r["2_margin_rmse"] and r["verdict"] == "PROMOTE", r


def test_equal_models_keep_incumbent_and_small_sample_blocks():
    r = promotion.evaluate(_season(ch_noise=11.0), final=True, n_boot=500)
    assert r["verdict"] == "KEEP INCUMBENT"
    r = promotion.evaluate(_season(n=800), final=True, n_boot=500)
    assert not r["1_sample"] and r["verdict"] == "KEEP INCUMBENT"
