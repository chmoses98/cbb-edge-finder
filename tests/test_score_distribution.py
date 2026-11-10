"""Coherence of the single score distribution behind every FULL-game market."""

from __future__ import annotations

import math

import numpy as np
import pytest

from cbb_edge.kalshi.research.challenger import probability as contract_probability
from cbb_edge.model.score_distribution import ScoreDistribution, Unmodeled

P = {"margin": 6.0, "total": 142.0, "margin_sd": 11.0, "total_sd": 16.0}
IDENT = {"total_bias": 0.0, "margin_sd_scale": 1.0, "total_sd_scale": 1.0}


def test_means_and_variances_recompose_exactly():
    d = ScoreDistribution.from_projection(P)
    assert d.mean_home + d.mean_away == pytest.approx(P["total"])
    assert d.mean_home - d.mean_away == pytest.approx(P["margin"])
    var_total = 2 * d.var_team + 2 * d.cov_home_away
    var_margin = 2 * d.var_team - 2 * d.cov_home_away
    assert math.sqrt(var_total) == pytest.approx(P["total_sd"])
    assert math.sqrt(var_margin) == pytest.approx(P["margin_sd"])
    cov = np.array([[d.var_team, d.cov_home_away], [d.cov_home_away, d.var_team]])
    assert np.linalg.eigvalsh(cov).min() >= -1e-12  # positive semidefinite


def test_monte_carlo_agrees_with_closed_form():
    d = ScoreDistribution.from_projection(P)
    cov = [[d.var_team, d.cov_home_away], [d.cov_home_away, d.var_team]]
    x = np.random.default_rng(3).multivariate_normal([d.mean_home, d.mean_away], cov, 400_000)
    assert (x[:, 0] - x[:, 1] > 0).mean() == pytest.approx(d.p_home_win(), abs=0.004)
    assert (x.sum(1) > 140.5).mean() == pytest.approx(d.p_total_gt(140.5), abs=0.004)
    assert (x[:, 0] > 72.5).mean() == pytest.approx(d.p_team_total_gt("home", 72.5), abs=0.004)


def test_matches_the_existing_contract_pricer_for_winner_margin_total():
    d = ScoreDistribution.from_projection(P)
    sem_t = {"status": "parsed", "period": "FULL", "market_type": "TOTAL", "strike": 145.5}
    sem_m = {
        "status": "parsed",
        "period": "FULL",
        "market_type": "MARGIN",
        "subject_side": "away",
        "strike": 2.5,
    }
    sem_w = {"status": "parsed", "period": "FULL", "market_type": "WINNER", "subject_side": "home"}
    assert d.p_total_gt(145.5) == pytest.approx(contract_probability(sem_t, P, IDENT))
    assert d.p_margin_gt("away", 2.5) == pytest.approx(contract_probability(sem_m, P, IDENT))
    assert d.p_home_win() == pytest.approx(contract_probability(sem_w, P, IDENT))


def test_ladders_are_monotone_and_team_totals_cannot_contradict_the_game_total():
    d = ScoreDistribution.from_projection(P)
    ps = [d.p_total_gt(k) for k in range(120, 170, 5)]
    assert ps == sorted(ps, reverse=True)
    assert d.p_margin_gt("home", -100) > 0.999 and d.p_margin_gt("home", 100) < 0.001
    # complementary sides of the same margin are consistent
    assert d.p_margin_gt("home", 3.5) + d.p_margin_gt("away", -3.5) == pytest.approx(1.0)


def test_unsupported_markets_stay_unmodeled_not_fabricated():
    d = ScoreDistribution.from_projection(P)
    assert isinstance(d.period("1H"), Unmodeled) and "1H" in d.period("1H").reason
    assert isinstance(d.player(), Unmodeled)
    assert isinstance(ScoreDistribution.from_projection({"margin": 1.0}), Unmodeled)
    assert isinstance(ScoreDistribution.from_projection({**P, "margin_sd": 0.0}), Unmodeled)
    assert isinstance(ScoreDistribution.from_projection({**P, "total": float("nan")}), Unmodeled)
    assert d.to_dict()["status"] == "SHADOW_UNVALIDATED"
