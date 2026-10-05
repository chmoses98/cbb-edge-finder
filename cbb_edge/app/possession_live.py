"""Live player possession block (pure-0.5.0+): the research computation of
``scripts/research/run_wave5.py`` replayed for the current season only, from the
season-boundary checkpoint (``cbb_edge.app.checkpoints``).

Completed games (player rows with ``available_at`` < as_of) get exactly the research
pregame values. Upcoming games get each team's state after all its completed games,
which is the research value of that game whenever no other game of the team falls in
between.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.players import possession as pos
from cbb_edge.research import blocks


def _shots(season: int) -> pd.DataFrame:
    p = data_dir() / "silver" / "pbp_player_shots.parquet"
    if not p.exists():
        from cbb_edge.features.pbp_shots import OUT_COLS

        return pd.DataFrame(columns=["season", "game_id", "team_id", "player_id", *OUT_COLS])
    s = pd.read_parquet(p)
    return s[s["season"] == season]


def possession_frame(
    model: dict[str, Any],
    ck: Any,
    season: int,
    as_of: pd.Timestamp,
    games_info: pd.DataFrame,
    df: pd.DataFrame,
) -> pd.DataFrame:
    spec = model["possession"]
    sil = data_dir() / "silver"
    pg = pd.read_parquet(sil / "player_games.parquet")
    pg = pg[(pg["season"] == season) & (pg["available_at"] < as_of)]
    tg = pd.read_parquet(sil / "team_games.parquet")
    tg = tg[(tg["season"] == season) & (tg["available_at"] < as_of)]
    shots = _shots(season)
    x = pos.player_rows(pg, tg, shots)
    pr = pos.PlayerPrior(**spec["prior"])
    gs = games_info[games_info["season"] == season]
    prof = pos.team_profiles(
        x,
        pr,
        gs,
        ck.poss_p_ret(),
        offset=ck.poss_careers(),
        end_val_init=ck.poss_end_values(),
        end_w_init=ck.poss_end_weights(),
        pos_mix=spec["pos_mix"],
        extra_teams=[
            (season, t)
            for t in pd.concat([gs["home_team_id"], gs["away_team_id"]]).dropna().unique()
        ],
    )
    nxt = pos.team_profiles.next_state  # type: ignore[attr-defined]
    # upcoming = not yet available at as_of (completed games without rows stay missing,
    # exactly as in research, and get the fixed fill values)
    upc = gs[gs["available_at"] >= as_of]
    sides = pd.concat(
        [
            upc[["game_id", "home_team_id"]].rename(columns={"home_team_id": "team_id"}),
            upc[["game_id", "away_team_id"]].rename(columns={"away_team_id": "team_id"}),
        ]
    ).dropna()
    have = set(zip(prof["game_id"], prof["team_id"], strict=True))
    up = sides[
        [(g, t) not in have for g, t in zip(sides["game_id"], sides["team_id"], strict=True)]
    ]
    up_rows = [
        {"game_id": g, "team_id": t, "season": season, **nxt[(season, t)]}
        for g, t in zip(up["game_id"], up["team_id"], strict=True)
        if (season, t) in nxt
    ]
    prof_all = pd.concat([prof, pd.DataFrame(up_rows)], ignore_index=True) if up_rows else prof
    st = shots.drop(columns=["team_id"]).merge(
        x[["game_id", "player_id", "team_id"]].drop_duplicates(), on=["game_id", "player_id"]
    )
    act = pos.team_actuals(st, tg)
    k = float(spec["k_def"])
    de = pos.defense_excess(act, prof, k)
    dn = pos.defense_next(act, prof, k)
    have_d = set(zip(de["game_id"], de["def_id"], strict=True))
    up_d = sides[
        [(g, t) not in have_d for g, t in zip(sides["game_id"], sides["team_id"], strict=True)]
    ].rename(columns={"team_id": "def_id"})
    up_d = up_d.assign(season=season).merge(dn, on=["season", "def_id"], how="left")
    cols = [f"def_{t}" for t in pos.DEF_TERMS]
    up_d[cols] = up_d[cols].fillna(0.0)  # no completed game yet: zero excess (research)
    de_all = pd.concat([de, up_d[["game_id", "def_id", "season", *cols]]], ignore_index=True)
    lg = pos.league_running(act, gs, prev_full=ck.poss_league())
    return blocks.possession_frame(df, prof_all, de_all, lg, spec["fill"])
