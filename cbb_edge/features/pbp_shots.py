"""Player-game shot zones from ESPN play-by-play, 2010+ (Wave 5, B21).

Reads ONLY basketball columns of the SportsDataverse PBP files (the files also carry
betting columns; they are never read here).

Format-robust zones (the ESPN text format changed in 2025-26):

* ``ft``  free throws (type or text "free throw");
* ``t3``  text contains "three point" (any case) or a made shot worth 3;
* ``rim`` layup / dunk / tip / alley-oop / putback (type or text), not a three;
* ``j2``  every other two.

Per FG attempt also: ``ast`` (made and ``athlete_id_2`` present), ``pb`` (putback: same
team's offensive rebound <= 4 s of game clock earlier, same period) and ``tr``
(transition: same team's defensive rebound or steal <= 8 s earlier, same period).

Players are keyed by the exact box-score id ``"P" + ESPN athlete id`` and joined to
``silver/player_games`` on (game_id, player_id) for the team id. Unmatched rows are
dropped and counted, never fuzzy-matched.

Output ``data/silver/pbp_player_shots.parquet``: season, game_id, team_id, player_id,
rim_a, rim_m, j2_a, j2_m, t3_a, t3_m, fta, ftm, ast_m, pb_a, pb_m, tr_a, tr_m.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir

COLS = [
    "game_id",
    "sequence_number",
    "period_number",
    "start_game_seconds_remaining",
    "type_text",
    "text",
    "scoring_play",
    "shooting_play",
    "score_value",
    "team_id",
    "athlete_id_1",
    "athlete_id_2",
]
RIM = r"layup|lay-up|lay up|dunk|tip|alley|putback|put back"
OUT_COLS = [
    "rim_a", "rim_m", "j2_a", "j2_m", "t3_a", "t3_m", "fta", "ftm",
    "ast_m", "pb_a", "pb_m", "tr_a", "tr_m",
]  # fmt: skip
PUTBACK_S, TRANSITION_S = 4.0, 8.0


def classify(t: pd.DataFrame) -> pd.DataFrame:
    """Shot rows of one PBP table with zone / made / assisted flags."""
    s = t[t["shooting_play"].fillna(False).astype(bool) & t["athlete_id_1"].notna()].copy()
    txt = (s["type_text"].fillna("") + " " + s["text"].fillna("")).str.lower()
    made = s["scoring_play"].fillna(False).astype(bool)
    ft = txt.str.contains("free throw|freethrow")
    t3 = ~ft & (txt.str.contains("three point") | (made & (s["score_value"] == 3)))
    rim = ~ft & ~t3 & txt.str.contains(RIM)
    s["zone"] = np.select([ft, t3, rim], ["ft", "t3", "rim"], "j2")
    s["made"] = made
    s["ast"] = made & ~ft & s["athlete_id_2"].notna()
    return s


def _timing(t: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """pb / tr flags for FG attempts from the same team's previous ORB / DRB-or-steal."""
    ev = t[["game_id", "seq", "period_number", "start_game_seconds_remaining", "team_id"]].copy()
    typ = t["type_text"].fillna("")
    ev["orb"] = typ.eq("Offensive Rebound")
    ev["gain"] = typ.isin(["Defensive Rebound", "Steal"])
    out = []
    for kind, flag in (("pb", "orb"), ("tr", "gain")):
        e = ev[ev[flag]][
            ["game_id", "period_number", "team_id", "seq", "start_game_seconds_remaining"]
        ]
        e = e.rename(columns={"seq": "e_seq", "start_game_seconds_remaining": "e_t"})
        fg = shots[shots["zone"] != "ft"][
            ["game_id", "period_number", "team_id", "seq", "start_game_seconds_remaining"]
        ].reset_index()
        m = pd.merge_asof(
            fg.sort_values("seq"),
            e.sort_values("e_seq"),
            left_on="seq",
            right_on="e_seq",
            by=["game_id", "period_number", "team_id"],
            allow_exact_matches=False,
        )
        lim = PUTBACK_S if kind == "pb" else TRANSITION_S
        ok = (m["e_t"] - m["start_game_seconds_remaining"]).between(0, lim)
        out.append(pd.Series(ok.to_numpy(), index=m["index"].to_numpy(), name=kind))
    return pd.concat(out, axis=1).reindex(shots.index).fillna(False)


def season_table(season: int, pg: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    p = data_dir() / "bronze" / "sportsdataverse_releases" / local_rel("pbp", season)
    if not p.exists():
        return pd.DataFrame(), {"season": season, "missing": True}
    t = pq.read_table(p, columns=COLS).to_pandas()
    t["seq"] = pd.to_numeric(t["sequence_number"], errors="coerce")
    t["start_game_seconds_remaining"] = pd.to_numeric(
        t["start_game_seconds_remaining"], errors="coerce"
    )
    # one copy per game (some releases duplicate games); keep the longest
    t = t.sort_values(["game_id", "seq"]).drop_duplicates(["game_id", "seq", "text"])
    s = classify(t)
    s = s.join(_timing(t, s))
    s["player_id"] = "P" + s["athlete_id_1"].astype("int64").astype(str)
    fg = s["zone"] != "ft"
    rows = pd.DataFrame(
        {
            "game_id": s["game_id"].astype("int64"),
            "player_id": s["player_id"],
            **{f"{z}_a": (s["zone"] == z).astype(int) for z in ("rim", "j2", "t3")},
            **{f"{z}_m": ((s["zone"] == z) & s["made"]).astype(int) for z in ("rim", "j2", "t3")},
            "fta": (s["zone"] == "ft").astype(int),
            "ftm": ((s["zone"] == "ft") & s["made"]).astype(int),
            "ast_m": s["ast"].astype(int),
            "pb_a": (fg & s["pb"]).astype(int),
            "pb_m": (fg & s["pb"] & s["made"]).astype(int),
            "tr_a": (fg & s["tr"]).astype(int),
            "tr_m": (fg & s["tr"] & s["made"]).astype(int),
        }
    )
    agg = rows.groupby(["game_id", "player_id"], as_index=False).sum()
    ref = pg[pg["season"] == season][["game_id", "player_id", "team_id"]].copy()
    ref["game_id"] = ref["game_id"].astype("int64")
    m = agg.merge(ref, on=["game_id", "player_id"], how="left")
    unmatched = m["team_id"].isna()
    rep = {
        "season": season,
        "pbp_games": int(t["game_id"].nunique()),
        "shots": int(len(s)),
        "player_games": int(len(m)),
        "unmatched_player_games": int(unmatched.sum()),
        "unmatched_shots": int(m.loc[unmatched, OUT_COLS[:6] + ["fta"]].to_numpy().sum()),
        "zone_share": {z: float((s.loc[fg, "zone"] == z).mean()) for z in ("rim", "j2", "t3")},
        "assisted_share_of_makes": float(s.loc[fg & s["made"], "ast"].mean()),
        "putback_share": float(s.loc[fg, "pb"].mean()),
        "transition_share": float(s.loc[fg, "tr"].mean()),
    }
    m = m[~unmatched].assign(season=season)
    return m[["season", "game_id", "team_id", "player_id", *OUT_COLS]], rep


def build(seasons: list[int]) -> pd.DataFrame:
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "player_id", "team_id"],
    )
    pg = pg[pg["team_id"].notna()]
    parts, reps = [], []
    for s in seasons:
        x, rep = season_table(s, pg)
        print(json.dumps(rep), flush=True)
        reps.append(rep)
        if len(x):
            parts.append(x)
    out = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=["season", "game_id", "team_id", "player_id", *OUT_COLS])
    )
    out.to_parquet(data_dir() / "silver" / "pbp_player_shots.parquet", index=False)
    (data_dir() / "silver" / "pbp_player_shots.coverage.json").write_text(
        json.dumps(reps, indent=1)
    )
    return out


if __name__ == "__main__":
    build(list(range(2010, 2027)))
