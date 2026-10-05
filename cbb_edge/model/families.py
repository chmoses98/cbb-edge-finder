"""Model families and the market-independence contract.

PURE_BASKETBALL    the primary model family. Uses only basketball / context information
                   (results, box scores, possessions, lineups, players, schedule, venue).
                   FORBIDDEN: spreads, totals, moneylines, bookmaker or Kalshi prices, line
                   movement, consensus, or anything derived from a betting line.
MARKET_BENCHMARK   market-only reference ("how close is the independent model?").
MARKET_ENSEMBLE    diagnostic research arm mixing both. Never the default projection.

Enforcement
-----------
1. Structural: modules in ``PURE_PACKAGES`` may not import ``cbb_edge.market`` or
   ``cbb_edge.kalshi`` (``tests/test_market_independence.py``, AST scan).
2. Data: :func:`assert_pure_frame` rejects any feature frame with a market-looking column.
3. Behavioural: mutating every stored market line / Kalshi price must leave PURE
   projections bit-identical (``tests/test_market_independence.py``, permanent CI test).
"""

from __future__ import annotations

import re
from enum import StrEnum

import pandas as pd


class ModelFamily(StrEnum):
    PURE_BASKETBALL = "PURE_BASKETBALL"
    MARKET_BENCHMARK = "MARKET_BENCHMARK"
    MARKET_ENSEMBLE = "MARKET_ENSEMBLE"


# Packages/modules that make up the PURE_BASKETBALL pipeline.
PURE_PACKAGES = (
    "cbb_edge/ratings",
    "cbb_edge/features",
    "cbb_edge/players",
    "cbb_edge/lineups",
    "cbb_edge/data/silver",
    "cbb_edge/backtest/walkforward.py",
    "cbb_edge/backtest/config.py",
    "cbb_edge/model/arms.py",
    "cbb_edge/model/elo.py",
    "cbb_edge/model/pure.py",
    "cbb_edge/model/pace.py",
    "cbb_edge/model/uncertainty.py",
    "cbb_edge/research/blocks.py",
    "cbb_edge/backtest/residuals.py",
    "cbb_edge/app/prospective.py",
)
FORBIDDEN_IMPORTS = ("cbb_edge.market", "cbb_edge.kalshi")

MARKET_COLUMN = re.compile(
    r"(spread|moneyline|(^|_)ml(_|$)|over_?under|total_(open|close)|kalshi|yes_(bid|ask)|"
    r"no_(bid|ask)|last_price|(^|_)odds|implied|vig|market|(^|_)line(_|$)|consensus|"
    r"pickcenter|espn_wp|pregame_home_prob)",
    re.I,
)

ARM_FAMILY: dict[str, ModelFamily] = {
    **{
        a: ModelFamily.PURE_BASKETBALL
        for a in (
            "B0",
            "B1",
            "B2",
            "B3",
            "B4",
            "B5",
            "B6",
            "B6R",
            "B7",
            "B8",
            "B9",
            "B10",
            "B10_engine_only",
            "B10d",
            "B11",
            "B12",
            "B13",
            "B13_garbage_only",
            "B13_mismatch_only",
            "B14",
            "B14v",
            "B15",
            "ELO",
            "PURE",
        )
    },
    "MARKET": ModelFamily.MARKET_BENCHMARK,
    "ENSEMBLE": ModelFamily.MARKET_ENSEMBLE,
}


class MarketLeakError(ValueError):
    """A market-derived input reached the PURE_BASKETBALL pipeline."""


def market_columns(columns: list[str] | pd.Index) -> list[str]:
    return [c for c in columns if MARKET_COLUMN.search(str(c))]


def assert_pure_frame(df: pd.DataFrame, context: str = "features") -> pd.DataFrame:
    bad = market_columns(df.columns)
    if bad:
        raise MarketLeakError(f"{context}: market-derived columns in PURE input: {bad}")
    return df
