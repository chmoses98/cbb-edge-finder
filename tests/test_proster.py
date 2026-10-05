"""P-ROSTER-1 overlay spec, snapshot timing, scorecards (Wave 6)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.rosters import overlay, scorecard

REPO = Path(__file__).resolve().parents[1]
P_ROSTER_SHA = json.loads((REPO / "models" / "overlays" / "p-roster-1.json").read_text())["sha256"]


def test_overlay_spec_hash_pinned_and_market_free():
    spec = overlay.load_spec()
    assert spec["sha256"] == P_ROSTER_SHA
    assert spec["market_inputs"] == "NONE" and spec["base_version"] == "pure-0.5.0"
    assert spec["component_b"]["features"] == ["dcont", "tr_prev", "first_d1"]
    body = json.loads((REPO / "models" / "overlays" / "p-roster-1.json").read_text())
    sha = body.pop("sha256")
    assert sha == hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def test_latest_truth_is_strictly_before_as_of(tmp_path):
    d = tmp_path / "truth" / "2026" / "11" / "01"
    d.mkdir(parents=True)
    for stamp in ("20261101T110000Z", "20261101T170000Z"):
        pd.DataFrame(
            [{"player_id": "P1", "team_id": "T1", "status": "LIKELY", "stamp": stamp}]
        ).to_json(d / f"{stamp}_records.jsonl", orient="records", lines=True)
        (d / f"{stamp}_teams.json").write_text(
            json.dumps([{"team_id": "T1", "roster_confidence": "LIKELY"}])
        )
    got = overlay.latest_truth(tmp_path, pd.Timestamp("2026-11-01T17:00:00Z"))
    assert got is not None and got[2] == "20261101T110000Z"  # the 17:00 snapshot is not < as_of
    assert overlay.latest_truth(tmp_path, pd.Timestamp("2026-11-01T10:00:00Z")) is None


def test_rotation_scorecard_uses_only_snapshots_before_each_cut(tmp_path):
    d = tmp_path / "truth" / "2026" / "11" / "01"
    d.mkdir(parents=True)
    tip = pd.Timestamp("2026-11-03T00:00:00Z")
    early = [{"team_id": "T1", "roster_confidence": "LIKELY",
              "expected_rotation": [{"player_id": f"P{i}", "share": 0.5, "class": "returning"}
                                    for i in range(10)]}]  # fmt: skip
    late = [{"team_id": "T1", "roster_confidence": "CONFIRMED",
             "expected_rotation": [{"player_id": f"Q{i}", "share": 0.5, "class": "returning"}
                                   for i in range(10)]}]  # fmt: skip
    (d / "20261025T120000Z_proster_state.json").write_text(json.dumps(early))  # T-8d
    (d / "20261103T120000Z_proster_state.json").write_text(json.dumps(late))  # after tip
    box = pd.DataFrame({"espn_game_id": 1, "team_id": "T1", "player_id": [f"P{i}" for i in range(8)],
                        "minutes": [30, 30, 30, 30, 30, 20, 15, 15.0],
                        "starter": [True] * 5 + [False] * 3})  # fmt: skip
    first = pd.DataFrame({"team_id": ["T1"], "espn_game_id": [1], "tip": [tip]})
    sc = scorecard.rotation_scorecard(tmp_path, first, box)
    assert set(sc["snapshot"]) == set(scorecard.OFFSETS)
    # every snapshot is the pre-tip state; the post-game state never leaks in
    assert (sc["roster_confidence"] == "LIKELY").all()
    assert (sc["snapshot_ts"] == pd.Timestamp("2026-10-25T12:00:00Z").isoformat()).all()


def test_model_monitor_latest_pregame_record():
    def rec(v, asof, margin, gs=0):
        return {"model": {"version": v}, "game": {"espn_game_id": 7, "start_time_utc": "2026-11-03T00:00:00Z"},
                "prospective": {"as_of": asof}, "projection": {"margin": margin, "total": 140.0,
                                                              "home_win_prob": 0.6},
                "freshness": {"home_games_seen": gs, "away_games_seen": gs}}  # fmt: skip

    recs = [rec("pure-0.5.0", "2026-11-02T10:00:00Z", 1.0), rec("pure-0.5.0", "2026-11-02T20:00:00Z", 3.0),
            rec("pure-0.5.0", "2026-11-03T01:00:00Z", 99.0)]  # post-tip record ignored  # fmt: skip
    res = pd.DataFrame({"espn_game_id": [7], "result_margin": [5.0], "result_total": [150.0]})
    m = scorecard.model_monitor(recs, res)
    assert m["pure-0.5.0"]["all"]["n"] == 1
    assert np.isclose(m["pure-0.5.0"]["all"]["margin_rmse"], 2.0)
    assert np.isclose(m["pure-0.5.0"]["game_1"]["total_rmse"], 10.0)


def test_false_inclusion_counts_departed_players_in_base_and_roster(tmp_path):
    d = tmp_path / "truth" / "2026" / "10" / "25"
    d.mkdir(parents=True)
    st = [{"team_id": "T1", "roster_confidence": "CONFIRMED",
           "expected_rotation": [{"player_id": p, "share": 1.0} for p in ("A", "B", "C", "D", "N")]}]  # fmt: skip
    (d / "20261025T120000Z_proster_state.json").write_text(json.dumps(st))
    hist = pd.DataFrame({"player_id": ["A", "B", "C", "D", "X"], "role_season": [2026] * 5,
                         "role_team": ["T1"] * 5, "min_share": [1.0, 1.0, 1.0, 1.0, 1.0],
                         "usage_share": [0.05] * 5, "rapm_net": [2.0] * 5})  # fmt: skip
    box5 = pd.DataFrame({"espn_game_id": 1, "team_id": "T1",
                         "player_id": ["A", "B", "C", "D", "N"], "minutes": [40.0] * 5})  # fmt: skip
    first = pd.DataFrame({"team_id": ["T1"], "espn_game_id": [1],
                          "tip": [pd.Timestamp("2026-11-03T00:00:00Z")]})  # fmt: skip
    fi = scorecard.false_inclusion(tmp_path, first, box5, hist, 2027)
    base = fi[fi["rotation"] == "BASE"].iloc[0]
    assert base["false_players"] == 1 and base["false_minutes"] == 40.0  # X left the team
    assert np.isclose(base["false_value"], 2.0) and np.isclose(base["omitted_minutes_share"], 0.2)
    ro = fi[fi["rotation"] == "ROSTER"]
    assert set(ro["snapshot"]) == set(scorecard.OFFSETS) and (ro["false_players"] == 0).all()
