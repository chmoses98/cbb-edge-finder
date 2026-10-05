"""Frozen D-I player identity table for official-roster identity resolution (Wave 7).

Official athletics rosters carry names, not ESPN athlete ids. Incoming transfers are
missing from their new team's stale ESPN listing, so the same-team exact-name match of
Wave 6 cannot identify them. This table holds, for every player with D-I box-score
minutes in 2010-2026 (all in the past; it never changes), the ESPN-keyed player id, the
name exactly as box scores print it, its normalized key, last team / season and the
listed position. ``cbb_edge.rosters.identity`` matches only on an exact normalized
name that is unique in the whole table.

    python scripts/data/build_player_identity.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.rosters.truth import norm_name

OUT = Path("models/rosters/player_identity_2026.parquet")


def main() -> None:
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "player_id", "player_name", "team_id", "min", "position", "available_at"],
    )
    pg = pg[(pg["season"].between(2010, 2026)) & pg["player_id"].notna() & (pg["min"].fillna(0) > 0)]
    pg = pg.sort_values(["season", "available_at"])
    last = pg.groupby("player_id").tail(1)
    name = pg.groupby("player_id")["player_name"].agg(lambda v: v.mode().iloc[0])
    names_all = pg.groupby("player_id")["player_name"].agg(lambda v: sorted(set(v.dropna())))
    out = pd.DataFrame({
        "player_id": last["player_id"].to_numpy(),
        "last_team": last["team_id"].to_numpy(),
        "last_season": last["season"].to_numpy(),
        "position": last["position"].to_numpy(),
    })  # fmt: skip
    out["name"] = out["player_id"].map(name)
    out["names_seen"] = out["player_id"].map(names_all)
    out["name_key"] = out["name"].map(norm_name)
    out = out.sort_values("player_id").reset_index(drop=True)
    out.to_parquet(OUT, index=False)
    man = Path("models/rosters/manifest.json")
    m = json.loads(man.read_text())
    m["files"][OUT.name] = hashlib.sha256(OUT.read_bytes()).hexdigest()
    man.write_text(json.dumps(m, indent=1))
    print(len(out), int(out["name_key"].duplicated(keep=False).sum()), "duplicate-name rows")


if __name__ == "__main__":
    main()
