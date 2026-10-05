"""Prospective capture of ESPN pre-tip lines (MARKET_BENCHMARK only, free).

ESPN's public scoreboard carries the current pregame line (provider, spread, total,
moneylines) for most D-I games. Historical bulk copies only keep the CLOSING line, so to
benchmark convergence against the market at fixed horizons we snapshot it ourselves:
every run records the line for each game tipping within the next 30 hours, tagged with
the minutes to tip and a horizon bucket (T-24h, T-6h, T-90m, T-30m, latest).

Reads only the free ``espn_public`` source through the cost-policy chokepoint. Output
rows are append-only snapshots; nothing here is importable by the PURE pipeline (CI).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cbb_edge.data.http import fetch

SOURCE = "espn_public"
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
HORIZONS = ((24 * 60, "T-24h"), (6 * 60, "T-6h"), (90, "T-90m"), (30, "T-30m"))
SCHEMA = "espn-line-snapshot-v1"


def horizon(minutes_to_tip: float) -> str:
    """Nearest named horizon at or beyond ``minutes_to_tip`` (else 'latest')."""
    for m, name in HORIZONS:
        if minutes_to_tip >= m * 0.75:
            return name
    return "latest"


def parse(board: dict[str, Any], captured_at: datetime) -> list[dict[str, Any]]:
    rows = []
    for ev in board.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        tip = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        mins = (tip - captured_at).total_seconds() / 60.0
        state = ((comp.get("status") or {}).get("type") or {}).get("state")
        if state != "pre" or mins < 0:
            continue
        teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        for odds in comp.get("odds") or []:
            rows.append(
                {
                    "schema": SCHEMA,
                    "game_id": int(ev["id"]),
                    "tip_utc": tip.isoformat(),
                    "captured_at": captured_at.isoformat(),
                    "minutes_to_tip": round(mins, 1),
                    "horizon": horizon(mins),
                    "neutral_site": bool(comp.get("neutralSite")),
                    "home_espn_id": (teams.get("home") or {}).get("id"),
                    "away_espn_id": (teams.get("away") or {}).get("id"),
                    "provider": (odds.get("provider") or {}).get("name"),
                    "details": odds.get("details"),
                    "spread": odds.get("spread"),
                    "over_under": odds.get("overUnder"),
                    "home_moneyline": (odds.get("homeTeamOdds") or {}).get("moneyLine"),
                    "away_moneyline": (odds.get("awayTeamOdds") or {}).get("moneyLine"),
                    "home_favorite": (odds.get("homeTeamOdds") or {}).get("favorite"),
                }
            )
    return rows


def capture(out: Path, hours_ahead: float = 30.0) -> dict[str, Any]:
    now = datetime.now(UTC)
    et = ZoneInfo("America/New_York")
    days = sorted(
        {
            (now + timedelta(hours=h)).astimezone(et).strftime("%Y%m%d")
            for h in (0, hours_ahead / 2, hours_ahead)
        }
    )
    rows: list[dict[str, Any]] = []
    for d in days:
        res = fetch(
            SOURCE,
            URL,
            {"dates": d, "groups": "50", "limit": "500"},
            use_cache=False,
            dest=Path("scoreboard") / now.strftime("%Y/%m/%d") / f"{d}_{time.time_ns()}.json",
            schema_version="espn-scoreboard-v1",
            timeout=60,
        )
        if res is None:
            continue
        rows += [r for r in parse(res.json(), now) if r["minutes_to_tip"] <= hours_ahead * 60]
    out.mkdir(parents=True, exist_ok=True)
    f = out / now.strftime("%Y/%m/%d") / f"{now.strftime('%H%M%S')}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {
        "captured_at": now.isoformat(),
        "dates": days,
        "rows": len(rows),
        "games": len({r["game_id"] for r in rows}),
        "file": str(f),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="espn_lines_out")
    ap.add_argument("--hours-ahead", type=float, default=30.0)
    a = ap.parse_args()
    print(json.dumps(capture(Path(a.out), a.hours_ahead)))


if __name__ == "__main__":
    main()
