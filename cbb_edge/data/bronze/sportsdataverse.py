"""Bulk download of SportsDataverse hoopR men's college basketball release assets.

All files are public GitHub release assets of ``sportsdataverse/sportsdataverse-data``
(cost class FREE_BULK). Each file is downloaded once, cached permanently and recorded
in ``manifests/bronze/sportsdataverse_releases.jsonl``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from cbb_edge.data.bronze import manifest
from cbb_edge.data.http import fetch

SOURCE = "sportsdataverse_releases"
BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"

# dataset -> (release tag, file stem template)
DATASETS: dict[str, tuple[str, str]] = {
    "schedules": ("espn_mens_college_basketball_schedules", "mbb_schedule_{season}"),
    "team_box": ("espn_mens_college_basketball_team_boxscores", "team_box_{season}"),
    "player_box": ("espn_mens_college_basketball_player_boxscores", "player_box_{season}"),
    "pbp": ("espn_mens_college_basketball_pbp", "play_by_play_{season}"),
    "shots": ("espn_mens_college_basketball_shots", "shots_{season}"),
    "rosters": ("espn_mens_college_basketball_rosters", "rosters_{season}"),
    "game_rosters": ("espn_mens_college_basketball_game_rosters", "game_rosters_{season}"),
    "player_core": ("espn_mens_college_basketball_player_core", "player_core_{season}"),
    "team_crosswalk": ("mbb_crosswalk", "mbb_team_crosswalk_{season}"),
    "schedule_crosswalk": ("mbb_crosswalk", "mbb_schedule_crosswalk_{season}"),
    "player_crosswalk": ("mbb_crosswalk", "mbb_player_crosswalk_{season}"),
    "standings": ("espn_mens_college_basketball_standings", "standings_{season}"),
    # stats.ncaa.org-derived (sportsdataverse/ncaa-mbb-hoops-data); NCAA contest ids
    "ncaa_lineups": ("ncaa_mbb_lineups", "ncaa_mbb_lineups_{season}"),
    "ncaa_matchup_stints": ("ncaa_mbb_matchup_stints", "ncaa_mbb_matchup_stints_{season}"),
    "ncaa_possessions": ("ncaa_mbb_possessions", "ncaa_mbb_possessions_{season}"),
    "ncaa_schedule": ("ncaa_mbb_schedule", "ncaa_mbb_schedule_{season}"),
    "ncaa_player_box": ("ncaa_mbb_player_box", "ncaa_mbb_player_box_{season}"),
}


def asset_url(dataset: str, season: int, ext: str = "parquet") -> str:
    tag, stem = DATASETS[dataset]
    return f"{BASE}/{tag}/{stem.format(season=season)}.{ext}"


def local_rel(dataset: str, season: int, ext: str = "parquet") -> Path:
    _, stem = DATASETS[dataset]
    return Path(dataset) / f"{stem.format(season=season)}.{ext}"


def download(dataset: str, seasons: Iterable[int]) -> list[Path]:
    paths = []
    for season in seasons:
        res = fetch(
            SOURCE,
            asset_url(dataset, season),
            dest=local_rel(dataset, season),
            schema_version=f"sdv-{dataset}-v1",
            not_found_ok=True,
            timeout=600,
        )
        if res is None:
            print(f"  {dataset} {season}: not published (404, cached)")
            continue
        manifest.record(res.meta, dataset=dataset, season=season)
        tag = "cached" if res.from_cache else "downloaded"
        print(f"  {dataset} {season}: {tag} {res.meta['bytes'] / 1e6:.1f} MB")
        paths.append(res.path)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("datasets", nargs="+", choices=sorted(DATASETS))
    ap.add_argument("--seasons", default="2006-2026", help="e.g. 2010-2026 or 2024,2025")
    args = ap.parse_args()
    seasons: list[int] = []
    for part in args.seasons.split(","):
        if "-" in part:
            a, b = part.split("-")
            seasons.extend(range(int(a), int(b) + 1))
        else:
            seasons.append(int(part))
    for ds in args.datasets:
        print(f"[{ds}]")
        download(ds, seasons)


if __name__ == "__main__":
    main()
