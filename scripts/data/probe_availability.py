"""Probe FREE ESPN public endpoints for player availability and roster data.

Runs from GitHub Actions (the sandbox blocks ESPN). A handful of uncached requests
through the cost-policy chokepoint (``espn_public`` = FREE_RATE_LIMITED, 1 req/s).
Prints a JSON summary of each endpoint's structure: top-level keys, whether injury /
status / starter / roster fields exist, and a small sample of those fields.
"""

from __future__ import annotations

import json
from typing import Any

from cbb_edge.data.http import fetch

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball"
TEAMS = ["150", "2", "333", "2305"]  # Duke, Auburn, Alabama, Kansas

PROBES: list[tuple[str, str, dict[str, Any] | None]] = [
    *[(f"site_roster_{t}", f"{SITE}/teams/{t}/roster", None) for t in TEAMS],
    *[(f"site_team_{t}", f"{SITE}/teams/{t}", {"enable": "roster,injuries"}) for t in TEAMS[:2]],
    *[(f"core_injuries_{t}", f"{CORE}/teams/{t}/injuries", None) for t in TEAMS[:2]],
    ("site_injuries_league", f"{SITE}/injuries", None),
    ("core_season_athletes", f"{CORE}/seasons/2027/teams/150/athletes", {"limit": "50"}),
    ("summary_past_game", f"{SITE}/summary", {"event": "401745970"}),
    ("scoreboard_today", f"{SITE}/scoreboard", {"groups": "50", "limit": "50"}),
]

KEYS = {
    "injuries",
    "injury",
    "status",
    "starter",
    "starters",
    "didnotplay",
    "dnp",
    "active",
    "experience",
    "height",
    "position",
    "birthplace",
    "jersey",
    "shortcomment",
    "longcomment",
    "type",
    "details",
    "date",
    "fantasystatus",
    "reason",
}


def shape(x: Any, depth: int = 0) -> Any:
    if depth > 3:
        return type(x).__name__
    if isinstance(x, dict):
        return {k: shape(v, depth + 1) for k, v in list(x.items())[:25]}
    if isinstance(x, list):
        return [shape(x[0], depth + 1), f"len={len(x)}"] if x else []
    return type(x).__name__


def find_keys(x: Any, keys: set[str], path: str = "", out: dict | None = None) -> dict:
    out = {} if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            p = f"{path}.{k}"
            if k.lower() in keys and p not in out and len(out) < 40:
                out[p] = v if isinstance(v, str | int | float | bool) else shape(v, 2)
            find_keys(v, keys, p, out)
    elif isinstance(x, list):
        for v in x[:3]:
            find_keys(v, keys, path + "[]", out)
    return out


def main() -> None:
    out: dict[str, Any] = {}
    for name, url, params in PROBES:
        try:
            res = fetch(
                "espn_public",
                url,
                params,
                use_cache=False,
                timeout=30,
                not_found_ok=True,
                dest=f"probe_availability/{name}.json",
            )
            if res is None:
                out[name] = {"status": 404}
                continue
            data = res.json()
            out[name] = {"status": 200, "shape": shape(data), "fields": find_keys(data, KEYS)}
        except Exception as e:  # noqa: BLE001 - the probe reports every failure
            out[name] = {"error": f"{type(e).__name__}: {e}"[:300]}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
