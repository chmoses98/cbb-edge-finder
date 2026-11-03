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
from datetime import date
from typing import Any

# Official-source status (read this before trusting any ROI figure): kalshi.com and
# api.elections.kalshi.com are unreachable from the development sandbox, so the general formula
# below is corroborated only by third-party summaries. The capture workflow records each series'
# own ``fee_type`` / ``fee_multiplier`` straight from the Kalshi API; when a contract's series
# carries them, they replace the assumption and ``fee_basis`` becomes ``series_api``.
FEE_SCHEDULE_VERSION = "kalshi-quadratic-v1"
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


@dataclass(frozen=True)
class FeeRule:
    """One versioned, effective-dated fee rule. ``taker_rate`` already includes any multiplier."""

    version: str
    effective_from: date
    effective_to: date | None
    taker_rate: float
    maker_rate: float
    basis: str  # series_api | assumed_default
    supported: bool = True  # False => fee unknown (e.g. flat fees): no ROI is ever computed

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)

    def per_contract(self, price: float, contracts: int = 25) -> float:
        return fee_per_contract(price, contracts, self.taker_rate)


# Effective-dated defaults, newest last. Add a row (and close the previous one) when Kalshi
# publishes a change; contracts are priced with the rule in force on their QUOTE date.
DEFAULT_RULES: tuple[FeeRule, ...] = (
    FeeRule(
        FEE_SCHEDULE_VERSION, date(2020, 1, 1), None, TAKER_RATE, MAKER_RATE, "assumed_default"
    ),
)


def rule_for(series_meta: dict[str, Any] | None, on: date) -> FeeRule:
    """Fee rule for a series on a date. Series metadata from the API wins over the default."""
    if series_meta:
        ftype = str(series_meta.get("fee_type") or "").lower()
        mult = series_meta.get("fee_multiplier")
        if ftype in ("quadratic", "quadratic_with_maker_fees") and isinstance(mult, int | float):
            m = float(mult)
            return FeeRule(
                f"series-api:{ftype}:x{m:g}", date(2020, 1, 1), None,
                TAKER_RATE * m, MAKER_RATE * m, "series_api",
            )  # fmt: skip
        if ftype:  # flat / unknown fee types: refuse to guess
            return FeeRule(f"series-api:{ftype}:unsupported", date(2020, 1, 1), None,
                           0.0, 0.0, "series_api", supported=False)  # fmt: skip
    for r in reversed(DEFAULT_RULES):
        if r.covers(on):
            return r
    return DEFAULT_RULES[0]


@dataclass(frozen=True)
class Execution:
    """Cash accounting for one position, every component kept apart.

    ``kind`` is ``actual_fill`` for a real order and ``hypothetical_quote`` for a researched
    quote; the two must never be pooled without saying so.
    """

    kind: str
    quote_price: float  # displayed top-of-book price when the order was considered
    fill_price: float  # raw per-contract execution price (before fees)
    contracts: int
    fee_total: float  # dollars, whole order, counted once
    total_cash: float  # fill*contracts + fee_total: what the account is debited
    fee_inclusive_avg_cost: float  # total_cash / contracts (Kalshi's displayed average cost)

    @property
    def fee_per_contract(self) -> float:
        return self.fee_total / self.contracts

    def settle(self, won: bool) -> dict[str, float]:
        payout = float(self.contracts) if won else 0.0
        gross = payout - self.fill_price * self.contracts
        net = payout - self.total_cash
        return {
            "payout": payout, "gross_pnl": gross, "net_pnl": net,
            "gross_roi": gross / (self.fill_price * self.contracts) if self.fill_price else float("nan"),
            "net_roi": net / self.total_cash if self.total_cash else float("nan"),
        }  # fmt: skip


def hypothetical_execution(
    quote: float, contracts: int, rule: FeeRule, fill: float | None = None
) -> Execution:
    """Build an Execution from a displayed quote (fill defaults to the quote: a taker lifts it)."""
    px = quote if fill is None else fill
    fee = order_fee(px, contracts, rule.taker_rate)
    cash = px * contracts + fee
    return Execution("hypothetical_quote", quote, px, contracts, fee, cash, cash / contracts)


def execution_from_inclusive_display(
    avg_cost_inclusive: float, contracts: int, rule: FeeRule, quote: float | None = None
) -> Execution | None:
    """Actual fill whose ONLY datum is Kalshi's fee-inclusive displayed average cost.

    The raw fill is recovered by inverting the fee formula; None when ambiguous. Total cash is
    ``avg_cost_inclusive * contracts`` (the fee is already in it) - never add the fee again.
    """
    raw = raw_fill_from_inclusive(avg_cost_inclusive, contracts, rule.taker_rate)
    if raw is None:
        return None
    fee = order_fee(raw, contracts, rule.taker_rate)
    return Execution(
        "actual_fill", raw if quote is None else quote, raw, contracts, fee,
        raw * contracts + fee, (raw * contracts + fee) / contracts,
    )  # fmt: skip


def side_prices(yes_bid: float | None, yes_ask: float | None) -> dict[str, float | None]:
    """Executable taker price per side from top-of-book: YES at yes_ask, NO at 1 - yes_bid.

    A price of exactly 0 or 1 (empty-book placeholders) is not executable and yields None.
    """
    yes_px = yes_ask if yes_ask is not None and _EPS < yes_ask < 1.0 - _EPS else None
    no_px = 1.0 - yes_bid if yes_bid is not None and _EPS < yes_bid < 1.0 - _EPS else None
    return {"yes": yes_px, "no": no_px}


def breakeven_entry_price(
    prob: float, contracts: int = REFERENCE_CONTRACTS, rate: float = TAKER_RATE
) -> float | None:
    """Highest cent-price c with prob - c - fee(c) >= 0 (max acceptable raw entry), else None."""
    best = None
    for cent in range(1, 100):
        c = cent / 100.0
        if prob - total_cost_per_contract(c, contracts, rate) >= -_EPS:
            best = c
    return best


def expected_value(
    prob: float, price: float, contracts: int = REFERENCE_CONTRACTS, rate: float = TAKER_RATE
) -> float:
    """Net EV per contract of buying a side that wins with ``prob`` at raw ``price``."""
    return prob - total_cost_per_contract(price, contracts, rate)


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
        "gross_roi": gross / price if price > 0 else float("nan"),
        "net_pnl": gross - fee,
        "net_roi": (gross - fee) / cost if cost > 0 else float("nan"),
    }


@dataclass(frozen=True)
class Clv:
    gross: float  # closing_side_price - raw entry price
    fee_adjusted: float  # gross - entry fee (position held to settlement: no exit fee)


def clv(
    entry_price: float,
    close_price: float,
    contracts: int = REFERENCE_CONTRACTS,
    rate: float = TAKER_RATE,
) -> Clv:
    """CLV in probability points for a side bought at ``entry_price``; close is the same side's
    closing fair price (midpoint). Entry fee is subtracted once for the fee-adjusted figure."""
    gross = close_price - entry_price
    return Clv(gross=gross, fee_adjusted=gross - fee_per_contract(entry_price, contracts, rate))
