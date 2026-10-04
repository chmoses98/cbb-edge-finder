"""Silver-layer rules: D-I membership, neutral-site location, possession sanity."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.data.silver.build import D1_MIN_GAMES, d1_membership


def _sched(pairs):
    return pd.DataFrame(
        [{"home_espn_id": h, "away_espn_id": a, "status": "STATUS_FINAL"} for h, a in pairs]
    )


def test_d1_membership_threshold():
    pairs = [(1, 2)] * D1_MIN_GAMES * 300 + [(1, 99)]  # 99 = non-D-I opponent, 1 game
    d1 = d1_membership(_sched(pairs))
    assert d1 == {1, 2}


def test_partial_schedule_falls_back_to_previous_season():
    pairs = [(1, 2)] * 3  # pre-season: only 3 games listed so far
    assert d1_membership(_sched(pairs), prev_d1={1, 2, 3}) == {1, 2, 3}


def test_neutral_site_location_coding(tmp_path):
    from tests.synthetic import make_league

    games, tg, _ = make_league(neutral_share=1.0, n_days=3)
    assert set(tg["loc"].unique()) == {0}
    games, tg, _ = make_league(neutral_share=0.0, n_days=3)
    assert set(tg["loc"].unique()) == {-1, 1}
    # each game has exactly one home (+1) and one away (-1) row
    assert (tg.groupby("game_id")["loc"].sum() == 0).all()


def test_possessions_equal_for_both_teams():
    from tests.synthetic import make_league

    _, tg, _ = make_league(n_days=3)
    per_game = tg.groupby("game_id")["poss"].nunique()
    assert (per_game == 1).all()
    assert np.isfinite(tg["ppp"]).all()
