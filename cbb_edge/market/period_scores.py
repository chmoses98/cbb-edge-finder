"""Official per-period scores (1H / 2H / regulation / overtime) for completed D-I games.

Source: ESPN's free public site API (``espn_public``), through the cost-policy chokepoint.
Assumed JSON shape (scoreboard ``events[]`` or summary ``header.competitions[]``)::

    competition.status.type = {"name": "STATUS_FINAL", "completed": true, "state": "post"}
    competition.competitors[] = {"homeAway": "home"|"away", "id": "150", "team": {"id": "150"},
        "score": "78", "linescores": [{"value": 34.0, "displayValue": "34"}, ...]}

``linescores[0]`` / ``[1]`` are the regulation halves; ``[2:]`` are overtime periods.

Hard rules: a record is ``verified`` only if every consistency check passes. Failures are
FLAGGED, never repaired; halftime is never inferred from full-game results; games that are not
final yield no record. The archive is append-only (``periods/YYYY/MM/DD/<stamp>.jsonl``).

    python -m cbb_edge.market.period_scores --out DIR --date 20261103 [--date ...] | --days 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cbb_edge.data.http import fetch

SOURCE = "espn_public"
SCHEMA_VERSION = "period-scores-v1"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
SCOREBOARD_URL = f"{BASE}/scoreboard"
SUMMARY_URL = f"{BASE}/summary"
CONFLICT_FLAG = "superseded_by_conflict"


def _int(v: Any) -> int | None:
    """Exact non-negative integer from an ESPN numeric (``34``, ``34.0``, ``"34"``) else None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < 0 or f != int(f):
        return None
    return int(f)


def _linescores(comp: dict[str, Any]) -> list[int | None] | None:
    ls = comp.get("linescores")
    if not isinstance(ls, list) or not ls:
        return None
    out: list[int | None] = []
    for item in ls:
        v = item.get("value") if isinstance(item, dict) else item
        n = _int(v)
        if n is None and isinstance(item, dict):
            n = _int(item.get("displayValue"))
        out.append(n)
    return out


def check(rec: dict[str, Any]) -> list[str]:
    """Recompute every consistency flag from a record's raw numbers (empty list = verified)."""
    flags: list[str] = []
    if not rec.get("completed"):
        flags.append("not_final")
    h, a = rec.get("home_periods"), rec.get("away_periods")
    if not isinstance(h, list) or not isinstance(a, list) or not h or not a:
        return [*flags, "missing_linescores"]
    if len(h) != len(a):
        flags.append("period_count_mismatch")
    if len(h) < 2 or len(a) < 2:
        flags.append("fewer_than_two_periods")
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (*h, *a)):
        return [*flags, "non_integer_period_points"]
    if flags:
        return flags
    reg_h, reg_a = h[0] + h[1], a[0] + a[1]
    ot_h, ot_a = sum(h[2:]), sum(a[2:])
    if (rec.get("regulation_home"), rec.get("regulation_away")) != (reg_h, reg_a):
        flags.append("regulation_total_mismatch")
    if (rec.get("overtime_home"), rec.get("overtime_away")) != (ot_h, ot_a):
        flags.append("overtime_total_mismatch")
    fh, fa = rec.get("final_home"), rec.get("final_away")
    if not isinstance(fh, int) or not isinstance(fa, int):
        flags.append("missing_final_score")
    elif (fh, fa) != (reg_h + ot_h, reg_a + ot_a):
        flags.append("final_total_mismatch")
    elif fh == fa:
        flags.append("tied_final")
    if len(h) > 2 and reg_h != reg_a:
        flags.append("overtime_without_regulation_tie")
    if len(h) == 2 and reg_h == reg_a:
        flags.append("tied_regulation_without_overtime")
    return flags


def parse_competition(
    game_id: Any,
    comp: dict[str, Any],
    source_url: str,
    observed_at: datetime,
) -> dict[str, Any] | None:
    """Build a record from one ESPN competition; ``None`` if the game is not final/identifiable."""
    stype = (comp.get("status") or {}).get("type") or {}
    completed = bool(stype.get("completed")) and str(stype.get("name", "")).startswith(
        "STATUS_FINAL"
    )
    if not completed:
        return None
    gid = _int(game_id)
    sides = {c.get("homeAway"): c for c in comp.get("competitors") or [] if isinstance(c, dict)}
    home, away = sides.get("home"), sides.get("away")
    if gid is None or home is None or away is None:
        return None

    def tid(c: dict[str, Any]) -> str | None:
        v = (c.get("team") or {}).get("id", c.get("id"))
        return None if v is None else str(v)

    hl, al = _linescores(home), _linescores(away)
    rec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "espn_game_id": gid,
        "home_team_id": tid(home),
        "away_team_id": tid(away),
        "status": str(stype.get("name")),
        "completed": True,
        "home_periods": None,
        "away_periods": None,
        "first_half_home": None,
        "first_half_away": None,
        "regulation_home": None,
        "regulation_away": None,
        "overtime_home": None,
        "overtime_away": None,
        "overtime_periods": None,
        "final_home": _int(home.get("score")),
        "final_away": _int(away.get("score")),
        "source_url": source_url,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
    }
    flags: list[str] = []
    if hl is None or al is None:
        flags.append("missing_linescores")
    elif any(v is None for v in (*hl, *al)):
        flags.append("non_integer_period_points")
    else:
        h, a = [int(v) for v in hl if v is not None], [int(v) for v in al if v is not None]
        rec["home_periods"], rec["away_periods"] = h, a
        if len(h) >= 2 and len(a) >= 2:
            rec["first_half_home"], rec["first_half_away"] = h[0], a[0]
            rec["regulation_home"], rec["regulation_away"] = h[0] + h[1], a[0] + a[1]
            rec["overtime_home"], rec["overtime_away"] = sum(h[2:]), sum(a[2:])
            rec["overtime_periods"] = len(h) - 2
    flags += [f for f in check(rec) if f not in flags]
    rec["flags"] = flags
    rec["verified"] = not flags
    return rec


def parse_scoreboard(
    board: dict[str, Any], source_url: str, observed_at: datetime
) -> list[dict[str, Any]]:
    out = []
    for ev in board.get("events") or []:
        for comp in (ev.get("competitions") or [])[:1]:
            r = parse_competition(ev.get("id"), comp, source_url, observed_at)
            if r:
                out.append(r)
    return out


def parse_summary(
    summary: dict[str, Any], source_url: str, observed_at: datetime
) -> dict[str, Any] | None:
    header = summary.get("header") or {}
    comps = header.get("competitions") or []
    if not comps:
        return None
    gid = header.get("id") or comps[0].get("id")
    return parse_competition(gid, comps[0], source_url, observed_at)


def identity(rec: dict[str, Any]) -> str:
    """Hash of the observed facts (not of observation time / url) for idempotency."""
    keys = (
        "espn_game_id", "home_team_id", "away_team_id", "status", "home_periods",
        "away_periods", "final_home", "final_away", "verified", "flags",
    )  # fmt: skip
    core = {k: rec.get(k) for k in keys}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def _facts(rec: dict[str, Any]) -> tuple[Any, ...]:
    return (rec.get("home_periods"), rec.get("away_periods"), rec.get("final_home"),
            rec.get("final_away"))  # fmt: skip


def read_archive(out: Path) -> dict[int, list[dict[str, Any]]]:
    """All archived records by game id, oldest first (file order, then line order)."""
    res: dict[int, list[dict[str, Any]]] = {}
    for p in sorted((out / "periods").glob("**/*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                res.setdefault(int(r["espn_game_id"]), []).append(r)
    return res


def plan(rec: dict[str, Any], existing: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The record to append for ``rec`` given what is archived, or None to skip (identical)."""
    ident = identity(rec)
    if any(identity(e) == ident for e in existing):
        return None
    if rec["verified"]:
        prior = [e for e in existing if e.get("verified") and CONFLICT_FLAG not in e["flags"]]
        if prior and any(_facts(e) != _facts(rec) for e in prior):
            rec = {**rec, "flags": [*rec["flags"], CONFLICT_FLAG]}
    return rec


def append_records(out: Path, day: str, recs: list[dict[str, Any]], stamp: datetime) -> Path | None:
    """Write ``periods/YYYY/MM/DD/<stamp>.jsonl`` exclusively (never overwrites)."""
    if not recs:
        return None
    d = out / "periods" / day[:4] / day[4:6] / day[6:8]
    d.mkdir(parents=True, exist_ok=True)
    base = stamp.strftime("%Y%m%dT%H%M%SZ")
    n = 0
    while True:
        f = d / (f"{base}.jsonl" if n == 0 else f"{base}_{n}.jsonl")
        try:
            with f.open("x", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))
            return f
        except FileExistsError:
            n += 1


def _get(url: str, params: dict[str, str], tag: str) -> Any:
    res = fetch(
        SOURCE,
        url,
        params,
        use_cache=False,
        dest=Path("period_scores") / f"{tag}_{time.time_ns()}.json",
        schema_version="espn-scoreboard-v1",
        timeout=60,
    )
    return None if res is None else res.json()


def collect(out: Path, dates: list[str], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    archive = read_archive(out)
    summary: dict[str, Any] = {"observed_at": now.isoformat(), "dates": {}, "files": []}
    for d in dates:
        board = _get(SCOREBOARD_URL, {"dates": d, "groups": "50", "limit": "500"}, d)
        if board is None:
            summary["dates"][d] = {"error": "no_scoreboard"}
            continue
        recs = parse_scoreboard(board, f"{SCOREBOARD_URL}?dates={d}&groups=50&limit=500", now)
        # Final games whose scoreboard row lacks linescores: ask the summary endpoint, once.
        for i, r in enumerate(recs):
            if "missing_linescores" in r["flags"]:
                s_url = f"{SUMMARY_URL}?event={r['espn_game_id']}"
                sb = _get(SUMMARY_URL, {"event": str(r["espn_game_id"])}, f"summary_{d}")
                alt = parse_summary(sb, s_url, now) if sb else None
                if alt and alt["verified"]:
                    recs[i] = alt
        new = []
        for r in recs:
            p = plan(r, archive.get(r["espn_game_id"], []))
            if p is not None:
                new.append(p)
                archive.setdefault(r["espn_game_id"], []).append(p)
        f = append_records(out, d, new, now)
        if f:
            summary["files"].append(str(f))
        summary["dates"][d] = {
            "final_games": len(recs),
            "verified": sum(1 for r in recs if r["verified"]),
            "flagged": [{"id": r["espn_game_id"], "flags": r["flags"]} for r in recs if r["flags"]],
            "appended": len(new),
            "skipped_identical": len(recs) - len(new),
            "conflicts": sum(1 for r in new if CONFLICT_FLAG in r["flags"]),
        }
    return summary


def recent_dates(days: int, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    et = ZoneInfo("America/New_York")
    return [(now - timedelta(days=i)).astimezone(et).strftime("%Y%m%d") for i in range(days)][::-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--date", action="append", default=[], help="YYYYMMDD (repeatable)")
    ap.add_argument("--days", type=int, default=0, help="also collect the last N ET days")
    a = ap.parse_args()
    dates = sorted(set(a.date) | set(recent_dates(a.days) if a.days else []))
    if not dates:
        ap.error("give --date and/or --days")
    print(json.dumps(collect(a.out, dates), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
