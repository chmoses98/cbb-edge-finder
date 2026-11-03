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
