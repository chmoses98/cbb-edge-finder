"""Opponent adjustment, shrinkage and possession-formula tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.features.possessions import add_possessions_and_factors, team_possessions
from cbb_edge.ratings.adjusted import solve


def test_possession_formula():
    assert team_possessions(60, 10, 12, 20) == 60 - 10 + 12 + 0.475 * 20


def test_four_factors_and_tempo_ot():
    row = {
        "fga": 60,
        "fgm": 25,
        "fg3a": 20,
        "fg3m": 7,
        "fta": 20,
        "ftm": 15,
        "orb": 10,
        "drb": 25,
        "tov": 12,
        "pts": 72,
        "n_ot": 1,
    }
    opp = {f"opp_{k}": v for k, v in row.items() if k != "n_ot"}
    df = add_possessions_and_factors(pd.DataFrame([{**row, **opp}]))
    r = df.iloc[0]
    assert np.isclose(r.poss, 60 - 10 + 12 + 0.475 * 20)
    assert np.isclose(r.efg, (25 + 0.5 * 7) / 60)
    assert np.isclose(r.to_rate, 12 / r.poss)
    assert np.isclose(r.orb_rate, 10 / (10 + 25))
    assert np.isclose(r.ftr, 20 / 60)
    assert np.isclose(r.tempo, r.poss * 40 / 45)  # one overtime


def _design(n=8, games=600, seed=1, noise=0.5, hca=3.0):
    rng = np.random.default_rng(seed)
    a, b = rng.normal(0, 5, n), rng.normal(0, 5, n)
    a -= a.mean()
    b -= b.mean()
    t = rng.integers(0, n, games)
    o = (t + rng.integers(1, n, games)) % n
    loc = rng.choice([-1, 0, 1], games)
    y = 100 + a[t] + b[o] + hca * loc + rng.normal(0, noise, games)
    return t, o, y, loc, a, b


def test_opponent_adjustment_recovers_truth():
    t, o, y, loc, a, b = _design()
    n = len(a)
    f = solve(
        t,
        o,
        y,
        np.ones(len(y)),
        loc,
        n,
        np.zeros(n),
        np.zeros(n),
        1e-3,
        prior_mu=100,
        prior_eta=0,
        lam_mu=1e-6,
        lam_eta=1e-6,
    )
    assert np.allclose(f.off - f.off.mean(), a, atol=0.15)
    assert np.allclose(f.deff - f.deff.mean(), b, atol=0.15)
    assert abs(f.eta - 3.0) < 0.1


def test_adjustment_beats_raw_under_unbalanced_schedule():
    """Team 0 plays only strong defenses: raw offense is biased, adjusted is not."""
    rng = np.random.default_rng(3)
    n = 6
    a = np.array([5.0, 0, 0, 0, 0, -5])
    b = np.array([0, -6.0, -6.0, 0, 3, 3])  # teams 1,2 are elite defenses
    rows = []
    for _ in range(400):
        ti = rng.integers(0, n)
        oi = rng.choice([1, 2]) if ti == 0 else rng.choice([j for j in range(n) if j != ti])
        rows.append((ti, oi))
    t, o = np.array(rows).T
    y = 100 + a[t] + b[o] + rng.normal(0, 0.3, len(t))
    loc = np.zeros(len(t))
    kw = dict(prior_mu=100, prior_eta=0, lam_mu=1e-6, lam_eta=1e-6)
    adj = solve(t, o, y, np.ones(len(y)), loc, n, np.zeros(n), np.zeros(n), 1e-3, **kw)
    raw = solve(
        t, o, y, np.ones(len(y)), loc, n, np.zeros(n), np.zeros(n), 1e-3, adjust=False, **kw
    )
    err_adj = abs((adj.off[0] - adj.off.mean()) - a[0])
    err_raw = abs((raw.off[0] - raw.off.mean()) - a[0])
    assert err_adj < 0.3 < err_raw


def test_shrinkage_toward_prior_decays_with_data():
    t, o, y, loc, a, b = _design(games=2000, noise=0.1)
    n = len(a)
    prior = np.full(n, 10.0)
    small = solve(
        t[:5],
        o[:5],
        y[:5],
        np.ones(5),
        loc[:5],
        n,
        prior,
        prior,
        50.0,
        prior_mu=100,
        prior_eta=3,
        lam_mu=1e3,
        lam_eta=1e3,
    )
    big = solve(
        t,
        o,
        y,
        np.ones(len(y)),
        loc,
        n,
        prior,
        prior,
        50.0,
        prior_mu=100,
        prior_eta=3,
        lam_mu=1e3,
        lam_eta=1e3,
    )
    # with ~no data teams sit at their prior; with lots of data they leave it
    assert np.mean(np.abs(small.off - 10)) < 1.0
    assert np.mean(np.abs(big.off - 10)) > 3.0


def test_neutral_site_has_no_home_term():
    t, o, y, loc, a, b = _design(hca=4.0)
    n = len(a)
    f = solve(
        t,
        o,
        y,
        np.ones(len(y)),
        loc,
        n,
        np.zeros(n),
        np.zeros(n),
        1e-3,
        prior_mu=100,
        prior_eta=0,
        lam_mu=1e-6,
        lam_eta=1e-6,
    )
    # prediction at neutral (loc=0) equals mu + a + b exactly; home adds eta
    i, j = 0, 1
    neutral = f.mu + f.off[i] + f.deff[j]
    home = f.mu + f.off[i] + f.deff[j] + f.eta
    assert np.isclose(home - neutral, f.eta)
    assert f.eta > 3.5


def test_pace_model_symmetric():
    rng = np.random.default_rng(5)
    n = 6
    p = rng.normal(0, 3, n)
    t = rng.integers(0, n, 800)
    o = (t + rng.integers(1, n, 800)) % n
    y = 67 + p[t] + p[o]
    f = solve(
        t,
        o,
        y,
        np.ones(len(y)),
        np.zeros(len(y)),
        n,
        np.zeros(n),
        np.zeros(n),
        1e-4,
        prior_mu=67,
        prior_eta=0,
        lam_mu=1e-6,
        pace=True,
        use_loc=False,
    )
    assert np.allclose(f.off - f.off.mean(), p - p.mean(), atol=0.05)
