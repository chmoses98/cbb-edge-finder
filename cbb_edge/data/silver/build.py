"""Bronze -> silver: canonical games, team-games and player-games tables.

Silver tables (gitignored, rebuilt deterministically from bronze manifests):

``games.parquet``        one row per scheduled game (all statuses), canonical IDs,
                         UTC start time, ET game date, neutral flag, D-I flags, score.
``team_games.parquet``   one row per team per completed game with box stats, opponent
                         box stats, possessions and Four Factors (raw, not adjusted).
``player_games.parquet`` one row per player per game (box score).

Every row carries ``available_at`` = the earliest UTC time the row's *result* could be
known (start time + 3h is a conservative proxy for final). Walk-forward code only
ever reads rows with ``available_at`` strictly before the prediction cut-off.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir
from cbb_edge.data.ids import teams as team_ids
from cbb_edge.features.possessions import add_possessions_and_factors

BRONZE = "sportsdataverse_releases"
RESULT_LAG = pd.Timedelta(hours=3)
D1_MIN_GAMES = 15  # D-I teams play ~30 ESPN-listed games; non-D-I opponents < 10
PARTIAL_SCHEDULE_GAMES = 4000  # a complete D-I season lists ~5,500-6,300 games


def silver_dir() -> Path:
    return data_dir() / "silver"


def _bronze(dataset: str, season: int) -> Path:
    return data_dir() / "bronze" / BRONZE / local_rel(dataset, season)


def load_schedule(season: int) -> pd.DataFrame:
    s = pd.read_parquet(_bronze("schedules", season))
    # Wave 11: games SDV does not list yet, written by this prospective run from ESPN's
    # archived scoreboard rows in SDV's own schema (cbb_edge.ops.schedule_completion).
    # Current season only (never historical); an SDV game is never replaced.
    from cbb_edge.ops.schedule_completion import fallback_rows_for_silver

    fb = fallback_rows_for_silver(season)
    if fb is not None and len(fb):
        fb = fb[~fb["game_id"].astype("int64").isin(set(s["game_id"].astype("int64")))]
        s = pd.concat([s, fb[[c for c in fb.columns if c in s.columns]]], ignore_index=True)
    return schedule_rows_to_silver(s, season)


def schedule_rows_to_silver(s: pd.DataFrame, season: int) -> pd.DataFrame:
    """SDV-schema schedule rows -> the silver games columns (one transform for SDV rows
    and ESPN-fallback rows alike)."""
    out = pd.DataFrame(
        {
            "game_id": s["game_id"].astype("int64"),
            "season": season,
            "season_type": s["season_type"].astype("Int64"),
            "start_time_utc": pd.to_datetime(s["date"], utc=True, format="mixed"),
            "neutral_site": s["neutral_site"].fillna(False).astype(bool),
            "conference_game": s["conference_competition"].fillna(False).astype(bool),
            "tournament_id": s.get("tournament_id"),
            "notes": s.get("notes_headline"),
            "venue_id": s.get("venue_id"),
            "venue_name": s.get("venue_full_name"),
            "venue_city": s.get("venue_address_city"),
            "venue_state": s.get("venue_address_state"),
            "home_espn_id": s["home_id"].astype("Int64"),
            "away_espn_id": s["away_id"].astype("Int64"),
            "home_name": s["home_location"],
            "away_name": s["away_location"],
            "home_conference_id": s.get("home_conference_id"),
            "away_conference_id": s.get("away_conference_id"),
            "home_score": s["home_score"].astype("Int64"),
            "away_score": s["away_score"].astype("Int64"),
            "periods": s.get("status_period"),
            "status": s["status_type_name"],
            "completed": s["status_type_completed"].fillna(False).astype(bool),
        }
    )
    out["game_date_et"] = out["start_time_utc"].dt.tz_convert("America/New_York").dt.date
    out["available_at"] = out["start_time_utc"] + RESULT_LAG
    out["n_ot"] = (pd.to_numeric(out["periods"], errors="coerce").fillna(2) - 2).clip(lower=0)
    return out.drop_duplicates("game_id")


def d1_membership(
    sched: pd.DataFrame, prev_d1: set[int] | None = None, members: frozenset[int] | None = None
) -> set[int]:
    """D-I teams for a season: teams with >= D1_MIN_GAMES listed games.

    D-I membership is an administrative fact known before the season (published
    schedules), so using the season's schedule to classify it is not result leakage.
    For a season whose schedule is still partial (pre-season), membership falls back to
    the previous season's D-I set plus any team already listed >= D1_MIN_GAMES times.

    Wave 9: ``members`` = the season's AUTHORITATIVE membership (NCAA directory; 2026-27
    on). When given it IS the D-I set (an entering member with few listed games counts,
    a departed one does not). Every season without it (all of 2006-2026) keeps the rule
    above unchanged.
    """
    if members is not None:
        return set(members)
    listed = sched[sched["status"].ne("STATUS_CANCELED")]
    counts = pd.concat([listed["home_espn_id"], listed["away_espn_id"]]).value_counts()
    d1 = {int(t) for t, n in counts.items() if n >= D1_MIN_GAMES}
    if len(listed) < PARTIAL_SCHEDULE_GAMES and prev_d1:
        d1 |= prev_d1
    return d1


def load_team_box(season: int) -> pd.DataFrame:
    p = _bronze("team_box", season)
    if not p.exists():
        return pd.DataFrame()
    tb = pd.read_parquet(p)
    tov = np.fmax(tb["turnovers"].astype(float), tb["total_turnovers"].astype(float))
    out = pd.DataFrame(
        {
            "game_id": tb["game_id"].astype("int64"),
            "team_espn_id": tb["team_id"].astype("int64"),
            "opp_espn_id": tb["opponent_team_id"].astype("int64"),
            "home_away": tb["team_home_away"],
            "pts": tb["team_score"].astype(float),
            "fgm": tb["field_goals_made"].astype(float),
            "fga": tb["field_goals_attempted"].astype(float),
            "fg3m": tb["three_point_field_goals_made"].astype(float),
            "fg3a": tb["three_point_field_goals_attempted"].astype(float),
            "ftm": tb["free_throws_made"].astype(float),
            "fta": tb["free_throws_attempted"].astype(float),
            "orb": tb["offensive_rebounds"].astype(float),
            "drb": tb["defensive_rebounds"].astype(float),
            "ast": tb["assists"].astype(float),
            "stl": tb["steals"].astype(float),
            "blk": tb["blocks"].astype(float),
            "tov": tov,
            "pf": tb["fouls"].astype(float),
        }
    )
    return out.drop_duplicates(["game_id", "team_espn_id"])


def build_season(
    season: int, prev_d1: set[int] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sched = load_schedule(season)
    d1 = d1_membership(sched, prev_d1, team_ids.authoritative_members(season))
    to_id = team_ids.season_mapper(season)  # entering teams get no id before entry
    sched["home_is_d1"] = sched["home_espn_id"].isin(d1)
    sched["away_is_d1"] = sched["away_espn_id"].isin(d1)
    sched["home_team_id"] = sched["home_espn_id"].map(to_id)
    sched["away_team_id"] = sched["away_espn_id"].map(to_id)

    box = load_team_box(season)
    tg = pd.DataFrame()
    if not box.empty:
        opp = box.drop(columns=["opp_espn_id", "home_away"]).rename(
            columns=lambda c: c if c in ("game_id",) else f"opp_{c}"
        )
        opp = opp.rename(columns={"opp_team_espn_id": "opp_espn_id"})
        tg = box.merge(opp, on=["game_id", "opp_espn_id"], how="inner")
        meta = sched[
            [
                "game_id",
                "season",
                "season_type",
                "start_time_utc",
                "game_date_et",
                "available_at",
                "neutral_site",
                "conference_game",
                "n_ot",
                "completed",
                "home_espn_id",
            ]
        ]
        tg = tg.merge(meta, on="game_id", how="inner")
        tg = tg[tg["completed"]]
        tg["is_home"] = (tg["team_espn_id"] == tg["home_espn_id"]) & ~tg["neutral_site"]
        tg["is_away"] = (tg["team_espn_id"] != tg["home_espn_id"]) & ~tg["neutral_site"]
        tg["loc"] = np.where(tg["is_home"], 1, np.where(tg["is_away"], -1, 0))
        tg["team_is_d1"] = tg["team_espn_id"].isin(d1)
        tg["opp_is_d1"] = tg["opp_espn_id"].isin(d1)
        tg["team_id"] = tg["team_espn_id"].map(to_id)
        tg["opp_id"] = tg["opp_espn_id"].map(to_id)
        tg = add_possessions_and_factors(tg)
        tg = tg.drop(columns=["home_espn_id", "completed"])

    pg = pd.DataFrame()
    pp = _bronze("player_box", season)
    if pp.exists():
        pb = pd.read_parquet(pp)
        keep = {
            "game_id": "game_id",
            "athlete_id": "athlete_espn_id",
            "athlete_display_name": "player_name",
            "team_id": "team_espn_id",
            "opponent_team_id": "opp_espn_id",
            "minutes": "min",
            "field_goals_made": "fgm",
            "field_goals_attempted": "fga",
            "three_point_field_goals_made": "fg3m",
            "three_point_field_goals_attempted": "fg3a",
            "free_throws_made": "ftm",
            "free_throws_attempted": "fta",
            "offensive_rebounds": "orb",
            "defensive_rebounds": "drb",
            "assists": "ast",
            "steals": "stl",
            "blocks": "blk",
            "turnovers": "tov",
            "fouls": "pf",
            "points": "pts",
            "starter": "starter",
            "did_not_play": "dnp",
            "athlete_position_abbreviation": "position",
        }
        pg = pb[[c for c in keep if c in pb.columns]].rename(columns=keep)
        pg = pg.dropna(subset=["athlete_espn_id"])
        pg["athlete_espn_id"] = pg["athlete_espn_id"].astype("int64")
        pg["player_id"] = "P" + pg["athlete_espn_id"].astype(str)
        pg["season"] = season
        pg["team_id"] = pg["team_espn_id"].map(to_id)
        pg = pg.merge(sched[["game_id", "available_at", "game_date_et"]], on="game_id", how="inner")
    return sched, tg, pg


def build(seasons: list[int], update_registry: bool = True) -> None:
    """Build silver tables. ``update_registry=False`` (prospective runs) keeps the
    committed team registry untouched; unseen D-I teams then have no canonical id and
    are logged rather than silently numbered."""
    if update_registry:
        team_ids.build_registry(seasons)
    out = silver_dir()
    out.mkdir(parents=True, exist_ok=True)
    gs, tgs, pgs = [], [], []
    prev_d1: set[int] | None = None
    for s in seasons:
        if not _bronze("schedules", s).exists():
            continue
        g, tg, pg = build_season(s, prev_d1)
        prev_d1 = set(g.loc[g["home_is_d1"], "home_espn_id"].astype(int)) | set(
            g.loc[g["away_is_d1"], "away_espn_id"].astype(int)
        )
        gs.append(g)
        tgs.append(tg)
        pgs.append(pg)
        print(f"  silver {s}: games={len(g)} team_games={len(tg)} player_games={len(pg)}")
    games = pd.concat(gs, ignore_index=True)
    games["tournament_id"] = pd.to_numeric(games["tournament_id"], errors="coerce")
    for c in ("venue_id", "home_conference_id", "away_conference_id", "periods"):
        games[c] = pd.to_numeric(games[c], errors="coerce")
    games.to_parquet(out / "games.parquet", index=False)
    pd.concat(tgs, ignore_index=True).to_parquet(out / "team_games.parquet", index=False)
    pd.concat(pgs, ignore_index=True).to_parquet(out / "player_games.parquet", index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", default="2006-2027")
    a, b = ap.parse_args().seasons.split("-")
    build(list(range(int(a), int(b) + 1)))


if __name__ == "__main__":
    main()
