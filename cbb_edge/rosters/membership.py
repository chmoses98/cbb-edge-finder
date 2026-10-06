"""Season-aware Division I men's basketball membership (Wave 8).

One committed table, ``models/rosters/d1_membership.csv``, one row per (season, team):

* seasons 2006-2026 come from the frozen data pipeline's OWN classification
  (``silver/build.py: d1_membership``, >= ``D1_MIN_GAMES`` listed games), read from the
  silver games table. They are what every frozen model was trained and scored on and are
  never edited here (``evidence = silver_d1_membership``);
* season 2027 (2026-27) comes from the NCAA Membership Directory (``ncaa_directory``,
  ``models/rosters/ncaa_d1_mbb_universe.csv``): the administrative fact for the season
  ahead (``evidence = ncaa_directory``).

Entities are never renamed, merged or deleted: Saint Francis (PA) (T0293) keeps its
2006-2026 rows and has no 2027 row (left D-I; omitted by the 2026-27 directory). A
member without a canonical team id (University of West Florida, entering D-I in
2026-27) is a row with ``team_id`` empty and its ESPN id, when an ESPN schedule lists
it, with that evidence. Giving it a canonical id is an append to
``cbb_edge/data/ids/teams.csv``, an owner decision (it changes which 2026-27 games the
frozen pipeline projects), not something this module does.

This module never changes ``silver/build.py: d1_membership`` or any projection; it is
the reference used by roster capture, scoring diagnostics and coverage reports.

    python -m cbb_edge.rosters.membership --write  # regenerate (needs local silver)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
TABLE = REPO / "models" / "rosters" / "d1_membership.csv"
UNIVERSE = REPO / "models" / "rosters" / "ncaa_d1_mbb_universe.csv"
REGISTRY = REPO / "models" / "rosters" / "ncaa_athletics_domains.json"
DIRECTORY_SEASON = 2027
COLUMNS = ["season", "team_id", "espn_team_id", "ncaa_org_id", "school", "conference",
           "status", "evidence", "evidence_detail"]  # fmt: skip


def _schedule_espn_ids(sched: pd.DataFrame) -> dict[int, tuple[str, int]]:
    """ESPN id -> (location, listed games) from a raw SDV schedule frame."""
    rows = pd.concat([
        sched[["home_id", "home_location"]].set_axis(["e", "loc"], axis=1),
        sched[["away_id", "away_location"]].set_axis(["e", "loc"], axis=1),
    ]).dropna(subset=["e"])  # fmt: skip
    n = rows["e"].astype(int).value_counts()
    loc = rows.assign(e=rows["e"].astype(int)).drop_duplicates("e").set_index("e")["loc"]
    return {int(e): (str(loc[e]), int(n[e])) for e in n.index}


def historical(games: pd.DataFrame, last_season: int) -> pd.DataFrame:
    """Rows for seasons <= ``last_season`` from silver games' D-I flags (frozen rule)."""
    out = []
    for s, x in games[games["season"] <= last_season].groupby("season"):
        h = x.loc[x["home_is_d1"], ["home_team_id", "home_espn_id"]].set_axis(["t", "e"], axis=1)
        a = x.loc[x["away_is_d1"], ["away_team_id", "away_espn_id"]].set_axis(["t", "e"], axis=1)
        d = pd.concat([h, a]).dropna(subset=["e"]).drop_duplicates("e")
        for t, e in zip(d["t"], d["e"].astype(int), strict=True):
            out.append({"season": int(s), "team_id": t if isinstance(t, str) else None,
                        "espn_team_id": e, "status": "MEMBER",
                        "evidence": "silver_d1_membership",
                        "evidence_detail": "silver/build.py d1_membership (>= D1_MIN_GAMES "
                        "listed games)"})  # fmt: skip
    return pd.DataFrame(out)


def directory_season(universe: pd.DataFrame, registry: dict, sched: pd.DataFrame | None,
                     sched_meta: dict | None) -> pd.DataFrame:  # fmt: skip
    """2026-27 rows from the NCAA directory; an unmapped member gets its ESPN id only by
    EXACT location match in the season's ESPN schedule (one id, D-I conference games)."""
    ids = _schedule_espn_ids(sched) if sched is not None and len(sched) else {}
    by_loc: dict[str, list[int]] = {}
    for e, (loc, _n) in ids.items():
        by_loc.setdefault(loc.lower(), []).append(e)
    rows = []
    for u in universe.itertuples(index=False):
        tid = u.team_id if isinstance(u.team_id, str) and u.team_id else None
        esp = int(u.espn_team_id) if pd.notna(u.espn_team_id) else None
        detail = (f"memberList academicYear {registry.get('academic_year')} retrieved "
                  f"{registry.get('retrieved_at')}; reconciliation {u.resolution}")  # fmt: skip
        status = "MEMBER"
        if tid is None:
            status = "MEMBER_NO_CANONICAL_ID"
            short = str(u.school).removeprefix("University of ").strip().lower()
            hit = by_loc.get(short, [])
            if len(hit) == 1:
                esp = hit[0]
                detail += (f"; ESPN id {esp} = exact location '{ids[esp][0]}' in the "
                           f"{DIRECTORY_SEASON} ESPN schedule ({ids[esp][1]} listed games; "
                           f"SDV asset sha256 {(sched_meta or {}).get('sha256', '?')[:16]}, "
                           f"retrieved {(sched_meta or {}).get('retrieved_at')})")  # fmt: skip
        rows.append({"season": DIRECTORY_SEASON, "team_id": tid, "espn_team_id": esp,
                     "ncaa_org_id": int(u.ncaa_org_id), "school": u.school,
                     "conference": u.conference, "status": status,
                     "evidence": "ncaa_directory", "evidence_detail": detail})  # fmt: skip
    return pd.DataFrame(rows)


def build(games: pd.DataFrame, universe: pd.DataFrame, registry: dict,
          sched: pd.DataFrame | None = None, sched_meta: dict | None = None) -> pd.DataFrame:  # fmt: skip
    h = historical(games, DIRECTORY_SEASON - 1)
    names = universe.dropna(subset=["team_id"]).set_index("team_id")
    if len(h):
        h["ncaa_org_id"] = h["team_id"].map(names["ncaa_org_id"])
        h["school"] = h["team_id"].map(names["school"])
    d = directory_season(universe, registry, sched, sched_meta)
    t = pd.concat([h, d], ignore_index=True).reindex(columns=COLUMNS)
    t["ncaa_org_id"] = t["ncaa_org_id"].astype("Int64")
    t["espn_team_id"] = t["espn_team_id"].astype("Int64")
    return t.sort_values(["season", "espn_team_id", "school"], na_position="last").reset_index(
        drop=True
    )


@lru_cache(maxsize=1)
def table() -> pd.DataFrame:
    return pd.read_csv(TABLE, dtype={"team_id": str, "espn_team_id": "Int64",
                                     "ncaa_org_id": "Int64"})  # fmt: skip


def members(season: int) -> pd.DataFrame:
    return table()[table()["season"] == season].reset_index(drop=True)


def is_member(team_id: str, season: int) -> bool:
    m = members(season)
    return bool((m["team_id"] == team_id).any())


def transitions(t: pd.DataFrame | None = None) -> dict[str, list[dict]]:
    """Entities entering / leaving D-I between consecutive seasons (by ESPN id)."""
    t = table() if t is None else t
    out: dict[str, list[dict]] = {}
    seasons = sorted(t["season"].unique())
    for a, b in zip(seasons, seasons[1:], strict=False):
        ea = set(t.loc[t["season"] == a, "espn_team_id"].dropna())
        eb = set(t.loc[t["season"] == b, "espn_team_id"].dropna())
        nb = t[(t["season"] == b) & t["espn_team_id"].isna()]
        out[f"{a}->{b}"] = (
            [{"espn_team_id": int(e), "change": "left"} for e in sorted(ea - eb)]
            + [{"espn_team_id": int(e), "change": "entered"} for e in sorted(eb - ea)]
            + [{"school": s, "change": "entered_no_espn_id"} for s in nb["school"]]
        )
    return out


def sha256(path: Path = TABLE) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    from cbb_edge.data.bronze.sportsdataverse import local_rel
    from cbb_edge.data.http import data_dir
    from cbb_edge.data.silver.build import BRONZE

    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    sp = data_dir() / "bronze" / BRONZE / local_rel("schedules", DIRECTORY_SEASON)
    sched = pd.read_parquet(sp) if sp.exists() else None
    meta_p = sp.with_name(sp.name + ".meta.json")
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else None
    t = build(games, pd.read_csv(UNIVERSE, dtype={"team_id": str}),
              json.loads(REGISTRY.read_text()), sched, meta)  # fmt: skip
    summary = {
        "rows": int(len(t)),
        "by_season": {int(k): int(v) for k, v in t["season"].value_counts().sort_index().items()},
        "no_canonical_id": t[t["team_id"].isna()][["season", "school", "espn_team_id"]]
        .astype(str).to_dict("records"),
        "transitions_2026_2027": transitions(t).get("2026->2027"),
    }  # fmt: skip
    if a.write:
        t.to_csv(TABLE, index=False)
        summary["sha256"] = sha256()
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
