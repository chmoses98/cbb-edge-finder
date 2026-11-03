"""Kalshi fee, cost, payout and CLV arithmetic. All money in dollars per $1 contract.

Four quantities are kept strictly separate and are never merged into one "price":

* ``quote``      - the observed top-of-book price (what the book displayed);
* ``fill``       - the raw execution price per contract (before fees);
* ``fee``        - transaction fee, per contract, counted exactly once;
* ``total_cost`` - fill + fee, i.e. what the account is debited.

Kalshi's *fee-inclusive displayed average cost* equals ``fill + fee`` and must NEVER be used as
the raw fill (that double counts the fee when the fee is added again). ``raw_fill_from_inclusive``
is the only supported way to recover a raw fill, and it refuses when it cannot be done unambiguously.

Fee schedule assumption (documented, parameterised): taker fee = ceil_to_cent(0.07 * C * P * (1-P))
for C contracts at price P; maker fee uses 0.0175. Kalshi publishes the schedule and may change
it per series; ``FEE_SCHEDULE_VERSION`` is stored with every evaluation so results can be
recomputed. Settlement itself is free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

FEE_SCHEDULE_VERSION = "kalshi-general-2026-assumed-0.07"
TAKER_RATE = 0.07
MAKER_RATE = 0.0175
REFERENCE_CONTRACTS = 25  # hypothetical order size: fee rounding is <0.04c/contract and the
# displayed top-of-book size must cover it for a hypothetical fill to count
_EPS = 1e-9


def _cents_ceil(x: float) -> float:
    return math.ceil(round(x * 100.0, 6)) / 100.0


def order_fee(price: float, contracts: int, rate: float = TAKER_RATE) -> float:
    """Total dollar fee for an order of ``contracts`` at raw ``price`` (rounded up to a cent)."""
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"price out of range: {price}")
    if contracts <= 0:
        raise ValueError("contracts must be positive")
    return _cents_ceil(rate * contracts * price * (1.0 - price))


def fee_per_contract(
    price: float, contracts: int = REFERENCE_CONTRACTS, rate: float = TAKER_RATE
) -> float:
    return order_fee(price, contracts, rate) / contracts


def total_cost_per_contract(
    price: float, contracts: int = REFERENCE_CONTRACTS, rate: float = TAKER_RATE
) -> float:
    return price + fee_per_contract(price, contracts, rate)


def raw_fill_from_inclusive(
    avg_cost_inclusive: float, contracts: int, rate: float = TAKER_RATE
) -> float | None:
    """Recover the raw per-contract fill from a fee-INCLUSIVE average cost.

    Searches cent-granular prices whose ``price + fee/contracts`` rounds to the observed cost.
    Returns None when zero or several prices match (ambiguous): never guess.
    """
    hits = []
    for cent in range(0, 101):
        p = cent / 100.0
        inc = p + order_fee(p, contracts, rate) / contracts
        if abs(inc - avg_cost_inclusive) <= 0.5 / (100.0 * contracts) + _EPS:
            hits.append(p)
    return hits[0] if len(hits) == 1 else None


def side_prices(yes_bid: float | None, yes_ask: float | None) -> dict[str, float | None]:
    """Executable taker price per side from top-of-book: YES at yes_ask, NO at 1 - yes_bid.

    A price of exactly 0 or 1 (empty-book placeholders) is not executable and yields None.
    """
    yes_px = yes_ask if yes_ask is not None and _EPS < yes_ask < 1.0 - _EPS else None
    no_px = 1.0 - yes_bid if yes_bid is not None and _EPS < yes_bid < 1.0 - _EPS else None
    return {"yes": yes_px, "no": no_px}


def breakeven_entry_price(prob: float, contracts: int = REFERENCE_CONTRACTS) -> float | None:
    """Highest cent-price c with prob - c - fee(c) >= 0 (max acceptable raw entry), else None."""
    best = None
    for cent in range(1, 100):
        c = cent / 100.0
        if prob - total_cost_per_contract(c, contracts) >= -_EPS:
            best = c
    return best


def expected_value(prob: float, price: float, contracts: int = REFERENCE_CONTRACTS) -> float:
    """Net EV per contract of buying a side that wins with ``prob`` at raw ``price``."""
    return prob - total_cost_per_contract(price, contracts)


def realized_return(
    won: bool, price: float, contracts: int = REFERENCE_CONTRACTS
) -> dict[str, float]:
    """Gross / net P&L per contract at settlement; the fee is deducted exactly once."""
    gross = (1.0 if won else 0.0) - price
    fee = fee_per_contract(price, contracts)
    cost = price + fee
    return {
        "gross_pnl": gross,
        "fee": fee,
        "total_cost": cost,
        "net_pnl": gross - fee,
        "net_roi": (gross - fee) / cost if cost > 0 else float("nan"),
    }


@dataclass(frozen=True)
class Clv:
    gross: float  # closing_side_price - raw entry price
    fee_adjusted: float  # gross - entry fee (position held to settlement: no exit fee)


def clv(entry_price: float, close_price: float, contracts: int = REFERENCE_CONTRACTS) -> Clv:
    """CLV in probability points for a side bought at ``entry_price``; close is the same side's
    closing fair price (midpoint). Entry fee is subtracted once for the fee-adjusted figure."""
    gross = close_price - entry_price
    return Clv(gross=gross, fee_adjusted=gross - fee_per_contract(entry_price, contracts))
