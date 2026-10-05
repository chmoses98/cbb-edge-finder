"""Daily prospective run (GitHub Actions): refresh free inputs, rebuild silver, project.

1. completed seasons: cached bulk downloads (FREE_BULK);
2. current season: dated immutable live copies (FREE_BULK);
3. silver games / team_games / player_games, stints, shot profile;
4. current-season PBP player shot zones when an active model needs them (pure-0.5.0+);
5. PURE projections for games in the next ``--horizon-h`` hours -> append-only archive.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cbb_edge.app.prospective import (
    active_models,
    availability_overlay,
    load_model,
    project_window,
    write_archive,
)
from cbb_edge.availability.overlay import load_overrides
from cbb_edge.data.bronze import sportsdataverse as sdv
from cbb_edge.data.http import data_dir
from cbb_edge.data.silver.build import build as build_silver
from cbb_edge.features.pbp_shots import build as build_pbp_shots
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
    ap.add_argument(
        "--availability-dir",
        default=None,
        help="checked-out availability-archive (P-AVAIL overlay, challengers)",
    )
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
    act = active_models()
    versions = [act["incumbent"], *act.get("challengers", [])]
    if any("possession" in load_model(v).get("extra_blocks", []) for v in versions):
        # pure-0.5.0+: player shot zones of the CURRENT season only (history comes from
        # the season-boundary checkpoint); free SDV release asset, basketball columns only
        if sdv.download_live("pbp", a.season, stamp) is not None:
            build_pbp_shots([a.season])
    # incumbent + shadow challengers, each from its own frozen artifact; records of one
    # version never touch another's (separate archive paths, append-only)
    out = {}
    failed: dict[str, str] = {}
    for role, version in [("incumbent", act["incumbent"])] + [
        ("challenger", v) for v in act.get("challengers", [])
    ]:
        model = load_model(version)
        try:
            recs = project_window(a.season, now, a.horizon_h, model=model)
        except Exception as e:  # a challenger must never block the incumbent or others
            if role == "incumbent":
                raise
            failed[version] = f"{type(e).__name__}: {e}"
            continue
        for r in recs:
            r["prospective"]["role"] = role
        out[version] = write_archive(recs, Path(a.out))
        if role == "challenger" and a.availability_dir:
            over, when = load_overrides(Path(a.availability_dir), now)
            av = availability_overlay(a.season, now, model, recs, over, when, a.horizon_h)
            for r in av:
                r["prospective"]["role"] = "challenger_availability_overlay"
            out[f"{version}+avail"] = write_archive(av, Path(a.out))
    print(
        json.dumps(
            {"as_of": now.isoformat(), "inputs_stamp": stamp, "models": out, "failed": failed}
        )
    )
    # a failed challenger is reported in the summary; the workflow turns the run red
    # AFTER the healthy versions' records are appended to the archive


if __name__ == "__main__":
    main()
