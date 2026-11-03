"""Opening-night contract-level coverage audit and archive health monitor."""

from __future__ import annotations

import csv
from collections import Counter
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
        out.append("NO_PRETIP_QUOTE_CAPTURED")
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
                "flags": "|".join(c["status_flags"]), "issues": "|".join(issues),
            }
        )  # fmt: skip
    flag_counts: Counter[str] = Counter(f for c in sel for f in c["status_flags"])
    issue_counts: Counter[str] = Counter()
    for t in table:
        for i in filter(None, t["issues"].split("|")):
            issue_counts[i.split(":")[0] if i.startswith(("MODEL", "OUTCOME")) else i] += 1
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


def archive_health(
    ledger: list[dict[str, Any]],
    panel_info: dict[str, Any],
    summaries: list[dict[str, Any]],
    now: datetime | None = None,
    max_gap_minutes: int = 90,
    stale_minutes: int = 120,
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
