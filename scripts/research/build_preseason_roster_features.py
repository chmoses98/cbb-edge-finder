"""Build per team-season preseason roster / transfer features + a coverage report (research only).

Offline: reads local player-box parquet files (sift-data-vault sportsdataverse snapshot) and,
for seasons with official rosters, roster-archive snapshot JSONL files. No network, nothing is
written to any production path or data branch.

    python scripts/research/build_preseason_roster_features.py \
        --box-dir <dir with player_box_YYYY.parquet> --seasons 2008-2027 \
        --snapshots 2027=<dir of roster-archive snapshots/*.jsonl> --out <dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.rosters.preseason_features import build, player_seasons, snapshot_rosters


def _seasons(s: str) -> list[int]:
    a, _, b = s.partition("-")
    return list(range(int(a), int(b or a) + 1))


def coverage(feat: pd.DataFrame) -> dict:
    by = {}
    for s, f in feat[feat.d1_prev].groupby("season"):
        nonfr = f.n_roster - f.n_freshmen_class.fillna(f.n_newcomers_no_hist)
        by[int(s)] = {
            "d1_teams_with_prev_stats": int(len(f)),
            "membership_source": str(f.membership_source.iloc[0]),
            "roster_players": int(f.n_roster.sum()),
            "players_with_d1_box_history": int(f.n_with_d1_history.sum()),
            "history_match_rate_non_freshmen": round(
                float(f.n_with_d1_history.sum() / max(nonfr.sum(), 1)), 4
            ),
            "median_ret_minutes_share": round(float(f.ret_minutes_share.median()), 3),
            "median_tr_in_minutes_rel": round(float(f.tr_in_minutes_rel.median()), 3),
        }
    return by


def proxy_vs_official(box_dir: Path, season: int, files: list[Path]) -> dict:
    """How well the box-appearance proxy matches the official preseason roster (season to date)."""
    b = pd.read_parquet(box_dir / f"player_box_{season}.parquet")
    ps = player_seasons(b)
    tip = pd.to_datetime(b.game_date_time, utc=True).groupby(b.team_id.astype(np.int64)).min()
    off = snapshot_rosters(files, tip, season)
    app = ps[["team_id", "athlete_id"]]
    teams = set(app.team_id) & set(off.team_id)
    o = off[off.team_id.isin(teams)].set_index(["team_id", "athlete_id"]).index
    a = app[app.team_id.isin(teams)].set_index(["team_id", "athlete_id"]).index
    return {
        "season": season,
        "teams_compared": len(teams),
        "appeared_players_on_official_roster": round(float(a.isin(o).mean()), 4),
        "official_roster_players_appeared_to_date": round(float(o.isin(a).mean()), 4),
        "box_data_through": str(pd.to_datetime(b.game_date).max().date()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--box-dir", type=Path, required=True)
    ap.add_argument("--seasons", default="2008-2027")
    ap.add_argument("--snapshots", action="append", default=[], help="SEASON=DIR (jsonl files)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    snaps = {}
    for s in a.snapshots:
        k, _, d = s.partition("=")
        snaps[int(k)] = sorted(Path(d).glob("*.jsonl"))
    feat = build(a.box_dir, _seasons(a.seasons), snaps)
    a.out.mkdir(parents=True, exist_ok=True)
    feat["membership_as_of"] = feat.membership_as_of.astype(str)
    feat.to_parquet(a.out / "preseason_roster_features.parquet", index=False)
    rep = {"coverage": coverage(feat), "proxy_vs_official": [
        proxy_vs_official(a.box_dir, s, f) for s, f in snaps.items()
    ]}  # fmt: skip
    (a.out / "coverage_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep["proxy_vs_official"]), len(feat))


if __name__ == "__main__":
    main()
