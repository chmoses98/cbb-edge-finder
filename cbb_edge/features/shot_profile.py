"""Team-game shot profile from the free stats.ncaa.org lineup data (SportsDataverse).

Per team-game (offense) we aggregate lineup-stint shot zones: rim / mid-range / three
attempts and makes, and assisted makes. Team identity: lineup rows name the NCAA school;
the possession file of the same contest gives that school's ESPN team id (exact key:
contest id + NCAA school name). Contest → ESPN game via ``stints.game_map`` (exact keys).

Raw rates written here are NOT predictive features; ``cbb_edge.ratings.adjusted`` turns
them into opponent-adjusted offense/defense ratings (``rim_rate``, ``rim_pct``,
``mid_rate``, ``mid_pct``, ``ast_share``).
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir
from cbb_edge.players.stints import game_map

ZONES = ["fga", "fgm", "rima", "rimm", "rim_ast", "mida", "midm", "mid_ast", "tpa", "tpm", "tp_ast"]


def _bronze(ds: str, season: int):
    return data_dir() / "bronze" / "sportsdataverse_releases" / local_rel(ds, season)


def build_season(season: int, games: pd.DataFrame) -> pd.DataFrame:
    lp, pp = _bronze("ncaa_lineups", season), _bronze("ncaa_possessions", season)
    if not lp.exists() or not pp.exists():
        return pd.DataFrame()
    lu = pd.read_parquet(lp, columns=["contest_id", "team", *ZONES])
    poss = pd.read_parquet(
        pp,
        columns=[
            "contest_id",
            "game_date",
            "home",
            "away",
            "home_espn_team_id",
            "away_espn_team_id",
            "espn_game_id",
        ],
    )
    if "espn_game_id" not in poss:
        poss["espn_game_id"] = pd.NA
    names = pd.concat(
        [
            poss[["contest_id", "home", "home_espn_team_id"]].set_axis(
                ["contest_id", "team", "espn"], axis=1
            ),
            poss[["contest_id", "away", "away_espn_team_id"]].set_axis(
                ["contest_id", "team", "espn"], axis=1
            ),
        ]
    ).drop_duplicates(["contest_id", "team"])
    names["espn"] = pd.to_numeric(names["espn"], errors="coerce")
    agg = lu.groupby(["contest_id", "team"], as_index=False)[ZONES].sum(min_count=1)
    agg = agg.merge(names, on=["contest_id", "team"], how="inner").dropna(subset=["espn"])
    gmap = game_map(poss, games[games["season"] == season])
    agg = agg.merge(gmap, on="contest_id", how="inner")
    agg = agg.rename(columns={"espn": "team_espn_id"})
    agg["team_espn_id"] = agg["team_espn_id"].astype("int64")
    agg = agg.drop_duplicates(["game_id", "team_espn_id"])
    agg["season"] = season
    return agg.drop(columns=["contest_id", "team"]).rename(columns={z: f"sz_{z}" for z in ZONES})


def add_rates(tg: pd.DataFrame) -> pd.DataFrame:
    """Derived shot-profile rates on team_games rows that carry sz_* columns."""
    tg = tg.copy()

    def div(a: str, b: str) -> pd.Series:
        den = tg[b].astype(float)
        return tg[a].astype(float).div(den.where(den > 0))

    tg["rim_rate"] = div("sz_rima", "sz_fga")
    tg["rim_pct"] = div("sz_rimm", "sz_rima")
    tg["mid_rate"] = div("sz_mida", "sz_fga")
    tg["mid_pct"] = div("sz_midm", "sz_mida")
    tg["ast_share"] = (
        tg[["sz_rim_ast", "sz_mid_ast", "sz_tp_ast"]]
        .sum(axis=1, min_count=1)
        .astype(float)
        .div(tg["sz_fgm"].where(tg["sz_fgm"] > 0))
    )
    # sanity: lineup totals must roughly match the box score, else drop the row's zones
    ok = (tg["sz_fga"] - tg["fga"]).abs() <= np.maximum(4, 0.08 * tg["fga"])
    for c in ("rim_rate", "rim_pct", "mid_rate", "mid_pct", "ast_share"):
        tg.loc[~ok, c] = np.nan
    tg["sz_ok"] = ok
    return tg


def enrich_team_games(tg: pd.DataFrame) -> pd.DataFrame:
    """team_games + shot-zone columns + derived rates (NaN where no lineup data)."""
    path = data_dir() / "silver" / "shot_profile.parquet"
    if not path.exists():
        return tg
    sp = pd.read_parquet(path).drop(columns=["season"])
    out = tg.merge(sp, on=["game_id", "team_espn_id"], how="left", validate="one_to_one")
    return add_rates(out)


def build(seasons: list[int]) -> pd.DataFrame:
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    parts = []
    for s in seasons:
        d = build_season(s, games)
        if len(d):
            print(f"  shot profile {s}: {len(d)} team-games", flush=True)
            parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(data_dir() / "silver" / "shot_profile.parquet", index=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", default="2010-2026")
    a, b = ap.parse_args().seasons.split("-")
    build(list(range(int(a), int(b) + 1)))


if __name__ == "__main__":
    main()
