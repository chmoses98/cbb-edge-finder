"""Integrity audit of raw snapshots vs as-of model-panel partitions.

Checks, per snapshot, WITHOUT modifying any archive:
* a panel partition exists (else the snapshot is listed as backlog);
* panel row count == raw market count (every contract accounted for) and no duplicate tickers;
* panel ``captured_at`` equals the raw capture time;
* no frozen projection version has ``as_of`` later than the capture (future leakage) or later
  than the game start (post-tip information in a pre-tip row);
* rows without any projection are labelled (``models_as_of_capture.versions`` empty), not filled.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

from cbb_edge.kalshi.research.universe import iter_snapshot_files, parse_ts


def _lines(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def audit_panels(kalshi_root: Path, panel_root: Path | None) -> dict[str, Any]:
    panels: dict[str, Path] = {}
    if panel_root is not None:
        for p in panel_root.glob("panels/**/*.panel.jsonl.gz"):
            panels[p.name.replace(".panel.jsonl.gz", "")] = p
    raw_files = iter_snapshot_files(kalshi_root)
    backlog: list[str] = []
    problems: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    for raw in raw_files:
        name = raw.name.replace(".jsonl.gz", "")
        part = panels.get(name)
        if part is None:
            backlog.append(name)
            continue
        raw_rows = _lines(raw)
        panel_rows = _lines(part)
        tickers = [str((r.get("market") or {}).get("ticker")) for r in raw_rows]
        ptickers = [str(r.get("kalshi_ticker")) for r in panel_rows]
        totals["partitions_checked"] += 1
        totals["raw_rows"] += len(tickers)
        totals["panel_rows"] += len(ptickers)
        if len(tickers) != len(ptickers) or set(tickers) != set(ptickers):
            problems.append(
                {"snapshot": name, "kind": "row_set_mismatch", "raw": len(tickers),
                 "panel": len(ptickers),
                 "missing_in_panel": len(set(tickers) - set(ptickers)),
                 "extra_in_panel": len(set(ptickers) - set(tickers))}
            )  # fmt: skip
        if len(set(ptickers)) != len(ptickers):
            problems.append({"snapshot": name, "kind": "duplicate_tickers_in_panel"})
        raw_at = parse_ts(raw_rows[0].get("captured_at")) if raw_rows else None
        leak = future = no_proj = 0
        for r in panel_rows:
            p_at = parse_ts(r.get("captured_at"))
            if raw_at is not None and p_at != raw_at:
                problems.append({"snapshot": name, "kind": "captured_at_mismatch",
                                 "ticker": r.get("kalshi_ticker")})  # fmt: skip
                break
            tip = parse_ts(r.get("game_start_utc"))
            vers = ((r.get("models_as_of_capture") or {}).get("versions")) or {}
            if r.get("espn_game_id") is not None and not vers:
                no_proj += 1
            for v in vers.values():
                a = parse_ts(v.get("as_of"))
                if a is None or p_at is None:
                    continue
                if a > p_at:
                    future += 1
                if r.get("market_phase") == "PRETIP" and tip is not None and a > tip:
                    leak += 1
        totals["future_projection_rows"] += future
        totals["posttip_projection_in_pretip_rows"] += leak
        totals["mapped_rows_without_projection"] += no_proj
        if future or leak:
            problems.append({"snapshot": name, "kind": "projection_leakage", "future": future,
                             "post_tip_in_pretip": leak})  # fmt: skip
    orphan = sorted(set(panels) - {r.name.replace(".jsonl.gz", "") for r in raw_files})
    return {
        "raw_snapshots": len(raw_files),
        "panel_partitions": len(panels),
        "backlog_snapshots": backlog,
        "backlog_count": len(backlog),
        "orphan_panels_without_raw": orphan,
        "totals": dict(totals),
        "problems": problems,
        "ok": not problems and not orphan,
    }
