"""Per-market research block for the SIFT publication (read-only; NEVER an authorized bet).

For every published Kalshi game market this states what the frozen model says and why/why not it can say
anything, what the market says, and the fee-adjusted theoretical edge at the CURRENT executable quote. It reuses
the research engine's pure functions (``semantics.probability``, ``fees``) and never prices a market the frozen
distribution cannot support: an unsupported market gets ``model_probability = null`` and the exact gap.

Edges exist only for a LIVE, fresh, two-sided quote (see ``quotes.classify_quote``); otherwise they are null with
the reason, so a stale/settled/empty book can never look tradable. ``max_acceptable_price`` is the highest price at
which the model's net expected value (fee included) is non-negative; it does not depend on the current quote.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from cbb_edge.kalshi import semantics
from cbb_edge.kalshi.research import fees

ORDER = fees.REFERENCE_CONTRACTS


def research_block(
    sem: dict[str, Any],
    proj: dict[str, Any] | None,
    version: str | None,
    as_of: str | None,
    quote: dict[str, Any] | None,
    yes_bid: float | None,
    yes_ask: float | None,
    series_meta: dict[str, Any] | None,
    on: date,
) -> dict[str, Any]:
    p: float | None = None
    gap: str | None = None
    if proj is None or version is None:
        gap = "no_pretip_frozen_projection_for_this_game"
    else:
        p, method = semantics.probability(sem, proj)
        if p is None:
            gap = method
    rule = fees.rule_for(series_meta, on)
    live = bool(quote and quote.get("live_probability_ok"))
    prices = fees.side_prices(yes_bid, yes_ask) if live else {"yes": None, "no": None}
    edge: dict[str, Any] = {}
    for side, ps in (("yes", p), ("no", None if p is None else 1.0 - p)):
        px = prices[side]
        if not rule.supported:
            edge[side] = {"price": px, "net_edge": None, "reason": "fee_rule_unsupported"}
        elif ps is None:
            edge[side] = {"price": px, "net_edge": None, "reason": "no_model_probability"}
        elif px is None:
            edge[side] = {"price": None, "net_edge": None, "reason": "quote_not_live_or_empty_side"}
        else:
            edge[side] = {
                "price": px,
                "fee_per_contract": rule.per_contract(px, ORDER),
                "net_edge": fees.expected_value(ps, px, ORDER, rule.taker_rate),
                "reason": None,
            }
    maxp: dict[str, float | None] = {"yes": None, "no": None}
    if p is not None and rule.supported:
        maxp = {
            "yes": fees.breakeven_entry_price(p, ORDER, rule.taker_rate),
            "no": fees.breakeven_entry_price(1.0 - p, ORDER, rule.taker_rate),
        }
    mid = None
    if live and yes_bid is not None and yes_ask is not None:
        mid = round((yes_bid + yes_ask) / 2.0, 6)
    return {
        "model_version": version, "model_as_of": as_of,
        "model_probability": p, "model_gap": gap,
        "market_implied_probability": mid,
        "market_probability_reason": None if live else "quote_not_live",
        "fee_rule": rule.version, "fee_basis": rule.basis, "order_contracts": ORDER,
        "net_edge": edge, "max_acceptable_price": maxp,
        "validation": {
            "status": "RESEARCH_ONLY",
            "authorized_bet": False,
            "note": "theoretical edge at the displayed top-of-book; no preregistered candidate is validated",
        },
    }  # fmt: skip
