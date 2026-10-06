"""Catch-up cadence for the scheduled workflows the prospective experiment needs (Wave 9).

GitHub cron ticks can arrive hours late or not at all (this repository's own history:
a 6-hourly schedule fired twice in ~36 h, at 14:49 and 00:06). Each required workflow
therefore keeps its regular slots AND gets an hourly catch-up tick that runs only when
something is actually owed:

* ``projections``  a regular slot (14:10 / 21:10 UTC) passed with no run manifest since,
                   OR a D-I game tipping in (now, now + horizon] lacks a pre-tip record
                   for any required version. Catch-up never writes a record for a game
                   that has tipped (projection covers tip > now only) and, when only a
                   coverage gap is owed, writes only the missing (version, game) records;
* ``scores``       the 12:40 UTC slot passed with no scoreboard since;
* ``rosters``      the 11:17 UTC slot (Sep-Nov daily; Dec-Apr Mondays 12:17) passed with
                   no truth snapshot since.

Everything is decided from the append-only archive branches themselves (no runner
state, no artifacts), so a duplicate tick re-decides from the same facts and does
nothing twice.

    python -m cbb_edge.ops.cadence projections --archive arch/projections-archive \
        --rosters rosters --now <iso> [--horizon-h 30]  -> JSON {"due", "mode", ...}
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

PROJECTION_SLOTS = ((14, 10), (21, 10))
SCORE_SLOTS = ((12, 40),)
ROSTER_SLOTS_DAILY = ((11, 17),)  # Sep-Nov
ROSTER_SLOTS_WEEKLY = ((12, 17),)  # Dec-Apr, Mondays
SEASON_MONTHS = (11, 12, 1, 2, 3, 4)


def _ts(x: object) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def last_slot(now: pd.Timestamp, slots: tuple[tuple[int, int], ...],
              weekday: int | None = None, months: tuple[int, ...] | None = None) -> pd.Timestamp | None:  # fmt: skip
    """The most recent scheduled slot at or before ``now`` (within the last 8 days)."""
    now = _ts(now)
    best = None
    for d in range(0, 8):
        day = (now - pd.Timedelta(days=d)).normalize()
        if weekday is not None and day.weekday() != weekday:
            continue
        if months is not None and day.month not in months:
            continue
        for h, m in slots:
            t = day + pd.Timedelta(hours=h, minutes=m)
            if t <= now and (best is None or t > best):
                best = t
        if best is not None:
            return best
    return best


def slot_owed(last_done: pd.Timestamp | None, now: pd.Timestamp, slots: tuple,
              weekday: int | None = None, months: tuple[int, ...] | None = None) -> bool:  # fmt: skip
    s = last_slot(now, slots, weekday, months)
    return s is not None and (last_done is None or _ts(last_done) < s)


# --------------------------------------------------------------------- evidence
def last_manifest(archive: Path) -> pd.Timestamp | None:
    """``as_of`` of the newest projection run manifest (every run writes one, also with
    no game in its window: the run's heartbeat)."""
    best = None
    for m in Path(archive).rglob("manifests/*.json"):
        try:
            t = _ts(json.loads(m.read_text())["as_of"])
        except (ValueError, KeyError):
            continue
        best = t if best is None or t > best else best
    return best


def existing_records(archive: Path, season: int) -> set[tuple[str, int]]:
    """(version, espn_game_id) pairs that already have a record (any time)."""
    out: set[tuple[str, int]] = set()
    for f in Path(archive).rglob("*.json"):
        if "manifests" in f.parts:
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        g = r.get("game") if isinstance(r, dict) else None
        if g and g.get("season") == season:
            out.add((r.get("model", {}).get("version"), int(g["espn_game_id"])))
    return out


def pre_tip_records(archive: Path, season: int) -> set[tuple[str, int]]:
    """(version, game) pairs with at least one record whose ``as_of`` < its tip."""
    out: set[tuple[str, int]] = set()
    for f in Path(archive).rglob("*.json"):
        if "manifests" in f.parts:
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        g = r.get("game") if isinstance(r, dict) else None
        if not g or g.get("season") != season:
            continue
        if _ts(r["prospective"]["as_of"]) < _ts(g["start_time_utc"]):
            out.add((r.get("model", {}).get("version"), int(g["espn_game_id"])))
    return out


def required_versions(roster_available: bool) -> list[str]:
    from cbb_edge.app.prospective import active_models, load_model

    act = active_models()
    vs = [act["incumbent"], *act.get("challengers", [])]
    out = list(vs)
    if roster_available:
        out += [f"{v}+roster" for v in vs if "possession" in load_model(v).get("extra_blocks", [])]
    return out


def coverage_gaps(sched: pd.DataFrame, have: set[tuple[str, int]], now: pd.Timestamp,
                  horizon_h: float, versions: list[str], d1: set[str],
                  live: dict | None = None) -> list[tuple[str, int]]:  # fmt: skip
    """(version, game) pairs owed: D-I vs D-I, not cancelled, tip in (now, now+h].
    ``live`` (Wave 10, ``schedule_state.live_window``): TBD games whose listed
    placeholder has passed but are positively "pre" are still owed (``extra``); games
    the live scoreboard shows started / postponed / cancelled never are (``exclude``)."""
    end = _ts(now) + pd.Timedelta(hours=horizon_h)
    extra = (live or {}).get("extra", set())
    excl = (live or {}).get("exclude", set())
    in_win = ((sched["tip"] > _ts(now)) & (sched["tip"] <= end)) | sched["espn_game_id"].isin(extra)
    w = sched[in_win & ~sched["espn_game_id"].isin(excl)
              & sched["home_team_id"].isin(d1) & sched["away_team_id"].isin(d1)
              & ~sched["status"].isin(["STATUS_CANCELED", "STATUS_POSTPONED"])]  # fmt: skip
    return sorted((v, int(g)) for g in w["espn_game_id"] for v in versions
                  if (v, int(g)) not in have)  # fmt: skip


def truth_last(rosters: Path) -> pd.Timestamp | None:
    fs = sorted(Path(rosters).rglob("truth/*/*/*/*_records.jsonl"))
    return _ts(fs[-1].name.split("_")[0]) if fs else None


def scores_last(scores: Path) -> pd.Timestamp | None:
    p = Path(scores) / "LATEST"
    if not p.exists():
        return None
    stamp = p.read_text().strip().rsplit("/", 1)[-1]
    try:
        return _ts(datetime.strptime(stamp, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC))
    except ValueError:
        return None


# --------------------------------------------------------------------- decisions
def decide_projections(archive: Path, sched: pd.DataFrame, now: pd.Timestamp, horizon_h: float,
                       d1: set[str], roster_available: bool, season: int = 2027,
                       live: dict | None = None) -> dict:  # fmt: skip
    last = last_manifest(archive) if Path(archive).exists() else None
    in_season = _ts(now).month in SEASON_MONTHS
    slot = in_season and slot_owed(last, now, PROJECTION_SLOTS)
    have = existing_records(archive, season) if Path(archive).exists() else set()
    gaps = coverage_gaps(sched, have, now, horizon_h, required_versions(roster_available), d1, live)
    mode = "full" if slot else ("missing_only" if gaps else "skip")
    return {"workflow": "projections", "due": mode != "skip", "mode": mode,
            "last_run_manifest": None if last is None else last.isoformat(),
            "last_slot": str(last_slot(now, PROJECTION_SLOTS)), "gaps": len(gaps),
            "gap_pairs": [f"{v}|{g}" for v, g in gaps]}  # fmt: skip


def decide_scores(scores: Path, now: pd.Timestamp) -> dict:
    last = scores_last(scores)
    owed = _ts(now).month in SEASON_MONTHS and slot_owed(last, now, SCORE_SLOTS)
    return {"workflow": "scores", "due": bool(owed), "mode": "full" if owed else "skip",
            "last_scoreboard": None if last is None else last.isoformat()}  # fmt: skip


def decide_rosters(rosters: Path, now: pd.Timestamp) -> dict:
    last = truth_last(rosters)
    now = _ts(now)
    if now.month in (9, 10, 11):
        owed = slot_owed(last, now, ROSTER_SLOTS_DAILY, months=(9, 10, 11))
    elif now.month in (12, 1, 2, 3, 4):
        owed = slot_owed(last, now, ROSTER_SLOTS_WEEKLY, weekday=0, months=(12, 1, 2, 3, 4))
    else:
        owed = False
    return {"workflow": "rosters", "due": bool(owed), "mode": "full" if owed else "skip",
            "last_truth_snapshot": None if last is None else last.isoformat()}  # fmt: skip


def schedule_frame(season: int, stamp: str) -> pd.DataFrame:
    from cbb_edge.data.bronze import sportsdataverse as sdv
    from cbb_edge.data.ids.teams import canonical_from_espn_in

    p = sdv.download_live("schedules", season, stamp)
    if p is None:
        return pd.DataFrame(columns=["espn_game_id", "home_team_id", "away_team_id", "tip",
                                     "status"])  # fmt: skip
    s = pd.read_parquet(p)
    return pd.DataFrame({
        "espn_game_id": s["game_id"].astype(int),
        "home_team_id": [canonical_from_espn_in(e, season) for e in s["home_id"]],
        "away_team_id": [canonical_from_espn_in(e, season) for e in s["away_id"]],
        "tip": pd.to_datetime(s["start_date"], utc=True), "status": s["status_type_name"],
        "home_espn": s["home_id"].astype("Int64"), "away_espn": s["away_id"].astype("Int64"),
        "time_state": [time_state_of(v, t, d) for v, t, d in zip(
            s["time_valid"] if "time_valid" in s else [None] * len(s), s["start_date"],
            s["status_type_short_detail"] if "status_type_short_detail" in s else [None] * len(s),
            strict=True)],
    })  # fmt: skip


def time_state_of(v: object, t: object, d: object) -> str:
    from cbb_edge.ops.schedule_state import time_state

    return time_state(None if v is None or (isinstance(v, float) and v != v) else bool(v), t, d)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", choices=["projections", "scores", "rosters"])
    ap.add_argument("--archive", type=Path, default=None)
    ap.add_argument("--rosters", type=Path, default=None)
    ap.add_argument("--scores", type=Path, default=None)
    ap.add_argument("--now", default=None)
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--horizon-h", type=float, default=30.0)
    ap.add_argument("--gaps-out", type=Path, default=None)
    a = ap.parse_args()
    now = _ts(a.now) if a.now else pd.Timestamp(datetime.now(UTC))
    if a.workflow == "projections":
        from cbb_edge.rosters import membership

        d1 = set(membership.members(a.season)["team_id"].dropna())
        sched = schedule_frame(a.season, now.strftime("%Y%m%dT%H%M%SZ"))
        roster_ok = bool(a.rosters and truth_last(a.rosters) is not None)
        from cbb_edge.ops import schedule_state

        obs, failed = schedule_state.fetch_scoreboard(
            schedule_state.window_dates(now, a.horizon_h), now.strftime("%Y%m%dT%H%M%SZ")
        )
        live = schedule_state.live_window(obs, now, a.horizon_h, sched[["espn_game_id", "tip"]])
        dec = decide_projections(a.archive or Path("none"), sched, now, a.horizon_h, d1,
                                 roster_ok, a.season, live)  # fmt: skip
        dec["live_scoreboard"] = {"observations": len(obs), "failed_dates": failed,
                                  "tbd_extra": len(live["extra"]), "excluded": len(live["exclude"])}  # fmt: skip
        if a.gaps_out:
            a.gaps_out.write_text(json.dumps(dec["gap_pairs"]))
    elif a.workflow == "scores":
        dec = decide_scores(a.scores or Path("none"), now)
    else:
        dec = decide_rosters(a.rosters or Path("none"), now)
    dec["now"] = now.isoformat()
    print(json.dumps({k: (v[:20] if k == "gap_pairs" else v) for k, v in dec.items()}))
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as fh:
            fh.write(f"due={'true' if dec['due'] else 'false'}\nmode={dec['mode']}\n")


if __name__ == "__main__":
    main()
