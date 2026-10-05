"""Read-only Kalshi college-basketball market discovery and full-board capture.

Free, unauthenticated public market-data endpoints only (cost class FREE_RATE_LIMITED).
This module never authenticates and never places, amends or cancels orders.

One capture run:

1. ``GET /series?category=Sports`` -> discover men's college basketball series
   (taxonomy rules in :mod:`cbb_edge.kalshi.taxonomy`);
2. for every CBB series, page ``GET /markets`` for status ``open`` and ``unopened``,
   plus markets that closed/settled in the last ``settled_lookback_h`` hours (so every
   contract's settlement result is archived);
3. optionally ``GET /markets/{ticker}/orderbook`` for markets closing soon;
4. write ONE immutable snapshot file (gzipped JSONL, one market per line, raw API
   payload preserved) + a board-accounting summary.

Snapshots are never overwritten. Over time they form our own free price archive.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cbb_edge.data.http import fetch
from cbb_edge.kalshi.taxonomy import classify_market, is_cbb_series

SOURCE = "kalshi_public"
DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SCHEMA_VERSION = "kalshi-snapshot-v1"


def base_url() -> str:
    return os.environ.get("KALSHI_BASE_URL", DEFAULT_BASE).rstrip("/")


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    # Live market data must not be served from cache: use_cache=False, but each
    # response is still written to bronze (immutable, timestamped) for provenance.
    res = fetch(
        SOURCE,
        f"{base_url()}{path}",
        params=params,
        use_cache=False,
        dest=Path("raw") / datetime.now(UTC).strftime("%Y/%m/%d") / f"{time.time_ns()}.json",
        schema_version="kalshi-api-v2",
        timeout=60,
    )
    assert res is not None
    data: dict[str, Any] = res.json()
    return data


def discover_series() -> list[dict[str, Any]]:
    data = _get("/series", {"category": "Sports"})
    series = data.get("series") or []
    return [s for s in series if is_cbb_series(s)]


def iter_markets(
    series_ticker: str, status: str | None = None, min_close_ts: int | None = None
) -> Iterator[dict[str, Any]]:
    cursor = None
    while True:
        params: dict[str, Any] = {"series_ticker": series_ticker, "limit": 1000}
        if status:
            params["status"] = status
        if min_close_ts:
            params["min_close_ts"] = min_close_ts
        if cursor:
            params["cursor"] = cursor
        data = _get("/markets", params)
        yield from data.get("markets") or []
        cursor = data.get("cursor")
        if not cursor:
            return


def capture(
    out_dir: Path,
    *,
    settled_lookback_h: int = 72,
    orderbook_within_h: float = 0,
    series_override: list[str] | None = None,
) -> dict[str, Any]:
    captured_at = datetime.now(UTC)
    if series_override:
        series = [{"ticker": t, "title": t} for t in series_override]
    else:
        series = discover_series()
    lookback = int((captured_at - timedelta(hours=settled_lookback_h)).timestamp())
    records: dict[str, dict[str, Any]] = {}
    for s in series:
        tk = s["ticker"]
        for status in ("open", "unopened"):
            for m in iter_markets(tk, status=status):
                records[m["ticker"]] = {"series": s, "market": m, "status_query": status}
        for m in iter_markets(tk, min_close_ts=lookback):
            records.setdefault(
                m["ticker"], {"series": s, "market": m, "status_query": "recent_close"}
            )
    books = 0
    if orderbook_within_h > 0:
        horizon = captured_at + timedelta(hours=orderbook_within_h)
        for tk, rec in records.items():
            ct = rec["market"].get("close_time")
            if (
                rec["market"].get("status") in ("open", "active")
                and ct
                and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= horizon
            ):
                rec["orderbook"] = _get(f"/markets/{tk}/orderbook", {"depth": 10})
                books += 1

    out_dir = out_dir / captured_at.strftime("%Y/%m/%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"kalshi_cbb_{stamp}.jsonl.gz"
    fam: Counter[str] = Counter()
    stat: Counter[str] = Counter()
    events: set[str] = set()
    with gzip.open(path, "wt") as fh:
        for tk in sorted(records):
            rec = records[tk]
            m = rec["market"]
            family = classify_market(rec["series"], m)
            fam[family] += 1
            stat[str(m.get("status"))] += 1
            events.add(str(m.get("event_ticker")))
            fh.write(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "captured_at": captured_at.isoformat(),
                        "series_ticker": rec["series"].get("ticker"),
                        "family": family,
                        "status_query": rec["status_query"],
                        "market": m,
                        "orderbook": rec.get("orderbook"),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at.isoformat(),
        "base_url": base_url(),
        "file": str(path),
        "n_series": len(series),
        "series": sorted(s["ticker"] for s in series),
        "n_events": len(events),
        "n_markets": len(records),
        "by_family": dict(fam),
        "by_status": dict(stat),
        "orderbooks": books,
    }
    path.with_name(path.name.replace(".jsonl.gz", ".summary.json")).write_text(
        json.dumps(summary, indent=1, sort_keys=True)
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/kalshi/snapshots")
    ap.add_argument("--settled-lookback-h", type=int, default=72)
    ap.add_argument("--orderbook-within-h", type=float, default=0.0)
    ap.add_argument("--series", nargs="*", help="override discovery with explicit tickers")
    a = ap.parse_args()
    summary = capture(
        Path(a.out),
        settled_lookback_h=a.settled_lookback_h,
        orderbook_within_h=a.orderbook_within_h,
        series_override=a.series,
    )
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
