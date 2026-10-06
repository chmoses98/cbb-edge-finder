"""Wave 9: catch-up cadence for missed / delayed / duplicate GitHub cron ticks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from cbb_edge.ops import cadence as C

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "prospective"))
import refresh_and_project as rp  # noqa: E402

T = pd.Timestamp


def test_last_slot_and_owed():
    s = C.PROJECTION_SLOTS
    assert C.last_slot(T("2026-11-02T13:00Z"), s) == T("2026-11-01T21:10Z")
    assert C.last_slot(T("2026-11-02T14:10Z"), s) == T("2026-11-02T14:10Z")
    assert C.last_slot(T("2026-11-02T23:59Z"), s) == T("2026-11-02T21:10Z")
    # the 14:10 tick never arrived: the 14:40 catch-up tick sees the slot owed
    assert C.slot_owed(T("2026-11-01T21:10Z"), T("2026-11-02T14:40Z"), s)
    # the slot was served (a run manifest at 14:52, delayed tick): later ticks skip
    assert not C.slot_owed(T("2026-11-02T14:52Z"), T("2026-11-02T15:40Z"), s)
    assert C.slot_owed(None, T("2026-11-02T15:40Z"), s)  # never ran at all
    # weekly roster slot (Mondays 12:17): a Wednesday tick owes Monday's slot if missed
    wk = dict(weekday=0, months=(12, 1, 2, 3, 4))
    assert C.last_slot(T("2026-12-09T10:00Z"), C.ROSTER_SLOTS_WEEKLY, **wk) == T(
        "2026-12-07T12:17Z"
    )
    assert not C.slot_owed(
        T("2026-12-07T13:00Z"), T("2026-12-09T10:00Z"), C.ROSTER_SLOTS_WEEKLY, **wk
    )


def _sched():
    return pd.DataFrame({
        "espn_game_id": [1, 2, 3, 4, 5],
        "home_team_id": ["T1", "T1", "T1", "T1", "T1"],
        "away_team_id": ["T2", "T2", "T9", "T2", "T2"],  # T9: not D-I
        "tip": [T("2026-11-02T18:00Z"), T("2026-11-03T23:00Z"), T("2026-11-02T19:00Z"),
                T("2026-11-02T20:00Z"), T("2026-11-02T12:00Z")],  # 5 already tipped
        "status": ["STATUS_SCHEDULED", "STATUS_SCHEDULED", "STATUS_SCHEDULED",
                   "STATUS_CANCELED", "STATUS_FINAL"],
    })  # fmt: skip


def test_coverage_gaps_only_future_d1_games_in_horizon():
    have = {("pure-0.5.0", 1)}
    gaps = C.coverage_gaps(_sched(), have, T("2026-11-02T14:40Z"), 30.0,
                           ["pure-0.5.0", "pure-0.5.0+roster"], {"T1", "T2"})  # fmt: skip
    # game 1 lacks only the roster version; 2 is beyond 30 h; 3 non-D-I; 4 cancelled;
    # 5 already tipped -> never owed (no post-tip reconstruction)
    assert gaps == [("pure-0.5.0+roster", 1)]


def _archive(tmp: Path, as_of: str, recs: list[tuple[str, int]]) -> Path:
    a = tmp / "pa" / "projections"
    for v, g in recs:
        p = a / v.replace("+", "_") / "2027" / "x" / f"G{g}" / "s.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"game": {"season": 2027, "espn_game_id": g,
                                          "start_time_utc": "2026-11-02T18:00:00+00:00"},
                                 "model": {"version": v}, "prospective": {"as_of": as_of}}))  # fmt: skip
    m = a / "manifests" / "m.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"as_of": as_of, "files": {}}))
    return tmp / "pa"


def test_decide_projections_full_missing_only_or_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "required_versions", lambda ok: ["pure-0.5.0", "pure-0.5.0+roster"])
    d1 = {"T1", "T2"}
    # slot served at 14:12 and game 1 fully covered -> the 14:40 and 15:40 ticks skip
    pa = _archive(
        tmp_path, "2026-11-02T14:12:00+00:00", [("pure-0.5.0", 1), ("pure-0.5.0+roster", 1)]
    )
    d = C.decide_projections(pa, _sched(), T("2026-11-02T15:40Z"), 30.0, d1, True)
    assert (d["due"], d["mode"]) == (False, "skip")
    # the 21:10 slot passes without a run: the 21:40 tick runs in full
    d = C.decide_projections(pa, _sched(), T("2026-11-02T21:40Z"), 30.0, d1, True)
    assert d["mode"] == "full"
    # served slot, but the roster version of game 1 is missing -> only that record
    pa2 = _archive(tmp_path / "b", "2026-11-02T14:12:00+00:00", [("pure-0.5.0", 1)])
    d = C.decide_projections(pa2, _sched(), T("2026-11-02T15:40Z"), 30.0, d1, True)
    assert d["mode"] == "missing_only" and d["gap_pairs"] == ["pure-0.5.0+roster|1"]
    # a duplicate tick right after: the same facts -> the same decision, never "full"
    assert (
        C.decide_projections(pa2, _sched(), T("2026-11-02T15:41Z"), 30.0, d1, True)["mode"]
        == "missing_only"
    )
    # off-season: no slot owed
    assert (
        C.decide_projections(pa, _sched().iloc[0:0], T("2026-10-06T15:40Z"), 30.0, d1, True)["mode"]
        == "skip"
    )


def test_decide_scores_and_rosters(tmp_path):
    sc = tmp_path / "ps"
    sc.mkdir()
    (sc / "LATEST").write_text("scores/2026/11/2026-11-02T124500Z\n")
    assert not C.decide_scores(sc, T("2026-11-02T15:50Z"))["due"]
    assert C.decide_scores(sc, T("2026-11-03T13:50Z"))["due"]  # 11-03 12:40 slot missed
    ra = tmp_path / "ra" / "truth" / "2026" / "11" / "02"
    ra.mkdir(parents=True)
    (ra / "20261102T111900Z_records.jsonl").write_text("")
    assert not C.decide_rosters(tmp_path / "ra", T("2026-11-02T15:47Z"))["due"]
    assert C.decide_rosters(tmp_path / "ra", T("2026-11-03T11:47Z"))["due"]


def test_catch_up_writes_only_missing_records_and_a_heartbeat(tmp_path, monkeypatch):
    def fake_window(season, now, h, model=None, **kw):
        return [{"game": {"espn_game_id": g, "game_id": f"G{g}", "season": 2027,
                          "start_time_utc": "2026-11-03T00:00:00+00:00"},
                 "model": {"version": model["version"]},
                 "prospective": {"as_of": now.isoformat()}} for g in (1, 2)]  # fmt: skip

    monkeypatch.setattr(rp, "active_models", lambda: {"incumbent": "pure-0.2.0",
                                                      "challengers": ["pure-0.5.0"]})  # fmt: skip
    monkeypatch.setattr(rp, "load_model", lambda v: {"version": v, "extra_blocks": []})
    monkeypatch.setattr(rp, "project_window", fake_window)
    now = T("2026-11-02T14:40Z")
    rp.project_all(2027, now, 30.0, tmp_path / "o", None, None, "sha", None,
                   only={("pure-0.5.0", 2)})  # fmt: skip
    files = [p for p in (tmp_path / "o").rglob("*.json") if "manifests" not in p.parts]
    assert len(files) == 1 and "G2" in str(files[0]) and "pure-0.5.0" in str(files[0])
    # a run with no game in its window still leaves its heartbeat manifest
    monkeypatch.setattr(rp, "project_window", lambda *a, **k: [])
    rp.project_all(2027, T("2026-11-02T21:10Z"), 30.0, tmp_path / "e", None, None, "sha", None)
    m = list((tmp_path / "e" / "manifests").glob("*.json"))
    assert len(m) == 1 and json.loads(m[0].read_text())["files"] == {}
    assert C.last_manifest(tmp_path / "e") == T("2026-11-02T21:10Z")
