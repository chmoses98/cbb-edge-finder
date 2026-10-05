"""Historical player-season roster graph (ESPN athlete ids, 2006–2026).

One row per (player, season, main team) with: games, starts, minutes, on-court share
(sum 5 per team), usage share, per-40 box production, true shooting, end-of-season
RAPM (when NCAA possession data exist and the player matched exactly), previous /
next D-I team, and status flags:

* ``returning``     – same main team as the previous season
* ``transfer_in``   – previous season on a DIFFERENT D-I team (exact ESPN athlete id)
* ``first_observed``– no earlier D-I season in our data (freshman, juco/D-II arrival,
                      or first season after 2006 coverage start)
* ``seasons_prior`` – number of earlier observed D-I seasons (class/experience proxy)

Identity is the ESPN athlete id only — no name matching here. ``rapm_matched`` records
whether the NCAA possession data matched this player exactly (see stints.py).

Realized-status columns (returning, transfer_in, next_team) describe what HAPPENED and
are for research diagnostics / training targets on prior seasons. Predictive preseason
features use only previous-season data plus models fitted on earlier seasons
(``cbb_edge.players.preseason``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir

BOX = [
    "pts",
    "ast",
    "orb",
    "drb",
    "stl",
    "blk",
    "tov",
    "pf",
    "fga",
    "fg3a",
    "fta",
    "fgm",
    "fg3m",
    "ftm",
]


def build(
    seasons: list[int] | None = None, pg: pd.DataFrame | None = None, save: bool = True
) -> pd.DataFrame:
    """``pg`` (optional) = player-game rows to use, e.g. restricted to games available
    before a prospective run's ``as_of``; default = the whole silver table."""
    if pg is None:
        pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & pg["min"].fillna(0).gt(0)].copy()
    if seasons:
        pg = pg[pg["season"].isin(seasons)]
    for c in BOX + ["min"]:
        pg[c] = pd.to_numeric(pg[c], errors="coerce").fillna(0.0)
    pg["starter"] = pg["starter"].fillna(False).astype(bool)
    team_tot = pg.groupby(["season", "team_id"]).agg(
        team_min=("min", "sum"),
        team_use=("fga", "sum"),
        team_fta=("fta", "sum"),
        team_tov=("tov", "sum"),
        team_games=("game_id", "nunique"),
    )
    agg = (
        pg.groupby(["player_id", "season", "team_id"])
        .agg(
            games=("game_id", "nunique"),
            starts=("starter", "sum"),
            minutes=("min", "sum"),
            position=("position", "last"),
            name=("player_name", "last"),
            **{c: (c, "sum") for c in BOX},
        )
        .reset_index()
    )
    # main team per player-season (most minutes); remember multi-team seasons
    agg = agg.sort_values("minutes", ascending=False)
    n_teams = agg.groupby(["player_id", "season"])["team_id"].transform("nunique")
    agg["n_teams"] = n_teams
    main = agg.drop_duplicates(["player_id", "season"]).copy()
    main = main.merge(team_tot.reset_index(), on=["season", "team_id"], how="left")
    main["min_share"] = 5.0 * main["minutes"] / main["team_min"]
    main["usage_share"] = (main["fga"] + 0.475 * main["fta"] + main["tov"]) / (
        main["team_use"] + 0.475 * main["team_fta"] + main["team_tov"]
    )
    m40 = main["minutes"].clip(lower=1) / 40.0
    for c in ("pts", "ast", "orb", "drb", "stl", "blk", "tov", "pf", "fga", "fg3a", "fta"):
        main[f"{c}_40"] = main[c] / m40
    main["ts"] = main["pts"] / (2 * (main["fga"] + 0.475 * main["fta"])).replace(0, np.nan)
    main["fg3a_rate"] = main["fg3a"] / main["fga"].replace(0, np.nan)
    main["start_rate"] = main["starts"] / main["games"]
    main = main.sort_values(["player_id", "season"])
    g = main.groupby("player_id")
    main["prev_season"] = g["season"].shift(1)
    main["prev_team"] = g["team_id"].shift(1)
    main["next_team"] = g["team_id"].shift(-1)
    main["next_season"] = g["season"].shift(-1)
    consecutive_prev = main["prev_season"] == main["season"] - 1
    main["seasons_prior"] = g.cumcount()
    main["returning"] = consecutive_prev & (main["prev_team"] == main["team_id"])
    # transfers before 2021 usually sat out a season, so the previous OBSERVED season
    # need not be consecutive; any earlier D-I team that differs counts
    main["transfer_in"] = main["prev_team"].notna() & (main["prev_team"] != main["team_id"])
    main["sat_out_before"] = main["prev_season"].notna() & ~consecutive_prev
    main["first_observed"] = main["seasons_prior"] == 0
    main["returns_next"] = (main["next_season"] == main["season"] + 1) & (
        main["next_team"] == main["team_id"]
    )
    main["transfers_next"] = main["next_team"].notna() & (main["next_team"] != main["team_id"])
    # end-of-season RAPM (wave-2 walk-forward run saves these; exact matches only)
    rapm = []
    for s in sorted(main["season"].unique()):
        p = data_dir() / "silver" / "players" / f"rapm_end_{s}.parquet"
        if p.exists():
            rapm.append(pd.read_parquet(p).assign(season=s))
    if rapm:
        r = pd.concat(rapm).rename(columns={"o": "rapm_o", "d": "rapm_d", "poss": "rapm_poss"})
        main = main.merge(r, on=["player_id", "season"], how="left")
        main["rapm_matched"] = main["rapm_poss"].fillna(0) > 0
        main["rapm_net"] = main["rapm_o"] - main["rapm_d"]
    if save:
        out = data_dir() / "silver" / "players" / "player_seasons.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        main.to_parquet(out, index=False)
    return main


def coverage(ps: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for s, x in ps.groupby("season"):
        rot = x[x["min_share"] >= 0.25]  # ~10+ mpg rotation players
        rows.append(
            {
                "season": int(s),
                "player_seasons": len(x),
                "rotation_players": len(rot),
                "returning_share_rot": float(rot["returning"].mean()),
                "transfer_in_share_rot": float(rot["transfer_in"].mean()),
                "first_observed_share_rot": float(rot["first_observed"].mean()),
                "rapm_matched_rot": float(rot["rapm_matched"].mean())
                if "rapm_matched" in rot
                else np.nan,
                "multi_team": int((x["n_teams"] > 1).sum()),
            }
        )
    return pd.DataFrame(rows)
