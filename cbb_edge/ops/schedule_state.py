"""Schedule-time state, live game state and the tip-time history (Wave 10).

Operational only: pre-game SCHEDULING metadata, never outcomes or market data.

**Tip-time state** of a listing:

| state | condition |
|---|---|
| ``ANNOUNCED`` | ESPN ``competitions[0].timeValid`` is true. Includes a genuinely announced 00:00 ET game |
| ``TBD`` | ``timeValid`` is false and the status detail reads "TBD". The date is known, the time is not, and the listed time is ESPN's 00:00 ET placeholder for that date |
| ``PLACEHOLDER`` | ``timeValid`` is false without the "TBD" detail. The listed time cannot be trusted |
| ``UNKNOWN`` | ``timeValid`` is absent. Handled like a placeholder (fail closed) |

Evidence, 2026-10-06:

- In the SDV 2026-27 schedule, ``time_valid`` = false, a 00:00 ET timestamp and a
  "M/D - TBD" status detail always occur together (1,520 games). Every ``time_valid`` =
  true game lists a real time (109).
- The completed 2023-24 to 2025-26 schedules end with ``time_valid`` = true and no
  00:00 ET listing at all.

**Game state** comes from the live ESPN scoreboard (``status.type``). A game counts as
NOT STARTED only when its state is ``pre`` and its status is a pre-game one. In
progress, halftime, final, postponed, cancelled, delayed, suspended, or anything
unrecognized or missing all count as "may have started / do not project" (fail closed).

**Archive.** Every observation (live scoreboard and the daily SDV schedule) is appended
to the ``schedule-archive`` branch as ``obs/YYYY/MM/DD/<stamp>_<source>.jsonl``. A
game's tip-time history is derived from that archive: first observation, time states,
every change and when it was seen, and the final announced tip. The proof that a game
had not started at time t is a live ``pre`` observation made at or after t.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
ET = ZoneInfo("America/New_York")
ANNOUNCED, TBD, PLACEHOLDER, UNKNOWN = "ANNOUNCED", "TBD", "PLACEHOLDER", "UNKNOWN"
PRE_NAMES = {"STATUS_SCHEDULED", "STATUS_PREGAME", "STATUS_TBD"}
NOT_PLAYED = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_FORFEIT"}
OBS_COLS = ["espn_game_id", "observed_at", "source", "start_utc", "date_et", "time_valid",
            "time_state", "state", "status_name", "short_detail", "home_espn", "away_espn",
            "neutral_site", "conference_game"]  # fmt: skip


def _ts(x: object) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def time_state(time_valid: object, start_utc: object, short_detail: object = None) -> str:
    if time_valid is True or (isinstance(time_valid, str) and time_valid.lower() == "true"):
        return ANNOUNCED
    if time_valid is False or (isinstance(time_valid, str) and time_valid.lower() == "false"):
        return TBD if "TBD" in str(short_detail or "") else PLACEHOLDER
    return UNKNOWN


def not_started(state: object, status_name: object) -> bool:
    """True only for positive evidence that the game has not begun (fail closed)."""
    return state == "pre" and str(status_name) in PRE_NAMES


def may_have_started(state: object, status_name: object) -> bool:
    return not not_started(state, status_name)


# ------------------------------------------------------------------------ sources
def parse_scoreboard(js: dict[str, Any], observed_at: str) -> list[dict[str, Any]]:
    out = []
    for ev in (js or {}).get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st = (comp.get("status") or ev.get("status") or {}).get("type") or {}
        teams = {c.get("homeAway"): c.get("id") for c in comp.get("competitors", [])}
        start = comp.get("date") or ev.get("date")
        tv = comp.get("timeValid", ev.get("timeValid"))
        out.append({
            "espn_game_id": int(ev["id"]), "observed_at": observed_at, "source": "espn_scoreboard",
            "start_utc": None if start is None else _ts(start).isoformat(),
            "date_et": None if start is None else _ts(start).tz_convert(ET).date().isoformat(),
            "time_valid": tv, "time_state": time_state(tv, start, st.get("shortDetail")),
            "state": st.get("state"), "status_name": st.get("name"),
            "short_detail": st.get("shortDetail"),
            "home_espn": None if teams.get("home") is None else int(teams["home"]),
            "away_espn": None if teams.get("away") is None else int(teams["away"]),
            "neutral_site": comp.get("neutralSite"),
            "conference_game": comp.get("conferenceCompetition"),
        })  # fmt: skip
    return out


def fetch_scoreboard(dates: list[str], stamp: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Live ESPN scoreboard for each ET date (YYYYMMDD), through the chokepoint
    (``espn_public``, 1 req/s). Returns (observations, failed dates). A failed date
    yields NO observation: callers treat its games as unprotected (fail closed)."""
    from cbb_edge.data.http import fetch

    obs, failed = [], []
    for d in dates:
        try:
            r = fetch("espn_public", f"{SITE}/scoreboard",
                      {"dates": d, "groups": "50", "limit": "500"},
                      dest=f"schedule_state/{stamp}/{d}.json", use_cache=False, timeout=30,
                      max_attempts=2)  # fmt: skip
            obs += parse_scoreboard(json.loads(r.path.read_text()), r.meta["retrieved_at"])
        except Exception:  # noqa: BLE001  any failure -> no evidence for that date
            failed.append(d)
    return obs, failed


def from_sdv(s: pd.DataFrame, observed_at: str) -> list[dict[str, Any]]:
    """Observations from an SDV schedule file (daily refresh: tip-time history only,
    never used as not-started evidence)."""
    out = []
    for r in s.itertuples(index=False):
        start = _ts(r.start_date)
        out.append({
            "espn_game_id": int(r.game_id), "observed_at": observed_at, "source": "sdv_schedule",
            "start_utc": start.isoformat(), "date_et": start.tz_convert(ET).date().isoformat(),
            "time_valid": None if pd.isna(r.time_valid) else bool(r.time_valid),
            "time_state": time_state(None if pd.isna(r.time_valid) else bool(r.time_valid),
                                     start, r.status_type_short_detail),
            "state": r.status_type_state, "status_name": r.status_type_name,
            "short_detail": r.status_type_short_detail,
            "home_espn": None if pd.isna(r.home_id) else int(r.home_id),
            "away_espn": None if pd.isna(r.away_id) else int(r.away_id),
        })  # fmt: skip
    return out


def window_dates(now: pd.Timestamp, hours_ahead: float, back_days: int = 1) -> list[str]:
    """ET dates from ``back_days`` before now through now + hours_ahead (YYYYMMDD)."""
    a = (_ts(now) - pd.Timedelta(days=back_days)).tz_convert(ET).date()
    b = (_ts(now) + pd.Timedelta(hours=hours_ahead)).tz_convert(ET).date()
    out, d = [], a
    while d <= b:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------------ archive
def write_obs(root: Path, obs: list[dict[str, Any]], stamp: str, source: str) -> Path | None:
    if not obs:
        return None
    p = Path(root) / "obs" / stamp[:4] / stamp[4:6] / stamp[6:8] / f"{stamp}_{source}.jsonl"
    if p.exists():
        raise FileExistsError(p)  # append-only
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(o, sort_keys=True, default=str) + "\n" for o in obs))
    return p


_KEY = ("start_utc", "time_valid", "time_state", "state", "status_name")


def _norm(v: object) -> str | None:
    return None if v is None or (isinstance(v, float) and v != v) else str(v)


def thin(obs: list[dict[str, Any]], prior: pd.DataFrame, now: pd.Timestamp) -> list[dict[str, Any]]:
    """What the hourly archive keeps of one run (bounded growth): every game's first
    observation and every change of (start, time state, game state); plus, unchanged,
    the scoreboard rows the gate needs as not-started evidence: games with no announced
    time, not finished, whose ET date has arrived (their 00:00 placeholder has passed)."""
    today = _ts(now).tz_convert(ET).date().isoformat()
    last: dict[tuple[int, str], tuple] = {}
    if prior is not None and len(prior):
        for r in prior.sort_values("observed_at").itertuples(index=False):
            last[(int(r.espn_game_id), r.source)] = tuple(_norm(getattr(r, k)) for k in _KEY)
    out = []
    for o in obs:
        k = (int(o["espn_game_id"]), o["source"])
        changed = last.get(k) != tuple(_norm(o.get(c)) for c in _KEY)
        evidence = (o["source"] == "espn_scoreboard" and o.get("time_state") != ANNOUNCED
                    and o.get("state") != "post" and (o.get("date_et") or "9") <= today)  # fmt: skip
        if changed or evidence:
            out.append(o)
    return out


def load_obs(*roots: Path | None) -> pd.DataFrame:
    rows = []
    for root in roots:
        if root is None or not Path(root).exists():
            continue
        for f in sorted(Path(root).rglob("*.jsonl")):
            if "obs" not in f.parts and "schedule_obs" not in f.parts:
                continue
            for line in f.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    d = pd.DataFrame(rows, columns=OBS_COLS)
    if len(d):
        d["observed_at"] = pd.to_datetime(d["observed_at"], utc=True)
        d["espn_game_id"] = d["espn_game_id"].astype(int)
        d = d.drop_duplicates(["espn_game_id", "observed_at", "source"]).sort_values(
            ["espn_game_id", "observed_at", "source"])  # fmt: skip
    return d


def history(obs: pd.DataFrame) -> pd.DataFrame:
    """Per game: first observation, time states seen, every (start, state) change with
    when it was observed, the final announced tip, and the not-started evidence."""
    rows = []
    if obs.empty:
        return pd.DataFrame()
    for gid, x in obs.groupby("espn_game_id"):
        x = x.sort_values("observed_at")
        changes, prev = [], None
        for r in x.itertuples(index=False):
            key = (r.start_utc, r.time_state, r.status_name)
            if key != prev:
                changes.append({"observed_at": r.observed_at.isoformat(), "source": r.source,
                                "start_utc": r.start_utc, "time_state": r.time_state,
                                "status": r.status_name})  # fmt: skip
                prev = key
        live = x[x["source"] == "espn_scoreboard"]
        pre = live[
            [not_started(s, n) for s, n in zip(live["state"], live["status_name"], strict=True)]
        ]
        started = live[[s in ("in", "post") and n not in NOT_PLAYED
                        for s, n in zip(live["state"], live["status_name"], strict=True)]]  # fmt: skip
        ann = x[x["time_state"] == ANNOUNCED]
        last = x.iloc[-1]
        rows.append({
            "espn_game_id": int(gid), "first_observed": x["observed_at"].min().isoformat(),
            "first_start_utc": x.iloc[0]["start_utc"], "first_time_state": x.iloc[0]["time_state"],
            "ever_tbd": bool(x["time_state"].isin([TBD, PLACEHOLDER, UNKNOWN]).any()),
            "latest_start_utc": last["start_utc"], "latest_time_state": last["time_state"],
            "latest_status": last["status_name"],
            "final_announced_tip": None if ann.empty else ann.iloc[-1]["start_utc"],
            "announced_first_seen": None if ann.empty else ann["observed_at"].min().isoformat(),
            "last_pre_observed": None if pre.empty else pre["observed_at"].max().isoformat(),
            "first_started_observed": None if started.empty else started["observed_at"].min().isoformat(),
            "n_observations": int(len(x)), "changes": changes,
        })  # fmt: skip
    return pd.DataFrame(rows)


# --------------------------------------------------------------- run decisions
def live_window(obs: list[dict[str, Any]], now: pd.Timestamp, horizon_h: float,
                listed: pd.DataFrame) -> dict[str, Any]:  # fmt: skip
    """From THIS run's live observations (fetched after ``now``):

    * ``exclude``  games the scoreboard shows started / postponed / cancelled / not
                   positively pre (never projected, whatever the listed tip);
    * ``extra``    games whose LISTED tip (``listed``: espn_game_id, tip) is <= now but
                   whose live state is positively "pre" and whose live time is not
                   announced, or is announced and still ahead, with the game's ET date
                   within the horizon (TBD protection);
    * ``unprotected`` listed-tip-passed games with no live observation at all (fetch
                   failed or not listed): NOT projected (fail closed), reported."""
    now = _ts(now)
    end_date = (now + pd.Timedelta(hours=horizon_h)).tz_convert(ET).date().isoformat()
    today = now.tz_convert(ET).date().isoformat()
    lv = {o["espn_game_id"]: o for o in obs}
    exclude, extra, unprotected = set(), set(), set()
    for gid, o in lv.items():
        if may_have_started(o["state"], o["status_name"]):
            exclude.add(gid)
    passed = listed[listed["tip"] <= now]
    for gid in passed["espn_game_id"].astype(int):
        o = lv.get(gid)
        if o is None:
            unprotected.add(gid)
            continue
        if gid in exclude or o["date_et"] is None or not (today <= o["date_et"] <= end_date):
            continue
        if o["time_state"] != ANNOUNCED or _ts(o["start_utc"]) > now:
            extra.add(gid)
    return {"extra": extra, "exclude": exclude, "unprotected": unprotected}


def _observe_sdv(archive: Path, season: int, stamp: str, prior: pd.DataFrame,
                 now: pd.Timestamp) -> tuple[int, int]:  # fmt: skip
    from cbb_edge.data.bronze import sportsdataverse as sdv

    p = sdv.download_live("schedules", season, stamp)
    if p is None:
        return 0, 0
    # fetched just now (the immutable live copy and its sidecar are recorded in the
    # bronze manifest); the canonical copy carries no sidecar
    so = from_sdv(pd.read_parquet(p), pd.Timestamp(datetime.now(UTC)).isoformat())
    so_kept = thin(so, prior, now)
    write_obs(archive, so_kept, stamp, "sdv_schedule")
    return len(so), len(so_kept)


def main() -> None:
    """``observe``: fetch the live scoreboard for the window and append the observations
    (and the SDV schedule's, if given) to the schedule archive."""
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["observe"])
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--hours", type=float, default=7 * 24)
    ap.add_argument("--back-days", type=int, default=1)
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--sdv", action="store_true", help="also archive the SDV schedule listing")
    ap.add_argument("--full-out", type=Path, default=None,
                    help="also write this run's complete observations (not archived)")  # fmt: skip
    a = ap.parse_args()
    now = pd.Timestamp(datetime.now(UTC))
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    prior = load_obs(a.archive)
    obs, failed = fetch_scoreboard(window_dates(now, a.hours, a.back_days), stamp)
    if a.full_out is not None and obs:
        f = a.full_out / "schedule_obs" / f"{stamp}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(o, sort_keys=True, default=str) + "\n" for o in obs))
    kept = thin(obs, prior, now)
    write_obs(a.archive, kept, stamp, "espn_scoreboard")
    n_sdv = n_sdv_kept = 0
    sdv_error = None
    if a.sdv:
        try:
            n_sdv, n_sdv_kept = _observe_sdv(a.archive, a.season, stamp, prior, now)
        except Exception as e:  # noqa: BLE001 -- the scoreboard observations above are still committed
            sdv_error = f"{type(e).__name__}: {e}"
    print(json.dumps({"stamp": stamp, "scoreboard_obs": len(obs), "scoreboard_archived": len(kept),
                      "failed_dates": failed, "sdv_obs": n_sdv,
                      "sdv_archived": n_sdv_kept, "sdv_error": sdv_error}))  # fmt: skip


if __name__ == "__main__":
    main()
