"""Probe free public sources and print a JSON coverage summary (used by the audit).

Every request goes through the cost-policy chokepoint. Only FREE_* sources are probed;
CollegeBasketballData (UNKNOWN_COST, API-key quota) and all paid sources are skipped.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from typing import Any

from cbb_edge.data.cost_policy import CostPolicyViolation
from cbb_edge.data.http import fetch

PROBES: list[tuple[str, str, str, dict[str, Any] | None]] = [
    (
        "espn_public",
        "espn_scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
        {"dates": "20250315", "groups": "50", "limit": "400"},
    ),
    (
        "espn_public",
        "espn_summary_odds",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary",
        {"event": "401745970"},
    ),
    ("torvik", "torvik_team_results_csv", "https://barttorvik.com/2025_team_results.csv", None),
    (
        "torvik",
        "torvik_timemachine_json",
        "https://barttorvik.com/timemachine/team_results/20250115_team_results.json.gz",
        None,
    ),
    (
        "torvik",
        "torvik_game_stats",
        "https://barttorvik.com/getgamestats.php",
        {"year": "2025", "csv": "1"},
    ),
    (
        "sports_reference",
        "sref_school_stats",
        "https://www.sports-reference.com/cbb/seasons/men/2025-school-stats.html",
        None,
    ),
    (
        "kalshi_public",
        "kalshi_series_sports",
        "https://api.elections.kalshi.com/trade-api/v2/series",
        {"category": "Sports"},
    ),
    (
        "kalshi_public",
        "kalshi_cbb_game_markets",
        "https://api.elections.kalshi.com/trade-api/v2/markets",
        {"series_ticker": "KXNCAAMBGAME", "limit": "5"},
    ),
    ("cbbd", "cbbd_games_SKIPPED", "https://api.collegebasketballdata.com/games", None),
]


def describe(name: str, body: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"bytes": len(body), "head": body[:160].decode("latin1")}
    try:
        if name.endswith(".gz") or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        js = json.loads(body)
        if isinstance(js, dict):
            out["json_keys"] = sorted(js)[:30]
            for k in ("series", "markets", "events"):
                if k in js:
                    out[f"n_{k}"] = len(js[k])
                    if k == "series":
                        out["cbb_like"] = sorted(
                            s["ticker"]
                            for s in js[k]
                            if any(
                                w in (s.get("title", "") + s["ticker"]).lower()
                                for w in (
                                    "college basketball",
                                    "ncaamb",
                                    "march madness",
                                    "ncaab",
                                    "marmad",
                                )
                            )
                        )
                    if k == "markets" and js[k]:
                        out["market_keys"] = sorted(js[k][0])
        elif isinstance(js, list):
            out["json_list_len"] = len(js)
            out["first"] = str(js[0])[:300] if js else None
    except (ValueError, UnicodeDecodeError, OSError):
        try:
            rows = list(csv.reader(io.StringIO(body.decode("utf-8", "replace"))))
            out["csv_rows"] = len(rows)
            out["csv_header"] = rows[0][:40] if rows else None
        except csv.Error:
            pass
    return out


def main() -> None:
    results = []
    for source, name, url, params in PROBES:
        rec: dict[str, Any] = {"probe": name, "source": source, "url": url}
        try:
            res = fetch(source, url, params, not_found_ok=True, timeout=60, max_attempts=2)
            if res is None:
                rec["status"] = 404
            else:
                rec["status"] = 200
                rec.update(describe(url, res.path.read_bytes()))
        except CostPolicyViolation as exc:
            rec["status"] = "BLOCKED_BY_COST_POLICY"
            rec["reason"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - probe reports, never crashes
            rec["status"] = "ERROR"
            rec["error"] = f"{type(exc).__name__}: {exc}"[:400]
        results.append(rec)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
