"""Synthetic league generator for engine tests (no network, no data lake)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.features.possessions import add_possessions_and_factors


def make_league(
    n_teams: int = 12,
    n_days: int = 40,
    seed: int = 0,
    season: int = 2020,
    neutral_share: float = 0.1,
    hca: float = 3.0,
):
    rng = np.random.default_rng(seed)
    teams = [f"T{i + 1:04d}" for i in range(n_teams)]
    off = rng.normal(0, 6, n_teams)
    deff = rng.normal(0, 6, n_teams)
    pace = rng.normal(0, 3, n_teams)
    start = pd.Timestamp(f"{season - 1}-11-10 23:00", tz="UTC")
    games, tgs = [], []
    gid = 1000
    for d in range(n_days):
        order = rng.permutation(n_teams)
        for k in range(0, n_teams - 1, 2):
            h, a = order[k], order[k + 1]
            neutral = rng.random() < neutral_share
            L = 0 if neutral else 1
            poss = 68 + pace[h] + pace[a] + rng.normal(0, 2)
            eh = 103 + off[h] + deff[a] + hca / 2 * L + rng.normal(0, 8)
            ea = 103 + off[a] + deff[h] - hca / 2 * L + rng.normal(0, 8)
            t0 = start + pd.Timedelta(days=d)
            ph, pa = round(eh * poss / 100), round(ea * poss / 100)
            gid += 1
            games.append(
                {
                    "game_id": gid,
                    "season": season,
                    "start_time_utc": t0,
                    "game_date_et": t0.tz_convert("America/New_York").date(),
                    "home_team_id": teams[h],
                    "away_team_id": teams[a],
                    "neutral_site": neutral,
                    "home_is_d1": True,
                    "away_is_d1": True,
                    "status": "STATUS_FINAL",
                    "completed": True,
                    "home_score": ph,
                    "away_score": pa,
                    "season_type": 2,
                    "conference_game": False,
                    "tournament_id": np.nan,
                }
            )
            for me, opp, pts, loc in ((h, a, ph, L), (a, h, pa, -L)):
                fga = round(poss * 0.85)
                orb, tov, fta = 10, round(poss * 0.17), 20
                fg3a = round(fga * 0.38)
                fgm = round((pts - 15) / 2.2)
                fg3m = round(fg3a * 0.34)
                tgs.append(
                    {
                        "game_id": gid,
                        "season": season,
                        "team_id": teams[me],
                        "opp_id": teams[opp],
                        "pts": pts,
                        "fga": fga,
                        "fgm": fgm,
                        "fg3a": fg3a,
                        "fg3m": fg3m,
                        "fta": fta,
                        "ftm": 14,
                        "orb": orb,
                        "drb": 24,
                        "tov": tov,
                        "ast": 12,
                        "stl": 6,
                        "blk": 3,
                        "pf": 17,
                        "loc": loc,
                        "start_time_utc": t0,
                        "n_ot": 0,
                        "available_at": t0 + pd.Timedelta(hours=3),
                        "team_is_d1": True,
                        "opp_is_d1": True,
                    }
                )
    tg = pd.DataFrame(tgs)
    opp = tg[
        [
            "game_id",
            "team_id",
            "pts",
            "fga",
            "fgm",
            "fg3a",
            "fg3m",
            "fta",
            "ftm",
            "orb",
            "drb",
            "tov",
        ]
    ].rename(columns=lambda c: c if c == "game_id" else f"opp_{c}")
    opp = opp.rename(columns={"opp_team_id": "opp_id"})
    tg = tg.merge(opp, on=["game_id", "opp_id"])
    # force exact possessions so efficiency targets are exact
    tg = add_possessions_and_factors(tg)
    tg["box_ok"] = True
    truth = pd.DataFrame({"team_id": teams, "off": off, "def": deff, "pace": pace})
    return pd.DataFrame(games), tg, truth
