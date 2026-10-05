"""Schedule / context features (basketball-only, known before tip-off).

* rest days since each team's previous game (any opponent; schedules are public in
  advance, and only the dates of *earlier* games are used), back-to-back flag;
* season phase: November, December, conference play, postseason;
* team-specific home-court residual from PRIOR seasons only (hierarchically shrunk to 0
  with ``k`` pseudo-games), computed by ``team_home_effect``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rest_days(games: pd.DataFrame, cap: float = 7.0) -> pd.DataFrame:
    g = games[~games["status"].isin(["STATUS_CANCELED", "STATUS_POSTPONED"])]
    long = (
        pd.concat(
            [
                g[["game_id", "season", "start_time_utc", "home_espn_id"]]
                .rename(columns={"home_espn_id": "team"})
                .assign(side="h"),
                g[["game_id", "season", "start_time_utc", "away_espn_id"]]
                .rename(columns={"away_espn_id": "team"})
                .assign(side="a"),
            ]
        )
        .dropna(subset=["team"])
        .sort_values(["team", "start_time_utc"])
    )
    prev = long.groupby(["team", "season"])["start_time_utc"].shift(1)
    long["rest"] = ((long["start_time_utc"] - prev).dt.total_seconds() / 86400).clip(upper=cap)
    long["rest"] = long["rest"].fillna(cap)
    w = long.pivot_table(index="game_id", columns="side", values="rest", aggfunc="first")
    w.columns = [f"{c}_rest" for c in w.columns]
    out = w.reset_index()
    out["rest_diff"] = out["h_rest"] - out["a_rest"]
    out["h_b2b"] = (out["h_rest"] <= 1.5).astype(float)
    out["a_b2b"] = (out["a_rest"] <= 1.5).astype(float)
    return out


def season_phase(df: pd.DataFrame) -> pd.DataFrame:
    """Phase indicators from the game itself (date, type) — no outcome information."""
    t = pd.to_datetime(df["start_time_utc"], utc=True).dt.tz_convert("America/New_York")
    out = pd.DataFrame(index=df.index)
    out["ph_nov"] = (t.dt.month == 11).astype(float)
    out["ph_dec"] = (t.dt.month == 12).astype(float)
    post = (df["season_type"].fillna(2) == 3) | df["tournament_id"].notna()
    out["ph_post"] = post.astype(float)
    out["ph_conf"] = (df["conference_game"].astype(bool) & ~post).astype(float)
    return out


def team_home_effect(
    df: pd.DataFrame, resid: pd.Series, k: float = 40.0, window: int = 3
) -> pd.Series:
    """Per-game feature: home team's shrunk mean home residual over the previous
    ``window`` seasons (prior seasons only). 0 for neutral sites."""
    out = pd.Series(0.0, index=df.index)
    home_games = df["L"] == 1
    for s in sorted(df["season"].unique()):
        past = home_games & df["season"].between(s - window, s - 1) & resid.notna()
        stats = resid[past].groupby(df.loc[past, "home_team_id"]).agg(["sum", "count"])
        shrunk = stats["sum"] / (stats["count"] + k)
        cur = (df["season"] == s) & home_games
        out[cur] = df.loc[cur, "home_team_id"].map(shrunk).fillna(0.0).to_numpy()
    return out.astype(float).replace([np.inf, -np.inf], 0.0)
