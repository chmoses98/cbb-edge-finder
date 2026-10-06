"""Wave 10: unknown tip times (ESPN "TBD" placeholders), game-start safety and the gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from cbb_edge.app import prospective as P
from cbb_edge.ops import cadence as C
from cbb_edge.ops import schedule_state as S
from cbb_edge.rosters import prospective_score as ps
from tests.test_pretip_gate import archive, rec, results, roster_archive, status

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "prospective"))
import refresh_and_project as rp  # noqa: E402

T = pd.Timestamp
PLACE = "2026-11-03T05:00:00+00:00"  # 00:00 ET Nov 3 (ESPN placeholder for "TBD")


def obs(gid, at, state="pre", name="STATUS_SCHEDULED", start=PLACE, tv=False, detail="11/3 - TBD"):
    return {"espn_game_id": gid, "observed_at": T(at).isoformat(), "source": "espn_scoreboard",
            "start_utc": T(start).isoformat(), "date_et": T(start).tz_convert(S.ET).date().isoformat(),
            "time_valid": tv, "time_state": S.time_state(tv, start, detail), "state": state,
            "status_name": name, "short_detail": detail, "home_espn": 1, "away_espn": 2}  # fmt: skip


# --------------------------------------------------------------- A. classification
def test_time_state_classification_from_pregame_metadata():
    assert S.time_state(True, "2026-11-03T00:00:00Z", "11/2 - 7:00 PM EST") == S.ANNOUNCED
    # a genuinely announced midnight-ET game (e.g. a late Hawaii tip) is ANNOUNCED
    assert S.time_state(True, "2026-11-03T05:00:00Z", "11/3 - 12:00 AM EST") == S.ANNOUNCED
    assert S.time_state(False, PLACE, "11/3 - TBD") == S.TBD
    assert S.time_state(False, PLACE, "Postponed") == S.PLACEHOLDER
    assert S.time_state(None, PLACE, None) == S.UNKNOWN
    assert S.time_state("false", PLACE, "TBD") == S.TBD


def test_game_state_is_fail_closed():
    assert S.not_started("pre", "STATUS_SCHEDULED")
    for st, name in (("in", "STATUS_IN_PROGRESS"), ("in", "STATUS_HALFTIME"),
                     ("post", "STATUS_FINAL"), ("post", "STATUS_POSTPONED"),
                     ("post", "STATUS_CANCELED"), ("pre", "STATUS_DELAYED"),
                     (None, None), ("pre", None)):  # fmt: skip
        assert S.may_have_started(st, name), (st, name)


def test_parse_scoreboard_event():
    js = {"events": [{"id": "401912207", "date": "2026-11-03T05:00Z", "competitions": [{
        "date": "2026-11-03T05:00Z", "timeValid": False,
        "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED", "shortDetail": "11/3 - TBD"}},
        "competitors": [{"homeAway": "home", "id": "2000"}, {"homeAway": "away", "id": "5"}]}]}]}  # fmt: skip
    (o,) = S.parse_scoreboard(js, "2026-11-02T14:11:00+00:00")
    assert o["espn_game_id"] == 401912207 and o["time_state"] == S.TBD and o["state"] == "pre"
    assert o["date_et"] == "2026-11-03" and o["home_espn"] == 2000


# ------------------------------------------------------- B/D. the live window
def _listed(*gid_tip):
    return pd.DataFrame(
        {"espn_game_id": [g for g, _ in gid_tip], "tip": [T(t) for _, t in gid_tip]}
    )


def test_live_window_extra_exclude_unprotected():
    now = T("2026-11-03T14:10Z")  # 09:10 ET on game day; every placeholder has passed
    listed = _listed((1, PLACE), (2, PLACE), (3, PLACE), (4, PLACE), (5, PLACE),
                     (6, "2026-11-03T23:00Z"))  # fmt: skip
    live = [
        obs(1, "2026-11-03T14:11Z"),  # TBD, still pre -> projectable (extra)
        obs(2, "2026-11-03T14:11Z", "in", "STATUS_IN_PROGRESS"),  # began under placeholder
        obs(
            3, "2026-11-03T14:11Z", start="2026-11-03T23:30Z", tv=True, detail="7:30 PM"
        ),  # announced later
        obs(4, "2026-11-03T14:11Z", "post", "STATUS_POSTPONED"),  # postponed
        obs(6, "2026-11-03T14:11Z", start="2026-11-03T23:00Z", tv=True, detail="7:00 PM"),
    ]  # game 5: no live observation (fetch failed)
    w = S.live_window(live, now, 30.0, listed)
    assert w["extra"] == {1, 3}
    assert w["exclude"] == {2, 4}
    assert w["unprotected"] == {5}  # never projected without evidence (fail closed)
    # a TBD game on a date beyond the horizon is not pulled in early
    far = S.live_window([obs(7, "2026-11-03T14:11Z", start="2026-11-08T05:00Z")], now, 30.0,
                        _listed((7, "2026-11-01T05:00Z")))  # fmt: skip
    assert far["extra"] == set()


def test_select_window_override_is_scoped_and_frozen_by_default():
    df = pd.DataFrame({"game_id": [1, 2, 3], "start_time_utc": [T(PLACE), T("2026-11-03T23:00Z"),
                                                               T("2026-11-03T23:30Z")]})  # fmt: skip
    as_of, end = T("2026-11-03T14:10Z"), T("2026-11-04T20:10Z")
    assert list(P.select_window(df, as_of, end)["game_id"]) == [2, 3]  # frozen rule
    with P.window_override(extra={1}, exclude={3}):
        assert list(P.select_window(df, as_of, end)["game_id"]) == [1, 2]
    assert list(P.select_window(df, as_of, end)["game_id"]) == [2, 3]  # restored


def _fake_window(season, now, h, model=None, **kw):
    df = pd.DataFrame({"game_id": [1, 2, 6], "start_time_utc": [T(PLACE), T(PLACE),
                                                               T("2026-11-03T23:00Z")]})  # fmt: skip
    win = P.select_window(df, now, now + pd.Timedelta(hours=h))
    return [{"game": {"espn_game_id": int(g), "game_id": f"G{g}", "season": 2027,
                      "start_time_utc": t.isoformat()},
             "model": {"version": model["version"]}, "prospective": {"as_of": now.isoformat()}}
            for g, t in zip(win["game_id"], win["start_time_utc"], strict=True)]  # fmt: skip


def test_production_step_never_projects_a_started_game(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "active_models", lambda: {"incumbent": "pure-0.5.0", "challengers": []})
    monkeypatch.setattr(rp, "load_model", lambda v: {"version": v, "extra_blocks": []})
    monkeypatch.setattr(rp, "project_window", _fake_window)
    games = tmp_path / "silver"
    games.mkdir()
    pd.DataFrame({"season": 2027, "game_id": [1, 2, 6], "start_time_utc": [T(PLACE), T(PLACE),
                  T("2026-11-03T23:00Z")]}).to_parquet(games / "games.parquet")  # fmt: skip
    monkeypatch.setattr(rp, "data_dir", lambda: tmp_path)
    now = T("2026-11-03T14:10Z")
    live = [obs(1, "2026-11-03T14:11Z"), obs(2, "2026-11-03T14:11Z", "in", "STATUS_IN_PROGRESS"),
            obs(6, "2026-11-03T14:11Z", start="2026-11-03T23:00Z", tv=True, detail="7 PM")]  # fmt: skip
    out, _ = rp.project_all(2027, now, 30.0, tmp_path / "o", None, None, "sha", None, None, live)
    files = {p.parent.name for p in (tmp_path / "o").rglob("*.json") if "manifests" not in p.parts}
    assert files == {"G1", "G6"}  # G2 began while the schedule still showed the placeholder
    assert out["_schedule_window"] == {
        "tbd_extra": 1,
        "live_excluded": 1,
        "unprotected_no_live_evidence": 0,
    }
    import json

    r1 = json.loads(next((tmp_path / "o").rglob("G1/*.json")).read_text())
    assert r1["schedule"]["window"] == "tbd_extra" and r1["schedule"]["live"]["state"] == "pre"
    assert list((tmp_path / "o" / "schedule_obs").glob("*.jsonl"))  # the run's evidence
    # live fetch failed entirely: nothing beyond the frozen rule, nothing started
    out2, _ = rp.project_all(2027, now, 30.0, tmp_path / "o2", None, None, "sha", None, None, [])
    files2 = {
        p.parent.name for p in (tmp_path / "o2").rglob("*.json") if "manifests" not in p.parts
    }
    assert files2 == {"G6"} and out2["_schedule_window"]["unprotected_no_live_evidence"] == 2


# ------------------------------------------------------------- G. catch-up
def _sched():
    return pd.DataFrame({"espn_game_id": [1, 2, 6], "home_team_id": "T1", "away_team_id": "T2",
                         "tip": [T(PLACE), T(PLACE), T("2026-11-03T23:00Z")],
                         "status": "STATUS_SCHEDULED"})  # fmt: skip


def test_catch_up_owes_tbd_games_while_pre_and_never_after_start():
    v = ["pure-0.5.0"]
    now = T("2026-11-03T18:40Z")  # several hourly ticks and a regular slot were missed
    live = S.live_window([obs(1, "2026-11-03T18:41Z"), obs(2, "2026-11-03T18:41Z", "post", "STATUS_FINAL")],
                         now, 30.0, _sched()[["espn_game_id", "tip"]])  # fmt: skip
    gaps = C.coverage_gaps(_sched(), set(), now, 30.0, v, {"T1", "T2"}, live)
    assert gaps == [("pure-0.5.0", 1), ("pure-0.5.0", 6)]  # 2 already final: never owed
    # without live evidence the placeholder-passed TBD games are not owed (fail closed)
    assert C.coverage_gaps(_sched(), set(), now, 30.0, v, {"T1", "T2"}, None) == [("pure-0.5.0", 6)]


# ------------------------------------------------------------------ E. the gate
def _games(time_state, tip):
    return pd.DataFrame({"espn_game_id": [1], "home_team_id": ["T1"], "away_team_id": ["T2"],
                         "tip": [T(tip)], "time_state": [time_state]})  # fmt: skip


def _score(pa, ra, games, schedule_obs):
    recs = ps.load_records(pa, 2027)
    return ps.score(recs, results(1), roster_archive=ra, games=games,
                    committed=ps.git_first_commit_times(pa),
                    committed_roster=ps.git_first_commit_times(ra), projections_root=pa,
                    expected=pd.DataFrame({"espn_game_id": [1]}), schedule_obs=schedule_obs)  # fmt: skip


def _recs(ra, asof, tip=PLACE):
    return [rec(ps.BASE, 1, "T1", "T2", 2.0, ra, asof=asof, tip=tip),
            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra, asof=asof, tip=tip)]  # fmt: skip


def test_tbd_record_after_placeholder_valid_once_tip_is_announced(tmp_path):
    """Tip announced late (7:30 PM ET): the record made on game day while the listing
    still showed the placeholder is pre-tip against the announced time."""
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, _recs(ra, "2026-11-03T14:10:00+00:00"), when="2026-11-03T14:16:00+00:00")
    frames, _ = _score(pa, ra, _games(S.ANNOUNCED, "2026-11-04T00:30:00Z"), None)
    assert status(frames, 1) == ("VALID", "")


def test_tip_moved_earlier_or_later(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, _recs(ra, "2026-11-03T14:10:00+00:00"), when="2026-11-03T14:16:00+00:00")
    # moved earlier than the record (announced 12:00 ET = 17:00Z, record at 14:10Z): VALID
    assert (
        status(_score(pa, ra, _games(S.ANNOUNCED, "2026-11-03T17:00:00Z"), None)[0], 1)[0]
        == "VALID"
    )
    # moved earlier than the record itself (09:00 ET = 14:00Z): not pre-tip -> UNSCORABLE
    assert (
        status(_score(pa, ra, _games(S.ANNOUNCED, "2026-11-03T14:00:00Z"), None)[0], 1)[0]
        == "UNSCORABLE"
    )


def test_never_announced_tip_needs_proof_or_is_unscorable(tmp_path):
    ra = roster_archive(tmp_path)
    late = "2026-11-03T14:10:00+00:00"  # after the placeholder, while live state was pre
    pa = archive(tmp_path, _recs(ra, late), when="2026-11-03T14:16:00+00:00")
    g = _games(S.TBD, PLACE)  # the FINAL listing never announced a time
    # no live observation after the record: cannot know it was pre-start -> UNSCORABLE
    st, why = status(_score(pa, ra, g, S.load_obs())[0], 1)
    assert st == "UNSCORABLE" and why == "tbd_start_unprovable"
    # a live "pre" observation AFTER the record's push proves it: VALID
    o = pd.DataFrame(
        [obs(1, "2026-11-03T15:25Z"), obs(1, "2026-11-04T01:25Z", "post", "STATUS_FINAL")]
    )
    o["observed_at"] = pd.to_datetime(o["observed_at"], utc=True)
    assert status(_score(pa, ra, g, o)[0], 1) == ("VALID", "")
    # the record exists by 14:10 but was pushed 14:16; the last "pre" is 14:12, the next
    # observation shows the game in progress: the push may be after the start
    o2 = pd.DataFrame(
        [obs(1, "2026-11-03T14:12Z"), obs(1, "2026-11-03T15:25Z", "in", "STATUS_IN_PROGRESS")]
    )
    o2["observed_at"] = pd.to_datetime(o2["observed_at"], utc=True)
    st, why = status(_score(pa, ra, g, o2)[0], 1)
    assert (st, why) == ("UNSCORABLE", "tbd_start_unprovable")


def test_record_before_the_placeholder_is_provably_pre_start(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, _recs(ra, "2026-11-02T21:10:00+00:00"), when="2026-11-02T21:16:00+00:00")
    frames, _ = _score(pa, ra, _games(S.TBD, PLACE), S.load_obs())
    assert status(frames, 1) == ("VALID", "")  # a game cannot start before its date


def test_delayed_run_after_start_adds_nothing_and_earlier_record_counts(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, _recs(ra, "2026-11-02T21:10:00+00:00"), when="2026-11-02T21:16:00+00:00")
    # an Actions run delayed past the start would have been excluded by the live check;
    # a record that somehow exists after the start never counts
    late = [rec(ps.ROSTER, 1, "T1", "T2", 9.0, ra, asof="2026-11-04T01:00:00+00:00")]
    archive(tmp_path, late, when="2026-11-04T01:06:00+00:00")
    frames, s = _score(pa, ra, _games(S.ANNOUNCED, "2026-11-04T00:30:00Z"), None)
    assert status(frames, 1) == ("VALID", "")
    assert frames["paired_games"].iloc[0]["roster_margin"] == 3.0  # the pre-tip record


def test_tip_history_records_every_change(tmp_path):
    o = [obs(1, "2026-10-06T05:00Z"), obs(1, "2026-10-20T05:00Z"),
         obs(1, "2026-10-28T05:00Z", start="2026-11-04T00:30Z", tv=True, detail="7:30 PM EST"),
         obs(1, "2026-11-04T01:00Z", "in", "STATUS_IN_PROGRESS", start="2026-11-04T00:30Z", tv=True)]  # fmt: skip
    S.write_obs(tmp_path, o[:2], "20261020T050000Z", "espn_scoreboard")
    S.write_obs(tmp_path, o[2:], "20261104T010000Z", "espn_scoreboard")
    try:
        S.write_obs(tmp_path, o, "20261104T010000Z", "espn_scoreboard")
        raise AssertionError("append-only archive overwritten")
    except FileExistsError:
        pass
    h = S.history(S.load_obs(tmp_path)).iloc[0]
    assert (
        h["first_time_state"] == S.TBD and h["ever_tbd"] and h["latest_time_state"] == S.ANNOUNCED
    )
    assert h["final_announced_tip"] == T("2026-11-04T00:30Z").isoformat()
    assert h["announced_first_seen"] == T("2026-10-28T05:00Z").isoformat()
    assert [c["time_state"] for c in h["changes"]] == [S.TBD, S.ANNOUNCED, S.ANNOUNCED]
    assert h["last_pre_observed"] == T("2026-10-28T05:00Z").isoformat()
    assert h["first_started_observed"] == T("2026-11-04T01:00Z").isoformat()


def test_archive_keeps_changes_and_gate_evidence_only(tmp_path):
    """Hourly observation stays bounded: unchanged rows are dropped except the
    not-started evidence for unannounced games whose date has arrived."""
    now = T("2026-11-03T15:00Z")
    first = [obs(1, "2026-11-01T15:00Z"), obs(9, "2026-11-01T15:00Z", start="2026-11-08T05:00Z"),
             obs(6, "2026-11-01T15:00Z", start="2026-11-03T23:00Z", tv=True, detail="7 PM")]  # fmt: skip
    S.write_obs(tmp_path, S.thin(first, S.load_obs(tmp_path), now), "20261101T150000Z", "x")
    again = [dict(o, observed_at=now.isoformat()) for o in first]
    kept = S.thin(again, S.load_obs(tmp_path), now)
    assert [o["espn_game_id"] for o in kept] == [1]  # game-day TBD: evidence kept
    moved = [dict(again[1], start_utc="2026-11-09T01:00:00+00:00", time_valid=True,
                  time_state=S.ANNOUNCED)]  # fmt: skip
    assert S.thin(moved, S.load_obs(tmp_path), now) == moved  # a time change is always kept
    # rows round-tripped through the archive compare equal (no NaN/None churn)
    sdv = [dict(o, source="sdv_schedule", state=None, status_name=None) for o in first]
    S.write_obs(tmp_path, sdv, "20261101T160000Z", "sdv_schedule")
    assert (
        S.thin([dict(o, observed_at=now.isoformat()) for o in sdv], S.load_obs(tmp_path), now) == []
    )


def test_observe_cli_archives_scoreboard_even_if_sdv_fails(tmp_path, monkeypatch, capsys):
    import json

    from cbb_edge.data.bronze import sportsdataverse as sdv
    from tests.espn_fixtures import event, payload

    js = payload(event(1, "2026-11-03T05:00Z", 11, 12, tv=False, detail="TBD"))
    monkeypatch.setattr(
        S, "fetch_scoreboard_raw", lambda dates, stamp: ([(js, "2026-11-03T14:11:00+00:00")], [])
    )

    def boom(*a, **k):
        raise FileNotFoundError("no sidecar")

    monkeypatch.setattr(sdv, "download_live", boom)
    monkeypatch.setattr(sys, "argv", ["x", "observe", "--archive", str(tmp_path / "sa"), "--sdv",
                                      "--full-out", str(tmp_path / "run")])  # fmt: skip
    S.main()
    out = json.loads(capsys.readouterr().out)
    assert out["scoreboard_archived"] == 1 and out["sdv_error"].startswith("FileNotFoundError")
    assert len(S.load_obs(tmp_path / "sa")) == 1 and len(S.load_obs(tmp_path / "run")) == 1
    from cbb_edge.ops import schedule_completion as sc

    assert out["schedule_rows_archived"] == 1 and len(sc.load_rows(tmp_path / "sa")) == 1


def test_tip_moved_later_and_postponed_to_another_date(tmp_path):
    """A TBD game later announced for a LATER time, or postponed and replayed on another
    date: records made before the original date stay pre-tip; the scored record is the
    latest one before the actual (new) tip."""
    ra = roster_archive(tmp_path)
    early = _recs(ra, "2026-11-02T21:10:00+00:00")
    later = [rec(ps.BASE, 1, "T1", "T2", 4.0, ra, asof="2026-11-09T21:10:00+00:00", tip=PLACE),
             rec(ps.ROSTER, 1, "T1", "T2", 5.0, ra, asof="2026-11-09T21:10:00+00:00", tip=PLACE)]  # fmt: skip
    pa = archive(tmp_path, early, when="2026-11-02T21:16:00+00:00")
    archive(tmp_path, later, when="2026-11-09T21:16:00+00:00")
    # moved later on the same date (announced 9 PM ET): the Nov 2 record is the latest pre-tip
    frames, _ = _score(pa, ra, _games(S.ANNOUNCED, "2026-11-04T02:00:00Z"), None)
    assert status(frames, 1) == ("VALID", "")
    assert frames["paired_games"].iloc[0]["roster_margin"] == 3.0
    # postponed, replayed Nov 10 at 7 PM ET: the Nov 9 record is the latest pre-tip
    frames, _ = _score(pa, ra, _games(S.ANNOUNCED, "2026-11-11T00:00:00Z"), None)
    assert status(frames, 1) == ("VALID", "")
    assert frames["paired_games"].iloc[0]["roster_margin"] == 5.0


def test_cancelled_or_postponed_games_are_not_projected_or_owed():
    now = T("2026-11-03T14:40Z")
    live = [obs(1, "2026-11-03T14:41Z", "post", "STATUS_CANCELED"),
            obs(2, "2026-11-03T14:41Z", "post", "STATUS_POSTPONED")]  # fmt: skip
    w = S.live_window(live, now, 30.0, _sched()[["espn_game_id", "tip"]])
    assert {1, 2} <= w["exclude"] and not ({1, 2} & w["extra"])
    gaps = C.coverage_gaps(_sched(), set(), now, 30.0, ["pure-0.5.0"], {"T1", "T2"}, w)
    assert gaps == [("pure-0.5.0", 6)]
