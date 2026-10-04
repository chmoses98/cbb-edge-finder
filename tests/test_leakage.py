"""Historical-integrity tests: no post-T information may enter a pregame state."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.backtest.walkforward import EngineConfig, default_priors, replay_season
from tests.synthetic import make_league

CFG = EngineConfig()


def _replay(games, tg):
    teams = sorted(set(tg.team_id))
    pri = default_priors(teams, tg)
    return replay_season(2020, games, tg, pri, CFG)


def test_info_set_strictly_before_tipoff():
    games, tg, _ = make_league()
    st, _ = _replay(games, tg)
    st = st.merge(games[["game_id", "start_time_utc"]], on="game_id")
    has = st.info_max_available_at.notna()
    assert (st.loc[has, "info_max_available_at"] < st.loc[has, "cutoff"]).all()
    assert (st.cutoff <= st.start_time_utc).all()
    # first day: nothing observed yet
    first = st.start_time_utc == st.start_time_utc.min()
    assert (st.loc[first, "info_rows"] == 0).all()


def test_future_results_cannot_change_past_states():
    games, tg, _ = make_league(seed=4)
    st1, _ = _replay(games, tg)
    cut = games.start_time_utc.sort_values().iloc[len(games) // 2]
    tg2 = tg.copy()
    fut = tg2.start_time_utc >= cut
    # wildly corrupt every future box score / result
    for c in ("ppp", "efg", "to_rate", "orb_rate", "ftr", "tempo", "fg3_pct", "fg2_pct"):
        tg2.loc[fut, c] = tg2.loc[fut, c] * 3 + 7
    st2, _ = _replay(games, tg2)
    past = st1.merge(games[["game_id", "start_time_utc"]], on="game_id")
    ids = past.loc[past.start_time_utc < cut, "game_id"]
    a = st1.set_index("game_id").loc[ids].drop(columns=["cutoff", "info_max_available_at"])
    b = st2.set_index("game_id").loc[ids].drop(columns=["cutoff", "info_max_available_at"])
    pd.testing.assert_frame_equal(a, b)
    # and the corruption DID change later states (the test has teeth)
    later = past.loc[past.start_time_utc > cut, "game_id"]
    assert not np.allclose(
        st1.set_index("game_id").loc[later, "h_off_eff"],
        st2.set_index("game_id").loc[later, "h_off_eff"],
    )


def test_same_day_games_do_not_see_each_other():
    games, tg, _ = make_league(seed=2)
    st, _ = _replay(games, tg)
    st = st.merge(games[["game_id", "game_date_et"]], on="game_id")
    # every game on a given day shares exactly the same information set size
    assert (st.groupby("game_date_et").info_rows.nunique() == 1).all()


def test_replay_is_reproducible():
    games, tg, _ = make_league(seed=9)
    a, _ = _replay(games, tg)
    b, _ = _replay(games, tg)
    pd.testing.assert_frame_equal(a, b)


def test_late_game_result_excluded_when_not_available():
    """A game whose result is available only after the next day's first tip is excluded."""
    games, tg, _ = make_league(seed=11, n_days=5)
    st, _ = _replay(games, tg)
    day2 = sorted(games.game_date_et.unique())[1]  # noqa: F841 (used in query)
    cutoff = (
        st.merge(games[["game_id", "game_date_et"]]).query("game_date_et == @day2").cutoff.iloc[0]
    )
    tg_late = tg.copy()
    first_day = tg_late.start_time_utc == tg_late.start_time_utc.min()
    tg_late.loc[first_day, "available_at"] = cutoff + pd.Timedelta(minutes=1)
    st_late, _ = _replay(games, tg_late)
    d2 = st_late.merge(games[["game_id", "game_date_et"]]).query("game_date_et == @day2")
    assert (d2.info_rows == 0).all()


def test_engine_tracks_truth_on_synthetic_league():
    games, tg, truth = make_league(n_days=60, seed=1)
    st, end = _replay(games, tg)
    est = end["eff"].off - end["eff"].off.mean()
    tru = truth.off.to_numpy() - truth.off.mean()
    assert np.corrcoef(est, tru)[0, 1] > 0.8
