"""Decision logic for the kalshi-capture self-chain (pure, unit-tested, no network).

The capture workflow waits after each production capture, lists recent capture runs with
``gh run list`` and asks :func:`decide` whether to dispatch the next one. Rules, in order:

1. the run listing failed -> SKIP (fail closed: never assume "zero active runs");
2. offseason (May-Oct) -> SKIP (the 6-hourly schedule tick is the intended cadence);
3. another capture is queued/running -> SKIP (the serialized concurrency group would cancel it);
4. circuit breaker: this run plus the previous completed production runs failed
   ``max_consecutive_failures`` times in a row -> SKIP (no infinite resubmission loop; the
   schedule tick, push kickoff, research-side stale check or a manual dispatch restart it);
5. otherwise DISPATCH, including after a single transient failure (bounded retry).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEASON_MONTHS = frozenset({11, 12, 1, 2, 3, 4})
ACTIVE = frozenset({"queued", "in_progress", "pending", "waiting", "requested"})
FAILED = frozenset({"failure", "timed_out", "startup_failure"})
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class Decision:
    action: str  # DISPATCH | SKIP
    reason: str
    consecutive_failures: int = 0
    other_active_runs: int = 0


def _created(run: dict[str, Any]) -> str:
    return str(run.get("createdAt") or "")


def decide(
    runs: list[dict[str, Any]],
    *,
    run_id: int,
    job_status: str,
    now: datetime,
    listing_ok: bool = True,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    season_months: frozenset[int] = SEASON_MONTHS,
) -> Decision:
    if not listing_ok:
        return Decision("SKIP", "run_listing_failed_fail_closed")
    if now.month not in season_months:
        return Decision("SKIP", "offseason_slow_cadence_via_schedule")
    # Only PRODUCTION runs can occupy or displace the capture slot: pull-request validation runs have their
    # own concurrency group and must never block the chain (4 queued PR runs once stopped it for ~47 min).
    others = [
        r
        for r in runs
        if int(r.get("databaseId") or 0) != run_id and r.get("event") != "pull_request"
    ]
    active = sum(1 for r in others if str(r.get("status")) in ACTIVE)
    if active:
        return Decision("SKIP", "capture_already_queued_or_running", other_active_runs=active)
    streak = 1 if job_status in FAILED else 0
    if streak:
        done = sorted(
            (
                r
                for r in others
                if str(r.get("status")) == "completed" and r.get("conclusion") != "cancelled"
            ),
            key=_created,
            reverse=True,
        )
        for r in done:
            if r.get("conclusion") in FAILED:
                streak += 1
            else:
                break
        if streak >= max_consecutive_failures:
            return Decision(
                "SKIP",
                f"circuit_open_after_{streak}_consecutive_failures",
                consecutive_failures=streak,
            )
    return Decision("DISPATCH", "ok" if not streak else "retry_after_failure", streak)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, help="gh run list --json output")
    ap.add_argument("--listing-failed", action="store_true")
    ap.add_argument("--run-id", type=int, required=True)
    ap.add_argument("--job-status", default="success")
    ap.add_argument("--max-failures", type=int, default=DEFAULT_MAX_CONSECUTIVE_FAILURES)
    a = ap.parse_args()
    runs: list[dict[str, Any]] = []
    ok = not a.listing_failed
    if ok and a.runs is not None:
        try:
            runs = json.loads(a.runs.read_text())
        except (OSError, ValueError):
            ok = False
    d = decide(
        runs, run_id=a.run_id, job_status=a.job_status, now=datetime.now(UTC),
        listing_ok=ok, max_consecutive_failures=a.max_failures,
    )  # fmt: skip
    print(json.dumps(asdict(d)))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"action={d.action}\nreason={d.reason}\n")


if __name__ == "__main__":
    main()
