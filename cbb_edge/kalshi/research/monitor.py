"""Pipeline monitor: failed/cancelled workflow runs and scheduler yield (from ``gh run list``)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from cbb_edge.kalshi.research.universe import parse_ts

PIPELINES = (
    "kalshi-capture",
    "kalshi-market-panel",
    "market-research",
    "prospective-projections",
    "prospective-scores",
    "espn-line-capture",
)
# expected scheduled ticks per hour (from each workflow's cron), used for yield only
EXPECTED_SCHEDULED_PER_HOUR = {
    "kalshi-capture": 4.0,
    "kalshi-market-panel": 1.0,
    "market-research": 1.0,
}


def pipeline_health(
    runs: list[dict[str, Any]], now: datetime | None = None, window_h: int = 24
) -> dict[str, Any]:
    """``runs`` items: workflowName, conclusion, status, event, createdAt (gh run list --json)."""
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=window_h)
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        t = parse_ts(r.get("createdAt"))
        if t is None or t < since:
            continue
        by[str(r.get("workflowName"))].append(r)
    out: dict[str, Any] = {}
    findings: list[str] = []
    for wf in PIPELINES:
        rs = by.get(wf, [])
        conc: Counter[str] = Counter(str(r.get("conclusion") or r.get("status")) for r in rs)
        prod = [r for r in rs if r.get("event") != "pull_request"]
        sched = [r for r in prod if r.get("event") == "schedule"]
        exp = EXPECTED_SCHEDULED_PER_HOUR.get(wf)
        yld = len(sched) / (exp * window_h) if exp else None
        out[wf] = {
            "runs": len(rs), "production_runs": len(prod), "scheduled_runs": len(sched),
            "conclusions": dict(conc),
            "scheduled_yield": None if yld is None else round(yld, 3),
        }  # fmt: skip
        prod_bad = sum(
            1 for r in prod if r.get("conclusion") in ("failure", "cancelled", "timed_out")
        )
        if prod_bad:
            findings.append(f"{wf}: {prod_bad} failed/cancelled production runs in {window_h}h")
        if yld is not None and yld < 0.5:
            findings.append(f"{wf}: scheduler delivered {yld:.0%} of expected ticks in {window_h}h")
    return {"window_hours": window_h, "pipelines": out, "findings": findings}


def panel_recovery_decision(
    health: dict[str, Any],
    runs: list[dict[str, Any]],
    now: datetime | None = None,
    *,
    min_backlog: int = 3,
    cooldown_minutes: int = 90,
) -> dict[str, Any]:
    """Bounded repair of archive gaps caused by dropped GitHub workflow_run/schedule ticks.

    Only production runs are considered. Fail closed without workflow visibility,
    and never dispatch when a panel is queued, running, or recently attempted.
    """
    now = now or datetime.now(UTC)
    backlog = (health.get("panel_integrity") or {}).get("backlog_count")
    base = {"action": "SKIP", "backlog": backlog, "cooldown_minutes": cooldown_minutes}
    if type(backlog) is not int or backlog < 0:
        return {**base, "reason": "panel_backlog_unavailable"}
    if backlog < min_backlog:
        return {**base, "reason": "below_recovery_threshold"}
    if not runs:
        return {**base, "reason": "workflow_run_visibility_unavailable"}
    candidates = [
        r for r in runs
        if r.get("workflowName") == "kalshi-market-panel"
        and r.get("event") != "pull_request"
    ]
    if any(r.get("status") in ("queued", "pending", "in_progress", "waiting", "requested")
           for r in candidates):
        return {**base, "reason": "production_panel_already_active"}
    observed = [t for r in candidates if (t := parse_ts(r.get("createdAt"))) is not None]
    recent = max(observed) if observed else None
    if recent is not None and now - recent < timedelta(minutes=cooldown_minutes):
        return {**base, "reason": "panel_attempt_within_cooldown",
                "latest_panel_created_at": recent.isoformat()}
    return {**base, "action": "DISPATCH", "reason": "missing_partitions_and_no_recent_panel"}
