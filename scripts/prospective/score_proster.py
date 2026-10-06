"""Daily P-ROSTER-1 prospective scorer (Wave 8). Read-only over the archives.

    python scripts/prospective/score_proster.py --projections arch/projections-archive \
        --rosters arch/roster-archive --espn arch/espn-lines-archive --out score_out

Results and box scores come from the free SportsDataverse release assets (the same
files the benchmark uses). The market column (latest ESPN line captured before tip) is
built HERE, never in ``cbb_edge.rosters``: it only feeds the preregistered downstream
``market_gap`` metric. With no settled game the run still writes an empty scoreboard,
so the experiment starts by itself when the first game settles.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cbb_edge.data.bronze import sportsdataverse as sdv
from cbb_edge.data.ids.teams import canonical_from_espn
from cbb_edge.rosters import membership, prospective_score


def schedule(season: int, stamp: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = sdv.download_live("schedules", season, stamp)
    if p is None:
        return pd.DataFrame(columns=["espn_game_id", "result_margin"]), pd.DataFrame()
    s = pd.read_parquet(p)
    sched = pd.DataFrame(
        {
            "espn_game_id": s["game_id"].astype(int),
            "home_team_id": s["home_id"].map(canonical_from_espn),
            "away_team_id": s["away_id"].map(canonical_from_espn),
            "tip": pd.to_datetime(s["start_date"], utc=True),
            "status": s["status_type_name"],
        }
    )
    sched = sched[sched["status"].ne("STATUS_CANCELED")]
    c = s[s["status_type_completed"].fillna(False).astype(bool)]
    res = pd.DataFrame(
        {
            "espn_game_id": c["game_id"].astype(int),
            "result_margin": c["home_score"].astype(float) - c["away_score"].astype(float),
            "result_total": c["home_score"].astype(float) + c["away_score"].astype(float),
        }
    )
    return res, sched


def box(season: int, stamp: str) -> pd.DataFrame:
    p = sdv.download_live("player_box", season, stamp)
    if p is None:
        return pd.DataFrame()
    b = pd.read_parquet(p)
    return pd.DataFrame(
        {
            "espn_game_id": b["game_id"].astype(int),
            "team_id": b["team_id"].map(canonical_from_espn),
            "player_id": "P" + b["athlete_id"].astype("Int64").astype(str),
            "minutes": pd.to_numeric(b["minutes"], errors="coerce").fillna(0.0),
            "starter": b["starter"].fillna(False).astype(bool),
        }
    )


def market(espn: Path | None, sched: pd.DataFrame) -> pd.DataFrame | None:
    """Latest ESPN home margin captured strictly before tip (benchmark only)."""
    if espn is None or not espn.exists() or sched.empty:
        return None
    from cbb_edge.market import stages

    lines = stages.espn_lines(stages.read_jsonl_tree(espn))
    if lines.empty:
        return None
    lines = lines.rename(columns={"game_id": "espn_game_id"}).merge(
        sched[["espn_game_id", "tip"]], on="espn_game_id"
    )
    lines = lines[pd.to_datetime(lines["captured_at"], utc=True) < lines["tip"]]
    last = lines.sort_values("captured_at").groupby("espn_game_id").tail(1)
    return last[["espn_game_id", "mkt_margin"]]


def expected_games(sched: pd.DataFrame, d1: set[str], now: pd.Timestamp) -> pd.DataFrame:
    """D-I vs D-I games (both canonical 2026-27 members) that have tipped by ``now``
    and were not cancelled: every one must end VALID, INVALID or UNSCORABLE."""
    if sched.empty:
        return pd.DataFrame(columns=["espn_game_id"])
    both = sched["home_team_id"].isin(d1) & sched["away_team_id"].isin(d1)
    return sched[both & (sched["tip"] < now)][["espn_game_id", "tip"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--projections", type=Path, required=True)
    ap.add_argument("--rosters", type=Path, required=True)
    ap.add_argument("--espn", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    recs = prospective_score.load_records(a.projections, a.season) if a.projections.exists() else []
    res, sched = schedule(a.season, stamp)
    bx = box(a.season, stamp) if len(res) else pd.DataFrame()
    d1 = set(membership.members(a.season)["team_id"].dropna())
    now = pd.Timestamp(datetime.now(UTC))
    expected = expected_games(sched, d1, now)
    frames, s = prospective_score.score(
        recs, res, market(a.espn, sched), a.rosters if a.rosters.exists() else None, bx,
        sched, a.season, d1,
        committed=prospective_score.git_first_commit_times(a.projections),
        committed_roster=prospective_score.git_first_commit_times(a.rosters),
        projections_root=a.projections if a.projections.exists() else None,
        expected=expected,
    )  # fmt: skip
    s["run"] = {
        "stamp": stamp,
        "records_read": len(recs),
        "completed_games_in_schedule": int(len(res)),
        "box_rows": int(len(bx)),
        "d1_members": len(d1),
    }
    prospective_score.write(a.out, frames, s, stamp)
    print(json.dumps({"settled_paired_games": s["settled_paired_games"], **s["run"]}))


if __name__ == "__main__":
    main()
