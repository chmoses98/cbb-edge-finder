"""OPTIONAL The Odds API client. DISABLED BY DEFAULT. PAID / METERED.

Nothing in this repository calls this module in tests or workflows. Every call goes
through ``cbb_edge.data.http.fetch`` -> ``cost_policy.authorize``, which refuses unless
BOTH ``ALLOW_PAID_ODDS_API=true`` AND ``ODDS_API_MAX_REQUESTS`` > 0 (lifetime budget,
counted in the persistent ledger, retries included). Default config = hard block.

Owner approval is required before setting those variables (docs/COST_POLICY.md).
"""

from __future__ import annotations

import os
from typing import Any

from cbb_edge.data.http import fetch

SOURCE = "the_odds_api"
BASE = "https://api.the-odds-api.com/v4"
SPORT = "basketball_ncaab"


def _key() -> str:
    return os.environ.get("ODDS_API_KEY", "")


def get_odds(markets: str = "spreads,totals", regions: str = "us") -> Any:
    url = f"{BASE}/sports/{SPORT}/odds"
    res = fetch(
        SOURCE, url, {"apiKey": _key(), "markets": markets, "regions": regions}, use_cache=False
    )
    return None if res is None else res.json()


def get_historical_odds(date_iso: str, markets: str = "spreads,totals") -> Any:
    url = f"{BASE}/historical/sports/{SPORT}/odds"
    res = fetch(
        SOURCE, url, {"apiKey": _key(), "date": date_iso, "markets": markets, "regions": "us"}
    )
    return None if res is None else res.json()
