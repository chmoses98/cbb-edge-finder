"""Fast tests for the research-only player roster overlay (synthetic data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.research import player_roster_overlay as po


def _pg(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    gid = 0
    for season in (2001, 2002):
        for k in range(8):
            gid += 1
            date = pd.Timestamp(f"{season - 1}-11-10") + pd.Timedelta(days=3 * k)
            for team, pids in (("T1", range(1, 9)), ("T2", range(11, 19))):
                for p in pids:
                    if season == 2002 and p == 1:  # player 1 transfers to T2
                        team_p = "T2"
                    else:
                        team_p = team
                    m = float(rng.integers(0, 35))
                    row = dict(
                        game_id=gid,
                        athlete_espn_id=p,
                        team_id=team_p,
                        season=season,
                        game_date_et=date.date(),
                        min=m,
                        available_at=date,
                    )
                    row.update({s: float(rng.integers(0, 6)) for s in po.RATE_STATS})
                    rows.append(row)
    return pd.DataFrame(rows)


def test_player_state_uses_only_earlier_games():
    d = po._clean(_pg())
    base = po.player_state(d)
    d2 = d.copy()
    late = d2.date >= pd.Timestamp("2001-11-01")
    d2.loc[late, "pts"] = 99.0
    mut = po.player_state(d2)
    early = (base.date <= pd.Timestamp("2001-11-01")).to_numpy()
    np.testing.assert_allclose(base.loc[early, "r_pts"], mut.loc[early, "r_pts"])
    assert (base.loc[~early, "r_pts"] != mut.loc[~early, "r_pts"]).any()


def test_rosters_follow_transfers_and_never_use_current_game_minutes():
    d = po._clean(_pg())
    st = po.player_state(d)
    ped = po.pedigree(
        d,
        pd.DataFrame(
            columns=[
                "season",
                "home_team_id",
                "away_team_id",
                "home_score",
                "away_score",
                "completed",
            ]
        ),
    )
    ros = po.team_rosters(d, st, ped, [2002])
    t2 = ros[(ros.team_id == "T2") & (ros.k == 3)]
    assert 1 in set(t2.pid)  # transferred player is on his new team's pregame roster
    d2 = d.copy()
    d2.loc[d2.date == d2[d2.season == 2002].date.max(), "min"] = 40.0
    ros2 = po.team_rosters(d2, po.player_state(d2), ped, [2002])
    last = ros.k == ros.k.max()
    np.testing.assert_allclose(
        ros.loc[last, "m_proj"].to_numpy(), ros2.loc[ros2.k == ros2.k.max(), "m_proj"].to_numpy()
    )
