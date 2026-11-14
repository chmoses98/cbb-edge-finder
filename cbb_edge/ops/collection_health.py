"""Prospective collection coverage / freshness diagnostics (read-only, RESEARCH_ONLY).

Answers, from immutable archives and saved ``gh run list`` output only, whether missed or
delayed GitHub Actions runs LOST prospective evidence or only DELAYED it:

* ``scheduler``  per workflow: cron ticks expected in the window vs ``schedule`` runs GitHub
                 actually created, production runs by event / conclusion, the longest gap
                 between production runs, and runs stalled in a queued state (> 30 min);
* ``pregame``    per model version, games that tipped in the window: no pre-tip record at
                 all (LOST: never reconstructable), latest pre-tip record pushed at/after
                 tip (POISONED: the Wave 14-16 evaluators select the latest ``as_of < tip``
                 record and then exclude the game when that record's push time is not
                 before tip, even if an earlier record was safely frozen), push time not
                 provable, and the forecast lead time (tip - as_of) of the freshest safely
                 pushed record;
* ``finals``     games that tipped in the window: final observed or not, and hours from tip
                 to the final first reaching ``schedule-archive`` (DELAYED, not lost: an
                 ESPN final stays retrievable).

Nothing here writes to an archive or changes a record; a missing input makes its section
``UNKNOWN`` (never "OK").

    python -m cbb_edge.ops.collection_health --projections arch/projections-archive \
        --schedule-archive arch/schedule-archive --runs prospective-projections=pp.json \
        --runs kalshi-capture=kc.json --workflows .github/workflows --hours 72 --out health.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from cbb_edge.ops.dispatch_guard import STALE_QUEUED_MIN, parse_ts

REQUIRED_VERSIONS = ("pure-0.5.0", "pure-0.5.0+roster")
LOW_LEAD_H = 0.5
FINAL_OVERDUE_H = 6.0
ALERTS = {
    "PRETIP_RECORD_LOST": "CRITICAL",  # a required version has no pre-tip record for a tipped game
    "LATEST_PRETIP_PUSHED_AFTER_TIP": "CRITICAL",  # Waves 14-16 would exclude the game
    "PRETIP_PUSH_TIME_UNPROVABLE": "WARNING",
    "PRETIP_LEAD_LOW": "WARNING",  # freshest safe record < 30 min before tip (near miss)
    "FINAL_OVERDUE": "WARNING",  # tipped > 6 h ago, no archived final yet
    "RUN_STALLED_IN_QUEUE": "WARNING",  # production run queued > 30 min (e.g. 0-job orphan)
    "CRON_DELIVERY_LOW": "WARNING",  # < 50% of cron ticks produced a schedule run
}


# ------------------------------------------------------------------------- cron
def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return out


def cron_ticks(expr: str, start: datetime, end: datetime) -> list[datetime]:
    """UTC ticks of a 5-field cron expression in [start, end). Supports the forms this
    repository uses (lists, ranges, steps, ``*``). Day-of-month and day-of-week are ORed
    when both are restricted, as in standard cron."""
    mi, hr, dom, mon, dow = expr.split()
    m_s, h_s, mo_s = _field(mi, 0, 59), _field(hr, 0, 23), _field(mon, 1, 12)
    dom_any, dow_any = dom == "*", dow == "*"
    d_s, w_s = _field(dom, 1, 31), {x % 7 for x in _field(dow, 0, 7)}
    out = []
    t = start.replace(second=0, microsecond=0)
    if t < start:
        t += timedelta(minutes=1)
    while t < end:
        if t.minute in m_s and t.hour in h_s and t.month in mo_s:
            cw = (t.weekday() + 1) % 7  # cron: Sunday = 0
            day_ok = (
                True
                if dom_any and dow_any
                else (t.day in d_s)
                if dow_any
                else (cw in w_s)
                if dom_any
                else (t.day in d_s or cw in w_s)
            )
            if day_ok:
                out.append(t)
        t += timedelta(minutes=1)
    return out


def workflow_crons(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text())
    trig = doc.get(True, doc.get("on")) or {}
    return [c["cron"] for c in (trig.get("schedule") or []) if isinstance(c, dict)]


def scheduler(
    runs: list[dict[str, Any]],
    crons: list[str],
    start: datetime,
    end: datetime,
    *,
    stale_queued_min: float = STALE_QUEUED_MIN,
) -> dict[str, Any]:
    """Cron adherence and run-state summary for one workflow over [start, end)."""
    expected = sorted({t for c in crons for t in cron_ticks(c, start, end)})
    prod = [
        r
        for r in runs
        if r.get("event") != "pull_request"
        and (t := parse_ts(r.get("createdAt"))) is not None
        and start <= t < end
    ]
    sched = [r for r in prod if r.get("event") == "schedule"]
    created = sorted(t for r in prod if (t := parse_ts(r.get("createdAt"))) is not None)
    edges = [start, *created, end]
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(edges, edges[1:], strict=False)]
    stalled = [
        int(r.get("databaseId") or 0)
        for r in prod
        if r.get("status") in ("queued", "pending", "waiting", "requested")
        and (t := parse_ts(r.get("createdAt"))) is not None
        and end - t >= timedelta(minutes=stale_queued_min)
    ]
    return {
        "expected_cron_ticks": len(expected),
        "schedule_runs_created": len(sched),
        "cron_delivery_ratio": round(len(sched) / len(expected), 3) if expected else None,
        "production_runs": len(prod),
        "by_event_conclusion": dict(
            Counter(f"{r.get('event')}:{r.get('conclusion') or r.get('status')}" for r in prod)
        ),
        "max_gap_hours": round(max(gaps), 2) if gaps else None,
        "stalled_queued_runs": stalled,
    }


# --------------------------------------------------------------------- pregame
def pregame(
    records: list[dict[str, Any]],
    tips: dict[int, datetime],
    start: datetime,
    end: datetime,
    versions: tuple[str, ...] = REQUIRED_VERSIONS,
) -> dict[str, Any]:
    """``records``: {version, gid, as_of, pushed_at|None}; ``tips``: gid -> best-known tip.
    Only games that have at least one record of any version (the projected universe) and
    tipped in [start, end) are graded; missing schedule coverage is readiness.py's job."""
    by: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    universe = set()
    for r in records:
        by[(r["version"], r["gid"])].append(r)
        universe.add(r["gid"])
    games = sorted(g for g in universe if g in tips and start <= tips[g] < end)
    out: dict[str, Any] = {"games_tipped": len(games), "versions": {}}
    for v in versions:
        lost, poisoned, unprovable, leads = [], [], [], []
        for g in games:
            tip = tips[g]
            pre = [r for r in by.get((v, g), []) if r["as_of"] < tip]
            if not pre:
                lost.append(g)
                continue
            latest = max(pre, key=lambda r: r["as_of"])
            if latest["pushed_at"] is None:
                unprovable.append(g)
                continue
            if latest["pushed_at"] >= tip:
                poisoned.append(g)
                continue
            leads.append((g, (tip - latest["as_of"]).total_seconds() / 3600))
        hs = sorted(h for _, h in leads)

        def q(p: float, hs: list[float] = hs) -> float | None:
            return round(hs[int(p * (len(hs) - 1))], 2) if hs else None

        out["versions"][v] = {
            "ok": len(leads),
            "lost_no_pretip_record": lost,
            "latest_pretip_pushed_after_tip": poisoned,
            "push_time_unprovable": unprovable,
            "lead_hours": {"min": q(0), "p10": q(0.1), "p50": q(0.5), "max": q(1)},
            "low_lead_games": [g for g, h in leads if h < LOW_LEAD_H],
        }
    return out


# ---------------------------------------------------------------------- finals
def finals(
    obs: list[dict[str, Any]], start: datetime, end: datetime, now: datetime
) -> dict[str, Any]:
    """``obs``: {gid, start_utc, state, observed_at, pushed_at|None} scoreboard observations.
    A game's tip is its latest observed ``start_utc``; its final is archived at the earliest
    push (or, unknown push, observation) time of a ``post`` observation."""
    per: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for o in obs:
        per[o["gid"]].append(o)
    lat, overdue, tipped = [], [], 0
    for g, os_ in per.items():
        tip = max(os_, key=lambda o: o["observed_at"])["start_utc"]
        if not (start <= tip < end):
            continue
        tipped += 1
        posts = [o.get("pushed_at") or o["observed_at"] for o in os_ if o["state"] == "post"]
        if posts:
            lat.append((min(posts) - tip).total_seconds() / 3600)
        elif (now - tip).total_seconds() / 3600 > FINAL_OVERDUE_H:
            overdue.append(g)
    lat.sort()

    def q(p: float) -> float | None:
        return round(lat[int(p * (len(lat) - 1))], 2) if lat else None

    return {
        "games_tipped": tipped,
        "finals_archived": len(lat),
        "hours_tip_to_archived": {"p50": q(0.5), "p90": q(0.9), "max": q(1)},
        "final_overdue": sorted(overdue),
    }


# --------------------------------------------------------------------- loaders
def _added_at(root: Path) -> dict[str, datetime]:
    """path -> committer time of the commit that ADDED it (git checkout with history)."""
    p = subprocess.run(
        ["git", "-C", str(root), "log", "--format=C %cI", "--name-only", "--diff-filter=A"],
        capture_output=True,
        text=True,
        check=False,
    )
    out: dict[str, datetime] = {}
    cur = None
    for line in p.stdout.splitlines() if p.returncode == 0 else []:
        if line.startswith("C "):
            cur = parse_ts(line[2:])
        elif line and cur is not None:
            out[line] = cur  # log is newest first: the last write is the oldest (the add)
    return out


def load_records(root: Path) -> list[dict[str, Any]]:
    added = _added_at(root)
    out = []
    for f in root.glob("projections/**/G*/*.json"):
        try:
            r = json.loads(f.read_text())
            g = r["game"]
            out.append(
                {
                    "version": r["model"]["version"],
                    "gid": int(g["espn_game_id"]),
                    "as_of": parse_ts(r["prospective"]["as_of"]),
                    "listed_tip": parse_ts(g["start_time_utc"]),
                    "pushed_at": added.get(str(f.relative_to(root))),
                }
            )
        except (ValueError, KeyError, TypeError):
            continue
    return [r for r in out if r["as_of"] is not None]


def load_obs(root: Path) -> list[dict[str, Any]]:
    added = _added_at(root)
    out = []
    for f in root.glob("obs/**/*_espn_scoreboard.jsonl"):
        pushed = added.get(str(f.relative_to(root)))
        for line in f.read_text().splitlines():
            try:
                o = json.loads(line)
                out.append(
                    {
                        "gid": int(o["espn_game_id"]),
                        "start_utc": parse_ts(o["start_utc"]),
                        "state": o.get("state"),
                        "observed_at": parse_ts(o["observed_at"]),
                        "pushed_at": pushed,
                    }
                )
            except (ValueError, KeyError, TypeError):
                continue
    return [o for o in out if o["start_utc"] and o["observed_at"]]


def best_tips(records: list[dict[str, Any]], obs: list[dict[str, Any]]) -> dict[int, datetime]:
    tips: dict[int, datetime] = {}
    seen: dict[int, datetime] = {}
    for o in obs:  # latest observation wins
        if o["gid"] not in seen or o["observed_at"] > seen[o["gid"]]:
            seen[o["gid"]], tips[o["gid"]] = o["observed_at"], o["start_utc"]
    for r in records:  # no observation: the latest listed tip
        if r["gid"] not in seen and r["listed_tip"] is not None:
            tips[r["gid"]] = max(tips.get(r["gid"], r["listed_tip"]), r["listed_tip"])
    return tips


def alerts(report: dict[str, Any]) -> list[dict[str, Any]]:
    out = []

    def add(code: str, detail: Any) -> None:
        out.append({"code": code, "severity": ALERTS[code], "detail": detail})

    pg = report.get("pregame")
    if isinstance(pg, dict):
        for v, s in pg["versions"].items():
            if s["lost_no_pretip_record"]:
                add("PRETIP_RECORD_LOST", {"version": v, "games": s["lost_no_pretip_record"]})
            if s["latest_pretip_pushed_after_tip"]:
                add(
                    "LATEST_PRETIP_PUSHED_AFTER_TIP",
                    {"version": v, "games": s["latest_pretip_pushed_after_tip"]},
                )
            if s["push_time_unprovable"]:
                add(
                    "PRETIP_PUSH_TIME_UNPROVABLE",
                    {"version": v, "games": s["push_time_unprovable"]},
                )
            if s["low_lead_games"]:
                add("PRETIP_LEAD_LOW", {"version": v, "games": s["low_lead_games"]})
    fn = report.get("finals")
    if isinstance(fn, dict) and fn["final_overdue"]:
        add("FINAL_OVERDUE", fn["final_overdue"])
    for wf, s in (report.get("scheduler") or {}).items():
        if not isinstance(s, dict):
            continue
        if s["stalled_queued_runs"]:
            add("RUN_STALLED_IN_QUEUE", {"workflow": wf, "runs": s["stalled_queued_runs"]})
        if s["cron_delivery_ratio"] is not None and s["cron_delivery_ratio"] < 0.5:
            add("CRON_DELIVERY_LOW", {"workflow": wf, "ratio": s["cron_delivery_ratio"]})
    return out


def _runs_from(path: Path) -> list[dict[str, Any]] | None:
    """``gh run list --json`` output, or a raw REST ``{"workflow_runs": [...]}`` payload."""
    try:
        js = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if isinstance(js, dict) and "workflow_runs" in js:
        return [
            {
                "databaseId": r.get("id"),
                "event": r.get("event"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "createdAt": r.get("created_at"),
            }
            for r in js["workflow_runs"]
        ]
    return js if isinstance(js, list) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--projections", type=Path)
    ap.add_argument("--schedule-archive", type=Path)
    ap.add_argument("--runs", action="append", default=[], help="workflow-name=path (repeatable)")
    ap.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--now", default=None)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    now = parse_ts(a.now) if a.now else datetime.now(UTC)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp with a timezone")
    start = now - timedelta(hours=a.hours)
    report: dict[str, Any] = {"now": now.isoformat(), "window_start": start.isoformat()}
    recs = load_records(a.projections) if a.projections and a.projections.is_dir() else None
    obs = (
        load_obs(a.schedule_archive) if a.schedule_archive and a.schedule_archive.is_dir() else None
    )
    report["pregame"] = (
        pregame(recs, best_tips(recs, obs or []), start, now) if recs is not None else "UNKNOWN"
    )
    report["finals"] = finals(obs, start, now, now) if obs is not None else "UNKNOWN"
    sched: dict[str, Any] = {}
    for spec in a.runs:
        name, _, path = spec.partition("=")
        runs = _runs_from(Path(path))
        wf = a.workflows / f"{name}.yml"
        sched[name] = (
            scheduler(runs, workflow_crons(wf) if wf.exists() else [], start, now)
            if runs is not None
            else "UNKNOWN"
        )
    report["scheduler"] = sched
    report["alerts"] = alerts(report)
    text = json.dumps(report, indent=1, default=str)
    if a.out:
        a.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
