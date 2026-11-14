"""Fail-closed dispatch guards for collector recovery (pure, unit-tested, no network).

Why. In the 72 h before 2026-11-13T19:23Z, GitHub delivered 15 of the 78 cron ticks of
``prospective-projections`` (19%), 11 of 144 of ``espn-line-capture`` and 10 of 72 of
``ops-watch``. ``workflow_dispatch`` events, by contrast, were delivered every time: the
self-chained ``kalshi-capture`` never went more than 1.6 h between captures. So recovery is
driven by dispatch, and every dispatch is gated by the same question: is a healthy
production run of the target workflow already queued or running?

The bug this module fixes (kalshi-capture run 43467050714). A chained ``gh workflow run``
got ``HTTP 502`` from the dispatch API. GitHub had in fact created the run, but with ZERO
jobs; the retry then created a second, normal run. The orphan stayed ``queued`` for hours
and never occupied the concurrency slot (later captures ran normally). However, the
market-research stale-capture recovery counted ANY queued production run as "already
waiting for a runner" and refused to dispatch. That would have blocked recovery for as long
as the orphan stayed in its 20-run listing, if the capture chain had also stopped.

Rules (``classify``):

* only production runs count (``event != pull_request``): PR runs have their own
  concurrency group and can never fill the production slot;
* a queued-family run (``queued``/``pending``/``waiting``/``requested``) older than
  ``stale_queued_min`` (default 30) is STALE and no longer blocks. A healthy queued
  production run either starts or is superseded (cancelled) by the next pending run well
  within 30 min, so this threshold is conservative. If a stale-looking run is actually alive,
  the extra dispatch it lets through is coalesced by the serialized concurrency group and
  never runs alongside it;
* an ``in_progress`` run blocks until ``stale_running_min`` (default: the job timeout plus
  30 min). After that, GitHub has killed or abandoned it;
* the run listing failed or is malformed -> SKIP (fail closed, never assume "nothing is
  running").

``capture_recovery`` replaces the inline jq count in market-research. ``heartbeat`` is the
proposed projections failover: the reliable kalshi-capture chain asks it whether to dispatch
a *catch-up* tick of prospective-projections. That tick then decides for itself, from the
archives, whether anything is owed (``cbb_edge.ops.cadence``). It never writes a record for
a game that has tipped, so a missing pregame forecast is never reconstructed.

    python -m cbb_edge.ops.dispatch_guard capture-recovery --health health.json --runs runs.json
    python -m cbb_edge.ops.dispatch_guard heartbeat --runs runs.json [--max-age-min 55]
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

QUEUED = frozenset({"queued", "pending", "waiting", "requested"})
RUNNING = frozenset({"in_progress"})
FAILED = frozenset({"failure", "timed_out", "startup_failure"})
SEASON_MONTHS = frozenset({11, 12, 1, 2, 3, 4})
STALE_QUEUED_MIN = 30
CAPTURE_JOB_TIMEOUT_MIN = 25  # .github/workflows/kalshi-capture.yml
PROJECTIONS_JOB_TIMEOUT_MIN = 60  # .github/workflows/prospective-projections.yml


def parse_ts(x: Any) -> datetime | None:
    if not x:
        return None
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


@dataclass(frozen=True)
class RunState:
    blocking: list[int] = field(default_factory=list)  # healthy active production runs
    stale: list[int] = field(default_factory=list)  # active-looking but past the threshold
    newest_created_at: str | None = None  # newest production run of any status
    consecutive_failures: int = 0  # newest completed production runs, failed in a row


def classify(
    runs: list[dict[str, Any]],
    now: datetime,
    *,
    stale_queued_min: float = STALE_QUEUED_MIN,
    stale_running_min: float = CAPTURE_JOB_TIMEOUT_MIN + STALE_QUEUED_MIN,
    exclude_run_id: int | None = None,
) -> RunState:
    """Split production runs into blocking / stale and summarize recency (see module doc).

    A run whose ``createdAt`` cannot be parsed is treated as BLOCKING (fail closed: an
    unreadable run is never assumed dead)."""
    prod = [
        r
        for r in runs
        if r.get("event") != "pull_request"
        and (exclude_run_id is None or int(r.get("databaseId") or 0) != exclude_run_id)
    ]
    blocking, stale = [], []
    for r in prod:
        status = str(r.get("status") or "")
        if status not in QUEUED and status not in RUNNING:
            continue
        created = parse_ts(r.get("createdAt"))
        limit = stale_queued_min if status in QUEUED else stale_running_min
        rid = int(r.get("databaseId") or 0)
        if created is None or now - created < timedelta(minutes=limit):
            blocking.append(rid)
        else:
            stale.append(rid)
    stamps = [t for r in prod if (t := parse_ts(r.get("createdAt"))) is not None]
    done = sorted(
        (
            r
            for r in prod
            if r.get("status") == "completed"
            and r.get("conclusion") not in ("cancelled", "skipped")
        ),
        key=lambda r: str(r.get("createdAt") or ""),
        reverse=True,
    )
    streak = 0
    for r in done:
        if r.get("conclusion") not in FAILED:
            break
        streak += 1
    return RunState(
        blocking=blocking,
        stale=stale,
        newest_created_at=max(stamps).isoformat() if stamps else None,
        consecutive_failures=streak,
    )


@dataclass(frozen=True)
class Decision:
    action: str  # DISPATCH | SKIP
    reason: str
    blocking_runs: list[int] = field(default_factory=list)
    stale_runs_ignored: list[int] = field(default_factory=list)
    newest_created_at: str | None = None


def capture_recovery(
    latest_snapshot_stale: Any,
    runs: list[dict[str, Any]] | None,
    now: datetime,
    *,
    listing_ok: bool = True,
    stale_queued_min: float = STALE_QUEUED_MIN,
) -> Decision:
    """market-research -> kalshi-capture: dispatch ONE capture when the newest snapshot is
    stale and no healthy production capture is queued or running."""
    if latest_snapshot_stale is not True:
        # None / malformed health -> SKIP as well (the health build failed: fail closed)
        why = "capture_fresh" if latest_snapshot_stale is False else "staleness_unknown"
        return Decision("SKIP", why)
    if not listing_ok or runs is None:
        return Decision("SKIP", "run_listing_failed_fail_closed")
    st = classify(
        runs,
        now,
        stale_queued_min=stale_queued_min,
        stale_running_min=CAPTURE_JOB_TIMEOUT_MIN + stale_queued_min,
    )
    if st.blocking:
        return Decision(
            "SKIP", "healthy_capture_already_active", st.blocking, st.stale, st.newest_created_at
        )
    why = "stale_capture_ignoring_stalled_runs" if st.stale else "stale_capture_nothing_active"
    return Decision("DISPATCH", why, [], st.stale, st.newest_created_at)


def heartbeat(
    runs: list[dict[str, Any]] | None,
    now: datetime,
    *,
    listing_ok: bool = True,
    max_age_min: float = 55,
    stale_queued_min: float = STALE_QUEUED_MIN,
    job_timeout_min: float = PROJECTIONS_JOB_TIMEOUT_MIN,
    max_consecutive_failures: int = 3,
    season_months: frozenset[int] = SEASON_MONTHS,
) -> Decision:
    """Failover tick for a cron-driven collector (default: prospective-projections).

    Dispatch a catch-up run only when, in season, the run listing is readable, no healthy
    production run is queued or running, the NEWEST production run of any status was
    created more than ``max_age_min`` ago (bounded: at most one heartbeat per window, and
    none at all while GitHub's own cron ticks are being delivered), and the newest completed
    runs have not failed ``max_consecutive_failures`` times in a row (circuit breaker: a
    broken collector is not hammered; the cron and a manual dispatch still run it)."""
    if not listing_ok or runs is None:
        return Decision("SKIP", "run_listing_failed_fail_closed")
    if now.month not in season_months:
        return Decision("SKIP", "offseason")
    st = classify(
        runs,
        now,
        stale_queued_min=stale_queued_min,
        stale_running_min=job_timeout_min + stale_queued_min,
    )
    if st.blocking:
        return Decision(
            "SKIP", "healthy_run_already_active", st.blocking, st.stale, st.newest_created_at
        )
    if st.consecutive_failures >= max_consecutive_failures:
        return Decision(
            "SKIP",
            f"circuit_open_after_{st.consecutive_failures}_consecutive_failures",
            [],
            st.stale,
            st.newest_created_at,
        )
    newest = parse_ts(st.newest_created_at)
    if newest is not None and now - newest < timedelta(minutes=max_age_min):
        return Decision("SKIP", "recent_run_exists", [], st.stale, st.newest_created_at)
    return Decision("DISPATCH", "no_run_within_max_age", [], st.stale, st.newest_created_at)


# --------------------------------------------------------------------------- CLI
def _load_runs(path: Path | None, listing_failed: bool) -> tuple[list[dict[str, Any]] | None, bool]:
    if listing_failed or path is None:
        return None, False
    try:
        runs = json.loads(path.read_text())
    except (OSError, ValueError):
        return None, False
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        return None, False
    return runs, True


def _emit(d: Decision) -> None:
    print(json.dumps(asdict(d)))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"action={d.action}\nreason={d.reason}\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cr = sub.add_parser("capture-recovery")
    cr.add_argument("--health", type=Path, required=True)
    hb = sub.add_parser("heartbeat")
    hb.add_argument("--max-age-min", type=float, default=55)
    for p in (cr, hb):
        p.add_argument("--runs", type=Path)
        p.add_argument("--listing-failed", action="store_true")
        p.add_argument("--stale-queued-min", type=float, default=STALE_QUEUED_MIN)
        p.add_argument("--now", default=None, help="ISO time (tests / replays); default: now")
    a = ap.parse_args(argv)
    now = parse_ts(a.now) if a.now else datetime.now(UTC)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp with a timezone")
    runs, ok = _load_runs(a.runs, a.listing_failed)
    if a.cmd == "capture-recovery":
        try:
            stale = json.loads(a.health.read_text())["findings"]["latest_snapshot_stale"]
        except (OSError, ValueError, KeyError, TypeError):
            stale = None
        _emit(
            capture_recovery(stale, runs, now, listing_ok=ok, stale_queued_min=a.stale_queued_min)
        )
    else:
        _emit(
            heartbeat(
                runs,
                now,
                listing_ok=ok,
                max_age_min=a.max_age_min,
                stale_queued_min=a.stale_queued_min,
            )
        )


if __name__ == "__main__":
    main()
