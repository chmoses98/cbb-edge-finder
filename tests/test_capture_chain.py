"""Capture self-chain decisions and archive health grading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cbb_edge.kalshi.research.audit import HealthThresholds, capture_intervals, grade_health
from cbb_edge.ops.chain import decide

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def run(i, status="completed", conclusion="success", event="workflow_dispatch", age=10):
    return {
        "databaseId": i, "status": status, "conclusion": conclusion, "event": event,
        "createdAt": (NOW - timedelta(minutes=age)).isoformat(),
    }  # fmt: skip


def d(runs, status="success", **kw):
    return decide(runs, run_id=100, job_status=status, now=NOW, **kw)


def test_dispatches_when_nothing_else_is_active():
    r = d([run(99, age=15)])
    assert r.action == "DISPATCH" and r.reason == "ok"


def test_listing_failure_fails_closed_never_assumes_zero_active():
    r = d([], listing_ok=False)
    assert r.action == "SKIP" and "fail_closed" in r.reason


def test_pending_capture_cannot_strand_the_chain_if_it_fails_before_starting_a_job():
    # Production 41818299869 skipped dispatch for a queued schedule run which then failed
    # without any jobs (41819754338); there was no successor to run the chain step.
    assert d([run(100, status="in_progress", conclusion=None)]).action == "DISPATCH"
    for event in ("schedule", "workflow_dispatch"):
        r = d([run(101, status="queued", conclusion=None, event=event)])
        assert r.action == "DISPATCH"
        assert r.reason == "supersede_pending_capture"
        assert r.other_active_runs == 1


def test_offseason_does_not_chain():
    r = decide([], run_id=1, job_status="success", now=datetime(2026, 7, 4, tzinfo=UTC))
    assert r.action == "SKIP" and "offseason" in r.reason
    assert (
        decide([], run_id=1, job_status="success", now=datetime(2027, 3, 1, tzinfo=UTC)).action
        == "DISPATCH"
    )


def test_single_failure_retries_but_three_in_a_row_open_the_circuit():
    one = d([run(99, age=15)], status="failure")
    assert (
        one.action == "DISPATCH"
        and one.reason == "retry_after_failure"
        and one.consecutive_failures == 1
    )
    two = d([run(99, conclusion="failure", age=15), run(98, age=30)], status="failure")
    assert two.action == "DISPATCH" and two.consecutive_failures == 2
    three = d(
        [
            run(99, conclusion="failure", age=15),
            run(98, conclusion="failure", age=30),
            run(97, age=45),
        ],
        status="failure",
    )
    assert three.action == "SKIP" and three.reason.startswith("circuit_open_after_3")


def test_circuit_ignores_cancelled_and_pull_request_runs_and_resets_on_success():
    runs = [
        run(99, conclusion="failure", event="pull_request", age=5),
        run(98, conclusion="cancelled", age=10),
        run(97, conclusion="failure", age=15),
        run(96, conclusion="success", age=20),
        run(95, conclusion="failure", age=25),
    ]
    r = d(runs, status="failure")
    assert r.action == "DISPATCH" and r.consecutive_failures == 2


# ------------------------------------------------------------------ health grading
def health(age):
    return {"findings": {"latest_snapshot_age_minutes": age}}


def panel(**over):
    base = {"totals": {"raw_rows": 100000, "future_projection_rows": 0,
                       "posttip_projection_in_pretip_rows": 0}, "problems": [], "backlog_count": 0}  # fmt: skip
    base.update(over)
    return base


@pytest.mark.parametrize(
    "age,status",
    [
        (5, "HEALTHY"),
        (30, "HEALTHY"),
        (31, "DEGRADED"),
        (60, "DEGRADED"),
        (61, "CRITICAL"),
        (None, "CRITICAL"),
    ],
)
def test_capture_age_thresholds(age, status):
    assert grade_health(health(age), panel(), HealthThresholds())["status"] == status


def test_panel_backlog_and_leakage_and_mismatch():
    t = HealthThresholds()
    assert grade_health(health(5), panel(backlog_count=2), t)["status"] == "HEALTHY"
    assert grade_health(health(5), panel(backlog_count=3), t)["status"] == "DEGRADED"
    leak = panel(
        totals={"raw_rows": 10, "future_projection_rows": 1, "posttip_projection_in_pretip_rows": 0}
    )
    g = grade_health(health(5), leak, t)
    assert g["status"] == "CRITICAL" and "projection_leakage_detected" in g["critical"]
    bad = panel(
        problems=[{"kind": "row_set_mismatch", "missing_in_panel": 500, "extra_in_panel": 0}]
    )
    assert grade_health(health(5), bad, t)["status"] == "CRITICAL"  # 0.5% > 0.1%
    small = panel(
        problems=[{"kind": "row_set_mismatch", "missing_in_panel": 5, "extra_in_panel": 0}]
    )
    assert grade_health(health(5), small, t)["status"] == "DEGRADED"


def test_thresholds_are_configurable_from_env(monkeypatch):
    monkeypatch.setenv("CBB_HEALTH_CAPTURE_DEGRADED_MIN", "10")
    monkeypatch.setenv("CBB_HEALTH_CAPTURE_CRITICAL_MIN", "20")
    t = HealthThresholds.from_env()
    assert grade_health(health(15), panel(), t)["status"] == "DEGRADED"
    assert grade_health(health(25), panel(), t)["status"] == "CRITICAL"


def test_capture_intervals_preserve_real_gaps():
    stamps = [NOW - timedelta(minutes=m) for m in (100, 85, 70, 10)]
    out = capture_intervals([{"captured_at": s.isoformat()} for s in stamps])
    assert out["recent_minutes"] == [15.0, 15.0, 60.0] and out["max_recent"] == 60.0


def test_pull_request_validation_runs_never_block_the_chain():
    prs = [run(200 + i, status="queued", conclusion=None, event="pull_request") for i in range(4)]
    r = d(prs + [run(99, age=15)])
    assert r.action == "DISPATCH" and r.other_active_runs == 0
    # Real production pending runs must not strand the chain either; GitHub concurrency
    # coalesces the pending slot instead of allowing overlapping capture jobs.
    r = d(prs + [run(300, status="queued", conclusion=None, event="schedule")])
    assert r.action == "DISPATCH" and r.other_active_runs == 1
