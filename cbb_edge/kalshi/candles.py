"""Recovered Kalshi candlestick data for contracts whose pregame quotes we missed.

Official public endpoint (free, unauthenticated, cost class FREE_RATE_LIMITED)::

    GET /series/{series_ticker}/markets/{ticker}/candlesticks
        ?start_ts=<unix s>&end_ts=<unix s>&period_interval=<1|60|1440 minutes>

This is a proof-of-concept recovery path for the gap contracts the research engine labels
``capture_gap_first_captured_after_tip`` / ``captured_pretip_but_book_empty_or_non_live_status``
(or that lack the ``H1``/``CLOSE`` entry points). Hard rules:

* candle data is stored in a SEPARATE immutable archive (``candles/YYYY/MM/DD/<stamp>.jsonl``),
  never in the live snapshot archive, and live capture never imports this module;
* every record carries ``executable=False`` and
  ``provenance="recovered_candle_not_top_of_book"``: a candle OHLC is an aggregate over a period,
  NOT a top-of-book quote. It has no bid/ask size and must never feed a hypothetical fill;
* the raw API response is stored verbatim next to the parsed form;
* a failed request becomes an explicit error record and is retried at most
  ``MAX_ERROR_ATTEMPTS`` times across all runs.

    python -m cbb_edge.kalshi.candles --universe universe.jsonl.gz --archive candles_archive
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cbb_edge.data import cost_policy
from cbb_edge.data.http import fetch
from cbb_edge.kalshi.capture import SOURCE as HTTP_SOURCE
from cbb_edge.kalshi.capture import base_url

SCHEMA_VERSION = "kalshi-candles-v1"
RECORD_SOURCE = "kalshi_candlestick_api"
PROVENANCE = "recovered_candle_not_top_of_book"
CANDLE_LABEL = "approximate_close_not_top_of_book"

GAP_REASONS = frozenset(
    {"capture_gap_first_captured_after_tip", "captured_pretip_but_book_empty_or_non_live_status"}
)
# Causes where no pregame quote can exist, or the tip is unknown: never targeted.
NEVER_TARGET_REASONS = frozenset(
    {
        "listed_after_tip_live_line_no_pregame_quote_exists",
        "non_game_market_never_quoted",
        "no_verified_tip",
    }
)
WANTED_ENTRIES = ("H1", "CLOSE")
VALID_INTERVALS = (1, 60, 1440)
DEFAULT_INTERVAL = 60
DEFAULT_MAX_TARGETS = 150
DEFAULT_SLEEP_S = 0.5
DEFAULT_LOOKBACK_H = 24.0
MAX_ERROR_ATTEMPTS = 3
FETCH_ATTEMPTS = 3
OHLC = ("open", "high", "low", "close")


def _ts(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class Target:
    ticker: str
    series: str
    family: str
    game_start: datetime
    reason: str  # why it was selected

    def window(self, lookback_h: float = DEFAULT_LOOKBACK_H) -> tuple[int, int]:
        """(start_ts, end_ts): the lookback before tip up to tip. Ends at tip so no post-tip
        (live-line) candle is ever requested."""
        end = int(self.game_start.timestamp())
        return end - int(lookback_h * 3600), end


def target_reason(row: dict[str, Any]) -> str | None:
    """Selection rule for one universe row, or None when it must not be targeted."""
    gap = row.get("pretip_gap_reason")
    if gap in NEVER_TARGET_REASONS:
        return None
    if _ts(row.get("game_start")) is None or not row.get("ticker") or not row.get("series"):
        return None
    if gap in GAP_REASONS:
        return str(gap)
    missing = row.get("entry_points_missing") or []
    if any(e in missing for e in WANTED_ENTRIES):
        return "entry_points_missing:" + ",".join(e for e in WANTED_ENTRIES if e in missing)
    return None


def read_universe(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def window_key(ticker: str, interval: int, start_ts: int, end_ts: int) -> tuple[Any, ...]:
    return (ticker, int(interval), int(start_ts), int(end_ts))


def select_targets(
    universe_jsonl_gz: Path | list[dict[str, Any]],
    *,
    max_targets: int = DEFAULT_MAX_TARGETS,
    now: datetime | None = None,
    skip: set[tuple[Any, ...]] | None = None,
    interval: int = DEFAULT_INTERVAL,
    lookback_h: float = DEFAULT_LOOKBACK_H,
) -> list[Target]:
    """Gap contracts to recover, oldest tip first, capped at ``max_targets``.

    Only games whose tip has already passed are eligible (the window ends at tip). Contracts
    whose window is in ``skip`` (already archived / error budget spent) are removed BEFORE the
    cap so a backlog drains across runs instead of re-selecting the same head forever.
    """
    rows = (
        read_universe(universe_jsonl_gz)
        if isinstance(universe_jsonl_gz, Path)
        else universe_jsonl_gz
    )
    now = now or datetime.now(UTC)
    out: list[Target] = []
    for r in rows:
        reason = target_reason(r)
        gs = _ts(r.get("game_start"))
        if reason is None or gs is None or gs > now:
            continue
        t = Target(str(r["ticker"]), str(r["series"]), str(r.get("family") or "OTHER"), gs, reason)
        s, e = t.window(lookback_h)
        if skip and window_key(t.ticker, interval, s, e) in skip:
            continue
        out.append(t)
    out.sort(key=lambda t: (t.game_start, t.ticker))
    return out[: max(0, max_targets)]


# --------------------------------------------------------------------------- fetch + parse


def fetch_candles(
    series: str, ticker: str, start_ts: int, end_ts: int, interval: int = DEFAULT_INTERVAL
) -> dict[str, Any]:
    """One bounded request (<= FETCH_ATTEMPTS HTTP attempts inside ``fetch``). Returns the raw
    JSON object. Raises on failure; callers turn that into an explicit error record."""
    if interval not in VALID_INTERVALS:
        raise ValueError(f"period_interval must be one of {VALID_INTERVALS}, got {interval}")
    res = fetch(
        HTTP_SOURCE,
        f"{base_url()}/series/{series}/markets/{ticker}/candlesticks",
        params={"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": interval},
        use_cache=False,
        dest=Path("raw_candles")
        / datetime.now(UTC).strftime("%Y/%m/%d")
        / f"{time.time_ns()}.json",
        schema_version="kalshi-api-v2-candles",
        timeout=60,
        max_attempts=FETCH_ATTEMPTS,
        not_found_ok=True,
    )
    if res is None:
        raise LookupError("http_404_not_found")
    data = res.json()
    if not isinstance(data, dict):
        raise ValueError("unexpected_response_shape")
    return data


def _num(v: Any) -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _price(d: Any, key: str) -> float | None:
    """Dollar value from ``<key>_dollars`` (string/float) or legacy integer-cent ``<key>``."""
    if not isinstance(d, dict):
        return None
    dollars = _num(d.get(f"{key}_dollars"))
    if dollars is not None:
        return dollars
    cents = _num(d.get(key))
    return None if cents is None else cents / 100.0


def _ohlc(d: Any) -> dict[str, float | None]:
    return {k: _price(d, k) for k in OHLC}


def parse_candles(raw: Any) -> list[dict[str, Any]]:
    """Parse a candlesticks response defensively; unparseable entries are skipped (the raw
    response is always stored next to the parsed form)."""
    items = raw.get("candlesticks") if isinstance(raw, dict) else None
    out: list[dict[str, Any]] = []
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict):
            continue
        end = _num(c.get("end_period_ts"))
        if end is None:
            continue
        vol = _num(c.get("volume"))
        if vol is None:
            vol = _num(c.get("volume_fp"))
        oi = _num(c.get("open_interest"))
        if oi is None:
            oi = _num(c.get("open_interest_fp"))
        out.append(
            {
                "end_period_ts": int(end),
                "yes_bid": _ohlc(c.get("yes_bid")),
                "yes_ask": _ohlc(c.get("yes_ask")),
                "price": _ohlc(c.get("price")),
                "volume": vol,
                "open_interest": oi,
            }
        )
    out.sort(key=lambda x: x["end_period_ts"])
    return out


def build_record(
    target: Target,
    interval: int,
    start_ts: int,
    end_ts: int,
    *,
    raw: dict[str, Any] | None,
    error: str | None,
    fetched_at: datetime,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "ticker": target.ticker,
        "series": target.series,
        "family": target.family,
        "target_reason": target.reason,
        "game_start": target.game_start.isoformat(),
        "interval": interval,
        "window": {"start_ts": start_ts, "end_ts": end_ts},
        "status": "error" if error else "ok",
        "error": error,
        "raw_response": raw,
        "candles": [] if error else parse_candles(raw),
        "fetched_at": fetched_at.isoformat(),
        "source": RECORD_SOURCE,
        "executable": False,
        "provenance": PROVENANCE,
    }


# --------------------------------------------------------------------------- archive


def iter_archive_records(root: Path) -> Iterator[dict[str, Any]]:
    for p in sorted(root.glob("candles/**/*.jsonl")):
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def archived_state(root: Path) -> tuple[set[tuple[Any, ...]], dict[tuple[Any, ...], int]]:
    """(windows with a successful record, error-record count per window)."""
    done: set[tuple[Any, ...]] = set()
    errors: dict[tuple[Any, ...], int] = defaultdict(int)
    for r in iter_archive_records(root):
        w = r.get("window") or {}
        k = window_key(r["ticker"], r["interval"], w.get("start_ts", 0), w.get("end_ts", 0))
        if r.get("status") == "ok":
            done.add(k)
        else:
            errors[k] += 1
    return done, errors


def skip_set(root: Path) -> set[tuple[Any, ...]]:
    done, errors = archived_state(root)
    return done | {k for k, n in errors.items() if n >= MAX_ERROR_ATTEMPTS}


def write_partition(root: Path, records: list[dict[str, Any]], now: datetime) -> Path | None:
    """Append ONE new immutable partition file; existing files are never opened for writing."""
    if not records:
        return None
    day = root / "candles" / now.strftime("%Y/%m/%d")
    day.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    for n in range(100):
        path = day / (f"{stamp}.jsonl" if n == 0 else f"{stamp}_{n}.jsonl")
        try:
            with path.open("x", encoding="utf-8") as fh:  # exclusive create: never overwrite
                for r in records:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
            return path
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate an unused candle partition name")


def collect(
    universe: Path | list[dict[str, Any]],
    root: Path,
    *,
    max_targets: int = DEFAULT_MAX_TARGETS,
    interval: int = DEFAULT_INTERVAL,
    lookback_h: float = DEFAULT_LOOKBACK_H,
    sleep_s: float = DEFAULT_SLEEP_S,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Select, fetch (one bounded request per window), and archive. Never raises on a single
    failed request; a cost-policy violation is a bug and propagates."""
    now = now or datetime.now(UTC)
    targets = select_targets(
        universe,
        max_targets=max_targets,
        now=now,
        skip=skip_set(root),
        interval=interval,
        lookback_h=lookback_h,
    )
    summary: dict[str, Any] = {
        "targets": len(targets),
        "dry_run": dry_run,
        "ok": 0,
        "errors": 0,
        "candles": 0,
        "partition": None,
    }
    if dry_run:
        summary["sample"] = [t.ticker for t in targets[:10]]
        return summary
    records: list[dict[str, Any]] = []
    try:
        for i, t in enumerate(targets):
            if i and sleep_s > 0:
                time.sleep(sleep_s)
            s, e = t.window(lookback_h)
            try:
                raw = fetch_candles(t.series, t.ticker, s, e, interval)
                rec = build_record(
                    t, interval, s, e, raw=raw, error=None, fetched_at=datetime.now(UTC)
                )
                summary["ok"] += 1
                summary["candles"] += len(rec["candles"])
            except cost_policy.CostPolicyViolation:
                raise
            except Exception as exc:  # noqa: BLE001 - recorded explicitly, never dropped
                msg = f"{type(exc).__name__}: {exc}"[:500]
                rec = build_record(
                    t, interval, s, e, raw=None, error=msg, fetched_at=datetime.now(UTC)
                )
                summary["errors"] += 1
            records.append(rec)
    finally:
        path = write_partition(root, records, now)  # partial progress is still archived
        summary["partition"] = str(path) if path else None
    return summary


# --------------------------------------------------------------------------- loader + helpers


@dataclass(frozen=True)
class CandleObs:
    """One recovered candle. Never a top-of-book quote: no sizes, never executable."""

    ticker: str
    end_period_ts: int
    interval: int
    yes_bid: dict[str, float | None]
    yes_ask: dict[str, float | None]
    price: dict[str, float | None]
    volume: float | None
    open_interest: float | None
    fetched_at: str
    source: str = "candle"
    executable: bool = False
    bid_size: float | None = None
    ask_size: float | None = None


def load_candle_quotes(root: Path) -> dict[str, list[CandleObs]]:
    """Per-ticker candle observations sorted by end_period_ts. Error records are ignored; a
    candle seen in several records (overlapping windows) keeps the earliest fetch."""
    seen: dict[tuple[str, int, int], CandleObs] = {}
    for r in iter_archive_records(root):
        if r.get("status") != "ok":
            continue
        for c in r.get("candles") or []:
            k = (r["ticker"], int(r["interval"]), int(c["end_period_ts"]))
            if k in seen:
                continue
            seen[k] = CandleObs(
                ticker=r["ticker"],
                end_period_ts=int(c["end_period_ts"]),
                interval=int(r["interval"]),
                yes_bid=dict(c.get("yes_bid") or {}),
                yes_ask=dict(c.get("yes_ask") or {}),
                price=dict(c.get("price") or {}),
                volume=c.get("volume"),
                open_interest=c.get("open_interest"),
                fetched_at=str(r.get("fetched_at") or ""),
            )
    out: dict[str, list[CandleObs]] = defaultdict(list)
    for o in seen.values():
        out[o.ticker].append(o)
    for v in out.values():
        v.sort(key=lambda o: (o.end_period_ts, o.interval))
    return dict(out)


def candle_close_before(
    ticker_obs: list[CandleObs], cutoff: datetime | float | int
) -> dict[str, Any] | None:
    """Latest candle whose ``end_period_ts <= cutoff`` as a labelled APPROXIMATE closing price
    (accurate only to +/- one candle interval; not top of book; not executable)."""
    cut = cutoff.timestamp() if isinstance(cutoff, datetime) else float(cutoff)
    best: CandleObs | None = None
    for o in ticker_obs:
        if o.end_period_ts <= cut and (best is None or o.end_period_ts >= best.end_period_ts):
            best = o
    if best is None:
        return None
    return {
        "label": CANDLE_LABEL,
        "source": best.source,
        "executable": False,
        "bid_size": None,
        "ask_size": None,
        "end_period_ts": best.end_period_ts,
        "interval_minutes": best.interval,
        "tolerance_minutes": best.interval,
        "minutes_before_cutoff": (cut - best.end_period_ts) / 60.0,
        "yes_bid_close": best.yes_bid.get("close"),
        "yes_ask_close": best.yes_ask.get("close"),
        "price_close": best.price.get("close"),
        "candle": best,
    }


def candle_recovery_report(
    universe_rows: list[dict[str, Any]], candle_root: Path
) -> dict[str, Any]:
    """Per family: how many gap contracts got a recoverable candle at/before tip, and how far
    (minutes) the nearest such candle is from tip. Feasibility evidence only."""
    obs = load_candle_quotes(candle_root)
    fetched: set[str] = set()
    errored: set[str] = set()
    for r in iter_archive_records(candle_root):
        (fetched if r.get("status") == "ok" else errored).add(r["ticker"])
    fam: dict[str, dict[str, Any]] = {}
    gaps: dict[str, list[float]] = defaultdict(list)
    for row in universe_rows:
        if target_reason(row) is None:
            continue
        f = str(row.get("family") or "OTHER")
        b = fam.setdefault(
            f,
            {"gap_contracts": 0, "fetched_ok": 0, "fetch_errors_only": 0, "recoverable": 0},
        )
        b["gap_contracts"] += 1
        tk = str(row["ticker"])
        if tk in fetched:
            b["fetched_ok"] += 1
        elif tk in errored:
            b["fetch_errors_only"] += 1
        gs = _ts(row.get("game_start"))
        hit = candle_close_before(obs.get(tk, []), gs) if gs else None
        if hit and any(
            hit[k] is not None for k in ("yes_bid_close", "yes_ask_close", "price_close")
        ):
            b["recoverable"] += 1
            gaps[f].append(round(hit["minutes_before_cutoff"], 1))
    for f, b in fam.items():
        g = sorted(gaps[f])
        b["minutes_before_tip"] = (
            {"min": g[0], "median": statistics.median(g), "max": g[-1]} if g else None
        )
    return {
        "schema": SCHEMA_VERSION,
        "label": CANDLE_LABEL,
        "executable": False,
        "note": "approximate candle closes; not top of book; not used in fills or evaluation",
        "families": dict(sorted(fam.items())),
        "totals": {
            k: sum(b[k] for b in fam.values())
            for k in ("gap_contracts", "fetched_ok", "fetch_errors_only", "recoverable")
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe", required=True, type=Path)
    ap.add_argument("--archive", required=True, type=Path, help="checkout of the candles archive")
    ap.add_argument("--max-targets", type=int, default=DEFAULT_MAX_TARGETS)
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, choices=VALID_INTERVALS)
    ap.add_argument("--lookback-h", type=float, default=DEFAULT_LOOKBACK_H)
    ap.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S)
    ap.add_argument("--dry-run", action="store_true", help="select targets only; no requests")
    a = ap.parse_args()
    a.archive.mkdir(parents=True, exist_ok=True)
    summary = collect(
        a.universe,
        a.archive,
        max_targets=a.max_targets,
        interval=a.interval,
        lookback_h=a.lookback_h,
        sleep_s=a.sleep,
        dry_run=a.dry_run,
    )
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
