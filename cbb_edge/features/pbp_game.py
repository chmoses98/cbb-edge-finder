"""Per-game regulation / overtime / late-game scoring from ESPN play-by-play (2015+).

Reads ONLY basketball columns of the SportsDataverse PBP files (score, period, clock).
The files also carry betting columns (spread etc.); they are never read here.

Output ``data/silver/pbp_game.parquet``: game_id, reg_home, reg_away (score at the end of
regulation), ot_home, ot_away (overtime points), at2_home, at2_away (score with 2:00 left
in regulation), last2_pts (points in the last two regulation minutes), n_periods.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir

COLS = [
    "game_id",
    "sequence_number",
    "period_number",
    "clock_minutes",
    "clock_seconds",
    "home_score",
    "away_score",
]


def season_table(season: int) -> pd.DataFrame:
    p = data_dir() / "bronze" / "sportsdataverse_releases" / local_rel("pbp", season)
    if not p.exists():
        return pd.DataFrame()
    t = pq.read_table(p, columns=COLS).to_pandas()
    t = t.dropna(subset=["period_number", "home_score", "away_score"])
    t["seq"] = pd.to_numeric(t["sequence_number"], errors="coerce")
    t = t.sort_values(["game_id", "seq"])
    t["rem"] = pd.to_numeric(t["clock_minutes"], errors="coerce").fillna(0) * 60 + pd.to_numeric(
        t["clock_seconds"], errors="coerce"
    ).fillna(0)
    g = t.groupby("game_id")
    out = pd.DataFrame({"n_periods": g["period_number"].max()})
    reg = t[t["period_number"] <= 2]
    last_reg = reg.groupby("game_id").tail(1).set_index("game_id")
    out["reg_home"] = last_reg["home_score"]
    out["reg_away"] = last_reg["away_score"]
    fin = g.tail(1).set_index("game_id")
    out["ot_home"] = fin["home_score"] - out["reg_home"]
    out["ot_away"] = fin["away_score"] - out["reg_away"]
    pre2 = reg[(reg["period_number"] < 2) | (reg["rem"] >= 120)]
    at2 = pre2.groupby("game_id").tail(1).set_index("game_id")
    out["at2_home"] = at2["home_score"]
    out["at2_away"] = at2["away_score"]
    out["last2_pts"] = (out["reg_home"] + out["reg_away"]) - (out["at2_home"] + out["at2_away"])
    out = out.reset_index()
    out["game_id"] = out["game_id"].astype("int64")
    out["season"] = season
    return out.replace([np.inf, -np.inf], np.nan)


def build(seasons: list[int]) -> pd.DataFrame:
    df = pd.concat([season_table(s) for s in seasons], ignore_index=True)
    dest = data_dir() / "silver" / "pbp_game.parquet"
    df.to_parquet(dest, index=False)
    return df
