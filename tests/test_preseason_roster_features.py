import json

import pandas as pd
import pytest

from cbb_edge.rosters.preseason_features import (
    appearance_rosters,
    player_seasons,
    snapshot_rosters,
    team_features,
)

STATS = ["field_goals_made", "field_goals_attempted", "free_throws_made", "free_throws_attempted",
         "offensive_rebounds", "defensive_rebounds", "steals", "assists", "blocks", "fouls",
         "turnovers"]  # fmt: skip


def _box(rows):
    b = pd.DataFrame(
        rows, columns=["season", "game_id", "team_id", "athlete_id", "minutes", "points"]
    )
    b["game_date"] = pd.Timestamp("2025-12-01")
    for c in STATS:
        b[c] = 0
    return b


@pytest.fixture
def ps():
    # season 2026: team 1 = A (30 min, 20 pts), B (10 min); team 2 = C (40 min).
    # season 2027: A stays on 1, C transfers 2 -> 1, D is new (no history); B left.
    return player_seasons(_box([
        (2026, 1, 1, 100, 30, 20), (2026, 1, 1, 101, 10, 0), (2026, 1, 2, 102, 40, 10),
        (2027, 5, 1, 100, 20, 5), (2027, 5, 1, 102, 25, 8), (2027, 5, 1, 103, 5, 0),
    ]))  # fmt: skip


def test_returning_and_transfer_shares(ps):
    f = team_features(ps, appearance_rosters(ps, 2027), 2027).set_index("team_id")
    t = f.loc[1]
    assert t.ret_minutes_share == pytest.approx(30 / 40)
    assert t.ret_points_share == pytest.approx(1.0)
    assert t.tr_in_minutes_rel == pytest.approx(40 / 40)
    assert (t.n_returners, t.n_transfers_in, t.n_newcomers_no_hist) == (1, 1, 1)
    assert t.stats_through_season == 2026 and not t.membership_pit


def test_current_season_stats_never_used(ps):
    # changing season-2027 minutes / points must not change any 2027 preseason feature
    ps2 = ps.copy()
    ps2.loc[ps2.season == 2027, ["minutes", "points", "prod"]] *= 7
    cols = ["ret_minutes_share", "ret_prod_share", "tr_in_prod_rel", "tr_in_minutes"]
    a = team_features(ps, appearance_rosters(ps, 2027), 2027)[cols]
    b = team_features(ps2, appearance_rosters(ps2, 2027), 2027)[cols]
    pd.testing.assert_frame_equal(a, b)


def test_snapshot_uses_latest_capture_before_first_tip(tmp_path):
    def snap(name, ts, team, ids):
        rows = [{"schema": "roster-snapshot-v1", "captured_at": ts, "espn_team_id": team,
                 "espn_athlete_id": str(i), "class": "FR"} for i in ids]  # fmt: skip
        p = tmp_path / name
        p.write_text("\n".join(json.dumps(r) for r in rows))
        return p

    files = [
        snap("a.jsonl", "2026-10-01T00:00:00+00:00", 1, [100, 101]),
        snap("b.jsonl", "2026-11-01T00:00:00+00:00", 1, [100, 102]),
        snap("c.jsonl", "2026-11-10T00:00:00+00:00", 1, [100, 999]),  # after first tip
    ]
    tip = pd.Series({1: pd.Timestamp("2026-11-03", tz="UTC")})
    r = snapshot_rosters(files, tip, 2027)
    assert sorted(r.athlete_id) == [100, 102]
    assert r.membership_pit.all()
    assert (r.membership_as_of == pd.Timestamp("2026-11-01", tz="UTC")).all()
