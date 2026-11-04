"""Market-family evaluation matrix (dataset 5 rollups).

Every statistic reports contract count AND independent cluster count (one cluster = one game, or
one event for non-game markets). Contracts from one game are strongly correlated (a spread ladder,
a total ladder and a winner share one outcome), so headline means are CLUSTER-WEIGHTED (each
cluster counts once) with a cluster bootstrap 90% interval; the raw contract-weighted mean is shown
beside it, never instead of it.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from cbb_edge.kalshi.research.evaluate import ENTRY_POINTS

BOOT = 400
SEED = 20261102
HEADLINE_ENTRY = "CLOSE"
MAX_CLOSE_STALENESS_MIN = 120.0  # a "closing" quote older than this is not a closing price


def confidence(clusters: int) -> str:
    return "LOW" if clusters < 30 else "MEDIUM" if clusters < 100 else "HIGH"


def cluster_mean(pairs: list[tuple[str, float]]) -> dict[str, Any]:
    """Cluster-weighted mean with a cluster-bootstrap 90% CI."""
    if not pairs:
        return {"n": 0, "clusters": 0, "mean": None, "raw_mean": None, "lo": None, "hi": None}
    by: dict[str, list[float]] = defaultdict(list)
    for k, v in pairs:
        by[k].append(v)
    means = [sum(v) / len(v) for v in by.values()]
    est = sum(means) / len(means)
    lo = hi = None
    if len(means) >= 5:
        rng = random.Random(SEED)
        size = len(means)
        draws = sorted(sum(rng.choices(means, k=size)) / size for _ in range(BOOT))
        lo, hi = draws[int(0.05 * BOOT)], draws[int(0.95 * BOOT) - 1]
    return {
        "n": len(pairs), "clusters": len(by), "mean": est,
        "raw_mean": sum(v for _, v in pairs) / len(pairs), "lo": lo, "hi": hi,
    }  # fmt: skip


def cluster_ratio(items: list[tuple[str, float, float]]) -> dict[str, Any]:
    """sum(num)/sum(den) (e.g. net P&L / total cost) with cluster bootstrap 90% CI."""
    if not items:
        return {"n": 0, "clusters": 0, "ratio": None, "lo": None, "hi": None}
    by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for k, a, b in items:
        by[k][0] += a
        by[k][1] += b
    vals = list(by.values())
    den = sum(b for _, b in vals)
    est = sum(a for a, _ in vals) / den if den else None
    lo = hi = None
    if len(vals) >= 5 and den:
        rng = random.Random(SEED)
        draws = []
        for _ in range(BOOT):
            s = rng.choices(vals, k=len(vals))
            d = sum(b for _, b in s)
            if d:
                draws.append(sum(a for a, _ in s) / d)
        draws.sort()
        if len(draws) > 20:
            lo, hi = draws[int(0.05 * len(draws))], draws[int(0.95 * len(draws)) - 1]
    return {"n": len(items), "clusters": len(vals), "ratio": est, "lo": lo, "hi": hi}


def _scored(rows: Iterable[dict[str, Any]], entry: str) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if r["entry"] == entry
        and (
            entry != "CLOSE"
            or not r["tip_verified"]  # the cap is about pregame closes; non-game markets are exempt
            or (r["staleness_min"] or 0.0) <= MAX_CLOSE_STALENESS_MIN
        )
        and r["y"] is not None
        and r.get("mid") is not None
        and (r["tip_verified"] or r["ref_kind"] == "close_time" and r["family"].startswith("FUT"))
    ]


def calibration_buckets(pairs: list[tuple[float, int]], width: float = 0.1) -> list[dict[str, Any]]:
    nb = round(1 / width)
    acc: list[list[float]] = [[0, 0.0, 0.0] for _ in range(nb)]
    for p, y in pairs:
        i = min(int(p / width), nb - 1)
        acc[i][0] += 1
        acc[i][1] += p
        acc[i][2] += y
    return [
        {"lo": i * width, "hi": (i + 1) * width, "n": int(n),
         "mean_pred": s / n, "freq": h / n}
        for i, (n, s, h) in enumerate(acc)
        if n
    ]  # fmt: skip


def _roi(rows: list[dict[str, Any]], side: str) -> dict[str, Any]:
    items = [
        (r["cluster"], r[side]["net_pnl"], r[side]["total_cost"])
        for r in rows
        if r["y"] is not None and r[side].get("fill") == "FILLED" and "net_pnl" in r[side]
    ]
    out = cluster_ratio(items)
    out["gross_pnl_per_contract"] = (
        sum(
            r[side]["gross_pnl"]
            for r in rows
            if r[side].get("fill") == "FILLED" and "gross_pnl" in r[side]
        )
        / len(items)
        if items
        else None
    )
    gross = cluster_ratio(
        [
            (r["cluster"], r[side]["gross_pnl"], r[side]["price"])
            for r in rows
            if r["y"] is not None and r[side].get("fill") == "FILLED" and "gross_pnl" in r[side]
        ]
    )
    out["gross_roi"] = gross["ratio"]
    out["gross_roi_lo"], out["gross_roi_hi"] = gross["lo"], gross["hi"]
    out["fee_basis"] = dict(Counter(r["fee_basis"] for r in rows))
    out["fills"] = len(items)
    out["attempts"] = len(rows)
    return out


def _model_rule_roi(rows: list[dict[str, Any]], ver: str) -> dict[str, Any]:
    """Diagnostic only: buy the side with positive model EV at the displayed price."""
    items = []
    for r in rows:
        m = r["model"].get(ver)
        if not m or r["y"] is None:
            continue
        evs = [(m[f"ev_{s}"], s) for s in ("yes", "no") if f"ev_{s}" in m]
        if not evs:
            continue
        ev, s = max(evs)
        f = r[s]
        if ev > 0 and f.get("fill") == "FILLED" and "net_pnl" in f:
            items.append((r["cluster"], f["net_pnl"], f["total_cost"]))
    return cluster_ratio(items)


def _clv(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Mean of ``key`` over BOTH legs of every row (YES and NO, whatever a model would buy).

    For ``clv_gross``/``clv_net`` (quoted execution: close mid - entry ask) the two legs move in opposite directions,
    so any market movement cancels and the mean is the entry half-spread (plus the fee for ``clv_net``) BY CONSTRUCTION.
    It measures the cost of crossing the spread, not whether a selection beat the close. Use
    ``_model_side_clv(..., "clv_selection")`` for a selection measure."""
    pairs = [(r["cluster"], r[s][key]) for r in rows for s in ("yes", "no") if key in r[s]]
    return cluster_mean(pairs)


def _model_side_clv(rows: list[dict[str, Any]], ver: str, key: str = "clv_selection") -> dict[str, Any]:
    """``key`` on the side the model prefers (higher EV, the same side rule as ``_model_rule_roi`` but without the
    EV > 0 filter), clustered by game. ``clv_selection`` = close mid - entry mid of that side: spread- and fee-free."""
    pairs = []
    for r in rows:
        m = r["model"].get(ver)
        if not m:
            continue
        evs = [(m[f"ev_{s}"], s) for s in ("yes", "no") if f"ev_{s}" in m]
        if not evs:
            continue
        side = max(evs)[1]
        if key in r[side]:
            pairs.append((r["cluster"], r[side][key]))
    return cluster_mean(pairs)


def block(contracts: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The full metric block for one slice of the universe (a family, a series, a day, ...)."""
    st = Counter(c["status"]["outcome"].split(":")[0] for c in contracts)
    flags: Counter[str] = Counter(f for c in contracts for f in c["status_flags"])
    n = len(contracts)
    snaps = sum(c["n_snapshots"] for c in contracts)
    missing_entries = sum(len(c["entry_points_missing"]) for c in contracts)
    modeled = sum(1 for c in contracts if c["status"]["model"] == "MODELED")
    gaps = Counter(
        c["status"]["model_missing_capability"]
        for c in contracts
        if c["status"]["model"] == "UNMODELED"
    )
    close = _scored(rows, HEADLINE_ENTRY)
    mkt_b = cluster_mean([(r["cluster"], r["brier_mkt"]) for r in close])
    mkt_l = cluster_mean([(r["cluster"], r["logloss_mkt"]) for r in close])
    models: dict[str, Any] = {}
    versions = sorted({v for r in close for v in r["model"]})
    for v in versions:
        paired = [r for r in close if v in r["model"] and "brier" in r["model"][v]]
        models[v] = {
            "brier": cluster_mean([(r["cluster"], r["model"][v]["brier"]) for r in paired]),
            "logloss": cluster_mean([(r["cluster"], r["model"][v]["logloss"]) for r in paired]),
            "market_brier_same_contracts": cluster_mean(
                [(r["cluster"], r["brier_mkt"]) for r in paired]
            ),
            # negative => model beat the market on the SAME contracts at the same quote
            "brier_diff_model_minus_market": cluster_mean(
                [(r["cluster"], r["model"][v]["brier"] - r["brier_mkt"]) for r in paired]
            ),
            "logloss_diff_model_minus_market": cluster_mean(
                [(r["cluster"], r["model"][v]["logloss"] - r_ll(r)) for r in paired]
            ),
            "calibration": calibration_buckets([(r["model"][v]["p"], r["y"]) for r in paired]),
        }
    by_entry: dict[str, Any] = {}
    for name, _ in ENTRY_POINTS:
        er = [
            r
            for r in rows
            if r["entry"] == name
            and (
                r["tip_verified"] or r["family"].startswith("FUT") or r["ref_kind"] == "close_time"
            )
        ]
        sc = _scored(rows, name)
        by_entry[name] = {
            "rows": len(er),
            "brier": cluster_mean([(r["cluster"], r["brier_mkt"]) for r in sc]),
            "logloss": cluster_mean([(r["cluster"], r["logloss_mkt"]) for r in sc]),
            "mean_spread": cluster_mean(
                [(r["cluster"], r["spread"]) for r in er if r["spread"] is not None]
            ),
            "yes_buy": _roi(er, "yes"),
            "no_buy": _roi(er, "no"),
            # QUOTED-EXECUTION CLV pooled over both legs: equals the entry half-spread (and fee) by construction.
            "clv_gross": _clv(er, "clv_gross"),
            "clv_fee_adjusted": _clv(er, "clv_net"),
            "clv_pooled_legs_basis": "quoted_execution (close_mid - entry_ask) over YES and NO legs; movement cancels",
            # SELECTION CLV on the model-preferred side (additive, clv-canonical/1).
            "clv_selection_model_side": {v: _model_side_clv(er, v) for v in versions},
            "model_positive_ev_rule": {v: _model_rule_roi(er, v) for v in versions},
        }
    return {
        "discovered_contracts": n,
        "events": len({c["event"] for c in contracts}),
        "clusters": len({c["cluster"] for c in contracts}),
        "captured_snapshots": snaps,
        "snapshots_per_contract": snaps / n if n else None,
        "priced_pretip_contracts": sum(
            1 for c in contracts if c["status"]["observation"] == "PRICED"
        ),
        "model_coverage": {
            "modeled": modeled,
            "unmodeled": n - modeled,
            "share": modeled / n if n else None,
            "unmodeled_reasons": dict(gaps),
        },  # fmt: skip
        "outcome_coverage": {
            "settled": st.get("SETTLED", 0),
            "unsettled": st.get("UNSETTLED", 0),
            "other": {k: v for k, v in st.items() if k not in ("SETTLED", "UNSETTLED")},
        },  # fmt: skip
        "official_check": dict(Counter(c["status"]["official_check"] for c in contracts)),
        "status_flags": dict(flags),
        "scored_contracts_close": len(close),
        "market_brier_close": mkt_b,
        "market_logloss_close": mkt_l,
        "market_calibration_close": calibration_buckets([(r["mid"], r["y"]) for r in close]),
        "models": models,
        "by_entry": by_entry,
        "completeness": {
            "missing_entry_points": missing_entries,
            "contracts_without_any_entry": sum(
                1 for c in contracts if not c["entry_points_present"]
            ),
            "close_staleness_min": _stale_stats(rows),
            "tier_counts_close": dict(Counter(r["tier"] for r in rows if r["entry"] == "CLOSE")),
            "fee_basis_rows": dict(Counter(r["fee_basis"] for r in rows)),
        },  # fmt: skip
        "confidence": confidence(mkt_b["clusters"]),
    }


def _stale_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Closing-quote age for settled, tip-verified (pregame) contracts only: the population the
    120-minute cap applies to. Months-away closes of futures are not a staleness measure."""
    st = sorted(
        r["staleness_min"]
        for r in rows
        if r["entry"] == "CLOSE"
        and r["staleness_min"] is not None
        and r["tip_verified"]
        and r["y"] is not None
    )
    if not st:
        return {"n": 0}
    return {
        "n": len(st), "median": st[len(st) // 2],
        "share_le_60": sum(1 for x in st if x <= 60) / len(st),
        "share_le_120": sum(1 for x in st if x <= MAX_CLOSE_STALENESS_MIN) / len(st),
        "cap_minutes": MAX_CLOSE_STALENESS_MIN,
        "population": "settled contracts with a verified tip",
    }  # fmt: skip


def r_ll(r: dict[str, Any]) -> float:
    return float(r["logloss_mkt"])


def build_matrix(summaries: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_fam: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in summaries:
        by_fam[c["family"]].append(c)
    rows_by_fam: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_by_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        rows_by_fam[r["family"]].append(r)
        rows_by_series[r["series"]].append(r)
    families: dict[str, Any] = {}
    for fam in sorted(by_fam):
        b = block(by_fam[fam], rows_by_fam[fam])
        series: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in by_fam[fam]:
            series[c["series"]].append(c)
        b["series"] = {
            s: block(cs, [r for r in rows_by_series[s] if r["family"] == fam])
            for s, cs in sorted(series.items())
        }
        families[fam] = b
    return {
        "overall": block(summaries, rows),
        "families": families,
        "fill_assumption": __import__(
            "cbb_edge.kalshi.research.evaluate", fromlist=["FILL_ASSUMPTION"]
        ).FILL_ASSUMPTION,
    }


def apply_filter(
    rows: list[dict[str, Any]], pred: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    return [r for r in rows if pred(r)]
