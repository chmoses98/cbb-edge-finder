"""Read-only audits of the Kalshi archive and panel; settlement-parser validation.

* ``archive_audit``  — snapshot cadence, gaps, per-snapshot contract counts, panel coverage.
* ``settlement_validation`` — for contracts Kalshi has settled and that map to a completed
  game, compare the parsed payoff's expected YES/NO (from archived final scores) with
  Kalshi's own ``result``. This validates the parsers; it makes no profitability claim.
* ``calibration`` — Brier/log-loss of as-of model probabilities on settled, validated
  contracts only (last pre-tip snapshot per contract), with sample size. Report only.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cbb_edge.kalshi.semantics import settle


def _stamp(name: str) -> datetime:
    token = name.split("_")[-1].split(".")[0]
    return datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def archive_audit(
    kalshi_root: Path, panel_root: Path | None, max_gap_minutes: int = 90
) -> dict[str, Any]:
    files = sorted(kalshi_root.glob("snapshots/**/kalshi_cbb_*.jsonl.gz"))
    stamps = [_stamp(f.name) for f in files]
    gaps: list[dict[str, Any]] = []
    for a, b in zip(stamps, stamps[1:], strict=False):
        minutes = (b - a).total_seconds() / 60
        if minutes > max_gap_minutes:
            gaps.append(
                {"after": a.isoformat(), "before": b.isoformat(), "minutes": round(minutes)}
            )
    counts = {}
    for f in files:
        sp = f.with_name(f.name.replace(".jsonl.gz", ".summary.json"))
        if sp.exists():
            counts[f.name] = json.loads(sp.read_text()).get("n_markets")
        else:
            counts[f.name] = None
    panel_names = set()
    if panel_root is not None:
        panel_names = {
            p.name.replace(".panel.jsonl.gz", "")
            for p in panel_root.glob("panels/**/*.panel.jsonl.gz")
        }
    missing_panels = [f.name for f in files if f.name.replace(".jsonl.gz", "") not in panel_names]
    return {
        "snapshots": len(files),
        "first": stamps[0].isoformat() if stamps else None,
        "last": stamps[-1].isoformat() if stamps else None,
        "gap_threshold_minutes": max_gap_minutes,
        "gaps_over_threshold": gaps,
        "max_gap_minutes": max((g["minutes"] for g in gaps), default=0),
        "snapshots_missing_summary": [n for n, c in counts.items() if c is None],
        "contracts_first": counts.get(files[0].name) if files else None,
        "contracts_last": counts.get(files[-1].name) if files else None,
        "snapshots_without_panel_partition": missing_panels,
        "panel_partitions": len(panel_names),
    }


def _rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def settlement_validation(
    latest_panel: list[dict[str, Any]], games: pd.DataFrame
) -> dict[str, Any]:
    """Compare parser-expected outcome to Kalshi's settled result for mapped, completed games."""
    by_id = {int(r["espn_game_id"]): r for r in games.to_dict("records")}
    tally: Counter[str] = Counter()
    mismatches = []
    by_series: dict[str, Counter[str]] = defaultdict(Counter)
    for row in latest_panel:
        result = row.get("result")
        if result not in ("yes", "no") or row.get("espn_game_id") is None:
            continue
        game = by_id.get(int(row["espn_game_id"]))
        sem = row.get("contract_semantics") or {}
        series = str(row.get("series_ticker"))
        if game is None or not game.get("completed"):
            tally["settled_but_game_not_complete_in_archive"] += 1
            by_series[series]["game_not_complete"] += 1
            continue
        hp, ap = game.get("home_score"), game.get("away_score")
        expected, why = settle(
            sem, None if hp is None else int(hp), None if ap is None else int(ap)
        )
        if expected is None:
            tally[f"not_checkable:{why}"] += 1
            by_series[series][f"not_checkable:{why}"] += 1
        elif expected == result:
            tally["agree"] += 1
            by_series[series]["agree"] += 1
        else:
            tally["DISAGREE"] += 1
            by_series[series]["DISAGREE"] += 1
            mismatches.append(
                {"ticker": row.get("kalshi_ticker"), "expected": expected, "kalshi": result,
                 "home": hp, "away": ap, "semantics": sem.get("yes_condition")}
            )  # fmt: skip
    checked = tally["agree"] + tally["DISAGREE"]
    return {
        "checked": checked,
        "agree": tally["agree"],
        "disagree": tally["DISAGREE"],
        "agreement_rate": (tally["agree"] / checked) if checked else None,
        "other": {k: v for k, v in tally.items() if k not in ("agree", "DISAGREE")},
        "by_series": {k: dict(v) for k, v in by_series.items()},
        "mismatches": mismatches[:50],
    }


def calibration(
    panel_rows_by_snapshot: Iterable[list[dict[str, Any]]], settled: dict[str, str]
) -> dict[str, Any]:
    """Brier/log-loss over settled contracts, last PRETIP snapshot per contract only."""
    last: dict[str, dict[str, Any]] = {}
    for rows in panel_rows_by_snapshot:  # chronological
        for r in rows:
            if r.get("market_phase") == "PRETIP":
                last[str(r["kalshi_ticker"])] = r
    out: dict[str, dict[str, Any]] = {}
    for ticker, r in last.items():
        res = settled.get(ticker)
        if res not in ("yes", "no"):
            continue
        for version, pr in (r.get("market_specific_model_probability") or {}).items():
            p = pr.get("probability")
            if p is None:
                continue
            y = 1.0 if res == "yes" else 0.0
            bucket = out.setdefault(
                f"{r['series_ticker']}|{version}", {"n": 0, "brier": 0.0, "ll": 0.0}
            )
            q = min(max(float(p), 1e-6), 1 - 1e-6)
            bucket["n"] += 1
            bucket["brier"] += (q - y) ** 2
            bucket["ll"] += -(y * math.log(q) + (1 - y) * math.log(1 - q))
    return {
        k: {"n": v["n"], "brier": v["brier"] / v["n"], "log_loss": v["ll"] / v["n"]}
        for k, v in sorted(out.items())
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--projections", required=True)
    ap.add_argument("--rosters", default=None)
    ap.add_argument("--scores", default=None)
    ap.add_argument("--schedule-archive", default=None)
    ap.add_argument("--schedule-parquet", default=None)
    ap.add_argument("--kalshi", required=True)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--code-sha", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--calibration", action="store_true", help="scan every partition (slow)")
    args = ap.parse_args()
    from cbb_edge.app.sift_app import selection as S
    from cbb_edge.app.sift_app.__main__ import load_world
    from cbb_edge.app.sift_app.build import games_frame

    panel_root = Path(args.panel)
    report: dict[str, Any] = {"archive": archive_audit(Path(args.kalshi), panel_root)}
    parts = sorted(panel_root.glob("panels/**/*.panel.jsonl.gz"))
    if parts:
        w = load_world(args, S.ts(datetime.now(UTC)))
        games, _ = games_frame(w)
        latest = _rows(parts[-1])
        report["latest_partition"] = parts[-1].name
        report["settlement_validation"] = settlement_validation(latest, games)
        settled = {
            str(r["kalshi_ticker"]): str(r["result"])
            for r in latest
            if r.get("result") in ("yes", "no")
        }
        if args.calibration:
            report["calibration_settled_pretip"] = calibration((_rows(p) for p in parts), settled)
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
