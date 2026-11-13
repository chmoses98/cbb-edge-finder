"""Offline projection diagnostics: identical games, boundary exclusion, slopes, market benchmark."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from cbb_edge.research import projection_diagnostics as pdg

T0 = datetime(2026, 11, 3, 23, tzinfo=UTC)
BOUND = datetime(2026, 11, 11, 22, tzinfo=UTC)


def _world(n=120, compress=0.8, seed=3):
    rng = random.Random(seed)
    frozen = {v: {} for v in pdg.VERSIONS}
    finals, market = {}, {}
    for i in range(n):
        tip = T0 + timedelta(hours=1.5 * i)
        true_m, true_t = rng.uniform(-25, 25), rng.uniform(125, 160)
        for v in pdg.VERSIONS:
            frozen[v][i] = {"tip": tip, "as_of": tip - timedelta(hours=3), "margin": compress * true_m,
                            "total": true_t - 3.0, "margin_sd": 11.0, "total_sd": 16.0,
                            "home_wp": 0.5 + true_m / 60, "poss": 68.0,
                            "home_games_seen": i % 4, "away_games_seen": 3}  # fmt: skip
        h = round((true_t + true_m) / 2 + rng.gauss(0, 3))
        finals[i] = {"home": h, "away": round((true_t - true_m) / 2 + rng.gauss(0, 3))}
        market[i] = {"spread": -true_m, "total": true_t}
    return frozen, finals, market


def test_identical_games_and_wave14_records_excluded():
    frozen, finals, market = _world()
    del frozen["pure-0.3.0"][5]
    del finals[6]
    frozen["pure-0.5.0_roster"][7]["as_of"] = BOUND
    rows, cnt = pdg.build_games(frozen, finals, market, before=BOUND)
    ids = {r["game_id"] for r in rows}
    assert {5, 6, 7}.isdisjoint(ids) and len(rows) == 117
    assert cnt == {
        "scored": 117,
        "version_missing": 1,
        "no_final": 1,
        "prospective_wave14_excluded": 1,
    }


def test_compressed_margins_show_slope_above_one_and_market_disagreement_near_one():
    frozen, finals, market = _world(compress=0.8)
    rows, _ = pdg.build_games(frozen, finals, market, before=BOUND)
    r = pdg.run(rows)
    assert r["versions"]["pure-0.5.0"]["margin_slope"] == pytest.approx(1 / 0.8, rel=0.05)
    assert r["versions"]["pure-0.5.0"]["total_bias"] == pytest.approx(3.0, abs=0.6)
    md = r["market_disagreement"]["margin"]
    assert md["est"] == pytest.approx(1.0, abs=0.1) and md["lo"] <= md["est"] <= md["hi"]
    assert set(r["by_min_games_seen"]) == {"0", "1", "2", "3+"}


def test_bootstrap_is_deterministic():
    frozen, finals, market = _world(n=40)
    rows, _ = pdg.build_games(frozen, finals, market, before=BOUND)
    assert pdg.run(rows)["ci_base"] == pdg.run(rows)["ci_base"]
