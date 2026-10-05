"""Frozen pre-2026-27 player history for roster truth and P-ROSTER-1 (Wave 6).

The daily runner does not rebuild multi-season silver history, so the information the
roster layer needs about seasons <= 2026 is frozen here once (it can never change: all
of it is in the past):

* ``models/rosters/history_2026.parquet``: per player, observed D-I participation
  through 2025-26 (seasons, games, minutes, last team, last season) and last-season
  role (minute share, start rate, usage share, net rating, position, team net);
* ``models/rosters/rotation_train.parquet``: the expected-rotation training table
  (features from seasons < s, target = first-five-games minute share) for 2011-2026;
* ``models/rosters/manifest.json``: sha256 of both.

    python scripts/data/build_roster_history.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.rosters import truth

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import run_wave3 as w3  # noqa: E402
import run_wave6 as w6  # noqa: E402

OUT = Path("models/rosters")
TARGET = 2027


def main() -> None:
    ctx = w3.Ctx()
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min", "starter", "available_at"],
    )
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    exp = truth.experience(pg, TARGET)
    ps = ctx.ps
    last = ps[ps["season"] <= TARGET - 1].sort_values(["season", "minutes"])
    last = last.groupby("player_id").tail(1)
    fin = ctx.finals9.assign(team_net=lambda f: f["o"] - f["d"])[["team_id", "season", "team_net"]]
    h = exp.merge(
        last[["player_id", "season", "team_id", "min_share", "start_rate", "usage_share",
              "rapm_net", "seasons_prior", "position"]].rename(
            columns={"season": "role_season", "team_id": "role_team"}),
        on="player_id", how="left",
    )  # fmt: skip
    h = h.merge(
        fin.rename(columns={"team_id": "role_team", "season": "role_season"}),
        on=["role_team", "role_season"], how="left",
    )  # fmt: skip
    tgo = w6.team_game_order(ctx)
    tg = w6.first5_targets(pg[pg["season"] >= 2010], tgo)
    feats = w6.rotation_rows(ps, pg, tg[["season", "team_id", "player_id"]], ctx.finals9)
    train = feats.merge(tg, on=["season", "team_id", "player_id"], how="inner")
    train = train[train["season"].between(2011, TARGET - 1)]
    OUT.mkdir(parents=True, exist_ok=True)
    h.to_parquet(OUT / "history_2026.parquet", index=False)
    train.to_parquet(OUT / "rotation_train.parquet", index=False)
    fin[fin["season"] == TARGET - 1].to_parquet(OUT / "team_net_2026.parquet", index=False)
    man = {
        "target_season": TARGET,
        "files": {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(OUT.glob("*.parquet"))
        },
        "rotation_features": w6.ROT_FEATURES,
        "rotation_model": "HistGradientBoostingRegressor(max_depth=3, max_iter=200, "
        "learning_rate=0.05, random_state=0), retrained at run time from rotation_train",
    }
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True))
    print(json.dumps({"players": len(h), "train_rows": len(train), **man}, indent=1))


if __name__ == "__main__":
    main()
