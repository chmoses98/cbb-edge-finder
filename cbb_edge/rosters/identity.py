"""Conservative identity resolution for official roster rows (Wave 7).

Official athletics pages list names; the model keys players by ESPN athlete id. The
order below is fixed (research/hypotheses/WAVE7.md, before any 2026-27 game). Every
step is an EXACT match on the normalized name (accents, punctuation and Jr./II-style
suffixes removed). There is no fuzzy matching anywhere; a name that needs judgment
stays unresolved, visibly.

1. ``verified_alias``        ``models/rosters/player_aliases.csv`` (team, official
                             name -> player id), each row checked by hand and documented;
2. ``exact_same_team``       unique exact name among the SAME team's ESPN-family rows;
3. ``exact_history``         unique exact name among all D-I players with box-score
                             minutes in the last ``POOL_SEASONS`` seasons
                             (``models/rosters/player_identity_2026.parquet``);
4. ``exact_espn_any_team``   unique exact name among every team's ESPN-family rows
                             (the player's ESPN id, wherever ESPN still lists him).

A match is rejected as ``conflicting_identity`` when the official page lists the player
as a true freshman (FR, not redshirt) but the matched id has D-I minutes, or when two
official rows of one team resolve to the same id. Unmatched rows are split:

* ``no_d1_history``: no exact name match in the history pool or any ESPN listing AND
  the official class is a (redshirt) freshman, i.e. a player the model has no D-I
  history for by construction (classified ``first_d1``);
* ``unresolved``: everything else (counts against the team's identity coverage).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.rosters.truth import norm_name

REPO = Path(__file__).resolve().parents[2]
IDENTITY = REPO / "models" / "rosters" / "player_identity_2026.parquet"
ALIASES = REPO / "models" / "rosters" / "player_aliases.csv"
POOL_SEASONS = 5  # a 2026-27 player can have D-I minutes from 2021-22 onward at most
RESOLVED = ("verified_alias", "exact_same_team", "exact_history", "exact_espn_any_team")


FIRST_YEAR = ("FR", "FRESHMAN", "FY", "FIRST YEAR", "1ST", "1ST YEAR")


def is_freshman(label: object) -> bool | None:
    """True for FR / first-year labels (FY, 1st), False for a redshirt freshman or an
    upperclassman, None if unknown."""
    s = str(label or "").strip().upper().replace(".", "")
    if not s:
        return None
    if s.startswith(("R-", "RS", "R ")) and ("FR" in s or "FRESH" in s):
        return False
    return s in FIRST_YEAR


def is_any_freshman(label: object) -> bool:
    s = str(label or "").strip().upper().replace(".", "")
    return "FR" in s or "FRESH" in s or s in FIRST_YEAR


_PREFIX = re.compile(r"^\s*(?:previous|last|prior)\s+(?:team|school|college)\s*:\s*", re.I)


@lru_cache(maxsize=1)
def d1_school_keys() -> frozenset[str]:
    """Exact normalized names of every program that was ever D-I in the lake (ESPN
    location / short / display names, NCAA official names and their short forms)."""
    from cbb_edge.data.ids.teams import normalize
    from cbb_edge.rosters.ncaa_directory import UNIVERSE, name_keys

    t = pd.read_csv(REPO / "cbb_edge" / "data" / "ids" / "teams.csv")
    keys: set[str] = set()
    for c in ("espn_location", "espn_short_name", "espn_display_name"):
        keys |= {normalize(x) for x in t[c].dropna()}
    if UNIVERSE.exists():
        for n in pd.read_csv(UNIVERSE)["school"].dropna():
            keys |= name_keys(n)
    return frozenset(k for k in keys if k)


def previous_school_is_d1(text: object) -> bool | None:
    """None when the page lists no previous school; True when any listed school is a
    D-I program by exact normalized name; False otherwise (JUCO, D-II, NAIA, prep, HS,
    international)."""
    from cbb_edge.data.ids.teams import normalize

    s = _PREFIX.sub("", str(text or "")).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    parts = [re.sub(r"\([^)]*\)", " ", x).strip() for x in re.split(r"[/|,;]", s)]
    parts = [normalize(x) for x in parts if x]
    return any(x in d1_school_keys() for x in parts if x)


def _unique_index(keys: pd.Series, ids: pd.Series) -> dict[str, str]:
    g = pd.DataFrame({"k": keys, "id": ids}).dropna().drop_duplicates()
    n = g.groupby("k")["id"].nunique()
    return g[g["k"].isin(n[n == 1].index)].drop_duplicates("k").set_index("k")["id"].to_dict()


def resolve(
    official: pd.DataFrame,
    espn: pd.DataFrame,
    target_season: int,
    identity: pd.DataFrame | None = None,
    aliases: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """``official``: team_id, name, class_label (one row per official listing).
    ``espn``: team_id, player_id, name for every ESPN-family row (any freshness).
    Returns ``official`` with player_id, identity, d1_history_minutes."""
    idt = pd.read_parquet(IDENTITY) if identity is None else identity
    if aliases is None:
        aliases = pd.read_csv(ALIASES, dtype=str) if ALIASES.exists() else pd.DataFrame(
            columns=["team_id", "official_name", "player_id"])  # fmt: skip
    o = official.copy().reset_index(drop=True)
    o["name_key"] = o["name"].map(norm_name)
    # keys from every name the box scores printed for the player (computed here, so the
    # frozen table never pins an old normalization)
    names = idt[["player_id", "last_season", "names_seen"]].explode("names_seen")
    names = names.assign(name_key=names["names_seen"].map(norm_name))
    pool = names[names["last_season"] >= target_season - POOL_SEASONS]
    hist = _unique_index(pool["name_key"], pool["player_id"])
    any_hist = set(names.loc[names["last_season"] >= target_season - 2 * POOL_SEASONS, "name_key"])
    e = espn.dropna(subset=["player_id"]).assign(name_key=lambda x: x["name"].map(norm_name))
    e = e[e["name_key"] != ""]
    any_team = _unique_index(e["name_key"], e["player_id"])
    same = {
        (t, k): v
        for (t, k), v in e.groupby(["team_id", "name_key"])["player_id"]
        .agg(lambda v: v.iloc[0] if v.nunique() == 1 else None)
        .items()
        if v is not None
    }
    al = {(r.team_id, norm_name(r.official_name)): r.player_id for r in aliases.itertuples()}
    has_min = set(idt["player_id"])
    espn_keys = set(e["name_key"])
    pid, how = [], []
    for r in o.itertuples(index=False):
        k = (r.team_id, r.name_key)
        if k in al:
            p, m = al[k], "verified_alias"
        elif k in same:
            p, m = same[k], "exact_same_team"
        elif r.name_key in hist:
            p, m = hist[r.name_key], "exact_history"
        elif r.name_key in any_team:
            p, m = any_team[r.name_key], "exact_espn_any_team"
        else:
            p = None
            known = r.name_key in any_hist or r.name_key in espn_keys
            prev_d1 = previous_school_is_d1(getattr(r, "previous_school", None))
            # A4: a listed previous school that is not a D-I program also shows there
            # is no D-I history to find
            new = is_any_freshman(r.class_label) or prev_d1 is False
            m = "no_d1_history" if (new and not known) else "unresolved"
        if p is not None and m != "verified_alias" and is_freshman(r.class_label) and p in has_min:
            # a true freshman sharing a D-I player's name: a namesake when the page's
            # previous school is not a D-I program (A4), otherwise a conflict
            if previous_school_is_d1(getattr(r, "previous_school", None)) is False:
                p, m = None, "no_d1_history"
            else:
                p, m = None, "conflicting_identity"
        pid.append(p)
        how.append(m)
    o["player_id"], o["identity"] = pid, how
    dup = o["player_id"].notna() & o.duplicated(["team_id", "player_id"], keep=False)
    o.loc[dup, "identity"] = "conflicting_identity"
    o.loc[dup, "player_id"] = None
    o["identity_resolved"] = o["identity"].isin(RESOLVED) | (o["identity"] == "no_d1_history")
    o["player_id"] = o["player_id"].where(o["player_id"].notna(), np.nan)
    return o.drop(columns=["name_key"])
