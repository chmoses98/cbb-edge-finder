"""Daily prospective run (GitHub Actions): refresh free inputs, rebuild silver, project.

1. completed seasons: cached bulk downloads (FREE_BULK);
2. current season: dated immutable live copies (FREE_BULK);
3. silver games / team_games / player_games, stints, shot profile;
4. PURE projections for games in the next ``--horizon-h`` hours -> append-only archive.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cbb_edge.app.prospective import active_models, load_model, project_window, write_archive
from cbb_edge.data.bronze import sportsdataverse as sdv
from cbb_edge.data.http import data_dir
from cbb_edge.data.silver.build import build as build_silver
from cbb_edge.features.shot_profile import build as build_shot
from cbb_edge.players.stints import build_season as build_stints

HIST = ("schedules", "team_box", "player_box", "team_crosswalk")
NCAA = ("ncaa_possessions", "ncaa_lineups")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--horizon-h", type=float, default=30.0)
    ap.add_argument("--out", default="projections_out")
    a = ap.parse_args()
    now = pd.Timestamp(datetime.now(UTC))
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    seasons = list(range(a.season - a.warmup, a.season + 1))
    for ds in HIST:
        sdv.download(ds, seasons[:-1])
        sdv.download_live(ds, a.season, stamp)
    for ds in NCAA:
        sdv.download(ds, list(range(a.season - 5, a.season)))
        sdv.download_live(ds, a.season, stamp)
    build_silver(seasons, update_registry=False)
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "team_espn_id", "athlete_espn_id", "player_name"],
    )
    for s in range(a.season - 5, a.season + 1):
        build_stints(s, games, pg)
    build_shot(list(range(a.season - 5, a.season + 1)))
    # incumbent + shadow challengers, each from its own frozen artifact; records of one
    # version never touch another's (separate archive paths, append-only)
    act = active_models()
    out = {}
    for role, version in [("incumbent", act["incumbent"])] + [
        ("challenger", v) for v in act.get("challengers", [])
    ]:
        recs = project_window(a.season, now, a.horizon_h, model=load_model(version))
        for r in recs:
            r["prospective"]["role"] = role
        out[version] = write_archive(recs, Path(a.out))
    print(json.dumps({"as_of": now.isoformat(), "inputs_stamp": stamp, "models": out}))


if __name__ == "__main__":
    main()
