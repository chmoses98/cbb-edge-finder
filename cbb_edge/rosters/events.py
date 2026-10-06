"""Roster change events (Wave 7): what changed between two truth snapshots.

Each event is timestamped with the snapshot that first shows it and is appended to
``events/YYYY/<stamp>_events.jsonl`` in the roster archive; earlier snapshots are never
touched. Event types:

* ``player_added`` / ``player_removed``  a (player, team) entering / leaving the team's
  ON-ROSTER set (status CONFIRMED or LIKELY);
* ``player_team_changed``  an identified player on-roster for a different team than in
  the previous snapshot;
* ``identity_resolved``    an official name unidentified before, identified now;
* ``source_freshness_changed``  a (source, team) became fresh or stale;
* ``confidence_changed``   a team's roster confidence changed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

ON = ("CONFIRMED", "LIKELY")


def _key(r: pd.DataFrame) -> pd.Series:
    return r["player_id"].fillna("U:" + r["team_id"].astype(str) + ":" + r["name"].astype(str))


def diff(
    stamp: str,
    recs: pd.DataFrame,
    teams: pd.DataFrame,
    fresh: pd.DataFrame,
    prev_recs: pd.DataFrame | None,
    prev_teams: pd.DataFrame | None,
    prev_fresh: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    if prev_recs is None or prev_recs.empty:
        return []
    ev: list[dict[str, Any]] = []

    def add(kind: str, team: object, **kw: Any) -> None:
        ev.append({"stamp": stamp, "event": kind, "team_id": team, **kw})

    now = recs[recs["status"].isin(ON)].assign(key=lambda x: _key(x))
    was = prev_recs[prev_recs["status"].isin(ON)].assign(key=lambda x: _key(x))
    n_set = set(zip(now["key"], now["team_id"], strict=True))
    w_set = set(zip(was["key"], was["team_id"], strict=True))
    names = dict(zip(zip(now["key"], now["team_id"], strict=True), now["name"], strict=True))
    names |= dict(zip(zip(was["key"], was["team_id"], strict=True), was["name"], strict=True))
    for k, t in sorted(n_set - w_set, key=str):
        add("player_added", t, player_key=k, name=names.get((k, t)))
    for k, t in sorted(w_set - n_set, key=str):
        add("player_removed", t, player_key=k, name=names.get((k, t)))
    ni = now[now["player_id"].notna()].groupby("player_id")["team_id"].agg(lambda v: sorted(set(v)))
    wi = was[was["player_id"].notna()].groupby("player_id")["team_id"].agg(lambda v: sorted(set(v)))
    for p in sorted(set(ni.index) & set(wi.index)):
        if ni[p] != wi[p]:
            add("player_team_changed", ni[p], player_key=p, previous_team=wi[p])
    un = prev_recs[prev_recs["player_id"].isna()]
    gained = recs[recs["player_id"].notna()]
    m = un.merge(gained, on=["team_id", "name"], suffixes=("_was", ""))
    for r in m.itertuples(index=False):
        add("identity_resolved", r.team_id, name=r.name, player_key=r.player_id)
    if prev_fresh is not None and len(prev_fresh) and len(fresh):
        f = fresh.merge(prev_fresh, on=["source", "team_id"], suffixes=("", "_was"))
        for r in f[f["fresh"] != f["fresh_was"]].itertuples(index=False):
            add("source_freshness_changed", r.team_id, source=r.source,
                fresh=bool(r.fresh), reason=r.reason, previous_reason=r.reason_was)  # fmt: skip
    if prev_teams is not None and len(prev_teams) and len(teams):
        c = teams.merge(prev_teams, on="team_id", suffixes=("", "_was"))
        for r in c[c["roster_confidence"] != c["roster_confidence_was"]].itertuples(index=False):
            add("confidence_changed", r.team_id, confidence=r.roster_confidence,
                previous=r.roster_confidence_was)  # fmt: skip
    return ev
