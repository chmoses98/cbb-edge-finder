"""Wave 9: readiness / observability and the explicit failure states (fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cbb_edge.ops import readiness as R

T = pd.Timestamp
V = ["pure-0.5.0", "pure-0.5.0+roster"]


def _sched():
    return pd.DataFrame({
        "espn_game_id": [1, 2, 3, 4, 5],
        "home_team_id": ["T1", "T3", "T1", "T5", "T1"], "away_team_id": ["T2", "T4", "T3", "T6", "T9"],
        "tip": [T("2026-11-02T23:00Z"), T("2026-11-02T23:30Z"), T("2026-11-05T01:00Z"),
                T("2026-11-05T02:00Z"), T("2026-11-05T05:00Z")],
        "status": ["STATUS_FINAL", "STATUS_FINAL", "STATUS_SCHEDULED", "STATUS_SCHEDULED",
                   "STATUS_SCHEDULED"],
        "home_espn": [1, 3, 1, 5, 1], "away_espn": [2, 4, 3, 6, 999],
    })  # fmt: skip


def _proj(tmp: Path, recs: list[tuple[str, int, str, str]], manifest_as_of: str) -> Path:
    for v, g, asof, tip in recs:
        p = tmp / "pa" / "projections" / v.replace("+", "_") / f"G{g}" / f"{asof[:13]}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"game": {"season": 2027, "espn_game_id": g, "start_time_utc": tip},
                                 "model": {"version": v}, "prospective": {"as_of": asof},
                                 "roster": {"truth_snapshot": "20261101T120000Z"}}))  # fmt: skip
    m = tmp / "pa" / "projections" / "manifests" / "m.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"as_of": manifest_as_of, "files": {}}))
    return tmp / "pa"


def _scores(tmp: Path, rows: list[dict], stamp: str = "2026-11-04T124000Z") -> Path:
    d = tmp / "ps" / "scores" / "2026" / "11" / stamp
    d.mkdir(parents=True)
    pd.DataFrame(rows, columns=["espn_game_id", "status", "reasons"]).to_csv(
        d / "integrity_gate.csv", index=False
    )
    (tmp / "ps" / "LATEST").write_text(f"scores/2026/11/{stamp}\n")
    return tmp / "ps"


def _patch(monkeypatch):
    elig = pd.DataFrame([{"team_id": t, "roster_confidence": c, "valid_expected_rotation": True,
                          "identity_coverage": 1.0, "identity_sufficient": c == "CONFIRMED",
                          "proster_input_substitution": c != "STALE",
                          "proster_continuity_correction": c == "CONFIRMED", "truth_snapshot": "s",
                          "confidence_reason": "", "preseason_expected_returning": 0.5}
                         for t, c in (("T1", "CONFIRMED"), ("T2", "LIKELY"), ("T3", "CONFLICTED"),
                                      ("T4", "STALE"), ("T5", "UNKNOWN"))])  # fmt: skip
    monkeypatch.setattr(R, "team_eligibility", lambda *a, **k: elig)
    monkeypatch.setattr(
        R, "projection_capable", lambda season: {"T1", "T2", "T3", "T4", "T5", "T6"}
    )


def _codes(r):
    return {a["code"] for a in r["alerts"]}


def test_lost_and_broken_observations_raise_critical_alerts(tmp_path, monkeypatch):
    _patch(monkeypatch)
    d1 = {"T1", "T2", "T3", "T4", "T5", "T6"}
    # game 1 (both teams' opener) has only the base record; game 2 has both
    pa = _proj(tmp_path, [("pure-0.5.0", 1, "2026-11-02T14:10:00+00:00", "2026-11-02T23:00:00+00:00"),
                          ("pure-0.5.0", 2, "2026-11-02T14:10:00+00:00", "2026-11-02T23:30:00+00:00"),
                          ("pure-0.5.0+roster", 2, "2026-11-02T14:10:00+00:00", "2026-11-02T23:30:00+00:00")],
               "2026-11-04T21:10:00+00:00")  # fmt: skip
    ps = _scores(tmp_path, [{"espn_game_id": 2, "status": "PENDING", "reasons": ""}])
    now = T("2026-11-04T22:00Z")
    r = R.build(_sched(), tmp_path, pa, ps, now, now, 7, 2027, V, d1, {1, 2, 3, 4, 5, 6, 999})
    c = _codes(r)
    assert "OPENING_GAME_MISSED" in c  # game 1: P-ROSTER-1 never projected it pre-tip
    assert "SETTLED_GAME_NEVER_SCORED" in c  # game 2: final > 36 h ago, still PENDING
    assert "EXPECTED_PROJECTION_MISSING" in c  # game 3 tips within 6 h with no record
    assert "TEAM_ID_UNRESOLVED" in c  # espn 999 is a member without a canonical id
    sev = {a["code"]: a["severity"] for a in r["alerts"]}
    assert (
        sev["OPENING_GAME_MISSED"] == "CRITICAL" and sev["EXPECTED_PROJECTION_MISSING"] == "WARNING"
    )


def test_gate_failures_scorer_and_workflow_staleness(tmp_path, monkeypatch):
    _patch(monkeypatch)
    pa = _proj(tmp_path, [], "2026-11-03T21:10:00+00:00")
    ps = _scores(tmp_path, [
        {"espn_game_id": 7, "status": "INVALID", "reasons": "truth_snapshot_not_before_as_of_and_tip"},
        {"espn_game_id": 8, "status": "INVALID", "reasons": "roster_hash_mismatch_vs_manifest"},
        {"espn_game_id": 9, "status": "INVALID", "reasons": "base_duplicate_record_differs"},
        {"espn_game_id": 10, "status": "INVALID", "reasons": "roster_archived_file_mutated"},
    ], stamp="2026-11-01T124000Z")  # fmt: skip
    now = T("2026-11-04T18:00Z")  # the 14:10 slot owed for 3 h 50 min; scorer silent 3 days
    r = R.build(_sched().iloc[0:0], tmp_path, pa, ps, now, now, 7, 2027, V, set(), None)
    c = _codes(r)
    for code in ("POST_TIP_SNAPSHOT_SELECTED", "HASH_MISMATCH", "DUPLICATE_RECORD_DIFFERS",
                 "ARCHIVE_FILE_MUTATED", "SCORER_NOT_RUNNING", "WORKFLOW_STALE"):  # fmt: skip
        assert code in c, code


def test_readiness_answers_and_tbd_tips(tmp_path, monkeypatch):
    _patch(monkeypatch)
    now = T("2026-10-06T04:00Z")
    r = R.build(_sched(), tmp_path, None, None, now, T("2026-11-02T00:00Z"), 7, 2027, V,
                {"T1", "T2", "T3", "T4", "T5", "T6"}, None)  # fmt: skip
    rd = r["readiness"].set_index("team_id")
    assert set(rd["roster_confidence"].dropna()) == {
        "CONFIRMED",
        "LIKELY",
        "CONFLICTED",
        "STALE",
        "UNKNOWN",
    }
    assert (
        rd.loc["T4", "proster_input_substitution"] is False
        or not rd.loc["T4", "proster_input_substitution"]
    )
    assert rd.loc["T6", "currently_unscorable"] and "no roster truth row" in rd.loc["T6", "why"]
    assert R.tip_tbd(T("2026-11-05T05:00Z")) and not R.tip_tbd(T("2026-11-05T01:00Z"))
    assert "1-8. Readiness" in R.markdown(r) and not [
        a for a in r["alerts"] if a["severity"] == "CRITICAL"
    ]


def test_game_missing_from_schedule_source_is_never_silent(tmp_path, monkeypatch):
    """Wave 10: a D-I game the live scoreboard lists but SDV does not (SDV lag) cannot be
    projected; it must appear in the readiness table and raise an alert (CRITICAL
    within 30 h of tip)."""
    from cbb_edge.data.ids import teams

    _patch(monkeypatch)
    monkeypatch.setattr(
        teams, "canonical_from_espn_in", lambda e, s: {1: "T1", 2: "T2", 5: "T5"}.get(e)
    )
    obs = pd.DataFrame([
        {"espn_game_id": g, "observed_at": T("2026-11-02T03:00Z"), "source": "espn_scoreboard",
         "start_utc": tip, "date_et": tip[:10], "time_valid": True, "time_state": "ANNOUNCED",
         "state": "pre", "status_name": st, "short_detail": "", "home_espn": 1, "away_espn": h}
        for g, tip, h, st in ((77, "2026-11-02T23:00:00+00:00", 2, "STATUS_SCHEDULED"),
                              (78, "2026-11-08T23:00:00+00:00", 5, "STATUS_SCHEDULED"),
                              (79, "2026-11-02T23:00:00+00:00", 2, "STATUS_POSTPONED"))])  # fmt: skip
    now = T("2026-11-02T03:00Z")
    r = R.build(_sched(), tmp_path, None, None, now, now, 7, 2027, V,
                {"T1", "T2", "T3", "T4", "T5", "T6"}, None, None, obs)  # fmt: skip
    a = {x["code"]: x for x in r["alerts"]}
    assert a["GAME_MISSING_FROM_SCHEDULE_SOURCE_IMMINENT"]["espn_game_id"] == 77
    assert a["GAME_MISSING_FROM_SCHEDULE_SOURCE"]["espn_game_ids"] == [78]
    g = r["games"].set_index("espn_game_id")
    assert (
        not g.loc[77, "in_schedule_source"]
        and "absent from both projection schedule sources" in g.loc[77, "why"]
    )
    assert 79 not in g.index  # postponed: not owed
    assert "ABSENT from both projection sources" in R.markdown(r)
