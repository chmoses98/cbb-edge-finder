"""Preseason roster / transfer features per team-season (research builder; not wired into production).

For ESPN season ``S`` (2027 = 2026-27) and team ``t``:

* production statistics come ONLY from player box scores of season ``S-1`` (and earlier, for the
  "has D-I history" test), so they are known before season ``S`` starts;
* roster MEMBERSHIP comes from one of two sources, recorded per row in ``membership_source``:
    - ``espn_roster_snapshot``: the repo's official ESPN roster capture (``roster-archive``), the
      latest full snapshot captured strictly before the team's first game of ``S``
      (``membership_pit = True``, ``membership_as_of`` = snapshot ``captured_at``);
    - ``box_appearance_proxy``: players who logged minutes for ``t`` at any time in ``S`` (no
      historical preseason rosters exist in free data).  This uses hindsight about WHO played
      (never how well), so ``membership_pit = False``; it misses players who never appear
      (injured / redshirt) and adds mid-season arrivals.

Features: returning share of last season's minutes / points / game-score production, incoming
transfer minutes / production (players whose S-1 minutes were for another D-I team), freshmen /
newcomers without D-I box history, and the identity match rate behind them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

BOX_SOURCE = "sportsdataverse ESPN player boxscores (sift-data-vault snapshot-20261116)"
ROSTER_SOURCE = "roster-archive snapshots (ESPN team roster, roster-snapshot-v1)"


def game_score(b: pd.DataFrame) -> pd.Series:
    """Hollinger game score from a player box row (production proxy, box columns only)."""
    f = b.fillna(0)
    return (
        f.points
        + 0.4 * f.field_goals_made
        - 0.7 * f.field_goals_attempted
        - 0.4 * (f.free_throws_attempted - f.free_throws_made)
        + 0.7 * f.offensive_rebounds
        + 0.3 * f.defensive_rebounds
        + f.steals
        + 0.7 * f.assists
        + 0.7 * f.blocks
        - 0.4 * f.fouls
        - f.turnovers
    )


def player_seasons(box: pd.DataFrame) -> pd.DataFrame:
    """(season, team_id, athlete_id) -> minutes, points, prod, games; minutes > 0 only."""
    b = box[box.athlete_id.notna() & (box.minutes.fillna(0) > 0)].copy()
    b["athlete_id"] = b.athlete_id.astype(np.int64)
    b["team_id"] = b.team_id.astype(np.int64)
    b["prod"] = game_score(b)
    g = b.groupby(["season", "team_id", "athlete_id"], as_index=False)
    return g.agg(
        minutes=("minutes", "sum"),
        points=("points", "sum"),
        prod=("prod", "sum"),
        games=("game_id", "nunique"),
        first_date=("game_date", "min"),
    )


def appearance_rosters(ps: pd.DataFrame, season: int) -> pd.DataFrame:
    """Hindsight membership proxy: everyone with minutes for the team in ``season``."""
    r = ps.loc[ps.season == season, ["team_id", "athlete_id"]].copy()
    r["season"] = season
    r["cls"] = None
    r["membership_source"] = "box_appearance_proxy"
    r["membership_pit"] = False
    r["membership_as_of"] = None
    return r


def snapshot_rosters(
    snapshot_files: Iterable[Path], first_tip: pd.Series, season: int
) -> pd.DataFrame:
    """Official roster per team from the latest snapshot holding that team captured before its
    first tip (change-only snapshots carry the changed teams' full rosters).

    ``first_tip``: team_id -> first game timestamp (UTC) of ``season``; teams without a game yet
    use the latest snapshot.
    """
    rows = []
    for p in snapshot_files:
        with open(p) as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("schema") != "roster-snapshot-v1":
                    continue
                if not r.get("espn_athlete_id") or r.get("espn_team_id") is None:
                    continue
                rows.append(
                    (int(r["espn_team_id"]), int(r["espn_athlete_id"]), r.get("class"),
                     r["captured_at"])
                )  # fmt: skip
    s = pd.DataFrame(rows, columns=["team_id", "athlete_id", "cls", "captured_at"])
    s["captured_at"] = pd.to_datetime(s.captured_at, utc=True, format="ISO8601")
    cut = s.team_id.map(first_tip).fillna(pd.Timestamp("2100-01-01", tz="UTC"))
    s = s[s.captured_at < cut]
    last = s.groupby("team_id").captured_at.transform("max")
    s = s[s.captured_at == last].drop_duplicates(["team_id", "athlete_id"])
    out = s.rename(columns={"captured_at": "membership_as_of"})
    out["season"] = season
    out["membership_source"] = "espn_roster_snapshot"
    out["membership_pit"] = True
    return out[["season", "team_id", "athlete_id", "cls", "membership_source",
                "membership_pit", "membership_as_of"]]  # fmt: skip


def team_features(ps: pd.DataFrame, roster: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per-team preseason features for ``season`` from S-1 player seasons + a membership table."""
    prev = ps[ps.season == season - 1]
    hist_ids = set(ps.loc[ps.season < season, "athlete_id"])
    tot = prev.groupby("team_id")[["minutes", "points", "prod"]].sum()
    # an athlete's main S-1 team (most minutes) and S-1 totals across teams
    main = prev.sort_values("minutes").groupby("athlete_id").team_id.last()
    ptot = prev.groupby("athlete_id")[["minutes", "points", "prod"]].sum()
    r = roster.copy()
    r["prev_team"] = r.athlete_id.map(main)
    r["has_hist"] = r.athlete_id.isin(hist_ids)
    ret = r.merge(prev, on=["team_id", "athlete_id"], how="inner")
    ret_sum = ret.groupby("team_id")[["minutes", "points", "prod"]].sum()
    tr = r[r.prev_team.notna() & (r.prev_team != r.team_id)].join(ptot, on="athlete_id")
    tr_sum = tr.groupby("team_id")[["minutes", "points", "prod"]].sum()
    g = r.groupby("team_id")
    out = pd.DataFrame({"n_roster": g.size(), "n_with_d1_history": g.has_hist.sum()})
    out["n_returners"] = ret.groupby("team_id").size()
    out["n_transfers_in"] = tr.groupby("team_id").size()
    out["n_newcomers_no_hist"] = (~r.has_hist).groupby(r.team_id).sum()
    out["n_freshmen_class"] = (
        (r.cls == "FR").groupby(r.team_id).sum() if r.cls.notna().any() else np.nan
    )
    out = out.join(tot.add_prefix("prev_team_"), how="left")
    # max player games ~ team games in S-1; >= 15 marks a D-I team (non-D-I opponents only
    # appear in boxes of their games against D-I teams)
    out["prev_team_games"] = prev.groupby("team_id").games.max().reindex(out.index).fillna(0)
    out["d1_prev"] = out.prev_team_games >= 15
    for k in ("minutes", "points", "prod"):
        d = out[f"prev_team_{k}"]
        out[f"ret_{k}_share"] = ret_sum[k].reindex(out.index).fillna(0) / d
        out[f"tr_in_{k}_rel"] = tr_sum[k].reindex(out.index).fillna(0) / d
    out["tr_in_minutes"] = tr_sum["minutes"].reindex(out.index).fillna(0)
    out["tr_in_prod"] = tr_sum["prod"].reindex(out.index).fillna(0)
    cnt = [c for c in out.columns if c.startswith("n_") and c != "n_freshmen_class"]
    out[cnt] = out[cnt].fillna(0).astype(int)
    meta = r.groupby("team_id").agg(
        membership_source=("membership_source", "first"),
        membership_pit=("membership_pit", "first"),
        membership_as_of=("membership_as_of", "first"),
    )
    out = out.join(meta)
    out["season"] = season
    out["stats_source"] = BOX_SOURCE
    out["stats_through_season"] = season - 1
    return out.reset_index()


def build(
    box_dir: Path,
    seasons: Iterable[int],
    snapshot_files: dict[int, list[Path]] | None = None,
) -> pd.DataFrame:
    """Team-season table for ``seasons``. ``box_dir`` holds player_box_{YYYY}.parquet files.

    Seasons listed in ``snapshot_files`` use official roster snapshots; the others use the
    appearance proxy.
    """
    seasons = sorted(seasons)
    need = range(min(seasons) - 1, max(seasons) + 1)
    cols = ["game_id", "season", "game_date", "game_date_time", "athlete_id", "team_id",
            "minutes", "points", "field_goals_made", "field_goals_attempted",
            "free_throws_made", "free_throws_attempted", "offensive_rebounds",
            "defensive_rebounds", "steals", "assists", "blocks", "fouls", "turnovers"]  # fmt: skip
    box = pd.concat(
        [pd.read_parquet(box_dir / f"player_box_{y}.parquet", columns=cols) for y in need],
        ignore_index=True,
    )
    ps = player_seasons(box)
    snapshot_files = snapshot_files or {}
    out = []
    for s in seasons:
        if s in snapshot_files:
            b = box[box.season == s]
            tip = pd.to_datetime(b.game_date_time, utc=True).groupby(b.team_id.astype(np.int64))
            roster = snapshot_rosters(snapshot_files[s], tip.min(), s)
        else:
            roster = appearance_rosters(ps, s)
        out.append(team_features(ps, roster, s))
    return pd.concat(out, ignore_index=True)
