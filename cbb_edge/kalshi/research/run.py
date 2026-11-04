"""Build the full market-research dataset set from the immutable archives.

    python -m cbb_edge.kalshi.research.run --kalshi arch/kalshi-archive \
        --panel arch/kalshi-panel-archive --schedule arch/schedule-archive --out research_out

Outputs (derived and reproducible; raw evidence stays in the archive branches):
  latest/universe.jsonl.gz      one row per discovered contract (inventory + independent statuses)
  latest/evaluations.jsonl.gz   one row per (contract, entry point) with scores, fills, CLV
  latest/matrix.json            market-family evaluation matrix
  latest/opening_night.{json,csv,md}
  latest/health.json            missing-data monitor
  latest/dashboard.html
  daily/YYYY-MM-DD/summary.json append-only dated summary
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cbb_edge.kalshi.research import audit, dashboard, fees, matrix, monitor, panel_audit
from cbb_edge.kalshi.research.evaluate import FILL_ASSUMPTION, evaluate_all
from cbb_edge.kalshi.research.universe import (
    attach_panel,
    load_period_scores,
    load_scores,
    load_universe,
)


def _jsonl_gz(path: Path, items: list[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, sort_keys=True, default=str) + "\n")


def _opening_md(a: dict[str, Any]) -> str:
    lines = [
        f"# Opening night {a['night']} - contract-level coverage audit",
        "",
        f"* contracts: **{a['contracts']}** across **{a['games']}** games/clusters",
        f"* fully clean (nothing missing): **{a['fully_clean_contracts']}**; "
        f"with at least one issue: **{a['contracts_with_issue']}**",
        f"* by family: {a['by_family']}",
        f"* status flags (overlap by design): {a['status_flags']}",
        f"* official-check vs Kalshi settlement: {a['official_check']} "
        f"(disagreements: {len(a['official_disagreements'])})",
        f"* unmatched: {len(a['unmatched'])}; unsettled: {len(a['unsettled'])}",
        "",
        "## Issue counts",
        "",
    ]
    lines += [f"* `{k}`: {v}" for k, v in a["issue_counts"].items()]
    lines += [
        "",
        "Per-contract detail: `opening_night.csv` (one row per contract, every issue listed).",
    ]
    return "\n".join(lines) + "\n"


def build(
    kalshi: Path,
    panel: Path | None,
    schedule: Path | None,
    out: Path,
    now: datetime | None = None,
    runs: Path | None = None,
    periods: Path | None = None,
    thresholds: audit.HealthThresholds | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    contracts, ledger = load_universe(kalshi)
    panel_info = attach_panel(contracts, panel)
    scores = load_scores(schedule)
    period_scores = load_period_scores(periods)
    summaries, rows = evaluate_all(contracts, scores, period_scores)
    mx = matrix.build_matrix(summaries, rows)
    night = audit.opening_night(summaries, rows)
    health = audit.archive_health(ledger, panel_info, summaries, now)
    pa = panel_audit.audit_panels(kalshi, panel)
    health["panel_integrity"] = {k: v for k, v in pa.items() if k != "problems"} | {
        "problems": pa["problems"][:50]
    }
    health["findings"]["panel_backlog"] = pa["backlog_count"]
    health["findings"]["panel_integrity_ok"] = pa["ok"]
    if runs is not None and runs.exists():
        health["pipelines"] = monitor.pipeline_health(json.loads(runs.read_text()), now)
        health["findings"]["pipeline_findings"] = len(health["pipelines"]["findings"])
    health["capture_intervals"] = audit.capture_intervals(ledger)
    health["grade"] = audit.grade_health(
        health, pa, pipelines=health.get("pipelines"), thresholds=thresholds
    )
    health["healthy"] = health["grade"]["status"] == "HEALTHY"
    latest = out / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    _jsonl_gz(latest / "universe.jsonl.gz", summaries)
    _jsonl_gz(latest / "evaluations.jsonl.gz", rows)
    (latest / "snapshot_ledger.json").write_text(json.dumps(ledger, indent=1))
    mx["fee_schedule"] = fees.FEE_SCHEDULE_VERSION
    mx["fee_basis_rows"] = mx["overall"]["completeness"]["fee_basis_rows"]
    (latest / "matrix.json").write_text(json.dumps(mx, indent=1, default=str))
    (latest / "health.json").write_text(json.dumps(health, indent=1, default=str))
    (latest / "opening_night.json").write_text(
        json.dumps({k: v for k, v in night.items() if k != "table"}, indent=1)
    )
    audit.write_audit_csv(night, latest / "opening_night.csv")
    (latest / "opening_night.md").write_text(_opening_md(night))
    meta = {
        "generated_at": now.isoformat(), "snapshots": len(ledger),
        "fill_assumption": FILL_ASSUMPTION, "fee_schedule": fees.FEE_SCHEDULE_VERSION,
        "bet_authority": "RESEARCH_ONLY",
    }  # fmt: skip
    (latest / "dashboard.html").write_text(
        dashboard.render(
            mx, dashboard.slim(summaries, rows, contracts, night), {**meta, "health": health}
        ),
        encoding="utf-8",
    )
    summary = {
        **meta,
        "contracts": len(summaries),
        "entry_rows": len(rows),
        "status_flags": mx["overall"]["status_flags"],
        "families": {f: b["discovered_contracts"] for f, b in mx["families"].items()},
        "panel_rows_joined": panel_info["rows"],
        "scores_loaded": len(scores),
        "period_scores_loaded": len(period_scores),
        "health": health["findings"],
        "healthy": health["healthy"],
        "health_status": health["grade"]["status"],
        "opening_night": {k: v for k, v in night.items() if k in (
            "contracts", "games", "fully_clean_contracts", "contracts_with_issue")},
    }  # fmt: skip
    daily = out / "daily" / now.strftime("%Y-%m-%d")
    daily.mkdir(parents=True, exist_ok=True)
    (daily / f"summary_{now.strftime('%H%M%SZ')}.json").write_text(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kalshi", required=True, type=Path)
    ap.add_argument("--panel", type=Path)
    ap.add_argument("--schedule", type=Path)
    ap.add_argument("--periods", type=Path, help="period-scores-archive checkout (optional)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--runs", type=Path, help="gh run list --json output for the pipeline monitor")
    a = ap.parse_args()
    print(
        json.dumps(
            build(a.kalshi, a.panel, a.schedule, a.out, runs=a.runs, periods=a.periods),
            indent=1,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
