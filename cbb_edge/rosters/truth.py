"""Roster truth: multi-source, timestamped resolution of who is on each D-I roster.

ESPN's preseason roster feed is visibly stale (Wave 5 audit), so no single source is
treated as truth. Every source row is kept as raw evidence; this module only decides,
deterministically and with rules fixed BEFORE any model evaluation
(research/hypotheses/WAVE6.md, docs/ROSTER_SOURCE_AUDIT.md):

1. **Freshness of a source for a team** (``team_freshness``)
   * any source whose native season label is older than the target season -> stale;
   * an ESPN-family listing (site roster, core season athletes, SportsDataverse copy)
     whose player set is IDENTICAL to that team's previous-season ESPN core list is a
     copied, not-yet-updated roster -> stale ("copy_of_previous_season");
   * official sources (stats.ncaa.org, the school's athletics site) are fresh when their
     season label is the target season.
2. **Independence.** Sources are grouped: ``espn`` (site, core, SDV copy: one feed),
   ``ncaa``, ``school``. Agreement only counts across groups. Within a group a
   player's listing in the group's MOST RECENT fresh capture supersedes older captures
   of the same feed (e.g. a September SportsDataverse copy vs an October ESPN pull:
   the player moved), so same-feed lag is never reported as a conflict.
3. **Player status per (player, team)** from FRESH sources only:
   * ``CONFIRMED``  listed by >= 2 independent groups, or by an official group alone
                    when no fresh source lists him elsewhere;
   * ``LIKELY``     listed by exactly one fresh group (ESPN only);
   * ``CONFLICTED`` fresh sources list the player on more than one team (never
                    silently resolved: every team is kept, flagged);
   * ``STALE``      listed only by stale sources;
   * ``UNKNOWN``    no usable evidence (e.g. an unmatched official name).
4. **Identity.** ESPN athlete ids are the canonical key (``"P" + id`` = box-score id).
   Official rows carry names only: they are matched to an ESPN row of the SAME team by
   exact normalized name, and only when that name is unique on both sides. Anything
   else stays unmatched and is flagged; never fuzzy-matched.
5. **Experience is observed, not labelled.** D-I seasons / games / minutes / previous
   team come from box-score participation strictly before the target season; the
   listed class string is kept but never used to decide newcomer status.

Snapshots are append-only; ``first_seen`` and ``last_confirmed`` carry forward from the
previous state and never rewrite an older snapshot.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd

GROUP = {
    "espn_site": "espn",
    "espn_core": "espn",
    "sdv_rosters": "espn",
    "ncaa_stats": "ncaa",
    "school_site": "school",
}
OFFICIAL = {"ncaa", "school"}
STATUSES = ("CONFIRMED", "LIKELY", "CONFLICTED", "STALE", "UNKNOWN")
ROW_COLS = [
    "source", "captured_at", "team_id", "player_id", "ncaa_player_id", "name", "position",
    "class_label", "height_in", "jersey", "source_season", "previous_school",
]  # fmt: skip


@dataclass(frozen=True)
class TruthConfig:
    target_season: int
    # a player whose last D-I season is older than this many seasons is not a
    # "returner" even if he is back on the same team (injury / redshirt gap)
    returner_gap: int = 1


def norm_name(s: object) -> str:
    """Exact-match key: accents stripped, lower case, punctuation and suffixes removed."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z ]", " ", t.lower())
    t = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def rows_frame(rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(rows).reindex(columns=ROW_COLS)
    df["group"] = df["source"].map(GROUP)
    if df["group"].isna().any():
        raise ValueError(f"unknown roster source(s): {sorted(df.loc[df.group.isna(), 'source'])}")
    df["name_key"] = df["name"].map(norm_name)
    return df


# ------------------------------------------------------------------ freshness --------
def team_freshness(
    rows: pd.DataFrame, target_season: int, prev_core: dict[str, set[str]] | None = None
) -> pd.DataFrame:
    """One row per (source, team): fresh?, reason, n_players.

    ``prev_core[team_id]`` = the team's previous-season ESPN core athlete set."""
    out = []
    for (src, team), x in rows.groupby(["source", "team_id"]):
        g = GROUP[src]
        seasons = pd.to_numeric(x["source_season"], errors="coerce")
        players = set(x["player_id"].dropna())
        if seasons.notna().any() and seasons.max() < target_season:
            fresh, reason = False, f"season_label_{int(seasons.max())}"
        elif (
            g == "espn"
            and prev_core
            and team in prev_core
            and players
            and (players == prev_core[team])
        ):
            fresh, reason = False, "copy_of_previous_season"
        elif seasons.notna().any():
            fresh, reason = True, "season_label_current"
        else:
            fresh, reason = False, "no_season_label"
        ts = pd.to_datetime(x["captured_at"], utc=True, format="ISO8601").max()
        out.append({"source": src, "group": g, "team_id": team, "fresh": fresh,
                    "reason": reason, "n_players": len(x), "captured_ts": ts})  # fmt: skip
    f = pd.DataFrame(out)
    if f.empty:
        return f
    # same feed: if the team's LATEST capture of a group is stale, an older capture of
    # that group cannot be fresher (a September copy of a roster ESPN still shows stale)
    last = f.sort_values("captured_ts").groupby(["group", "team_id"]).tail(1)
    stale_last = last[~last["fresh"]].set_index(["group", "team_id"])["captured_ts"]
    k = list(zip(f["group"], f["team_id"], strict=True))
    older = [
        kk in stale_last.index and ts < stale_last[kk]
        for kk, ts in zip(k, f["captured_ts"], strict=True)
    ]
    m = np.array(older, dtype=bool) & f["fresh"].to_numpy()
    f.loc[m, "fresh"] = False
    f.loc[m, "reason"] = "older_copy_of_stale_feed"
    return f


# ------------------------------------------------------------------ identity ---------
def match_official(rows: pd.DataFrame) -> pd.DataFrame:
    """Give official (name-only) rows the ESPN id of the same team's unique exact-name
    match. Returns rows with ``player_id`` filled where matched and ``identity`` flag."""
    rows = rows.copy()
    rows["identity"] = np.where(rows["player_id"].notna(), "espn_id", "unmatched")
    espn = rows[(rows["group"] == "espn") & rows["player_id"].notna()]
    key = espn.drop_duplicates(["team_id", "player_id"]).groupby(["team_id", "name_key"])
    uniq = key["player_id"].agg(lambda v: v.iloc[0] if v.nunique() == 1 else None)
    counts = key["player_id"].nunique()
    off = rows["player_id"].isna()
    dup_off = rows[off].groupby(["source", "team_id", "name_key"])["name"].transform("size") > 1
    for i in rows.index[off]:
        k = (rows.at[i, "team_id"], rows.at[i, "name_key"])
        if k in uniq.index and counts.get(k, 0) == 1 and not dup_off.get(i, False):
            rows.at[i, "player_id"] = uniq[k]
            rows.at[i, "identity"] = "exact_name_same_team"
        elif k in uniq.index:
            rows.at[i, "identity"] = "ambiguous_name"
    return rows


# ------------------------------------------------------------------ experience -------
def experience(pg: pd.DataFrame, target_season: int) -> pd.DataFrame:
    """Observed D-I participation strictly before ``target_season`` per player:
    d1_seasons, d1_games, d1_minutes, last_team, last_season, last_season_minutes."""
    h = pg[(pg["season"] < target_season) & (pg["min"].fillna(0) > 0) & pg["team_id"].notna()]
    g = h.groupby("player_id")
    last = h.sort_values(["season", "available_at"]).groupby("player_id").tail(1)
    last_min = h.merge(
        last[["player_id", "season", "team_id"]], on=["player_id", "season", "team_id"]
    )
    out = pd.DataFrame(
        {
            "d1_seasons": g["season"].nunique(),
            "d1_games": g["game_id"].nunique(),
            "d1_minutes": g["min"].sum(),
        }
    )
    out["last_team"] = last.set_index("player_id")["team_id"]
    out["last_season"] = last.set_index("player_id")["season"]
    out["last_season_minutes"] = last_min.groupby("player_id")["min"].sum()
    return out.reset_index()


def classify(team: pd.Series, exp: pd.DataFrame, cfg: TruthConfig) -> pd.DataFrame:
    """returning / returning_after_gap / transfer / first_d1 from observed history."""
    x = pd.DataFrame({"player_id": team.index, "team_id": team.to_numpy()})
    x = x.merge(exp, on="player_id", how="left")
    has = x["d1_seasons"].fillna(0) > 0
    same = x["last_team"] == x["team_id"]
    recent = x["last_season"] >= cfg.target_season - cfg.returner_gap
    x["classification"] = np.select(
        [has & same & recent, has & same, has & ~same],
        ["returning", "returning_after_gap", "transfer"],
        "first_d1",
    )
    x["prior_d1_experience"] = has
    return x


# ------------------------------------------------------------------ resolution -------
def resolve(
    rows: pd.DataFrame,
    fresh: pd.DataFrame,
    exp: pd.DataFrame,
    cfg: TruthConfig,
    as_of: pd.Timestamp,
    prev_state: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Truth records (one per player x listed team) and the conflict log."""
    r = match_official(rows)
    r = r.merge(
        fresh[["source", "team_id", "fresh", "reason"]], on=["source", "team_id"], how="left"
    )
    r["fresh"] = r["fresh"].fillna(False).astype(bool)
    r["key"] = r["player_id"].fillna("U:" + r["team_id"].astype(str) + ":" + r["name_key"])
    # same-feed supersession: per (player, group) keep the latest fresh capture only
    r["captured_ts"] = pd.to_datetime(r["captured_at"], utc=True, format="ISO8601")
    latest = r[r["fresh"]].groupby(["key", "group"])["captured_ts"].transform("max")
    r.loc[latest.index, "superseded"] = r.loc[latest.index, "captured_ts"] < latest
    r["superseded"] = r["superseded"].fillna(False).astype(bool)
    r.loc[r["superseded"], "fresh"] = False
    fr = r[r["fresh"]]
    fresh_teams = fr.groupby("key")["team_id"].agg(lambda v: sorted(set(v)))
    recs = []
    for (key, team), x in r.groupby(["key", "team_id"]):
        fx = x[x["fresh"]]
        groups = sorted(set(fx["group"]))
        other = [t for t in fresh_teams.get(key, []) if t != team]
        if str(key).startswith("U:"):
            status = "UNKNOWN"
        elif fx.empty:
            status = "STALE"
        elif other:
            status = "CONFLICTED"
        elif len(groups) >= 2 or (set(groups) & OFFICIAL):
            status = "CONFIRMED"
        else:
            status = "LIKELY"
        first = x.iloc[0]
        recs.append(
            {
                "player_id": None if str(key).startswith("U:") else key,
                "espn_athlete_id": None if str(key).startswith("U:") else str(key)[1:],
                "ncaa_player_id": x["ncaa_player_id"].dropna().iloc[0]
                if x["ncaa_player_id"].notna().any()
                else None,
                "team_id": team,
                "as_of": as_of.isoformat(),
                "name": first["name"],
                "sources": sorted(set(x["source"])),
                "fresh_sources": sorted(set(fx["source"])),
                "source_seasons": sorted({int(v) for v in x["source_season"].dropna()}),
                "class_labels": sorted({str(v) for v in x["class_label"].dropna()}),
                "position": x["position"].dropna().iloc[0] if x["position"].notna().any() else None,
                "height_in": float(x["height_in"].dropna().iloc[0])
                if x["height_in"].notna().any()
                else None,
                "previous_school_listed": x["previous_school"].dropna().iloc[0]
                if x["previous_school"].notna().any()
                else None,
                "identity": ",".join(sorted(set(x["identity"]))),
                "status": status,
                "conflict_teams": other,
            }
        )
    t = pd.DataFrame(recs)
    if t.empty:
        return t, pd.DataFrame()
    cls = (
        classify(t.set_index("player_id")["team_id"].dropna(), exp, cfg)
        if t["player_id"].notna().any()
        else None
    )
    if cls is not None:
        t = t.merge(
            cls.drop(columns=["team_id"]).drop_duplicates("player_id"), on="player_id", how="left"
        )
    t["classification"] = t.get("classification", pd.Series(index=t.index)).fillna("first_d1")
    t["prior_d1_experience"] = t.get("prior_d1_experience", False)
    t["prior_d1_experience"] = t["prior_d1_experience"].fillna(False).astype(bool)
    fr_lbl = t["class_labels"].map(lambda v: any(str(c).upper() in ("FR", "FRESHMAN") for c in v))
    t["class_label_conflict"] = fr_lbl & t["prior_d1_experience"]
    # carry first_seen / last_confirmed (append-only state, never rewritten)
    t["first_seen"] = as_of.isoformat()
    t["last_confirmed"] = np.where(
        t["status"].isin(["CONFIRMED", "LIKELY"]), as_of.isoformat(), None
    )
    if prev_state is not None and len(prev_state):
        ps = prev_state.set_index(["player_id", "team_id"])
        idx = list(zip(t["player_id"], t["team_id"], strict=True))
        fs = [ps["first_seen"].get(k) for k in idx]
        t["first_seen"] = [
            f if isinstance(f, str) else d for f, d in zip(fs, t["first_seen"], strict=True)
        ]
        lc = [ps["last_confirmed"].get(k) for k in idx]
        t["last_confirmed"] = [
            c if c is not None else (p if isinstance(p, str) else None)
            for c, p in zip(t["last_confirmed"], lc, strict=True)
        ]
    conflicts = t[t["status"] == "CONFLICTED"][
        ["player_id", "name", "team_id", "conflict_teams", "fresh_sources"]
    ]
    return t, conflicts


def team_summary(truth: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """Per team: fresh groups, counts by status / classification, roster confidence."""
    if truth.empty:
        return pd.DataFrame()
    g = truth.groupby("team_id")
    s = pd.DataFrame(
        {
            "n_listed": g.size(),
            **{
                f"n_{k.lower()}": g["status"].apply(lambda v, k=k: int((v == k).sum()))
                for k in STATUSES
            },
            **{
                f"n_{c}": g["classification"].apply(lambda v, c=c: int((v == c).sum()))
                for c in ("returning", "returning_after_gap", "transfer", "first_d1")
            },
            "n_class_label_conflict": g["class_label_conflict"].sum(),
        }
    )
    fg = fresh[fresh["fresh"]].groupby("team_id")["group"].agg(lambda v: sorted(set(v)))
    s["fresh_groups"] = fg.reindex(s.index)
    s["fresh_groups"] = s["fresh_groups"].map(lambda v: v if isinstance(v, list) else [])
    ok = (s["n_confirmed"] + s["n_likely"]) / s["n_listed"].clip(lower=1)
    # team-level: CONFIRMED (>= 2 independent fresh groups, or an official one), LIKELY
    # (one fresh group covering >= 80% of listed players), else STALE; any conflicted
    # player makes the team CONFLICTED; UNKNOWN = team absent from every source
    s["roster_confidence"] = np.select(
        [
            s["fresh_groups"].map(len) >= 2,
            s["fresh_groups"].map(lambda v: bool(set(v) & OFFICIAL)),
            (s["fresh_groups"].map(len) == 1) & (ok >= 0.8),
        ],
        ["CONFIRMED", "CONFIRMED", "LIKELY"],
        "STALE",
    )
    s.loc[(s["n_conflicted"] > 0) & (s["roster_confidence"] != "STALE"), "roster_confidence"] = (
        "CONFLICTED"
    )
    return s.reset_index()
