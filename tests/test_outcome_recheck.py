from datetime import UTC, datetime

from cbb_edge.research import outcome_recheck as orc


def _ev(gid, hs, as_, status="STATUS_FINAL", hid="1", aid="2"):
    return {
        "id": str(gid),
        "competitions": [
            {
                "status": {"type": {"name": status}},
                "competitors": [
                    {"homeAway": "home", "score": str(hs), "team": {"id": hid}},
                    {"homeAway": "away", "score": str(as_), "team": {"id": aid}},
                ],
            }
        ],
    }


def test_parse_scoreboard():
    got = orc.parse_scoreboard({"events": [_ev(10, 70, 60), {"id": "x"}]})
    assert got == {
        10: {
            "espn_status": "STATUS_FINAL",
            "espn_home_id": "1",
            "espn_away_id": "2",
            "home": 70,
            "away": 60,
        }
    }


def test_recheck_merges_keeps_history_and_unlisted():
    t0, t1 = datetime(2026, 11, 13, tzinfo=UTC), datetime(2026, 11, 14, tzinfo=UTC)
    calls = []

    def day(d):
        calls.append(d)
        return {"events": [_ev(10, 70, 60)]}

    graded = [{"game_id": 10, "date": "2026-11-12"}, {"game_id": 11, "date": "2026-11-12"}]
    first = orc.recheck(graded, day, None, now=t0)
    assert calls == ["20261112"]  # one request per ET date, not per game
    g = {x["game_id"]: x for x in first["games"]}
    assert g[10]["home"] == 70 and g[11]["espn_status"] == "NOT_LISTED"

    second = orc.recheck(graded, lambda d: {"events": [_ev(10, 71, 60)]}, first, now=t1)
    g2 = {x["game_id"]: x for x in second["games"]}
    assert g2[10]["home"] == 71 and g2[10]["history"][0]["home"] == 70
    assert "history" not in g2[11]  # unchanged NOT_LISTED re-observation adds no history


def test_compare_is_orientation_aware():
    cc = {
        "games": [
            {"game_id": 1, "espn_status": "STATUS_FINAL", "home": 80, "away": 70},
            {"game_id": 2, "espn_status": "STATUS_FINAL", "home": 80, "away": 70},
            {"game_id": 3, "espn_status": "STATUS_FINAL", "home": 81, "away": 70},
            {"game_id": 4, "espn_status": "STATUS_IN_PROGRESS", "home": 40, "away": 30},
        ]
    }
    rows = [
        {"game_id": 1, "actual_margin": 10, "actual_total": 150, "orientation": "SAME"},
        {"game_id": 2, "actual_margin": -10, "actual_total": 150, "orientation": "SWAPPED"},
        {"game_id": 3, "actual_margin": 10, "actual_total": 150, "orientation": "SAME"},
        {"game_id": 4, "actual_margin": 10, "actual_total": 150, "orientation": "SAME"},
        {"game_id": 5, "actual_margin": 1, "actual_total": 1, "orientation": "SAME"},
    ]
    out = orc.compare(cc, rows)
    assert out["graded_finals"] == {
        "match": 2,
        "MISMATCH": 1,
        "NOT_FINAL_ON_RECHECK": 1,
        "not_rechecked": 1,
    }
    assert out["problem_game_ids"] == [3, 4]
