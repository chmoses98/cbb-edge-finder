"""Opening-night contract-level coverage audit and archive health monitor."""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cbb_edge.kalshi.mapping import event_date
from cbb_edge.kalshi.research.universe import parse_ts

OPENING_NIGHT = date(2026, 11, 2)


def contract_issues(c: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    """Every reason this contract is not fully evaluable. Empty list == nothing missing."""
    st = c["status"]
    out: list[str] = []
    if not c["entry_points_present"]:
        out.append(f"NO_PRETIP_QUOTE:{c.get('pretip_gap_reason')}")
    elif "CLOSE" not in c["entry_points_present"]:
        out.append("NO_CLOSING_QUOTE")
    if c["open_observed_late_minutes"] is not None and c["open_observed_late_minutes"] > 60:
        out.append("OPEN_OBSERVED_LATE_GT_1H_AFTER_LISTING")
    missing = [e for e in c["entry_points_missing"] if e in ("H24", "H6", "H1")]
    if missing and c["entry_points_present"]:
        out.append("MISSING_HORIZONS:" + "+".join(missing))
    if st["outcome"] != "SETTLED":
        out.append(f"OUTCOME:{st['outcome']}")
    if st["mapping"] != "MATCHED":
        out.append(f"MAPPING:{st['mapping']}")
    if st["support"] != "SUPPORTED":
        out.append(f"SUPPORT:{st['support']}")
    if st["model"] != "MODELED":
        out.append(f"MODEL:{st['model_missing_capability']}")
    if st["official_check"] not in ("CONFIRMED",):
        out.append(f"OFFICIAL_CHECK:{st['official_check']}")
    if not c["status"]["tip_verified"]:
        out.append("TIP_UNVERIFIED")
    return out


def opening_night(
    summaries: list[dict[str, Any]], rows: list[dict[str, Any]], night: date = OPENING_NIGHT
) -> dict[str, Any]:
    """Market-by-market audit of every contract whose event is dated ``night`` (ET)."""
    by_ticker: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], {})[r["entry"]] = r
    sel = [c for c in summaries if event_date(c["event"]) == night]
    table: list[dict[str, Any]] = []
    for c in sel:
        e = by_ticker.get(c["ticker"], {})
        o, cl = e.get("OPEN"), e.get("CLOSE")
        models = (cl or {}).get("model", {})
        issues = contract_issues(c, list(e.values()))
        close_row = cl or {}
        has_model = bool(close_row.get("model"))
        mkt_ok = bool(cl and cl.get("mid") is not None and c["result"] in ("yes", "no"))
        fill_ok = bool(
            cl and any(cl[s].get("net_pnl") is not None for s in ("yes", "no") if s in cl)
        ) or any(r[s].get("net_pnl") is not None for r in e.values() for s in ("yes", "no"))
        table.append(
            {
                "ticker": c["ticker"], "family": c["family"], "series": c["series"],
                "game": c["cluster"], "title": c["title"], "yes_sub_title": c["yes_sub_title"],
                "listed_open_time": c["open_time"], "first_captured": c["first_seen"],
                "snapshots": c["n_snapshots"], "panel_rows": c["n_panel_rows"],
                "open_t": o and o["t"], "open_bid": o and o["yes_bid"],
                "open_ask": o and o["yes_ask"], "open_mid": o and o["mid"],
                "close_t": cl and cl["t"], "close_bid": cl and cl["yes_bid"],
                "close_ask": cl and cl["yes_ask"], "close_mid": cl and cl["mid"],
                "close_staleness_min": cl and cl["staleness_min"],
                "model_versions": ",".join(sorted(models)),
                "model_p_pure-0.5.0": (models.get("pure-0.5.0") or {}).get("p"),
                "model_p_pure-0.5.0+roster": (models.get("pure-0.5.0+roster") or {}).get("p"),
                "kalshi_result": c["result"], "settlement_ts": c["settlement_ts"],
                "official_check": c["status"]["official_check"],
                "mapping": c["status"]["mapping"], "support": c["status"]["support"],
                "model": c["status"]["model"], "outcome": c["status"]["outcome"],
                "captured": c["n_snapshots"] > 0,
                "valid_pretip_quote": bool(c["entry_points_present"]),
                "pretip_gap_reason": c.get("pretip_gap_reason"),
                "frozen_pretip_model_prediction": has_model,
                "closing_quote_captured": "CLOSE" in c["entry_points_present"],
                "official_result_available": c["status"]["official_check"]
                in ("CONFIRMED", "DISAGREE"),
                "official_agrees_with_kalshi": {"CONFIRMED": True, "DISAGREE": False}.get(
                    c["status"]["official_check"]
                ),
                "market_accuracy_evaluable": mkt_ok,
                "model_accuracy_evaluable": mkt_ok and has_model,
                "after_fee_profitability_evaluable": mkt_ok and fill_ok,
                "flags": "|".join(c["status_flags"]), "issues": "|".join(issues),
            }
        )  # fmt: skip
    flag_counts: Counter[str] = Counter(f for c in sel for f in c["status_flags"])
    issue_counts: Counter[str] = Counter()
    for t in table:
        for i in filter(None, t["issues"].split("|")):
            issue_counts[i.split(":")[0] if i.startswith(("MODEL", "OUTCOME")) else i] += 1
            if i.startswith("MODEL:"):
                issue_counts[i] += 1
    clean = [t for t in table if not t["issues"]]
    return {
        "night": night.isoformat(),
        "contracts": len(table),
        "games": len({c["cluster"] for c in sel}),
        "by_family": dict(Counter(c["family"] for c in sel)),
        "status_flags": dict(flag_counts),
        "fully_clean_contracts": len(clean),
        "contracts_with_issue": len(table) - len(clean),
        "issue_counts": dict(issue_counts.most_common()),
        "official_check": dict(Counter(c["status"]["official_check"] for c in sel)),
        "pretip_gap_reasons": dict(
            Counter(c.get("pretip_gap_reason") for c in sel if c.get("pretip_gap_reason"))
        ),
        "readiness": {
            k: sum(1 for t in table if t[k])
            for k in (
                "captured",
                "valid_pretip_quote",
                "frozen_pretip_model_prediction",
                "closing_quote_captured",
                "official_result_available",
                "official_agrees_with_kalshi",
                "market_accuracy_evaluable",
                "model_accuracy_evaluable",
                "after_fee_profitability_evaluable",
            )
        },  # fmt: skip
        "official_disagreements": [t["ticker"] for t in table if t["official_check"] == "DISAGREE"],
        "unmatched": [t["ticker"] for t in table if t["mapping"] != "MATCHED"],
        "unsettled": [t["ticker"] for t in table if t["outcome"] != "SETTLED"],
        "table": table,
    }


def write_audit_csv(audit: dict[str, Any], path: Path) -> None:
    table = audit["table"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not table:
            return
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)


@dataclass(frozen=True)
class HealthThresholds:
    """Freshness/consistency thresholds (override via CBB_HEALTH_* environment variables)."""

    capture_degraded_min: float = 30.0
    capture_critical_min: float = 60.0
    panel_missing_degraded: int = 2
    research_degraded_min: float = 180.0
    mismatch_critical_fraction: float = 0.001  # share of raw rows absent from the panel

    @classmethod
    def from_env(cls) -> HealthThresholds:
        def f(name: str, default: float) -> float:
            try:
                return float(os.environ.get(f"CBB_HEALTH_{name}", default))
            except ValueError:
                return default

        return cls(
            f("CAPTURE_DEGRADED_MIN", cls.capture_degraded_min),
            f("CAPTURE_CRITICAL_MIN", cls.capture_critical_min),
            int(f("PANEL_MISSING_DEGRADED", cls.panel_missing_degraded)),
            f("RESEARCH_DEGRADED_MIN", cls.research_degraded_min),
            f("MISMATCH_CRITICAL_FRACTION", cls.mismatch_critical_fraction),
        )


def capture_intervals(ledger: list[dict[str, Any]], recent: int = 12) -> dict[str, Any]:
    """Real consecutive-snapshot intervals in minutes (gaps are preserved, never smoothed)."""
    stamps = [t for t in (parse_ts(s["captured_at"]) for s in ledger) if t is not None]
    mins = [
        round((b - a).total_seconds() / 60.0, 1) for a, b in zip(stamps, stamps[1:], strict=False)
    ]
    last = mins[-recent:]
    srt = sorted(last)
    return {
        "recent_minutes": last,
        "median": srt[len(srt) // 2] if srt else None,
        "p90": srt[min(len(srt) - 1, int(0.9 * len(srt)))] if srt else None,
        "max_recent": max(last) if last else None,
    }


def grade_health(
    health: dict[str, Any],
    panel: dict[str, Any],
    thresholds: HealthThresholds | None = None,
    pipelines: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Overall status HEALTHY | DEGRADED | CRITICAL with the reasons. Leakage or a material
    archive-to-panel row mismatch is CRITICAL immediately."""
    t = thresholds or HealthThresholds.from_env()
    crit: list[str] = []
    deg: list[str] = []
    age = health["findings"].get("latest_snapshot_age_minutes")
    if age is None:
        crit.append("no_capture_snapshot")
    elif age > t.capture_critical_min:
        crit.append(f"capture_age_{age:.0f}min_over_{t.capture_critical_min:.0f}")
    elif age > t.capture_degraded_min:
        deg.append(f"capture_age_{age:.0f}min_over_{t.capture_degraded_min:.0f}")
    totals = panel.get("totals", {})
    if totals.get("future_projection_rows") or totals.get("posttip_projection_in_pretip_rows"):
        crit.append("projection_leakage_detected")
    raw_rows = max(int(totals.get("raw_rows", 0)), 1)
    missing_rows = sum(
        int(p.get("missing_in_panel", 0)) + int(p.get("extra_in_panel", 0))
        for p in panel.get("problems", [])
        if p.get("kind") == "row_set_mismatch"
    )
    if missing_rows / raw_rows > t.mismatch_critical_fraction:
        crit.append(f"archive_panel_row_mismatch_{missing_rows}_rows")
    elif panel.get("problems"):
        deg.append("panel_integrity_problems")
    if panel.get("backlog_count", 0) > t.panel_missing_degraded:
        deg.append(f"panel_backlog_{panel['backlog_count']}_over_{t.panel_missing_degraded}")
    if pipelines and pipelines.get("findings"):
        deg.extend(f"pipeline:{f}" for f in pipelines["findings"])
    status = "CRITICAL" if crit else "DEGRADED" if deg else "HEALTHY"
    return {"status": status, "critical": crit, "degraded": deg, "thresholds": asdict(t)}


def archive_health(
    ledger: list[dict[str, Any]],
    panel_info: dict[str, Any],
    summaries: list[dict[str, Any]],
    now: datetime | None = None,
    max_gap_minutes: int = 90,
    stale_minutes: float = 30.0,
) -> dict[str, Any]:
    """Missing-data monitor. ``recovery`` names the idempotent job that repairs each finding."""
    now = now or datetime.now(UTC)
    stamps = [parse_ts(s["captured_at"]) for s in ledger]
    gaps: list[dict[str, Any]] = [
        {"after": a.isoformat(), "before": b.isoformat(),
         "minutes": round((b - a).total_seconds() / 60)}
        for a, b in zip(stamps, stamps[1:], strict=False)
        if a and b and (b - a).total_seconds() / 60 > max_gap_minutes
    ]  # fmt: skip
    have = set(panel_info.get("snapshots_with_panel", []))
    no_panel = [s["snapshot"] for s in ledger if s["snapshot"] not in have]
    last = stamps[-1] if stamps else None
    age = (now - last).total_seconds() / 60 if last else None
    overdue = [
        c["ticker"]
        for c in summaries
        if c["status"]["outcome"] != "SETTLED"
        and c["status"]["mapping"] == "MATCHED"
        and c["game_start"]
        and (parse_ts(c["game_start"]) or now) < now
        and (now - (parse_ts(c["game_start"]) or now)).total_seconds() > 24 * 3600
    ]
    findings = {
        "snapshot_gaps": len(gaps),
        "snapshots_without_panel": len(no_panel),
        "latest_snapshot_age_minutes": age,
        "latest_snapshot_stale": bool(age is not None and age > stale_minutes),
        "matched_game_contracts_unsettled_over_24h": len(overdue),
        "contracts_never_priced_pretip": sum(
            1 for c in summaries if c["status"]["observation"] != "PRICED"
        ),
    }
    return {
        "generated_at": now.isoformat(),
        "snapshots": len(ledger),
        "first_snapshot": stamps[0].isoformat() if stamps and stamps[0] else None,
        "last_snapshot": last.isoformat() if last else None,
        "gap_threshold_minutes": max_gap_minutes,
        "gaps": gaps[:100],
        "max_gap_minutes": max((int(g["minutes"]) for g in gaps), default=0),
        "snapshots_without_panel_partition": no_panel[:200],
        "overdue_unsettled_sample": overdue[:50],
        "findings": findings,
        "recovery": {
            "snapshots_without_panel": "kalshi-market-panel workflow (hourly --all-missing backfill)",
            "overdue_unsettled": "next capture re-lists recently closed markets (72h lookback); "
            "contracts older than the lookback need a manual --settled-lookback-h dispatch",
            "snapshot_gaps": "irrecoverable: a missed capture is a gap, never fabricated",
            "stale_capture": "kalshi-capture.yml push/dispatch kickoff + 15-min cron",
        },
        "healthy": not findings["latest_snapshot_stale"] and len(no_panel) <= 12,
    }
