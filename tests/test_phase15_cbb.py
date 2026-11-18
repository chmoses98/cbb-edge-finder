"""Phase 15 CBB research model tests (synthetic data only; no network, no data lake)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "phase15"))
M = pytest.importorskip("cbb_p15_model")
KX = pytest.importorskip("cbb_p15_kalshi")


def _season(seed=0, n_teams=12, n_days=40, season=2030):
    rng = np.random.default_rng(seed)
    off, de, tem = rng.normal(0, 6, n_teams), rng.normal(0, 6, n_teams), rng.normal(0, 3, n_teams)
    rows, gid = [], 1
    for day in range(n_days):
        perm = rng.permutation(n_teams)
        for h, a in zip(perm[::2], perm[1::2]):
            poss = 68 + tem[h] + tem[a] + rng.normal(0, 2)
            hp = (100 + off[h] - de[a] + 2) * poss / 100 + rng.normal(0, 6)
            ap = (100 + off[a] - de[h] - 2) * poss / 100 + rng.normal(0, 6)
            rows.append((gid, season, pd.Timestamp("2029-11-01") + pd.Timedelta(days=day), False, 100 + h, 100 + a,
                         True, True, round(hp), round(ap), poss, f"T{h}", f"T{a}"))
            gid += 1
    g = pd.DataFrame(rows, columns=["game_id", "season", "date", "neutral", "home_id", "away_id", "home_d1", "away_d1",
                                    "home_pts", "away_pts", "poss", "home_abbr", "away_abbr"])
    return g, off, de


def _prior(n):
    z = np.zeros(n)
    return {"mu": 100.0, "hca": 0.0, "O": z, "D": z, "muP": 68.0, "T": z}


def test_ridge_recovers_ratings():
    g, off, de = _season()
    idx, n = M.team_index(g)
    r = M.fit_ratings(g, idx, n, g.date.max() + pd.Timedelta(days=1), M.Cfg(lam_prior=0.5, lam_mu=0.01, lam_hca=0.01), _prior(n))
    est = np.array([r["O"][idx[100 + i]] for i in range(len(off))])
    assert np.corrcoef(est, off - off.mean())[0, 1] > 0.9
    assert 2.0 < r["hca"] < 6.0


def test_walk_forward_is_date_strict():
    """Truncation test: predictions for date d are identical when every game on/after d has garbage outcomes."""
    g, _, _ = _season(seed=1)
    idx, n = M.team_index(g)
    d = sorted(g.date.unique())[25]
    cfg = M.Cfg(variant="base", tau=30.0)
    ref = M.walk_season(g, cfg, _prior(n), idx, n, dates=[d])
    bad = g.copy()
    later = bad.date >= d
    bad.loc[later, ["home_pts", "away_pts"]] = 999
    bad.loc[later, "poss"] = 41.0
    bad = bad[bad.date <= d]
    got = M.walk_season(bad, cfg, _prior(n), idx, n, dates=[d])
    np.testing.assert_array_equal(ref.sort_values("game_id").values, got.sort_values("game_id").values)


def test_roster_state_is_date_strict():
    pm = pd.DataFrame({"season": [2030] * 4, "game_id": [1, 1, 2, 2], "team_id": [10, 10, 10, 10],
                       "athlete_id": [1, 2, 1, 3], "minutes": [30.0, 20, 30, 25],
                       "date": pd.to_datetime(["2029-11-01", "2029-11-01", "2029-11-05", "2029-11-05"])})
    prev = pd.DataFrame({"season": [2029] * 3, "team_id": [10, 10, 11], "athlete_id": [1, 3, 2], "minutes": [600.0, 400, 500],
                         "k_seen": [2, 1, 3]})
    rs = M.RosterState(2030, pm, prev, {10: (1.0, 0.0, 0.0), 11: (5.0, -2.0, 1.0)}, {1: 0.7, 2: 0.6, 3: 0.5}, q=0.5)
    a = rs.at(pd.Timestamp("2029-11-03"))      # athlete 3 not yet seen; athlete 2 transferred in from team 11
    assert a.at[10, "c"] == pytest.approx((600 + 400 * 0.7 * 0.5) / 1000)
    assert a.at[10, "tr"] == pytest.approx(0.5) and a.at[10, "inO"] == pytest.approx(5.0)
    b = rs.at(None)
    assert b.at[10, "c"] == pytest.approx(1.0)


def test_contract_probabilities_coherent():
    import cbb_p15_eval as EV
    p = EV.GamePMF(4.0, 11.0, 145.0, 17.0, 0.02, n=200)
    w = sum(EV.contract_p(p, "winner", s, None) for s in ("home", "away", "tie"))
    assert w == pytest.approx(1.0, abs=1e-9)
    # home wins by > 2.5 and away wins by > -2.5 (i.e. home margin < 2.5) partition the line
    assert EV.contract_p(p, "spread", "home", 2.5) + EV.contract_p(p, "spread", "away", -2.5) == pytest.approx(1.0, abs=1e-9)
    assert EV.contract_p(p, "total", None, 145.5) == pytest.approx(0.5, abs=0.03)
    assert EV.contract_p(p, "team_total", "home", 74.5) == pytest.approx(0.5, abs=0.04)


def test_share_features_date_strict():
    import cbb_p15_eval as EV
    g, _, _ = _season(seed=2, n_days=10)
    hv = pd.DataFrame({"game_id": g.game_id, "season": g.season, "home_1h": (g.home_pts * 0.45).round().astype(int),
                       "away_1h": (g.away_pts * 0.5).round().astype(int), "n_ot": 0})
    hv["home_2hot"], hv["away_2hot"] = g.home_pts - hv.home_1h, g.away_pts - hv.away_1h
    d = sorted(g.date.unique())[6]
    a = EV.team_share_lookup(g, hv, 0.47)
    hv2 = hv.copy()
    hv2.loc[g.date.values >= d, "home_1h"] = 0
    b = EV.team_share_lookup(g, hv2, 0.47)
    on = g.game_id[g.date == d]
    pd.testing.assert_frame_equal(a[a.game_id.isin(on)].reset_index(drop=True), b[b.game_id.isin(on)].reset_index(drop=True))


def test_kalshi_matching_sides():
    games = pd.DataFrame({"game_id": [7], "date": [pd.Timestamp("2026-04-06")], "home_abbr": ["MICH"], "away_abbr": ["CONN"]})
    mk = pd.DataFrame({"series": ["KXNCAAMBSPREAD", "KXNCAAMBSPREAD", "KXNCAAMB1HWINNER"],
                       "ticker": ["KXNCAAMBSPREAD-26APR06CONNMICH-MICH20", "KXNCAAMBSPREAD-26APR06CONNMICH-CONN3",
                                  "KXNCAAMB1HWINNER-26APR06CONNMICH-TIE"],
                       "event": ["KXNCAAMBSPREAD-26APR06CONNMICH"] * 2 + ["KXNCAAMB1HWINNER-26APR06CONNMICH"],
                       "strike": [20.5, 3.5, None], "result": [0, 1, 0], "suffix": ["MICH20", "CONN3", "TIE"], "rules": ""})
    m = KX.match_events(mk, games)
    assert list(m.side) == ["home", "away", "tie"] and set(m.game_id) == {7}
