from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.features.context import rest_days, team_home_effect
from cbb_edge.model.families import MarketLeakError
from cbb_edge.research import blocks


def test_rest_days_uses_only_earlier_games():
    t0 = pd.Timestamp("2020-01-01 20:00", tz="UTC")
    g = pd.DataFrame(
        {
            "game_id": [1, 2, 3],
            "season": 2020,
            "start_time_utc": [t0, t0 + pd.Timedelta(days=2), t0 + pd.Timedelta(days=3)],
            "home_espn_id": [10, 10, 30],
            "away_espn_id": [20, 30, 10],
            "status": "STATUS_FINAL",
        }
    )
    r = rest_days(g).set_index("game_id")
    assert r.loc[1, "h_rest"] == 7.0  # first game -> capped default
    assert r.loc[2, "h_rest"] == 2.0
    assert r.loc[3, "a_rest"] == 1.0 and r.loc[3, "a_b2b"] == 1.0


def test_team_home_effect_uses_prior_seasons_only():
    df = pd.DataFrame({"season": [2019] * 50 + [2020] * 2, "L": 1, "home_team_id": ["T1"] * 52})
    resid = pd.Series([5.0] * 50 + [100.0, 100.0])
    f = team_home_effect(df, resid, k=50)
    assert np.allclose(f[df.season == 2019], 0.0)
    assert np.allclose(f[df.season == 2020], 250 / 100)


def test_blocks_reject_market_columns():
    import pytest

    df = pd.DataFrame({"h_rest": [1.0], "home_spread_close": [-3.0]})
    with pytest.raises(MarketLeakError):
        blocks.context_block(df, df)
