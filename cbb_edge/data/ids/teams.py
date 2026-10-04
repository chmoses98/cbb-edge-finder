"""Canonical team identity.

``teams.csv`` (committed, next to this module) is the registry of every team that was
Division I in any ingested season. Canonical IDs (``T0001`` ...) are internal and
permanent: once assigned they are never renumbered; new teams are appended.

``aliases.csv`` (committed) maps *source-scoped* names to canonical IDs. Resolution is
exact on a normalized string, scoped to the source first. There is NO fuzzy matching:
anything that does not resolve exactly is logged to ``$CBB_DATA_DIR/ids/unresolved.jsonl``
and returns ``None``, so a bad join can never happen silently.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

from cbb_edge.data.http import data_dir

HERE = Path(__file__).resolve().parent
TEAMS_CSV = HERE / "teams.csv"
ALIASES_CSV = HERE / "aliases.csv"
NON_D1 = None  # opponents outside D-I have no canonical ID

TEAM_COLUMNS = [
    "team_id",
    "espn_team_id",
    "espn_slug",
    "espn_display_name",
    "espn_location",
    "espn_short_name",
    "espn_abbreviation",
    "bart_team",
    "kp_team",
    "fox_team_id",
    "conference_latest",
    "first_d1_season",
    "last_d1_season",
    "n_d1_seasons",
    "kalshi_code",
    "sports_reference_slug",
]


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[\.'’`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


@lru_cache(maxsize=1)
def _registry() -> pd.DataFrame:
    if not TEAMS_CSV.exists():
        return pd.DataFrame(columns=TEAM_COLUMNS)
    return pd.read_csv(
        TEAMS_CSV, dtype={"team_id": str, "kalshi_code": str, "sports_reference_slug": str}
    )


@lru_cache(maxsize=1)
def _espn_map() -> dict[int, str]:
    reg = _registry()
    return {int(e): t for e, t in zip(reg["espn_team_id"], reg["team_id"], strict=True)}


def canonical_from_espn(espn_id: object) -> str | None:
    if espn_id is None or pd.isna(espn_id):  # type: ignore[call-overload]
        return None
    return _espn_map().get(int(espn_id))  # type: ignore[call-overload]


@lru_cache(maxsize=1)
def _aliases() -> pd.DataFrame:
    if not ALIASES_CSV.exists():
        return pd.DataFrame(columns=["source", "alias", "alias_norm", "team_id"])
    return pd.read_csv(ALIASES_CSV, dtype=str)


def resolve(name: str, source: str, *, log: bool = True) -> str | None:
    """Exact, source-scoped alias resolution. Ambiguity or miss -> None (+ logged)."""
    al = _aliases()
    key = normalize(name)
    hits = al[(al["source"] == source) & (al["alias_norm"] == key)]["team_id"].unique()
    if len(hits) == 0:
        hits = al[al["alias_norm"] == key]["team_id"].unique()
    if len(hits) == 1:
        return str(hits[0])
    if log:
        log_unresolved(
            "team",
            name,
            source,
            "ambiguous" if len(hits) > 1 else "missing",
            candidates=list(map(str, hits)),
        )
    return None


def log_unresolved(kind: str, name: str, source: str, reason: str, **extra: object) -> None:
    path = data_dir() / "ids" / "unresolved.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(UTC).isoformat(),
        "kind": kind,
        "name": name,
        "source": source,
        "reason": reason,
        **extra,
    }
    with path.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def clear_caches() -> None:
    _registry.cache_clear()
    _espn_map.cache_clear()
    _aliases.cache_clear()


def build_registry(seasons: list[int]) -> pd.DataFrame:
    """(Re)build teams.csv / aliases.csv from bronze schedules + SportsDataverse crosswalk.

    Existing canonical IDs are preserved; only never-seen D-I teams get new IDs.
    """
    from cbb_edge.data.bronze.sportsdataverse import local_rel
    from cbb_edge.data.silver.build import BRONZE, d1_membership, load_schedule

    rows = []
    prev_d1: set[int] | None = None
    for season in seasons:
        p = data_dir() / "bronze" / BRONZE / local_rel("schedules", season)
        if not p.exists():
            continue
        sched = load_schedule(season)
        d1 = d1_membership(sched, prev_d1)
        prev_d1 = d1
        raw = pd.read_parquet(p)
        for side in ("home", "away"):
            cols = {
                f"{side}_id": "espn_team_id",
                f"{side}_location": "espn_location",
                f"{side}_display_name": "espn_display_name",
                f"{side}_short_display_name": "espn_short_name",
                f"{side}_abbreviation": "espn_abbreviation",
                f"{side}_conference_id": "conference_id",
            }
            part = raw[list(cols)].rename(columns=cols)
            part["season"] = season
            rows.append(part[part["espn_team_id"].isin(d1)])
    obs = pd.concat(rows, ignore_index=True).dropna(subset=["espn_team_id"])
    obs["espn_team_id"] = obs["espn_team_id"].astype(int)

    latest = obs.sort_values("season").groupby("espn_team_id").tail(1).set_index("espn_team_id")
    span = obs.groupby("espn_team_id")["season"].agg(["min", "max", "nunique"])

    cw_rows = []
    for season in seasons:
        p = data_dir() / "bronze" / BRONZE / local_rel("team_crosswalk", season)
        if p.exists():
            cw_rows.append(pd.read_parquet(p))
    cw = (
        (
            pd.concat(cw_rows)
            .sort_values("season")
            .groupby("espn_team_id")
            .tail(1)
            .set_index("espn_team_id")
        )
        if cw_rows
        else pd.DataFrame()
    )

    old = _registry()
    old_map = {int(e): t for e, t in zip(old["espn_team_id"], old["team_id"], strict=True)}
    next_n = 1 + max([int(t[1:]) for t in old_map.values()], default=0)
    order = span.sort_values(["min"]).index.tolist()
    order = sorted(order, key=lambda e: (span.loc[e, "min"], e))
    recs = []
    for espn in order:
        tid = old_map.get(espn)
        if tid is None:
            tid = f"T{next_n:04d}"
            next_n += 1
        lt = latest.loc[espn]
        c = cw.loc[espn] if (len(cw) and espn in cw.index) else None
        prev = old[old["team_id"] == tid]
        recs.append(
            {
                "team_id": tid,
                "espn_team_id": espn,
                "espn_slug": None
                if c is None
                else normalize(str(c["espn_display_name"])).replace(" ", "-"),
                "espn_display_name": lt["espn_display_name"],
                "espn_location": lt["espn_location"],
                "espn_short_name": lt["espn_short_name"],
                "espn_abbreviation": lt["espn_abbreviation"],
                "bart_team": None if c is None else c.get("bart_team"),
                "kp_team": None if c is None else c.get("kp_team"),
                "fox_team_id": None if c is None else c.get("fox_team_id"),
                "conference_latest": None if c is None else c.get("espn_conference"),
                "first_d1_season": int(span.loc[espn, "min"]),
                "last_d1_season": int(span.loc[espn, "max"]),
                "n_d1_seasons": int(span.loc[espn, "nunique"]),
                "kalshi_code": prev["kalshi_code"].iloc[0] if len(prev) else None,
                "sports_reference_slug": prev["sports_reference_slug"].iloc[0]
                if len(prev)
                else None,
            }
        )
    # Keep any previously registered team that is no longer observed (never drop IDs).
    seen = {r["team_id"] for r in recs}
    kept = old[~old["team_id"].isin(seen)].to_dict("records")
    reg = pd.DataFrame(recs + kept, columns=TEAM_COLUMNS).sort_values("team_id")
    reg.to_csv(TEAMS_CSV, index=False)

    al = []
    for _, r in obs.drop_duplicates(
        ["espn_team_id", "espn_display_name", "espn_location", "espn_short_name"]
    ).iterrows():
        tid = reg.loc[reg["espn_team_id"] == r["espn_team_id"], "team_id"].iloc[0]
        for col in ("espn_display_name", "espn_location", "espn_short_name"):
            if pd.notna(r[col]):
                al.append(("espn", r[col], tid))
        if pd.notna(r["espn_abbreviation"]):
            al.append(("espn_abbr", r["espn_abbreviation"], tid))
    for _, r in reg.iterrows():
        for col, src in (("bart_team", "torvik"), ("kp_team", "kenpom_name")):
            if pd.notna(r[col]):
                al.append((src, r[col], r["team_id"]))
    alias = pd.DataFrame(al, columns=["source", "alias", "team_id"]).drop_duplicates()
    alias["alias_norm"] = alias["alias"].map(normalize)
    alias = alias.drop_duplicates(["source", "alias_norm", "team_id"])
    alias = alias.sort_values(["source", "alias_norm", "team_id"])
    alias[["source", "alias", "alias_norm", "team_id"]].to_csv(ALIASES_CSV, index=False)
    clear_caches()
    return reg
