"""ESPN pregame home win probability (public benchmark) from SportsDataverse PBP files.

``pregame_home_prob`` is the tip-off value of ESPN's published win-probability series:
a public pregame forecast that existed before each game, so it is timestamp-safe as a
benchmark. It is NEVER used as a model input. Rows where ESPN shows no forecast
(constant 0.5 / missing) are dropped.
"""

from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq

from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir


def build(seasons: list[int]) -> pd.DataFrame:
    out = []
    for s in seasons:
        p = data_dir() / "bronze" / "sportsdataverse_releases" / local_rel("pbp", s)
        if not p.exists():
            continue
        cols = ["game_id", "pregame_home_prob", "game_spread_available", "home_team_spread"]
        names = pq.ParquetFile(p).schema_arrow.names
        t = pq.read_table(p, columns=[c for c in cols if c in names]).to_pandas()
        t = t.drop_duplicates("game_id")
        t["season"] = s
        out.append(t)
    df = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["game_id"])
    df["game_id"] = df["game_id"].astype("int64")
    df = df[df["pregame_home_prob"].notna() & (df["pregame_home_prob"] != 0.5)]
    dest = data_dir() / "silver" / "espn_pregame.parquet"
    df.to_parquet(dest, index=False)
    return df
