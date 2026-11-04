"""Market universe + observation loader (dataset 1 and 2) from the immutable archives.

Reads every raw ``kalshi-snapshot-v1`` file (``kalshi-archive``) and, where present, the matching
``cbb-kalshi-model-panel-v2`` partition (``kalshi-panel-archive``). Nothing is filtered by
price, edge, recommendation or model support: every ticker ever captured is one universe row.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def price(m: dict[str, Any], key: str) -> float | None:
    """Dollar price from either ``<key>_dollars`` or legacy integer-cent ``<key>``."""
    d = _f(m.get(f"{key}_dollars"))
    if d is not None:
        return d
    c = _f(m.get(key))
    return None if c is None else c / 100.0


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def snapshot_stamp(path: Path) -> datetime:
    token = path.name.split("_")[-1].split(".")[0]
    return datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


@dataclass
class Obs:
    """A run of consecutive identical quotes: first/last capture time and number of captures."""

    t0: datetime
    t1: datetime
    n: int
    status: str
    yes_bid: float | None
    yes_ask: float | None
    last: float | None
    bid_sz: float | None
    ask_sz: float | None
    volume: float | None
    oi: float | None

    def key(self) -> tuple[Any, ...]:
        return (self.status, self.yes_bid, self.yes_ask, self.last, self.bid_sz, self.ask_sz,
                self.volume, self.oi)  # fmt: skip


@dataclass
class ModelPoint:
    t: datetime
    probs: dict[str, float]  # version -> probability (only versions that produced one)
    gaps: dict[str, str]  # version -> reason no probability exists


@dataclass
class Contract:
    ticker: str
    series: str
    family: str
    event_ticker: str = ""
    title: str = ""
    yes_sub_title: str = ""
    strike_type: str | None = None
    floor_strike: float | None = None
    cap_strike: float | None = None
    open_time: str | None = None
    close_time: str | None = None
    expected_expiration: str | None = None
    settlement_ts: str | None = None
    result: str | None = None
    settlement_value: float | None = None
    last_status: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    first_snapshot: str = ""
    last_snapshot: str = ""
    n_snapshots: int = 0
    n_with_event: int = 0
    n_with_orderbook: int = 0
    series_meta: dict[str, Any] | None = None
    series_meta_at: datetime | None = None  # first capture that carried the series fee fields
    obs: list[Obs] = field(default_factory=list)
    raw_last: dict[str, Any] = field(default_factory=dict)
    # panel-derived
    n_panel_rows: int = 0
    mapping_reason: str | None = None
    espn_game_id: int | None = None
    game_start: datetime | None = None
    semantics: dict[str, Any] | None = None
    models: list[ModelPoint] = field(default_factory=list)  # PRETIP rows only


def iter_snapshot_files(root: Path) -> list[Path]:
    return sorted(root.glob("snapshots/**/kalshi_cbb_*.jsonl.gz"), key=snapshot_stamp)


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


_KEEP_RAW = (
    "ticker", "event_ticker", "title", "yes_sub_title", "no_sub_title", "rules_primary",
    "market_type", "strike_type", "floor_strike", "cap_strike", "custom_strike", "open_time",
    "close_time", "expected_expiration_time", "expiration_time", "settlement_ts", "result",
    "settlement_value_dollars", "status", "can_close_early", "occurrence_datetime",
)  # fmt: skip


def load_universe(kalshi_root: Path) -> tuple[dict[str, Contract], list[dict[str, Any]]]:
    """Return (contracts by ticker, per-snapshot ledger). Missing data stays explicit."""
    contracts: dict[str, Contract] = {}
    ledger: list[dict[str, Any]] = []
    for path in iter_snapshot_files(kalshi_root):
        at = snapshot_stamp(path)
        name = path.name.replace(".jsonl.gz", "")
        n = 0
        for raw in _rows(path):
            m = raw.get("market") or {}
            tk = str(m.get("ticker") or "")
            if not tk:
                continue
            n += 1
            c = contracts.get(tk)
            if c is None:
                c = contracts[tk] = Contract(
                    ticker=tk,
                    series=str(raw.get("series_ticker") or ""),
                    family=str(raw.get("family") or "OTHER"),
                    first_seen=at,
                    first_snapshot=name,
                )
            c.last_seen, c.last_snapshot, c.n_snapshots = at, name, c.n_snapshots + 1
            c.family = str(raw.get("family") or c.family)
            c.n_with_event += 1 if raw.get("event") else 0
            c.n_with_orderbook += 1 if raw.get("orderbook") else 0
            c.event_ticker = str(m.get("event_ticker") or c.event_ticker)
            c.title = str(m.get("title") or c.title)
            c.yes_sub_title = str(m.get("yes_sub_title") or c.yes_sub_title)
            c.strike_type = m.get("strike_type") or c.strike_type
            c.floor_strike = (
                _f(m.get("floor_strike")) if m.get("floor_strike") is not None else c.floor_strike
            )
            c.cap_strike = (
                _f(m.get("cap_strike")) if m.get("cap_strike") is not None else c.cap_strike
            )
            c.open_time = m.get("open_time") or c.open_time
            c.close_time = m.get("close_time") or c.close_time
            c.expected_expiration = m.get("expected_expiration_time") or c.expected_expiration
            c.settlement_ts = m.get("settlement_ts") or c.settlement_ts
            res = m.get("result")
            if res not in (None, ""):
                c.result = str(res)
            sv = _f(m.get("settlement_value_dollars"))
            if sv is not None and c.result:
                c.settlement_value = sv
            if raw.get("series_meta"):
                c.series_meta = raw["series_meta"]
                if c.series_meta_at is None:
                    c.series_meta_at = at
            c.last_status = str(m.get("status") or "")
            c.raw_last = {k: m[k] for k in _KEEP_RAW if k in m}
            o = Obs(
                t0=at, t1=at, n=1, status=c.last_status,
                yes_bid=price(m, "yes_bid"), yes_ask=price(m, "yes_ask"),
                last=price(m, "last_price"), bid_sz=_f(m.get("yes_bid_size_fp")),
                ask_sz=_f(m.get("yes_ask_size_fp")), volume=_f(m.get("volume_fp")),
                oi=_f(m.get("open_interest_fp")),
            )  # fmt: skip
            if c.obs and c.obs[-1].key() == o.key():
                c.obs[-1].t1, c.obs[-1].n = at, c.obs[-1].n + 1
            else:
                c.obs.append(o)
        ledger.append({"snapshot": name, "captured_at": at.isoformat(), "contracts": n})
    return contracts, ledger


def attach_panel(contracts: dict[str, Contract], panel_root: Path | None) -> dict[str, Any]:
    """Join frozen as-of model probabilities / identity from panel partitions (if any)."""
    info: dict[str, Any] = {"partitions": 0, "rows": 0, "snapshots_with_panel": []}
    if panel_root is None:
        return info
    files = sorted(panel_root.glob("panels/**/*.panel.jsonl.gz"))
    for path in files:
        info["partitions"] += 1
        info["snapshots_with_panel"].append(path.name.replace(".panel.jsonl.gz", ""))
        for row in _rows(path):
            c = contracts.get(str(row.get("kalshi_ticker") or ""))
            if c is None:
                continue
            info["rows"] += 1
            c.n_panel_rows += 1
            c.mapping_reason = row.get("mapping_reason")
            if row.get("espn_game_id") is not None:
                c.espn_game_id = int(row["espn_game_id"])
            gs = parse_ts(row.get("game_start_utc"))
            if gs is not None:
                c.game_start = gs
            if row.get("contract_semantics"):
                c.semantics = row["contract_semantics"]
            if row.get("market_phase") != "PRETIP":
                continue
            probs: dict[str, float] = {}
            gaps: dict[str, str] = {}
            for ver, pr in (row.get("market_specific_model_probability") or {}).items():
                if pr.get("probability") is not None:
                    probs[ver] = float(pr["probability"])
                else:
                    gaps[ver] = str(pr.get("method_or_gap"))
            at = parse_ts(row.get("captured_at"))
            if at is None:
                continue
            if c.models and c.models[-1].probs == probs and c.models[-1].gaps == gaps:
                continue  # frozen prediction unchanged
            c.models.append(ModelPoint(at, probs, gaps))
    return info


def load_scores(schedule_root: Path | None) -> dict[int, tuple[int, int]]:
    """Official final (home, away) scores by ESPN game id from the schedule archive."""
    out: dict[int, tuple[int, int]] = {}
    if schedule_root is None:
        return out
    for path in sorted(schedule_root.glob("rows/**/*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if (
                    r.get("status_type_completed")
                    and r.get("home_score") is not None
                    and r.get("away_score") is not None
                    and r.get("game_id") is not None
                ):
                    out[int(r["game_id"])] = (int(r["home_score"]), int(r["away_score"]))
    return out
