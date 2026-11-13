"""Coverage / freshness diagnostics and the freeze guard (missed ticks, interrupted jobs)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from cbb_edge.ops import cadence as C
from cbb_edge.ops import collection_health as H

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "prospective"))
import refresh_and_project as rp  # noqa: E402

NOW = datetime(2026, 11, 13, 19, 23, tzinfo=UTC)
START = NOW - timedelta(hours=72)


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------- scheduler
def test_cron_expansion_matches_this_repositorys_schedules():
    assert len(H.cron_ticks("11,26,41,56 * * 1-4,11,12 *", START, NOW)) == 288
    assert len(H.cron_ticks("40 * * 11,12 *", START, NOW)) == 72
    assert len(H.cron_ticks("10 14,21 * 11,12 *", START, NOW)) == 6
    assert H.cron_ticks("23 */6 * 5-10 *", START, NOW) == []  # offseason-only tick
    # Mondays only (cron dow 1); 2026-11-16 is a Monday
    mon = H.cron_ticks("41 13 * 1-4,11,12 1", ts("2026-11-14T00:00Z"), ts("2026-11-21T00:00Z"))
    assert mon == [ts("2026-11-16T13:41Z")]


def test_scheduler_reports_dropped_ticks_gaps_and_stalled_queue():
    runs = [
        {"databaseId": 1, "event": "schedule", "status": "completed", "conclusion": "success",
         "createdAt": "2026-11-13T02:05:45Z"},
        {"databaseId": 2, "event": "schedule", "status": "completed", "conclusion": "success",
         "createdAt": "2026-11-13T09:55:59Z"},
        {"databaseId": 3, "event": "workflow_dispatch", "status": "queued", "conclusion": None,
         "createdAt": "2026-11-13T16:52:22Z"},
        {"databaseId": 4, "event": "pull_request", "status": "queued", "conclusion": None,
         "createdAt": "2026-11-13T16:00:00Z"},
    ]  # fmt: skip
    s = H.scheduler(runs, ["40 * * 11,12 *"], START, NOW)
    assert s["expected_cron_ticks"] == 72 and s["schedule_runs_created"] == 2
    assert s["cron_delivery_ratio"] == round(2 / 72, 3)
    assert s["stalled_queued_runs"] == [3]  # the PR run is not production
    assert s["max_gap_hours"] == 54.71  # window start (11-10 19:23) -> first run (11-13 02:05)
    al = H.alerts({"scheduler": {"prospective-projections": s}})
    assert {a["code"] for a in al} == {"RUN_STALLED_IN_QUEUE", "CRON_DELIVERY_LOW"}


# --------------------------------------------------------------------- pregame
def rec(v, g, as_of, pushed):
    return {"version": v, "gid": g, "as_of": ts(as_of), "listed_tip": None,
            "pushed_at": ts(pushed) if pushed else None}  # fmt: skip


def test_pregame_separates_lost_poisoned_unprovable_and_low_lead():
    v = "pure-0.5.0"
    tips = {g: ts("2026-11-12T23:00Z") for g in (1, 2, 3, 4, 5)}
    recs = [
        rec(v, 1, "2026-11-12T13:00Z", "2026-11-12T13:10Z"),  # ok, 10 h lead
        # 401916315 shape: an earlier safe record, then a run that started 2 min before tip
        # and pushed 1.5 min after it -> the evaluators exclude the game (POISONED)
        rec(v, 2, "2026-11-12T13:00Z", "2026-11-12T13:10Z"),
        rec(v, 2, "2026-11-12T22:57:54Z", "2026-11-12T23:01:34Z"),
        rec(v, 3, "2026-11-12T21:00Z", None),  # push time not provable
        rec(v, 4, "2026-11-12T22:46Z", "2026-11-12T22:49Z"),  # 14 min lead: near miss
        rec(v, 5, "2026-11-12T23:30Z", "2026-11-12T23:40Z"),  # only a post-tip record: LOST
        rec("pure-0.5.0+roster", 1, "2026-11-12T13:00Z", "2026-11-12T13:10Z"),
    ]
    p = H.pregame(recs, tips, START, NOW)
    s = p["versions"][v]
    assert p["games_tipped"] == 5
    assert s["lost_no_pretip_record"] == [5]
    assert s["latest_pretip_pushed_after_tip"] == [2]
    assert s["push_time_unprovable"] == [3]
    assert s["low_lead_games"] == [4] and s["ok"] == 2
    assert p["versions"]["pure-0.5.0+roster"]["lost_no_pretip_record"] == [2, 3, 4, 5]
    codes = {a["code"] for a in H.alerts({"pregame": p})}
    assert {"PRETIP_RECORD_LOST", "LATEST_PRETIP_PUSHED_AFTER_TIP",
            "PRETIP_PUSH_TIME_UNPROVABLE", "PRETIP_LEAD_LOW"} <= codes  # fmt: skip


def test_finals_latency_and_overdue_from_delayed_or_missed_observation_runs():
    tip = ts("2026-11-13T00:00Z")
    obs = [
        {"gid": 1, "start_utc": tip, "state": "pre", "observed_at": ts("2026-11-12T20:00Z"),
         "pushed_at": ts("2026-11-12T20:05Z")},
        # finished ~02:00 but no observing run fired until 09:00 (delayed, not lost)
        {"gid": 1, "start_utc": tip, "state": "post", "observed_at": ts("2026-11-13T09:00Z"),
         "pushed_at": ts("2026-11-13T09:02Z")},
        # never observed final: overdue (> 6 h after tip)
        {"gid": 2, "start_utc": tip, "state": "pre", "observed_at": ts("2026-11-12T20:00Z"),
         "pushed_at": None},
    ]  # fmt: skip
    f = H.finals(obs, START, NOW, NOW)
    assert f["finals_archived"] == 1 and f["hours_tip_to_archived"]["max"] == 9.03
    assert f["final_overdue"] == [2]


def test_missing_inputs_are_unknown_never_ok(tmp_path, capsys):
    H.main(["--projections", str(tmp_path / "nope"), "--now", NOW.isoformat()])
    r = json.loads(capsys.readouterr().out)
    assert r["pregame"] == "UNKNOWN" and r["finals"] == "UNKNOWN" and r["alerts"] == []
    bad = tmp_path / "runs.json"
    bad.write_text("not json")
    H.main(["--runs", f"kalshi-capture={bad}", "--now", NOW.isoformat()])
    assert json.loads(capsys.readouterr().out)["scheduler"]["kalshi-capture"] == "UNKNOWN"


def _git(root: Path, *args: str, when: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)


def _record(root: Path, v: str, g: int, as_of: str, tip: str) -> None:
    p = root / "projections" / v / "2027" / tip[:10] / f"G{g}" / f"{as_of}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "game": {"espn_game_id": g, "season": 2027, "start_time_utc": tip},
        "model": {"version": v}, "prospective": {"as_of": as_of}}))  # fmt: skip


def test_cli_reads_push_times_from_archive_git_history(tmp_path, capsys):
    root = tmp_path / "pa"
    root.mkdir()
    _git(root, "init", "-q", when="2026-11-12T00:00:00Z")
    tip = "2026-11-12T23:00:00+00:00"
    _record(root, "pure-0.5.0", 7, "2026-11-12T13:00:00+00:00", tip)
    _git(root, "add", "-A", when="2026-11-12T13:10:00Z")
    _git(root, "commit", "-qm", "a", when="2026-11-12T13:10:00Z")
    # an interrupted / slow run: as_of before tip, commit after it
    _record(root, "pure-0.5.0", 7, "2026-11-12T22:57:54+00:00", tip)
    _git(root, "add", "-A", when="2026-11-12T23:01:34Z")
    _git(root, "commit", "-qm", "b", when="2026-11-12T23:01:34Z")
    H.main(["--projections", str(root), "--now", NOW.isoformat()])
    r = json.loads(capsys.readouterr().out)
    assert r["pregame"]["versions"]["pure-0.5.0"]["latest_pretip_pushed_after_tip"] == [7]


# ---------------------------------------------------------------- freeze guard
def frec(v, g, tip):
    return {"model": {"version": v}, "game": {"espn_game_id": g, "start_time_utc": tip}}


def test_freeze_guard_keeps_earlier_safe_record_authoritative():
    now = pd.Timestamp("2026-11-12T22:20Z")
    existing = {("pure-0.5.0", 1): pd.Timestamp("2026-11-12T13:00Z"),
                ("pure-0.5.0", 3): pd.Timestamp("2026-11-12T23:30Z")}  # fmt: skip
    recs = [
        frec("pure-0.5.0", 1, "2026-11-12T23:00Z"),  # covered, tips in 40 min: drop
        frec("pure-0.5.0", 2, "2026-11-12T23:00Z"),  # NOT covered: its only chance, keep
        frec("pure-0.5.0+roster", 1, "2026-11-12T23:00Z"),  # other version not covered: keep
        frec("pure-0.5.0", 1, "2026-11-13T02:00Z"),  # beyond the guard: keep
        # covered only by a record made AFTER the (moved-earlier) tip: not covered, keep
        frec("pure-0.5.0", 3, "2026-11-12T23:00Z"),
    ]
    kept, dropped = C.freeze_guard(recs, existing, now, 60)
    assert dropped == [("pure-0.5.0", 1)] and len(kept) == 4
    assert C.freeze_guard(recs, existing, now, 0) == (recs, [])  # disabled = unchanged


def test_latest_pre_tip_as_of_reads_the_archive(tmp_path):
    tip = "2026-11-12T23:00:00+00:00"
    _record(tmp_path, "pure-0.5.0", 7, "2026-11-12T13:00:00+00:00", tip)
    _record(tmp_path, "pure-0.5.0", 7, "2026-11-12T21:00:00+00:00", tip)
    _record(tmp_path, "pure-0.5.0", 7, "2026-11-12T23:10:00+00:00", tip)  # post-tip: ignored
    (tmp_path / "projections" / "manifests").mkdir()
    (tmp_path / "projections" / "manifests" / "x.json").write_text("{}")
    got = C.latest_pre_tip_as_of(tmp_path, 2027)
    assert got == {("pure-0.5.0", 7): pd.Timestamp("2026-11-12T21:00Z")}


def test_project_all_with_guard_skips_only_covered_imminent_games(tmp_path, monkeypatch):
    def fake_window(season, now, h, model=None, **kw):
        return [{"game": {"espn_game_id": g, "game_id": f"G{g}", "season": 2027,
                          "start_time_utc": tip},
                 "model": {"version": model["version"]},
                 "prospective": {"as_of": now.isoformat()}}
                for g, tip in ((1, "2026-11-12T23:00:00+00:00"), (2, "2026-11-12T23:00:00+00:00"),
                               (3, "2026-11-13T03:00:00+00:00"))]  # fmt: skip

    monkeypatch.setattr(rp, "active_models", lambda: {"incumbent": "pure-0.5.0"})
    monkeypatch.setattr(rp, "load_model", lambda v: {"version": v, "extra_blocks": []})
    monkeypatch.setattr(rp, "project_window", fake_window)
    now = pd.Timestamp("2026-11-12T22:20Z")
    existing = {("pure-0.5.0", 1): pd.Timestamp("2026-11-12T13:00Z"),
                ("pure-0.5.0", 3): pd.Timestamp("2026-11-12T13:00Z")}  # fmt: skip
    out, _ = rp.project_all(2027, now, 30.0, tmp_path / "o", None, None, "sha", None,
                            guard=(existing, 60.0))  # fmt: skip
    files = sorted(p.parent.name for p in (tmp_path / "o").rglob("G*/*.json"))
    assert files == ["G2", "G3"] and out["_freeze_guard"] == {"minutes": 60.0, "dropped": 1}
    # no guard: unchanged behaviour (all three written, no _freeze_guard key)
    out2, _ = rp.project_all(2027, now, 30.0, tmp_path / "p", None, None, "sha", None)
    assert len(list((tmp_path / "p").rglob("G*/*.json"))) == 3 and "_freeze_guard" not in out2


def test_guard_never_aborts_or_drops_when_archive_is_unreadable(tmp_path, capsys):
    # the workflow mkdir's arch_proj even when the fetch fails: an empty dir is NOT coverage
    (tmp_path / "empty").mkdir()
    for arch in (None, str(tmp_path / "missing"), str(tmp_path / "empty")):
        assert rp.resolve_guard(60, arch, 2027) == (None, "UNGUARDED_ARCHIVE_UNREADABLE")
    assert "UNGUARDED" in capsys.readouterr().err
    assert rp.resolve_guard(0, None, 2027) == (None, "DISABLED")
    tip = "2026-11-12T23:00:00+00:00"
    _record(tmp_path / "ok", "pure-0.5.0", 7, "2026-11-12T13:00:00+00:00", tip)
    g, status = rp.resolve_guard(60, str(tmp_path / "ok"), 2027)
    assert status == "ACTIVE" and g == ({("pure-0.5.0", 7): pd.Timestamp("2026-11-12T13:00Z")}, 60)


def test_guard_without_any_prior_forecast_keeps_every_game_and_claims_nothing():
    # games with no existing forecast are ALWAYS written (their only chance), even tipping in
    # 5 min, so a late push stays possible: the guard is no guarantee for them (evaluation
    # quarantines such records via wave14.VerifiedPush instead)
    now = pd.Timestamp("2026-11-12T22:55Z")
    recs = [
        frec(v, g, "2026-11-12T23:00Z") for v in ("pure-0.5.0", "pure-0.5.0+roster") for g in (1, 2)
    ]
    assert C.freeze_guard(recs, {}, now, 60) == (recs, [])
    # a prior record made after the tip (moved earlier) is not coverage either
    assert (
        C.freeze_guard(recs, {("pure-0.5.0", 1): pd.Timestamp("2026-11-12T23:30Z")}, now, 60)[1]
        == []
    )
    # boundary: tip exactly at now + guard is dropped (covered); one second later is kept
    ex = {("pure-0.5.0", 1): pd.Timestamp("2026-11-12T13:00Z")}
    at = [frec("pure-0.5.0", 1, "2026-11-12T23:55Z")]
    after = [frec("pure-0.5.0", 1, "2026-11-12T23:55:01Z")]
    assert C.freeze_guard(at, ex, now, 60)[1] == [("pure-0.5.0", 1)]
    assert C.freeze_guard(after, ex, now, 60) == (after, [])
