"""Wave 1 Phase 4: what a better score distribution does to Kalshi contract fair values (RESEARCH ONLY).

Nothing here trades, sizes, ranks for execution or recommends. Every contract in the panel archive is
kept in the universe tallies - modelled or not - and prices are never merged: the executable ask (or
the NO price implied by the bid), the hypothetical fill, the fee and the mid are separate columns.

Reuses ``cbb_edge.kalshi.research.challenger.probability`` (the existing contract-semantics ->
probability mapping for FULL-game WINNER / MARGIN / TOTAL, ladders included) by handing it a score
distribution and an identity calibration; reuses ``cbb_edge.kalshi.research.fees`` for costs.
"""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from cbb_edge.kalshi.research import fees
from cbb_edge.kalshi.research.challenger import probability as contract_probability
from cbb_edge.research import wave1 as w

IDENTITY = {"total_bias": 0.0, "margin_sd_scale": 1.0, "total_sd_scale": 1.0}
RESEARCH_ONLY = "RESEARCH_ONLY: no bet, order or recommendation; hypothetical fills are diagnostics"


def settle(sem: dict[str, Any], home: int, away: int) -> int | None:
    """YES outcome of a parsed FULL-game contract from the final score; None if not score-resolvable
    here (halves, team totals, props...)."""
    if sem.get("status") != "parsed" or sem.get("period") != "FULL":
        return None
    t, side = sem.get("market_type"), sem.get("subject_side")
    if t == "WINNER" and side in ("home", "away"):
        return int((home > away) if side == "home" else (away > home))
    if t == "MARGIN" and side in ("home", "away") and sem.get("strike") is not None:
        m = (home - away) if side == "home" else (away - home)
        return int(m > float(sem["strike"]))
    if t == "TOTAL" and sem.get("strike") is not None:
        return int((home + away) > float(sem["strike"]))
    return None


def _px(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load_pretip_contracts(panel_root: Path, game_ids: set[int]) -> dict[str, dict[str, Any]]:
    """Latest PRETIP panel row per ticker for ``game_ids`` (rows captured before the tip only)."""
    best: dict[str, dict[str, Any]] = {}
    for path in sorted(panel_root.glob("panels/**/*.panel.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                g = r.get("espn_game_id")
                if g is None or int(g) not in game_ids or r.get("market_phase") != "PRETIP":
                    continue
                cap, tip = w.parse_ts(r.get("captured_at")), w.parse_ts(r.get("game_start_utc"))
                if cap is None or tip is None or cap >= tip:
                    continue
                cur = best.get(r["kalshi_ticker"])
                if cur is None or cap > cur["_cap"]:
                    r["_cap"] = cap
                    best[r["kalshi_ticker"]] = r
    return best


def universe_tally(panel_root: Path, latest_only: bool = True) -> dict[str, Any]:
    """Counts of EVERY contract in the newest panel partition (futures, props, halves, unmapped...)
    so the full universe stays visible next to the modelled subset."""
    files = sorted(panel_root.glob("panels/**/*.panel.jsonl.gz"))
    if not files:
        return {}
    cnt: Counter[str] = Counter()
    with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            sem = r.get("contract_semantics") or {}
            cnt[
                f"{r.get('family')}|{r.get('market_phase')}|{sem.get('market_type')}|{sem.get('period')}"
            ] += 1
    return {"partition": files[-1].name, "total_contracts": sum(cnt.values()), "by_key": dict(cnt)}


def contract_table(
    panel_root: Path, rows: list[dict[str, Any]], dists: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One record per pre-tip contract of the eligible games. ``dists`` maps a label to a key of
    ``row['proj']`` (frozen versions) or ``row['adapted']`` (challengers)."""
    by_game = {r["game_id"]: r for r in rows}
    latest = load_pretip_contracts(panel_root, set(by_game))
    out: list[dict[str, Any]] = []
    for ticker, p in sorted(latest.items()):
        r = by_game[int(p["espn_game_id"])]
        sem = p.get("contract_semantics") or {}
        yb, ya = _px(p, "yes_bid_dollars"), _px(p, "yes_ask_dollars")
        sides = fees.side_prices(yb, ya)
        rec: dict[str, Any] = {
            "ticker": ticker, "game_id": r["game_id"], "family": p.get("family"),
            "market_type": sem.get("market_type"), "period": sem.get("period"),
            "strike": sem.get("strike"), "subject_side": sem.get("subject_side"),
            "captured_at": p["_cap"].isoformat(), "yes_bid": yb, "yes_ask": ya,
            "yes_ask_size": _px(p, "yes_ask_size_fp"), "yes_bid_size": _px(p, "yes_bid_size_fp"),
            "yes_exec_price": sides["yes"], "no_exec_price": sides["no"],
            "mid": (yb + ya) / 2 if yb is not None and ya is not None and yb > 0 and ya < 1 else None,
            "outcome": settle(sem, r["home"], r["away"]),
        }  # fmt: skip
        modelled = False
        for label, key in dists.items():
            d = r["proj"].get(key) if key in r["proj"] else (r.get("adapted") or {}).get(key)
            pr = contract_probability(sem, d, IDENTITY) if d else None
            rec[f"p[{label}]"] = pr
            modelled = modelled or pr is not None
        rec["model_status"] = (
            "MODELLED" if modelled
            else f"UNMODELLED:{sem.get('model_gap') or sem.get('period') or sem.get('market_type')}"
        )  # fmt: skip
        out.append(rec)
    # main vs alternate: within (game, market_type, subject) the strike whose mid is nearest 50c
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for rec in out:
        if rec["model_status"] == "MODELLED" and rec["period"] == "FULL":
            groups.setdefault(
                (
                    rec["game_id"],
                    rec["market_type"],
                    rec["subject_side"] if rec["market_type"] == "MARGIN" else None,
                ),
                [],
            ).append(rec)
    for g in groups.values():
        cands = [x for x in g if x["mid"] is not None]
        main = min(cands, key=lambda x: abs(x["mid"] - 0.5)) if cands else None
        for x in g:
            x["line_role"] = "main" if x is main else "alt"
    return out, {"n_panel_contracts_pretip_for_eligible_games": len(out)}


def _ev_net(p: float, rec: dict[str, Any]) -> dict[str, Any] | None:
    """Best executable side's net EV per contract at the quoted ask, fees included (diagnostic)."""
    best = None
    for side, px in (("yes", rec["yes_exec_price"]), ("no", rec["no_exec_price"])):
        if px is None:
            continue
        prob = p if side == "yes" else 1 - p
        ev = fees.expected_value(prob, px)
        if best is None or ev > best["ev_net"]:
            best = {"side": side, "price": px, "ev_net": ev, "fee": fees.fee_per_contract(px)}
    return best


def evaluate_contracts(recs: list[dict[str, Any]], labels: list[str]) -> dict[str, Any]:
    """Probability scores and diagnostic hypothetical-fill economics per market type / line role,
    on IDENTICAL contracts (every label present, outcome known, a two-sided mid)."""
    out: dict[str, Any] = {
        "note": RESEARCH_ONLY,
        "universe": dict(Counter(r["model_status"] for r in recs)),
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in recs:
        if r["model_status"] != "MODELLED" or r["outcome"] is None or r["mid"] is None:
            continue
        if any(r.get(f"p[{lb}]") is None for lb in labels):
            continue
        for key in (
            f"{r['market_type']}",
            f"{r['market_type']}:{r.get('line_role', 'main')}",
            "ALL",
        ):
            groups.setdefault(key, []).append(r)
    for key, rs in sorted(groups.items()):
        entry: dict[str, Any] = {"n_contracts": len(rs), "n_games": len({r["game_id"] for r in rs})}
        entry["market_mid"] = {
            "brier": w.mean([w.brier(r["mid"], r["outcome"]) for r in rs]),
            "logloss": w.mean([w.logloss(r["mid"], r["outcome"]) for r in rs]),
        }
        for lb in labels:
            ps = [r[f"p[{lb}]"] for r in rs]
            evs = [_ev_net(p, r) for p, r in zip(ps, rs, strict=True)]
            pos = [(e, r) for e, r in zip(evs, rs, strict=True) if e and e["ev_net"] > 0]
            hyp = []
            for e, r in pos:
                won = r["outcome"] if e["side"] == "yes" else 1 - r["outcome"]
                hyp.append(fees.realized_return(bool(won), e["price"])["net_pnl"])
            entry[lb] = {
                "brier": w.mean([w.brier(p, r["outcome"]) for p, r in zip(ps, rs, strict=True)]),
                "logloss": w.mean([w.logloss(p, r["outcome"]) for p, r in zip(ps, rs, strict=True)]),
                "mean_prob": w.mean(ps),
                "mean_abs_model_minus_mid": w.mean([abs(p - r["mid"]) for p, r in zip(ps, rs, strict=True)]),
                "n_positive_net_ev_at_ask": len(pos),
                "mean_net_ev_of_positive_at_ask": w.mean([e["ev_net"] for e, _ in pos]) if pos else None,
                "hypothetical_net_pnl_per_contract_positive_ev": w.mean(hyp) if hyp else None,
                "hypothetical_games": len({r["game_id"] for _, r in pos}),
            }  # fmt: skip
        out[key] = entry
    return out


def ladder_demo(
    recs: list[dict[str, Any]], game_id: int, labels: list[str]
) -> list[dict[str, Any]]:
    """Every FULL-game contract of one game with each distribution's fair value next to the book."""
    rows = [r for r in recs if r["game_id"] == game_id and r["period"] == "FULL"]

    def sort_key(r: dict[str, Any]) -> tuple:
        return (
            r["market_type"] or "",
            r["subject_side"] or "",
            r["strike"] if r["strike"] is not None else -1,
        )

    out = []
    for r in sorted(rows, key=sort_key):
        row = {k: r[k] for k in ("ticker", "market_type", "subject_side", "strike", "line_role",
                                 "yes_bid", "yes_ask", "yes_exec_price", "no_exec_price",
                                 "outcome", "model_status") if k in r}  # fmt: skip
        for lb in labels:
            row[f"p[{lb}]"] = r.get(f"p[{lb}]")
        if r["yes_exec_price"] is not None:
            row["fee_at_yes_ask_per_contract"] = fees.fee_per_contract(r["yes_exec_price"])
        out.append(row)
    return out


def _isfinite(x: Any) -> bool:
    return isinstance(x, float) and math.isfinite(x)
