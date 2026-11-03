"""Per-contract market evaluation (dataset 5), independent of any recommendation.

For every contract in the universe this module derives, WITHOUT ever dropping a contract:

* independent status dimensions (observation / mapping / support / model / outcome / official
  check) and a list of overlapping ``status_flags``;
* entry points (OPEN, 24h, 6h, 1h before reference, CLOSE) built only from real captures. A missing
  entry point stays missing: no quote is ever interpolated or invented;
* market-implied scoring (Brier / log loss of the midpoint vs the outcome);
* frozen-model scoring and model-vs-market EV at the same observation (paired);
* hypothetical taker fills with explicit assumptions and fee-correct returns / CLV.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cbb_edge.kalshi.research import fees
from cbb_edge.kalshi.research.universe import Contract, Obs, parse_ts
from cbb_edge.kalshi.semantics import settle

LIVE_STATUSES = frozenset({"active", "open"})
ENTRY_POINTS: tuple[tuple[str, float | None], ...] = (
    ("OPEN", None),
    ("H24", 24.0),
    ("H6", 6.0),
    ("H1", 1.0),
    ("CLOSE", None),
)
ORDER_CONTRACTS = fees.REFERENCE_CONTRACTS
CLIP = 1e-4
FILL_ASSUMPTION = (
    f"hypothetical taker order of {ORDER_CONTRACTS} contracts at the displayed best price; filled "
    "only if the displayed top-of-book size covers it; no partial fills, no queue, no price "
    "impact, no maker orders; fee per fees.py"
)


def mid_of(o: Obs) -> float | None:
    b, a = o.yes_bid, o.yes_ask
    if b is None or a is None or b <= 0.0 or a >= 1.0 or a < b:
        return None
    return (a + b) / 2.0


def _tier(spread: float | None, ask_sz: float | None, stale_min: float | None) -> str:
    """Data-quality tier of ONE observation (A best, D no usable midpoint)."""
    if spread is None:
        return "D"
    stale_ok = stale_min is None or stale_min <= 30
    if spread <= 0.05 and (ask_sz or 0) >= ORDER_CONTRACTS and stale_ok:
        return "A"
    if spread <= 0.15:
        return "B"
    return "C"


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    q = min(max(p, CLIP), 1.0 - CLIP)
    return -(y * math.log(q) + (1 - y) * math.log(1.0 - q))


@dataclass
class Resolved:
    """Cutoff/reference timing for one contract."""

    ref: datetime | None
    cutoff: datetime | None
    ref_kind: str  # tip | close_time | none
    tip_verified: bool


def timing(c: Contract) -> Resolved:
    close = parse_ts(c.close_time)
    if c.game_start is not None:
        cutoff = min(c.game_start, close) if close else c.game_start
        return Resolved(c.game_start, cutoff, "tip", True)
    if close is not None:
        return Resolved(close, close, "close_time", False)
    return Resolved(None, None, "none", False)


def obs_time(o: Obs, cutoff: datetime | None) -> datetime:
    """Latest capture time of this quote run that is strictly before the cutoff."""
    return o.t1 if cutoff is None or o.t1 < cutoff else o.t0


def usable(o: Obs, cutoff: datetime | None) -> bool:
    if o.status not in LIVE_STATUSES:
        return False
    if cutoff is not None and o.t0 >= cutoff:
        return False
    return mid_of(o) is not None or any(fees.side_prices(o.yes_bid, o.yes_ask).values())


def pick_entries(c: Contract, tm: Resolved) -> dict[str, tuple[Obs, datetime] | None]:
    cand = [(o, obs_time(o, tm.cutoff)) for o in c.obs if usable(o, tm.cutoff)]
    out: dict[str, tuple[Obs, datetime] | None] = {k: None for k, _ in ENTRY_POINTS}
    if not cand:
        return out
    out["OPEN"] = (cand[0][0], cand[0][0].t0)
    out["CLOSE"] = cand[-1]
    if tm.ref is not None:
        for name, hours in ENTRY_POINTS:
            if hours is None:
                continue
            limit = tm.ref - timedelta(hours=hours)
            best = None
            for o, t in cand:
                if o.t0 <= limit:
                    best = (o, min(t, limit) if t > limit else t)
            out[name] = best
    return out


def model_at(c: Contract, t: datetime) -> tuple[dict[str, float], dict[str, str]]:
    """Frozen prediction in force at quote time ``t`` (never a later one)."""
    best = None
    for mp in c.models:
        if mp.t <= t:
            best = mp
    return (best.probs, best.gaps) if best else ({}, {})


def status_dimensions(c: Contract, scores: dict[int, tuple[int, int]]) -> dict[str, Any]:
    tm = timing(c)
    priced = any(usable(o, tm.cutoff) for o in c.obs)
    res = c.result if c.result in ("yes", "no") else None
    if res:
        outcome = "SETTLED"
    elif c.result:
        outcome = f"VOID_OR_NONBINARY:{c.result}"
    elif c.last_status in ("finalized", "settled", "determined"):
        outcome = "FINALIZED_NO_RESULT_RECORDED"
    else:
        outcome = "UNSETTLED"
    r = c.mapping_reason
    if c.n_panel_rows == 0:
        mapping = "NO_PANEL_ROW"
    elif r == "ok":
        mapping = "MATCHED"
    elif r == "non_game_market":
        mapping = "NON_GAME"
    else:
        mapping = f"UNMATCHED:{r}"
    sem = c.semantics or {}
    if sem.get("status") == "parsed":
        support = "SUPPORTED"
    elif mapping == "NON_GAME":
        support = "UNSUPPORTED:non_game_market_no_payoff_parser"
    elif mapping.startswith("UNMATCHED") or mapping == "NO_PANEL_ROW":
        support = "UNSUPPORTED:unmapped_so_payoff_unparsed"
    else:
        support = f"UNSUPPORTED:{sem.get('status') or 'no_validated_payoff_parser'}"
    modeled = any(mp.probs for mp in c.models)
    if modeled:
        model = "MODELED"
        model_reason = None
    else:
        if mapping == "NO_PANEL_ROW":
            model_reason = "no_panel_partition_for_any_snapshot_of_this_contract"
        elif mapping == "NON_GAME":
            model_reason = "non_game_market:no_model_capability"
        elif mapping.startswith("UNMATCHED"):
            model_reason = f"cannot_link_to_game:{r}"
        elif not c.models:
            model_reason = "no_pretip_frozen_projection_available"
        else:
            gaps = sorted({g for mp in c.models for g in mp.gaps.values()})
            model_reason = ";".join(gaps) or "no_frozen_projection_version_at_any_pretip_capture"
        model = "UNMODELED"
    official = "NOT_APPLICABLE"
    if res and sem.get("status") == "parsed" and c.espn_game_id is not None:
        sc = scores.get(c.espn_game_id)
        if sc is None:
            official = "GAME_NOT_COMPLETE_IN_ARCHIVE"
        else:
            exp, why = settle(sem, sc[0], sc[1])
            if exp is None:
                official = f"NOT_CHECKABLE:{why}"
            else:
                official = "CONFIRMED" if exp == res else "DISAGREE"
    return {
        "observation": "PRICED" if priced else "NEVER_PRICED_PRETIP",
        "mapping": mapping,
        "support": support,
        "model": model,
        "model_missing_capability": model_reason,
        "outcome": outcome,
        "official_check": official,
        "timing": tm.ref_kind,
        "tip_verified": tm.tip_verified,
    }


def pretip_gap_reason(c: Contract, tm: Resolved) -> str | None:
    """Why a contract has no usable pre-tip quote (None when it has one). Causes are exclusive:
    a live line that did not exist pregame is NOT a capture gap and is never 'recovered'."""
    if any(usable(o, tm.cutoff) for o in c.obs):
        return None
    if c.mapping_reason == "non_game_market":
        return "non_game_market_never_quoted"
    if c.game_start is None:
        return "no_verified_tip"
    opened = parse_ts(c.open_time)
    if opened is not None and opened >= c.game_start:
        return "listed_after_tip_live_line_no_pregame_quote_exists"
    if c.first_seen is not None and c.first_seen >= c.game_start:
        return "capture_gap_first_captured_after_tip"
    return "captured_pretip_but_book_empty_or_non_live_status"


def evaluate_contract(
    c: Contract, scores: dict[int, tuple[int, int]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dims = status_dimensions(c, scores)
    rule = fees.rule_for(c.series_meta, (c.first_seen or datetime.now(UTC)).date())
    tm = timing(c)
    y = 1 if c.result == "yes" else 0 if c.result == "no" else None
    entries = pick_entries(c, tm)
    close_pick = entries["CLOSE"]
    close_mid = mid_of(close_pick[0]) if close_pick else None
    rows: list[dict[str, Any]] = []
    for name, _ in ENTRY_POINTS:
        pick = entries[name]
        if pick is None:
            continue
        o, t = pick
        mid = mid_of(o)
        spread = None if o.yes_bid is None or o.yes_ask is None else o.yes_ask - o.yes_bid
        stale = (tm.cutoff - t).total_seconds() / 60.0 if name == "CLOSE" and tm.cutoff else None
        before = (tm.ref - t).total_seconds() / 3600.0 if tm.ref else None
        probs, gaps = model_at(c, t)
        row: dict[str, Any] = {
            "ticker": c.ticker, "series": c.series, "family": c.family,
            "event": c.event_ticker,
            "cluster": f"G{c.espn_game_id}" if c.espn_game_id else f"E:{c.event_ticker}",
            "entry": name, "t": t.isoformat(), "hours_before_ref": before,
            "ref_kind": tm.ref_kind, "tip_verified": tm.tip_verified,
            "yes_bid": o.yes_bid, "yes_ask": o.yes_ask, "spread": spread, "mid": mid,
            "bid_sz": o.bid_sz, "ask_sz": o.ask_sz, "volume": o.volume,
            "staleness_min": stale, "tier": _tier(spread if mid is not None else None,
                                                  o.ask_sz, stale),
            "y": y, "model": {}, "fee_rule": rule.version, "fee_basis": rule.basis,
        }  # fmt: skip
        if mid is not None and y is not None:
            row["brier_mkt"], row["logloss_mkt"] = brier(mid, y), logloss(mid, y)
        px = fees.side_prices(o.yes_bid, o.yes_ask)
        sizes = {"yes": o.ask_sz, "no": o.bid_sz}
        for side in ("yes", "no"):
            p = px[side]
            fill: dict[str, Any] = {"price": p}
            if p is None:
                fill["fill"] = "NO_QUOTE"
            elif (sz := sizes[side]) is None or sz < ORDER_CONTRACTS:
                fill["fill"] = "INSUFFICIENT_DISPLAYED_SIZE"
            else:
                if not rule.supported:
                    fill["fill"] = "FEE_UNSUPPORTED"
                else:
                    ex = fees.hypothetical_execution(p, ORDER_CONTRACTS, rule)
                    fill["fill"] = "FILLED"
                    fill["kind"] = ex.kind
                    fill["fee"] = ex.fee_per_contract
                    fill["total_cost"] = ex.fee_inclusive_avg_cost
                    if close_mid is not None and name != "CLOSE":
                        close_side = close_mid if side == "yes" else 1.0 - close_mid
                        cl = fees.clv(p, close_side, ORDER_CONTRACTS, rule.taker_rate)
                        fill["clv_gross"], fill["clv_net"] = cl.gross, cl.fee_adjusted
                    if y is not None:
                        won = (y == 1) == (side == "yes")
                        st = ex.settle(won)
                        fill.update(
                            gross_pnl=st["gross_pnl"] / ORDER_CONTRACTS,
                            net_pnl=st["net_pnl"] / ORDER_CONTRACTS,
                            gross_roi=st["gross_roi"],
                            net_roi=st["net_roi"],
                        )
            row[side] = fill
        for ver, pm in probs.items():
            m: dict[str, Any] = {"p": pm}
            if y is not None:
                m["brier"], m["logloss"] = brier(pm, y), logloss(pm, y)
            if mid is not None:
                m["vs_mkt"] = pm - mid
            for side, ps in (("yes", pm), ("no", 1.0 - pm)):
                side_px = px[side]
                if side_px is not None:
                    m[f"ev_{side}"] = fees.expected_value(
                        ps, side_px, ORDER_CONTRACTS, rule.taker_rate
                    )
                m[f"max_entry_{side}"] = fees.breakeven_entry_price(
                    ps, ORDER_CONTRACTS, rule.taker_rate
                )
            row["model"][ver] = m
        row["model_gaps"] = gaps
        rows.append(row)

    close_row = next((r for r in rows if r["entry"] == "CLOSE"), None)
    evaluated = bool(y is not None and close_row is not None and close_row.get("mid") is not None)
    has_evidence = bool(rows) or y is not None
    flags: list[str] = []
    if evaluated:
        flags.append("EVALUATED")
    elif has_evidence:
        flags.append("PARTIAL")
    if dims["model"] == "UNMODELED" and (evaluated or has_evidence):
        flags.append("UNMODELED")
    if dims["outcome"] != "SETTLED":
        flags.append("UNSETTLED")
    if dims["mapping"].startswith("UNMATCHED") or dims["mapping"] == "NO_PANEL_ROW":
        flags.append("UNMATCHED")
    if dims["support"] != "SUPPORTED":
        flags.append("UNSUPPORTED")
    if not has_evidence:
        flags.append("UNOBSERVABLE")
    open_late = None
    ot = parse_ts(c.open_time)
    if entries["OPEN"] is not None and ot is not None:
        open_late = max(0.0, (entries["OPEN"][1] - ot).total_seconds() / 60.0)
    summary = {
        "ticker": c.ticker, "series": c.series, "family": c.family, "event": c.event_ticker,
        "cluster": f"G{c.espn_game_id}" if c.espn_game_id else f"E:{c.event_ticker}",
        "espn_game_id": c.espn_game_id, "title": c.title, "yes_sub_title": c.yes_sub_title,
        "rules": str(c.raw_last.get("rules_primary") or ""),
        "strike_type": c.strike_type, "floor_strike": c.floor_strike, "cap_strike": c.cap_strike,
        "side_semantics": (c.semantics or {}).get("yes_condition"),
        "open_time": c.open_time, "close_time": c.close_time, "settlement_ts": c.settlement_ts,
        "game_start": c.game_start.isoformat() if c.game_start else None,
        "result": c.result, "settlement_value": c.settlement_value, "last_status": c.last_status,
        "first_seen": c.first_seen.isoformat() if c.first_seen else None,
        "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        "first_snapshot": c.first_snapshot, "last_snapshot": c.last_snapshot,
        "n_snapshots": c.n_snapshots, "n_panel_rows": c.n_panel_rows,
        "n_with_orderbook": c.n_with_orderbook, "n_with_event_meta": c.n_with_event,
        "open_observed_late_minutes": open_late,
        "pretip_gap_reason": pretip_gap_reason(c, tm),
        "entry_points_present": [r["entry"] for r in rows],
        "entry_points_missing": [n for n, _ in ENTRY_POINTS if entries[n] is None],
        "models_with_probability": sorted({v for mp in c.models for v in mp.probs}),
        "status_flags": flags, "status": dims,
    }  # fmt: skip
    return summary, rows


def evaluate_all(
    contracts: dict[str, Contract], scores: dict[int, tuple[int, int]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for tk in sorted(contracts):
        s, r = evaluate_contract(contracts[tk], scores)
        summaries.append(s)
        rows.extend(r)
    return summaries, rows
