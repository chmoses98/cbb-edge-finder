"""Audit the preseason roster archive (Wave 5). Read-only: never writes to the archive.

    python scripts/data/roster_archive_audit.py <checked-out roster-archive dir>

For the latest snapshot: coverage (teams, players, season label), field completeness,
and a classification of every listed player from EXACT ids against the player-game
history known at capture time (silver, seasons before the label season):
returning (played for this team last season), transfer-in (last D-I team differs),
newcomer (no D-I history). Staleness signals: team still labelled with the previous
season, and players listed as FR who already have a D-I season.
Writes research/wave5/roster_audit.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.data.ids.teams import _espn_map


def main() -> None:
    root = Path(sys.argv[1])
    snaps = sorted((root / "snapshots").rglob("*.jsonl"))
    rows = [json.loads(x) for x in snaps[-1].read_text().splitlines() if x.strip()]
    s = pd.DataFrame(rows)
    s["team_id"] = s["espn_team_id"].map(_espn_map())
    label_season = s["season_label"].str[:4].astype(int) + 1  # "2026-27" -> 2027
    s["label_season"] = label_season
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "team_id", "player_id", "min", "available_at"],
    )
    cap = pd.Timestamp(s["captured_at"].iloc[0])
    pg = pg[(pg["available_at"] < cap) & (pg["min"].fillna(0) > 0) & pg["team_id"].notna()]
    last = pg.sort_values("season").groupby("player_id").tail(1).set_index("player_id")
    seasons = pg.groupby("player_id")["season"].nunique()
    s["last_team"] = s["player_id"].map(last["team_id"])
    s["last_season"] = s["player_id"].map(last["season"])
    s["d1_seasons"] = s["player_id"].map(seasons).fillna(0).astype(int)
    tgt = 2027
    prev = tgt - 1
    s["class_vs_history"] = "newcomer"
    has = s["d1_seasons"] > 0
    s.loc[
        has & (s["last_team"] == s["team_id"]) & (s["last_season"] == prev), "class_vs_history"
    ] = "returning"
    s.loc[has & (s["last_team"] != s["team_id"]), "class_vs_history"] = "transfer_in"
    s.loc[
        has & (s["last_team"] == s["team_id"]) & (s["last_season"] < prev), "class_vs_history"
    ] = "returning_after_gap"
    stale_team = s.groupby("team_id")["label_season"].max() < tgt
    fr_prior = (s["class"] == "FR") & has
    by_label = s.groupby("label_season")["class_vs_history"].value_counts().unstack(fill_value=0)
    rep = {
        "snapshot": str(snaps[-1].relative_to(root)),
        "captured_at": str(cap),
        "snapshots_in_archive": len(snaps),
        "rows": len(s),
        "teams": int(s["team_id"].nunique()),
        "teams_unmapped_espn_id": int(s["team_id"].isna().sum()),
        "teams_labelled_target_season": int((~stale_team).sum()),
        "teams_still_labelled_previous_season": int(stale_team.sum()),
        "missing_share": {
            c: float(s[c].isna().mean()) for c in ("class", "height_in", "position", "weight_lb")
        },
        "classification_all": s["class_vs_history"].value_counts().to_dict(),
        "classification_by_label_season": {int(k): v for k, v in by_label.to_dict("index").items()},
        "fr_with_prior_d1_season": int(fr_prior.sum()),
        "fr_with_prior_d1_in_stale_teams": int((fr_prior & s["team_id"].map(stale_team)).sum()),
        "status_counts": s["status"].value_counts().to_dict(),
        "note": (
            "ESPN team rosters update over the off-season; a team still labelled with the "
            "previous season is stale, and its 'returning' players are over-counted. "
            "Snapshots are append-only; no later knowledge is ever written into them."
        ),
    }
    Path("research/wave5").mkdir(parents=True, exist_ok=True)
    Path("research/wave5/roster_audit.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
