"""GitHub Actions backfill recovery must avoid dispatch loops and fake readiness."""

from datetime import UTC, datetime, timedelta

from cbb_edge.kalshi.research.monitor import panel_recovery_decision

NOW = datetime(2026, 11, 4, 20, tzinfo=UTC)


def health(backlog=8):
    return {"panel_integrity": {"backlog_count": backlog}}


def run(*, minutes_ago=100, status="completed", event="schedule", name="kalshi-market-panel"):
    return {
        "workflowName": name,
        "status": status,
        "conclusion": "success" if status == "completed" else None,
        "event": event,
        "createdAt": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
    }


def test_no_dispatch_if_panel_is_recent_or_running_or_backlog_is_small():
    assert panel_recovery_decision(health(), [run(minutes_ago=20)], NOW)["reason"] == (
        "panel_attempt_within_cooldown"
    )
    assert (
        panel_recovery_decision(health(), [run(minutes_ago=120, status="queued")], NOW)["reason"]
        == "production_panel_already_active"
    )
    assert panel_recovery_decision(health(2), [run(minutes_ago=120)], NOW)["action"] == "SKIP"


def test_backlog_with_stale_panel_dispatches_only_once_per_cooldown():
    x = panel_recovery_decision(health(8), [run(minutes_ago=95)], NOW)
    assert x["action"] == "DISPATCH"
    assert x["reason"] == "missing_partitions_and_no_recent_panel"
    # The workflow run appears immediately in run history: do not dispatch again.
    y = panel_recovery_decision(health(8), [run(minutes_ago=2)], NOW)
    assert y["action"] == "SKIP"


def test_missing_health_or_workflow_visibility_fails_closed():
    assert panel_recovery_decision({}, [run()], NOW)["reason"] == "panel_backlog_unavailable"
    assert panel_recovery_decision(health(), [], NOW)["reason"] == (
        "workflow_run_visibility_unavailable"
    )


def test_pull_request_activity_does_not_block_real_backfill():
    x = panel_recovery_decision(
        health(12),
        [run(minutes_ago=3, event="pull_request"), run(minutes_ago=110)],
        NOW,
    )
    assert x["action"] == "DISPATCH"


def test_failed_panel_attempt_is_cooldown_protected():
    r = run(minutes_ago=10)
    r["conclusion"] = "failure"
    x = panel_recovery_decision(health(8), [r], NOW)
    assert x["action"] == "SKIP"
