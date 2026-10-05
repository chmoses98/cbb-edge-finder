"""Silver possession stints from the free stats.ncaa.org possession data (SportsDataverse).

Output per season: ``$CBB_DATA_DIR/silver/stints/stints_{season}.parquet`` with one row per
(game, offense side, offensive five, defensive five): possessions, points, garbage-time
possessions, and ``available_at`` of the game result (for walk-forward filtering).

Identity
--------
NCAA player ids are season-specific (a new id every season — verified: 0 of 3,177
2024→2025 name matches share an id). Cross-season and transfer identity therefore comes
from ESPN athlete ids: an NCAA player-season maps to the ESPN athlete with the *exact*
normalized name on the *same team in the same season* (a ~15-man roster). Ambiguous or
missing matches are logged and keep a season-local id ``N{season}_{ncaa_id}`` — never a
fuzzy guess. Typical exact-match rate: 97–98% of player-seasons.

Game mapping: ``espn_game_id`` when present (2024+); otherwise the exact key
(ET date ±1 day, home ESPN team id, away ESPN team id) against silver games, accepting
only a unique match (home/away swapped allowed for neutral sites).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir
from cbb_edge.data.ids.teams import log_unresolved, normalize

SIDES = ("home", "away")


def _poss_path(season: int) -> Path:
    return (
        data_dir() / "bronze" / "sportsdataverse_releases" / local_rel("ncaa_possessions", season)
    )


def stints_path(season: int) -> Path:
    return data_dir() / "silver" / "stints" / f"stints_{season}.parquet"


def player_map(poss: pd.DataFrame, pg_season: pd.DataFrame, season: int) -> pd.DataFrame:
    """NCAA player-season id -> canonical player id (``P<espn>`` or ``N<season>_<ncaa>``)."""
    rows = []
    for s in SIDES:
        for i in range(1, 6):
            rows.append(
                poss[[f"{s}_{i}_player_id", f"{s}_{i}_clean_name", f"{s}_espn_team_id"]].set_axis(
                    ["ncaa_pid", "name", "team_espn_id"], axis=1
                )
            )
    pl = pd.concat(rows).dropna(subset=["ncaa_pid"]).drop_duplicates("ncaa_pid")
    pl["team_espn_id"] = pd.to_numeric(pl["team_espn_id"], errors="coerce")
    pl["n"] = pl["name"].fillna("").map(normalize)
    espn = pg_season[["team_espn_id", "athlete_espn_id", "player_name"]].drop_duplicates(
        ["team_espn_id", "athlete_espn_id"]
    )
    espn = espn.assign(n=espn["player_name"].fillna("").map(normalize))
    m = pl.merge(espn, on=["team_espn_id", "n"], how="left")
    n_cand = m.groupby("ncaa_pid")["athlete_espn_id"].nunique()
    unique = n_cand[n_cand == 1].index
    first = m[m["ncaa_pid"].isin(unique)].drop_duplicates("ncaa_pid")
    out = pl[["ncaa_pid", "name", "team_espn_id"]].merge(
        first[["ncaa_pid", "athlete_espn_id"]], on="ncaa_pid", how="left"
    )
    out["player_id"] = np.where(
        out["athlete_espn_id"].notna(),
        "P" + out["athlete_espn_id"].astype("Int64").astype(str),
        "N" + str(season) + "_" + out["ncaa_pid"].astype(str),
    )
    for _, r in out[out["athlete_espn_id"].isna()].head(2000).iterrows():
        log_unresolved(
            "player",
            str(r["name"]),
            "ncaa_possessions",
            "missing_or_ambiguous",
            season=season,
            ncaa_pid=str(r["ncaa_pid"]),
            team_espn_id=None if pd.isna(r["team_espn_id"]) else int(r["team_espn_id"]),
        )
    out["match"] = out["athlete_espn_id"].notna()
    return out


def game_map(poss: pd.DataFrame, games_season: pd.DataFrame) -> pd.DataFrame:
    """contest_id -> ESPN game_id (exact keys only)."""
    c = poss.drop_duplicates("contest_id")[
        ["contest_id", "game_date", "home_espn_team_id", "away_espn_team_id", "espn_game_id"]
    ].copy()
    for k in ("home_espn_team_id", "away_espn_team_id", "espn_game_id"):
        c[k] = pd.to_numeric(c[k], errors="coerce").astype("Int64")
    c["d"] = pd.to_datetime(c["game_date"], format="mixed").dt.date
    g = games_season[["game_id", "game_date_et", "home_espn_id", "away_espn_id"]]
    direct = c[c["espn_game_id"].notna()][["contest_id", "espn_game_id"]].rename(
        columns={"espn_game_id": "game_id"}
    )
    rest = c[c["espn_game_id"].isna()]
    cand = []
    for shift in (0, -1, 1):
        r = rest.assign(d=rest["d"] + pd.Timedelta(days=shift))
        for h, a in (("home_espn_id", "away_espn_id"), ("away_espn_id", "home_espn_id")):
            cand.append(
                r.merge(
                    g,
                    left_on=["d", "home_espn_team_id", "away_espn_team_id"],
                    right_on=["game_date_et", h, a],
                )[["contest_id", "game_id"]].assign(pri=abs(shift))
            )
    cand_df = pd.concat(cand).drop_duplicates()
    best = cand_df.sort_values("pri").groupby("contest_id").head(1)
    counts = (
        cand_df[
            cand_df.set_index(["contest_id", "pri"]).index.isin(
                best.set_index(["contest_id", "pri"]).index
            )
        ]
        .groupby("contest_id")
        .size()
    )
    best = best[best["contest_id"].map(counts) == 1]
    out = pd.concat([direct, best[["contest_id", "game_id"]]], ignore_index=True)
    out["game_id"] = out["game_id"].astype("int64")
    return out.drop_duplicates("contest_id")


def build_season(season: int, games: pd.DataFrame, pg: pd.DataFrame) -> dict[str, float]:
    path = _poss_path(season)
    if not path.exists():
        return {}
    cols = (
        [
            "contest_id",
            "game_date",
            "home_espn_team_id",
            "away_espn_team_id",
            "poss_team_espn_team_id",
            "pts",
            "is_garbage_time",
            "espn_game_id",
        ]
        + [f"{s}_{i}_player_id" for s in SIDES for i in range(1, 6)]
        + [f"{s}_{i}_clean_name" for s in SIDES for i in range(1, 6)]
    )
    import pyarrow.parquet as pq

    names = pq.ParquetFile(path).schema_arrow.names
    poss = pd.read_parquet(path, columns=[c for c in cols if c in names])
    if "espn_game_id" not in poss:
        poss["espn_game_id"] = pd.NA
    gs = games[games["season"] == season]
    pmap = player_map(poss, pg[pg["season"] == season], season)
    gmap = game_map(poss, gs)
    pid = dict(zip(pmap["ncaa_pid"].astype(str), pmap["player_id"], strict=True))
    poss = poss.merge(gmap, on="contest_id", how="inner")
    poss = poss.merge(
        gs[
            [
                "game_id",
                "home_espn_id",
                "away_espn_id",
                "available_at",
                "neutral_site",
                "home_is_d1",
                "away_is_d1",
            ]
        ],
        on="game_id",
    )
    poss = poss[poss["home_is_d1"] & poss["away_is_d1"]]
    # orient NCAA home/away to OUR home/away (neutral-site listings may be reversed)
    ncaa_home = pd.to_numeric(poss["home_espn_team_id"], errors="coerce").astype(float)
    our_home = pd.to_numeric(poss["home_espn_id"], errors="coerce").astype(float)
    flipped = ncaa_home.to_numpy() != our_home.to_numpy()
    off_team = pd.to_numeric(poss["poss_team_espn_team_id"], errors="coerce").astype(float)
    ncaa_home_off = off_team.to_numpy() == ncaa_home.to_numpy()
    pcols = {s: [f"{s}_{i}_player_id" for i in range(1, 6)] for s in SIDES}
    H = poss[pcols["home"]].astype("string").to_numpy()
    A = poss[pcols["away"]].astype("string").to_numpy()
    ok = ~(pd.isna(H).any(axis=1) | pd.isna(A).any(axis=1)) & off_team.notna().to_numpy()
    off5 = np.where(ncaa_home_off[:, None], H, A)
    def5 = np.where(ncaa_home_off[:, None], A, H)
    off_is_our_home = np.where(flipped, ~ncaa_home_off, ncaa_home_off)
    vec = np.vectorize(lambda x: pid.get(str(x), "N" + str(season) + "_" + str(x)))
    off5 = np.sort(vec(off5[ok]), axis=1)
    def5 = np.sort(vec(def5[ok]), axis=1)
    sub = poss[ok]
    df = pd.DataFrame(
        {
            "game_id": sub["game_id"].to_numpy(),
            "available_at": sub["available_at"].to_numpy(),
            "neutral": sub["neutral_site"].to_numpy(),
            "off_home": off_is_our_home[ok],
            "pts": pd.to_numeric(sub["pts"], errors="coerce").fillna(0).to_numpy(),
            "garbage": pd.to_numeric(sub["is_garbage_time"], errors="coerce").fillna(0).to_numpy(),
        }
    )
    for i in range(5):
        df[f"o{i}"] = off5[:, i]
        df[f"d{i}"] = def5[:, i]
    keys = (
        ["game_id", "available_at", "neutral", "off_home"]
        + [f"o{i}" for i in range(5)]
        + [f"d{i}" for i in range(5)]
    )
    st = (
        df.groupby(keys, sort=False)
        .agg(poss=("pts", "size"), pts=("pts", "sum"), garbage=("garbage", "sum"))
        .reset_index()
    )
    st["season"] = season
    out = stints_path(season)
    out.parent.mkdir(parents=True, exist_ok=True)
    st.to_parquet(out, index=False)
    return {
        "season": season,
        "contests": int(gmap.shape[0]),
        "games_mapped": int(st["game_id"].nunique()),
        "possessions": int(st["poss"].sum()),
        "stints": len(st),
        "player_seasons": len(pmap),
        "player_espn_match_rate": float(pmap["match"].mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", default="2011-2026")
    a, b = ap.parse_args().seasons.split("-")
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "team_espn_id", "athlete_espn_id", "player_name"],
    )
    rows = []
    for s in range(int(a), int(b) + 1):
        r = build_season(s, games, pg)
        if r:
            print(r, flush=True)
            rows.append(r)
    summ = data_dir() / "silver" / "stints" / "_summary.csv"
    pd.DataFrame(rows).to_csv(summ, index=False)


if __name__ == "__main__":
    main()
