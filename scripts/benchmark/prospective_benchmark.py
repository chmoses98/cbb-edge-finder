"""Prospective MARKET_BENCHMARK report over the append-only archives (downstream only).

Reads checked-out archive branches (projections / ESPN lines / Kalshi / availability),
fetches the season's results from the free SportsDataverse schedule file, and writes:

    stage_benchmark.csv          PURE vs market vs result at T-24h ... latest
    future_market_alignment.csv  PURE_s vs later market (neutral diagnostic)
    kalshi.csv                   PURE prob vs Kalshi implied prob per projection snapshot
    availability_impact.csv      status-update overlays vs result / later market
    summary.json

Nothing here can influence a PURE projection: projections are read from the archive.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cbb_edge.data.bronze import sportsdataverse as sdv
from cbb_edge.data.ids.teams import canonical_from_espn, resolve
from cbb_edge.market import stages


def results(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    p = sdv.download_live("schedules", season, stamp)
    if p is None:
        return pd.DataFrame(columns=["game_id", "margin"]), pd.DataFrame()
    s = pd.read_parquet(p)
    s = s[s["status_type_completed"].fillna(False).astype(bool)]
    r = pd.DataFrame(
        {
            "game_id": s["game_id"].astype(int),
            "margin": (s["home_score"].astype(float) - s["away_score"].astype(float)),
        }
    )
    g = pd.DataFrame(
        {
            "game_id": s["game_id"].astype(int),
            "game_date_et": pd.to_datetime(s["start_date"], utc=True)
            .dt.tz_convert("America/New_York")
            .dt.date,
            "home_team_id": s["home_id"].map(canonical_from_espn),
            "away_team_id": s["away_id"].map(canonical_from_espn),
        }
    )
    return r, g


def kalshi_map(kalshi: pd.DataFrame, games: pd.DataFrame) -> dict[str, tuple[int, bool]]:
    from cbb_edge.kalshi.mapping import map_market

    out: dict[str, tuple[int, bool]] = {}
    if kalshi.empty or games.empty:
        return out
    hm = games.set_index("game_id")["home_team_id"]
    for m in kalshi.loc[kalshi["family"] == "GAME_WINNER", "market"]:
        tk = m.get("ticker")
        if tk in out:
            continue
        gid, why = map_market(m, games)
        yes = resolve(str(m.get("yes_sub_title") or ""), "kalshi", log=False)
        if gid is not None and yes is not None:
            out[tk] = (gid, yes == hm.get(gid))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--projections", type=Path, required=True)
    ap.add_argument("--espn", type=Path, required=True)
    ap.add_argument("--kalshi", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("benchmark_out"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    recs = [json.loads(f.read_text()) for f in sorted(a.projections.rglob("*.json"))]
    recs = [r for r in recs if r.get("game", {}).get("season") == a.season]
    proj = stages.projection_table(recs)
    lines = stages.espn_lines(stages.read_jsonl_tree(a.espn))
    res, games = results(a.season)
    sb = stages.stage_benchmark(proj, lines, res)
    fa = stages.future_market_alignment(proj, lines)
    kal = pd.DataFrame()
    if a.kalshi is not None and a.kalshi.exists():
        k = stages.read_jsonl_tree(a.kalshi, "*.jsonl.gz")
        kal = stages.kalshi_table(recs, k, kalshi_map(k, games), res)
    ai = stages.availability_impact(recs, lines, res)
    for name, df in (
        ("stage_benchmark", sb),
        ("future_market_alignment", fa),
        ("kalshi", kal),
        ("availability_impact", ai),
    ):
        df.to_csv(a.out / f"{name}.csv", index=False)
    summary = {
        "season": a.season,
        "projection_records": len(recs),
        "line_rows": len(lines),
        "completed_games": len(res),
        "kalshi_rows": len(kal),
        "availability_rows": len(ai),
        "note": "MARKET_BENCHMARK only; PURE projections are read from the archive",
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
