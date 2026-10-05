"""Availability / roster capture parsing (synthetic ESPN-shaped payloads, no network)."""

from __future__ import annotations

import json

import pandas as pd

from cbb_edge.availability import capture, espn


def _roster():
    return {
        "status": "success",
        "season": {"displayName": "2026-27"},
        "athletes": [
            {
                "id": "111",
                "displayName": "A Guard",
                "jersey": "1",
                "height": 74.0,
                "position": {"abbreviation": "G"},
                "experience": {"abbreviation": "Sr", "years": 4},
                "status": {"type": "active", "name": "Active"},
                "injuries": [],
            },
            {
                "id": "222",
                "displayName": "B Forward",
                "jersey": "22",
                "height": 80.0,
                "position": {"abbreviation": "F"},
                "experience": {"abbreviation": "So", "years": 2},
                "status": {"type": "active", "name": "Active"},
                "injuries": [
                    {"status": "Questionable", "date": "2026-11-20T15:00Z", "shortComment": "ankle"}
                ],
            },
        ],
    }


def test_canonical_status_map_is_preregistered():
    assert espn.canonical_status("Out") == "out"
    assert espn.canonical_status("Day-To-Day") == "day_to_day"
    assert espn.canonical_status("Game-time decision") == "questionable"
    assert espn.canonical_status("Suspended (team rules)") == "suspended"
    assert espn.canonical_status(None) == "unknown"
    assert espn.P_PLAY == {
        "out": 0.0,
        "suspended": 0.0,
        "inactive": 0.0,
        "doubtful": 0.25,
        "questionable": 0.5,
        "probable": 0.85,
        "day_to_day": 0.85,
        "available": 1.0,
        "unknown": 1.0,
    }


def test_parse_roster_rows():
    rows = espn.parse_roster(_roster(), 150)
    by = {r["espn_athlete_id"]: r for r in rows}
    assert by["111"]["status"] == "available" and by["111"]["p_play"] == 1.0
    assert by["111"]["confidence"] == "no_report" and by["111"]["class"] == "Sr"
    assert by["222"]["status"] == "questionable" and by["222"]["p_play"] == 0.5
    assert by["222"]["native_status"] == "Questionable" and by["222"]["player_id"] == "P222"


def test_parse_injury_list_and_box():
    js = {
        "injuries": [
            {
                "team": {"id": "150"},
                "injuries": [
                    {"athlete": {"id": "333", "displayName": "C"}, "status": "Out", "date": "x"}
                ],
            }
        ]
    }
    r = espn.parse_injury_list(js, "espn_league_injuries")
    assert r[0]["status"] == "out" and r[0]["espn_team_id"] == 150
    box = {
        "boxscore": {
            "players": [
                {
                    "team": {"id": "150"},
                    "statistics": [
                        {
                            "athletes": [
                                {"athlete": {"id": "111"}, "starter": True, "didNotPlay": False}
                            ]
                        }
                    ],
                }
            ]
        }
    }
    assert espn.parse_box_participation(box)[0]["starter"] is True


def test_checkpoints():
    assert capture.checkpoint(24 * 60) == "T-24h"
    assert capture.checkpoint(6 * 60) == "T-6h"
    assert capture.checkpoint(90) == "T-90m"
    assert capture.checkpoint(30) == "T-30m"
    assert capture.checkpoint(5) == "latest"
    assert capture.checkpoint(12 * 60) is None


def test_capture_games_change_detection(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    tip = (datetime.now(UTC) + timedelta(minutes=95)).strftime("%Y-%m-%dT%H:%MZ")
    board = {
        "events": [
            {
                "id": "401",
                "date": tip,
                "competitions": [
                    {
                        "status": {"type": {"state": "pre"}},
                        "competitors": [
                            {"homeAway": "home", "id": "150"},
                            {"homeAway": "away", "id": "2"},
                        ],
                    }
                ],
            }
        ]
    }
    calls = {"n": 0}

    def fake(url, params, dest):
        calls["n"] += 1
        if url.endswith("/scoreboard"):
            return board
        if url.endswith("/injuries"):
            return {
                "injuries": [
                    {
                        "team": {"id": "150"},
                        "injuries": [{"athlete": {"id": "111"}, "status": "Out"}],
                    }
                ]
            }
        if url.endswith("/summary"):
            return {}
        return _roster()

    monkeypatch.setattr(capture, "_get_json", fake)
    st = tmp_path / "state" / "s.json"
    res = capture.capture_games(tmp_path, st)
    assert res["games"] == 1 and res["rows"] == 4
    rows = [
        json.loads(x)
        for f in (tmp_path / "captures").rglob("*.jsonl")
        for x in f.read_text().splitlines()
    ]
    a111 = [r for r in rows if r["espn_athlete_id"] == "111" and r["side"] == "home"][0]
    assert a111["status"] == "out" and a111["checkpoint"] == "T-90m"
    assert a111["status_changed"] is False  # first sighting
    # second run: league report gone -> player back to available: a change
    monkeypatch.setattr(
        capture, "_get_json", lambda u, p, d: {} if u.endswith("/injuries") else fake(u, p, d)
    )
    import time

    time.sleep(1.1)
    capture.capture_games(tmp_path, st)
    files = sorted((tmp_path / "captures").rglob("*.jsonl"))
    assert len(files) == 2  # append-only: one file per run
    rows2 = [json.loads(x) for x in files[-1].read_text().splitlines()]
    a = [r for r in rows2 if r["espn_athlete_id"] == "111" and r["side"] == "home"][0]
    assert a["status"] == "available" and a["status_changed"] is True


def test_roster_snapshot_only_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "_get_json", lambda u, p, d: _roster())
    st = tmp_path / "s.json"
    assert capture.capture_rosters(tmp_path, st, teams=[150])["teams_written"] == 1
    import time

    time.sleep(1.1)
    assert capture.capture_rosters(tmp_path, st, teams=[150])["teams_written"] == 0
    time.sleep(1.1)
    assert capture.capture_rosters(tmp_path, st, full=True, teams=[150])["teams_written"] == 1


def test_classify_roster_uses_only_prior_seasons():
    ps = pd.DataFrame(
        {
            "player_id": ["P111", "P222", "P444"],
            "season": [2026, 2026, 2027],
            "team_id": ["T1", "T9", "T1"],
        }
    )
    snap = pd.DataFrame(
        {"player_id": ["P111", "P222", "P333", "P444"], "espn_team_id": [150, 150, 150, 150]}
    )
    c = capture.classify_roster(snap, ps, 2027, {150: "T1"}).set_index("player_id")
    assert c.loc["P111", "roster_class"] == "returning"
    assert c.loc["P222", "roster_class"] == "transfer"
    assert c.loc["P333", "roster_class"] == "new"
    assert c.loc["P444", "roster_class"] == "new"  # 2027 row is not prior history


def test_override_adjuster_and_loader(tmp_path):
    import numpy as np

    from cbb_edge.availability.overlay import load_overrides
    from cbb_edge.players import availability_model as am

    class TS:  # minimal TeamShares stand-in: 3 games, 6 players, all played
        S = np.array([[1.0, 1.0, 1.0, 1.0, 0.5, 0.5]] * 3)
        players = np.array(["P1", "P2", "P3", "P4", "P5", "P6"])

    pids = TS.players
    s = np.array([1.0, 1.0, 1.0, 1.0, 0.5, 0.5])
    pos = {"P1": "G", "P2": "G", "P3": "F", "P4": "F", "P5": "G", "P6": "F"}
    adj = am.AvailabilityAdjuster({}, pos, 0.5, 1.0, mode="override", p_override={(9, "P1"): 0.0})
    assert np.allclose(adj("T", 2027, TS, 3, pids, s, 8), s)  # no report for game 8
    out = adj("T", 2027, TS, 3, pids, s, 9)
    assert abs(out.sum() - 5.0) < 1e-9 and out[0] == 0.0 and (out <= 1.0 + 1e-12).all()
    assert out[4] - 0.5 > out[5] - 0.5  # guard P1's minutes go mostly to guard P5
    assert {c["player_id"] for c in adj.log[(9, "T")]} >= {"P1", "P5", "P6"}
    cap = tmp_path / "captures" / "2026" / "11" / "20"
    cap.mkdir(parents=True)
    rows = [
        {
            "game_id": 9,
            "espn_athlete_id": "1",
            "captured_at": "2026-11-20T10:00:00+00:00",
            "confidence": "reported",
            "p_play": 0.5,
        },
        {
            "game_id": 9,
            "espn_athlete_id": "1",
            "captured_at": "2026-11-20T20:00:00+00:00",
            "confidence": "reported",
            "p_play": 0.0,
        },
        {
            "game_id": 9,
            "espn_athlete_id": "2",
            "captured_at": "2026-11-20T10:00:00+00:00",
            "confidence": "no_report",
            "p_play": 1.0,
        },
    ]
    (cap / "x.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    over, _ = load_overrides(tmp_path, pd.Timestamp("2026-11-20T12:00:00Z"))
    assert over == {(9, "P1"): 0.5}  # later capture not yet known; no_report ignored
    over, _ = load_overrides(tmp_path, pd.Timestamp("2026-11-20T21:00:00Z"))
    assert over == {(9, "P1"): 0.0}
