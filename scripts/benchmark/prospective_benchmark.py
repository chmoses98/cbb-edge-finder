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
            "total": (s["home_score"].astype(float) + s["away_score"].astype(float)),
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
            "start_time_utc": pd.to_datetime(s["start_date"], utc=True),
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


def rotation_card(
    rosters: Path, games: pd.DataFrame, season: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Each team's first game vs the archived P-ROSTER states (actual minutes from the
    free SportsDataverse player box release asset): the rotation scorecard and the
    departed-player false-inclusion table (WAVE7.md 7)."""
    from cbb_edge.rosters import scorecard

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    p = sdv.download_live("player_box", season, stamp)
    if p is None:
        return pd.DataFrame(), pd.DataFrame()
    b = pd.read_parquet(p)
    box = pd.DataFrame(
        {
            "espn_game_id": b["game_id"].astype(int),
            "team_id": b["team_id"].map(canonical_from_espn),
            "player_id": "P" + b["athlete_id"].astype("Int64").astype(str),
            "minutes": pd.to_numeric(b["minutes"], errors="coerce").fillna(0.0),
            "starter": b["starter"].fillna(False).astype(bool),
        }
    )
    g = pd.concat(
        [
            games[["game_id", "home_team_id", "start_time_utc"]].rename(
                columns={"home_team_id": "team_id"}
            ),
            games[["game_id", "away_team_id", "start_time_utc"]].rename(
                columns={"away_team_id": "team_id"}
            ),
        ]
    ).dropna()
    first = g.sort_values("start_time_utc").groupby("team_id").head(1)
    first = first.rename(columns={"game_id": "espn_game_id", "start_time_utc": "tip"})
    # departed-player false inclusion (WAVE7.md 7): each team's first five games, DNP rows kept
    g5 = g.sort_values("start_time_utc").groupby("team_id").head(5)
    box5 = box.merge(
        g5.rename(columns={"game_id": "espn_game_id"})[["espn_game_id", "team_id"]],
        on=["espn_game_id", "team_id"],
    )
    hist = pd.read_parquet(Path(scorecard.__file__).resolve().parents[2] / "models" / "rosters"
                           / "history_2026.parquet")  # fmt: skip
    fi = scorecard.false_inclusion(rosters, first, box5, hist, season)
    return scorecard.rotation_scorecard(rosters, first, box), fi


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--projections", type=Path, required=True)
    ap.add_argument("--espn", type=Path, required=True)
    ap.add_argument("--kalshi", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path("benchmark_out"))
    ap.add_argument("--rosters", type=Path, default=None, help="roster-archive checkout")
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
    # Wave 6: weekly model monitor (every version incl. overlays), P-ROSTER-1 metrics,
    # game-1 rotation scorecard. Market is a downstream benchmark only.
    from cbb_edge.rosters import scorecard

    res2 = res.rename(columns={"game_id": "espn_game_id", "margin": "result_margin",
                               "total": "result_total"})  # fmt: skip
    mkt = pd.DataFrame(columns=["espn_game_id", "mkt_margin"])
    if len(lines):
        last = lines.sort_values("captured_at").groupby("game_id").tail(1)
        mkt = last.rename(columns={"game_id": "espn_game_id"})[["espn_game_id", "mkt_margin"]]
    monitor = scorecard.model_monitor(recs, res2, mkt)
    proster = scorecard.proster_metrics(recs, res2, mkt)
    (a.out / "model_monitor.json").write_text(json.dumps(monitor, indent=1, default=float))
    (a.out / "proster_metrics.json").write_text(json.dumps(proster, indent=1, default=float))
    rot = pd.DataFrame()
    if a.rosters is not None and a.rosters.exists() and len(games):
        rot, fi = rotation_card(a.rosters, games, a.season)
        rot.to_csv(a.out / "rotation_scorecard.csv", index=False)
        fi.to_csv(a.out / "false_inclusion.csv", index=False)
    summary = {
        "season": a.season,
        "projection_records": len(recs),
        "line_rows": len(lines),
        "completed_games": len(res),
        "kalshi_rows": len(kal),
        "availability_rows": len(ai),
        "monitor_versions": sorted(monitor),
        "rotation_scorecard_rows": len(rot),
        "note": "MARKET_BENCHMARK only; PURE projections are read from the archive",
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
