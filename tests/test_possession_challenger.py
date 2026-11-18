"""Fast tests for the research-only possession challenger (synthetic data, no lake)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.research import possession_challenger as pc


def _synthetic(n_teams: int = 12, days: int = 40, seasons=(2001, 2002), seed: int = 0):
    rng = np.random.default_rng(seed)
    teams = [f"T{i:04d}" for i in range(n_teams)]
    strength = rng.normal(0, 8, n_teams)
    pace = rng.normal(0, 3, n_teams)
    games, tgs, gid = [], [], 1
    for s in seasons:
        d0 = pd.Timestamp(f"{s - 1}-11-05T23:00:00Z")
        for day in range(days):
            order = rng.permutation(n_teams)
            for k in range(0, n_teams, 2):
                h, a = order[k], order[k + 1]
                start = d0 + pd.Timedelta(days=day)
                poss = 68 + pace[h] + pace[a] + rng.normal(0, 3)
                eh = 103 + strength[h] / 2 - strength[a] / 2 + 2 + rng.normal(0, 6)
                ea = 103 + strength[a] / 2 - strength[h] / 2 - 2 + rng.normal(0, 6)
                hp, ap = round(poss * eh / 100), round(poss * ea / 100)
                games.append(
                    dict(
                        game_id=gid,
                        season=s,
                        start_time_utc=start,
                        game_date_et=start.date(),
                        neutral_site=False,
                        home_team_id=teams[h],
                        away_team_id=teams[a],
                        home_is_d1=True,
                        away_is_d1=True,
                        completed=True,
                        home_score=hp,
                        away_score=ap,
                    )
                )
                for t, o, pts, opp, loc in ((h, a, hp, ap, 1), (a, h, ap, hp, -1)):
                    tgs.append(
                        dict(
                            game_id=gid,
                            season=s,
                            team_id=teams[t],
                            opp_id=teams[o],
                            pts=float(pts),
                            opp_pts=float(opp),
                            poss=float(poss),
                            loc=loc,
                            team_is_d1=True,
                            opp_is_d1=True,
                            box_ok=True,
                            start_time_utc=start,
                            available_at=start + pd.Timedelta(hours=3),
                        )
                    )
                gid += 1
    return pd.DataFrame(games), pd.DataFrame(tgs)


P = pc.Params(tau_days=60.0, lam_eff=200.0, lam_tempo=3.0, cal_seasons=1)


def test_no_leakage_future_results_do_not_move_earlier_forecasts():
    g, tg = _synthetic()
    base = pc.raw_walk_forward(g, tg, [2001, 2002], P)
    cut = pd.Timestamp("2001-12-01T00:00:00Z")
    tg2 = tg.copy()
    late = tg2.available_at >= cut
    tg2.loc[late, "pts"] = 500.0  # absurd future results
    tg2.loc[late, "poss"] = 99.0
    g2 = g.copy()
    g2.loc[g2.start_time_utc >= cut, ["home_score", "away_score"]] = [300, 0]
    mut = pc.raw_walk_forward(g2, tg2, [2001, 2002], P)
    x = base.merge(mut, on="game_id", suffixes=("", "_m"))
    early = x.start_time_utc < cut
    assert early.sum() > 50
    np.testing.assert_allclose(
        x.loc[early, "c_margin_raw"], x.loc[early, "c_margin_raw_m"], atol=1e-9
    )
    np.testing.assert_allclose(
        x.loc[early, "c_total_raw"], x.loc[early, "c_total_raw_m"], atol=1e-9
    )
    assert (x.loc[~early, "c_total_raw"] - x.loc[~early, "c_total_raw_m"]).abs().max() > 1.0


def test_same_day_games_are_not_in_the_information_set():
    g, tg = _synthetic(seasons=(2001,))
    base = pc.raw_walk_forward(g, tg, [2001], P)
    day = g.game_date_et.unique()[10]
    tg2 = tg.copy()
    same = tg2.game_id.isin(g.loc[g.game_date_et == day, "game_id"])
    tg2.loc[same, "pts"] = 400.0
    mut = pc.raw_walk_forward(g, tg2, [2001], P)
    ids = g.loc[g.game_date_et == day, "game_id"]
    a = base.set_index("game_id").loc[ids, "c_margin_raw"]
    b = mut.set_index("game_id").loc[ids, "c_margin_raw"]
    np.testing.assert_allclose(a, b, atol=1e-9)


def test_calibration_uses_only_earlier_seasons_and_ratings_learn():
    g, tg = _synthetic()
    raw = pc.raw_walk_forward(g, tg, [2001, 2002], P)
    cal = pc.calibrate(raw, 2002, P)
    assert cal["fit_seasons"] == [2001]
    f, _ = pc.forecasts(raw, [2002], P)
    ym = f.home_score - f.away_score
    late = f[f.start_time_utc > f.start_time_utc.quantile(0.5)]
    assert np.corrcoef(late.c_margin, late.home_score - late.away_score)[0, 1] > 0.5
    assert f.c_wp.between(0, 1).all() and np.isfinite(ym).all()
