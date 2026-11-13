"""Collector recovery guards: stalled queues, missed schedules, retries, duplicates (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from cbb_edge.ops import dispatch_guard as G

NOW = datetime(2026, 11, 13, 19, 23, tzinfo=UTC)


def run(i, status="completed", conclusion="success", event="workflow_dispatch", age=10):
    return {
        "databaseId": i, "status": status, "conclusion": conclusion, "event": event,
        "createdAt": (NOW - timedelta(minutes=age)).isoformat(),
    }  # fmt: skip


def old_inline_recovery(stale: bool, runs: list[dict]) -> str:
    """The market-research step this replaces (jq count of ANY queued/in-progress/pending run)."""
    active = sum(
        1
        for r in runs
        if r["event"] != "pull_request" and r["status"] in ("queued", "in_progress", "pending")
    )
    return "DISPATCH" if stale and active == 0 else "SKIP"


# ------------------------------------------------------------ the observed bug
def test_zero_job_orphan_from_a_502_retry_no_longer_blocks_stale_capture_recovery():
    # Real shape, 2026-11-13: the chain's dispatch got HTTP 502 but GitHub created run
    # 43467050714 with 0 jobs (queued forever); the retry created 43467085061. Suppose the chain
    # then died: every later capture completed, the snapshot went stale.
    runs = [
        run(43467050714, status="queued", conclusion=None, age=150),
        run(43467085061, age=150),
        run(43472756392, age=117),
    ]
    assert old_inline_recovery(True, runs) == "SKIP"  # the bug: recovery blocked
    d = G.capture_recovery(True, runs, NOW)
    assert d.action == "DISPATCH"
    assert d.stale_runs_ignored == [43467050714] and d.blocking_runs == []


@pytest.mark.parametrize(
    "age,action", [(5, "SKIP"), (29, "SKIP"), (30, "DISPATCH"), (90, "DISPATCH")]
)
def test_conservative_30_minute_threshold_for_queued_runs(age, action):
    d = G.capture_recovery(True, [run(1, status="queued", conclusion=None, age=age)], NOW)
    assert d.action == action


@pytest.mark.parametrize("status", ["pending", "waiting", "requested"])
def test_every_queued_family_status_uses_the_threshold(status):
    young = G.capture_recovery(True, [run(1, status=status, conclusion=None, age=10)], NOW)
    old = G.capture_recovery(True, [run(1, status=status, conclusion=None, age=45)], NOW)
    assert (young.action, old.action) == ("SKIP", "DISPATCH")


def test_running_capture_blocks_until_job_timeout_plus_threshold():
    assert G.capture_recovery(True, [run(1, "in_progress", None, age=54)], NOW).action == "SKIP"
    assert G.capture_recovery(True, [run(1, "in_progress", None, age=56)], NOW).action == "DISPATCH"


def test_healthy_queued_run_still_blocks_even_next_to_a_stale_orphan():
    runs = [run(1, "queued", None, age=200), run(2, "queued", None, age=3)]
    d = G.capture_recovery(True, runs, NOW)
    assert d.action == "SKIP" and d.blocking_runs == [2] and d.stale_runs_ignored == [1]


def test_fail_closed_inputs():
    assert G.capture_recovery(True, None, NOW).reason == "run_listing_failed_fail_closed"
    assert G.capture_recovery(True, [], NOW, listing_ok=False).action == "SKIP"
    assert G.capture_recovery(None, [], NOW).reason == "staleness_unknown"
    assert G.capture_recovery("True", [], NOW).action == "SKIP"  # malformed health
    assert G.capture_recovery(False, [], NOW).reason == "capture_fresh"
    # an unreadable createdAt is never assumed dead
    bad = {"databaseId": 9, "status": "queued", "event": "schedule", "createdAt": "garbage"}
    assert G.capture_recovery(True, [bad], NOW).action == "SKIP"


def test_pull_request_runs_never_block():
    prs = [run(i, "queued", None, event="pull_request", age=1) for i in range(4)]
    assert G.capture_recovery(True, prs, NOW).action == "DISPATCH"


# --------------------------------------------------------- projections heartbeat
def test_missed_schedule_triggers_one_catch_up_dispatch():
    # newest projections run 3 h ago (cron ticks dropped): dispatch one catch-up tick
    d = G.heartbeat([run(1, event="schedule", age=180)], NOW)
    assert d.action == "DISPATCH" and d.reason == "no_run_within_max_age"
    assert G.heartbeat([], NOW).action == "DISPATCH"  # nothing listed at all, listing OK


def test_delivered_cron_ticks_make_the_heartbeat_a_no_op():
    assert G.heartbeat([run(1, event="schedule", age=20)], NOW).reason == "recent_run_exists"


def test_duplicate_heartbeats_dispatch_at_most_once_per_window():
    first = G.heartbeat([run(1, event="schedule", age=180)], NOW)
    assert first.action == "DISPATCH"
    # 15 min later the next capture's heartbeat sees the dispatched run queued -> SKIP
    later = NOW + timedelta(minutes=15)
    runs = [run(2, "queued", None, age=-15 + 15), run(1, event="schedule", age=180)]
    assert G.heartbeat(runs, later).action == "SKIP"
    # even if that dispatch became a 0-job orphan, nothing is stacked inside max_age
    later2 = NOW + timedelta(minutes=45)
    assert G.heartbeat(runs, later2).reason == "recent_run_exists"
    # after max_age the orphan no longer suppresses a fresh attempt
    later3 = NOW + timedelta(minutes=60)
    d = G.heartbeat(runs, later3)
    assert d.action == "DISPATCH" and d.stale_runs_ignored == [2]


def test_heartbeat_respects_a_healthy_running_projection():
    d = G.heartbeat([run(1, "in_progress", None, event="schedule", age=70)], NOW)
    assert d.action == "SKIP" and d.reason == "healthy_run_already_active"  # < 60 + 30 min
    assert G.heartbeat([run(1, "in_progress", None, age=95)], NOW).action == "DISPATCH"


def test_heartbeat_circuit_breaker_and_reset():
    fails = [run(i, conclusion="failure", age=60 + i) for i in range(3)]
    assert G.heartbeat(fails, NOW).reason.startswith("circuit_open_after_3")
    two = [
        run(0, conclusion="failure", age=60),
        run(1, conclusion="failure", age=61),
        run(2, age=62),
    ]
    assert G.heartbeat(two, NOW).action == "DISPATCH"
    # an interrupted (cancelled) run neither counts as a failure nor resets the streak
    mixed = [run(9, conclusion="cancelled", age=59), *fails]
    assert G.heartbeat(mixed, NOW).action == "SKIP"


def test_heartbeat_fail_closed_and_offseason():
    assert G.heartbeat(None, NOW).reason == "run_listing_failed_fail_closed"
    assert G.heartbeat([], NOW, listing_ok=False).action == "SKIP"
    assert G.heartbeat([], datetime(2026, 7, 1, tzinfo=UTC)).reason == "offseason"


# ------------------------------------------------------------------------- CLI
def test_cli_replay_with_saved_listing(tmp_path, capsys):
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"findings": {"latest_snapshot_stale": True}}))
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps([run(43467050714, "queued", None, age=150)]))
    G.main(["capture-recovery", "--health", str(health), "--runs", str(runs),
            "--now", NOW.isoformat()])  # fmt: skip
    assert json.loads(capsys.readouterr().out)["action"] == "DISPATCH"
    G.main(["capture-recovery", "--health", str(health), "--listing-failed"])
    assert json.loads(capsys.readouterr().out)["action"] == "SKIP"
    runs.write_text("{not json")
    G.main(["heartbeat", "--runs", str(runs), "--now", NOW.isoformat()])
    assert json.loads(capsys.readouterr().out)["reason"] == "run_listing_failed_fail_closed"
    (tmp_path / "broken.json").write_text("{}")
    G.main(["capture-recovery", "--health", str(tmp_path / "broken.json"), "--runs", str(runs)])
    assert json.loads(capsys.readouterr().out)["reason"] == "staleness_unknown"
