"""Prospective, append-only availability and roster capture (free ESPN public data).

``python -m cbb_edge.availability.capture games --out availability_out --state state.json``
    For every D-I game tipping within the next 30 hours whose minutes-to-tip falls in a
    checkpoint window (T-24h 20–28h, T-6h 4.5–7.5h, T-90m 60–120m, T-30m 20–50m,
    latest 0–20m) capture both teams' roster status / injuries, the game summary's
    injury section (if ESPN publishes one) and the league injury list. One JSONL row
    per (player, team, game, capture) with canonical status, P(plays), source,
    source-native text, confidence and whether the status changed since the player's
    previous capture (``state`` holds the last seen status per player; snapshots are
    never rewritten).

``python -m cbb_edge.availability.capture rosters --out roster_out --state state.json``
    Snapshot every current D-I roster. A team's snapshot is written when its roster
    content changed since the last capture (or with ``--full``: weekly full snapshot).
    Returning / transfer / new classification is derived downstream from the repo's
    own player history by ESPN athlete id (:func:`classify_roster`).

All requests go through the cost-policy chokepoint (``espn_public``, 1 req/s).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from cbb_edge.availability import espn
from cbb_edge.data.http import fetch

SOURCE = "espn_public"
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
SCHEMA = "availability-capture-v1"
ROSTER_SCHEMA = "roster-snapshot-v1"
# (name, lower minutes, upper minutes) before tip
WINDOWS = (
    ("T-24h", 20 * 60, 28 * 60),
    ("T-6h", 270, 450),
    ("T-90m", 60, 120),
    ("T-30m", 20, 50),
    ("latest", 0, 20),
)


def checkpoint(minutes_to_tip: float) -> str | None:
    for name, lo, hi in WINDOWS:
        if lo <= minutes_to_tip < hi:
            return name
    return None


def _get_json(url: str, params: dict[str, Any] | None, dest: str) -> dict[str, Any] | None:
    res = fetch(
        SOURCE,
        url,
        params,
        use_cache=False,
        timeout=45,
        not_found_ok=True,
        dest=dest,
        schema_version="espn-availability-v1",
    )
    return None if res is None else res.json()


def _games_in_window(now: datetime, hours_ahead: float) -> list[dict[str, Any]]:
    et = ZoneInfo("America/New_York")
    days = sorted(
        {
            (now + timedelta(hours=h)).astimezone(et).strftime("%Y%m%d")
            for h in (0, hours_ahead / 2, hours_ahead)
        }
    )
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for d in days:
        js = _get_json(
            f"{SITE}/scoreboard",
            {"dates": d, "groups": "50", "limit": "500"},
            f"availability/scoreboard/{now:%Y/%m/%d}/{d}_{time.time_ns()}.json",
        )
        for ev in (js or {}).get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if ((comp.get("status") or {}).get("type") or {}).get("state") != "pre":
                continue
            tip = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            mins = (tip - now).total_seconds() / 60
            cp = checkpoint(mins)
            if cp is None:
                continue
            if int(ev["id"]) in seen:
                continue
            seen.add(int(ev["id"]))
            teams = {c.get("homeAway"): c.get("id") for c in comp.get("competitors", [])}
            out.append(
                {
                    "game_id": int(ev["id"]),
                    "tip_utc": tip.isoformat(),
                    "minutes_to_tip": round(mins, 1),
                    "checkpoint": cp,
                    "home_espn_id": teams.get("home"),
                    "away_espn_id": teams.get("away"),
                }
            )
    return out


def _load_state(p: Path | None) -> dict[str, Any]:
    if p is None or not p.exists():
        return {"players": {}, "rosters": {}}
    return json.loads(p.read_text())


def capture_games(out: Path, state_path: Path | None, hours_ahead: float = 30.0) -> dict[str, Any]:
    now = datetime.now(UTC)
    state = _load_state(state_path)
    games = _games_in_window(now, hours_ahead)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    raw_dir = out / "raw" / now.strftime("%Y/%m/%d") / stamp
    rows: list[dict[str, Any]] = []
    league = _get_json(f"{SITE}/injuries", None, f"availability/injuries/{stamp}.json") or {}
    league_rows = espn.parse_injury_list(league, "espn_league_injuries")
    _write_raw(raw_dir / "league_injuries.json.gz", league)
    by_team_league: dict[int, list[dict[str, Any]]] = {}
    for r in league_rows:
        by_team_league.setdefault(r["espn_team_id"], []).append(r)
    rosters: dict[str, list[dict[str, Any]]] = {}
    for g in games:
        summ = (
            _get_json(
                f"{SITE}/summary",
                {"event": str(g["game_id"])},
                f"availability/summary/{stamp}_{g['game_id']}.json",
            )
            or {}
        )
        summ_inj = espn.parse_injury_list(summ, "espn_game_summary")
        if summ.get("injuries"):
            _write_raw(
                raw_dir / f"summary_injuries_{g['game_id']}.json.gz",
                {"injuries": summ.get("injuries")},
            )
        for side in ("home", "away"):
            tid = g[f"{side}_espn_id"]
            if tid is None:
                continue
            if tid not in rosters:
                js = (
                    _get_json(
                        f"{SITE}/teams/{tid}/roster",
                        None,
                        f"availability/roster/{stamp}_{tid}.json",
                    )
                    or {}
                )
                rosters[tid] = espn.parse_roster(js, int(tid))
            reported = {
                r["espn_athlete_id"]: r
                for r in summ_inj + by_team_league.get(int(tid), [])
                if r["espn_team_id"] == int(tid) and r["espn_athlete_id"]
            }
            for base in rosters[tid]:
                r = dict(base)
                rep = reported.pop(r["espn_athlete_id"], None)
                if rep is not None:  # an explicit injury listing beats roster status
                    r.update(
                        {
                            k: rep[k]
                            for k in (
                                "native_status",
                                "status",
                                "p_play",
                                "injury_comment",
                                "injury_date",
                            )
                        }
                    )
                    r["source"] = f"{r['source']}+{rep['source']}"
                    r["confidence"] = "reported"
                rows.append(_row(r, g, side, now))
            for rep in reported.values():  # listed but not on the roster payload
                rows.append(_row(dict(rep), g, side, now))
    for r in rows:
        key = f"{r['game_id']}|{r['espn_athlete_id']}"
        pkey = f"{r['espn_team_id']}|{r['espn_athlete_id']}"
        prev = state["players"].get(pkey)
        r["status_changed"] = prev is not None and prev != r["status"]
        r["first_capture_for_game"] = key not in state.setdefault("seen", {})
        state["seen"][key] = stamp
        state["players"][pkey] = r["status"]
    f = out / "captures" / now.strftime("%Y/%m/%d") / f"{stamp}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    if state_path is not None:
        _prune_seen(state, now)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
    return {
        "captured_at": now.isoformat(),
        "games": len(games),
        "rows": len(rows),
        "reported_rows": sum(r["confidence"] == "reported" for r in rows),
        "league_injury_rows": len(league_rows),
        "file": str(f),
    }


def _row(r: dict[str, Any], g: dict[str, Any], side: str, now: datetime) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "captured_at": now.isoformat(),
        "game_id": g["game_id"],
        "tip_utc": g["tip_utc"],
        "minutes_to_tip": g["minutes_to_tip"],
        "checkpoint": g["checkpoint"],
        "side": side,
        **r,
        "expected_minutes_adjustment": None,  # model-derived later (replacement model)
    }


def _prune_seen(state: dict[str, Any], now: datetime) -> None:
    cutoff = (now - timedelta(days=3)).strftime("%Y%m%dT%H%M%SZ")
    state["seen"] = {k: v for k, v in state.get("seen", {}).items() if v >= cutoff}


def _write_raw(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(obj, sort_keys=True).encode()))


def current_d1_teams() -> list[int]:
    """ESPN ids of the current D-I teams. Wave 9: the authoritative membership of the
    newest season (NCAA directory; Saint Francis (PA) out, West Florida in) when the
    membership table has one, else the registry's recent-season rule."""
    from cbb_edge.data.ids.teams import authoritative_members

    t = pd.read_csv(Path(__file__).resolve().parents[1] / "data" / "ids" / "teams.csv")
    m = authoritative_members(int(t["last_d1_season"].max()))
    if m is not None:
        return sorted(m)
    t = t[t["last_d1_season"] >= t["last_d1_season"].max() - 1]
    return sorted(int(x) for x in t["espn_team_id"].dropna())


def capture_rosters(
    out: Path, state_path: Path | None, full: bool = False, teams: list[int] | None = None
) -> dict[str, Any]:
    now = datetime.now(UTC)
    state = _load_state(state_path)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    written, changed, failed = 0, 0, 0
    rows_all: list[dict[str, Any]] = []
    for tid in teams or current_d1_teams():
        js = _get_json(f"{SITE}/teams/{tid}/roster", None, f"rosters/{stamp}_{tid}.json")
        if not js:
            failed += 1
            continue
        rows = espn.parse_roster(js, tid)
        content = sorted(
            json.dumps(
                {
                    k: r[k]
                    for k in (
                        "espn_athlete_id",
                        "name",
                        "position",
                        "class",
                        "jersey",
                        "height_in",
                        "roster_status",
                        "native_status",
                    )
                },
                sort_keys=True,
            )
            for r in rows
        )
        h = hashlib.sha256("\n".join(content).encode()).hexdigest()
        prev = state["rosters"].get(str(tid))
        is_change = prev is not None and prev != h
        changed += int(is_change)
        if full or prev != h:
            for r in rows:
                rows_all.append(
                    {
                        "schema": ROSTER_SCHEMA,
                        "captured_at": now.isoformat(),
                        "season_label": js.get("season", {}).get("displayName"),
                        "content_sha256": h,
                        "changed_since_last": is_change,
                        "full_snapshot": full,
                        **r,
                    }
                )
            written += 1
        state["rosters"][str(tid)] = h
    f = out / "snapshots" / now.strftime("%Y/%m/%d") / f"{stamp}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows_all))
    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
    return {
        "captured_at": now.isoformat(),
        "teams_written": written,
        "teams_changed": changed,
        "teams_failed": failed,
        "rows": len(rows_all),
        "file": str(f),
    }


def classify_roster(
    snap: pd.DataFrame, player_seasons: pd.DataFrame, season: int, team_espn_to_id: dict[int, str]
) -> pd.DataFrame:
    """returning / transfer / new for a roster snapshot of ``season`` using only player
    history from seasons < season (ESPN athlete id; no name matching)."""
    hist = player_seasons[player_seasons["season"] < season].sort_values("season")
    last = hist.drop_duplicates("player_id", keep="last").set_index("player_id")
    s = snap.copy()
    s["team_id"] = s["espn_team_id"].map(team_espn_to_id)
    prev_team = s["player_id"].map(last["team_id"])
    s["prev_team_id"] = prev_team
    s["prev_season"] = s["player_id"].map(last["season"])
    s["roster_class"] = "new"
    s.loc[prev_team.notna() & (prev_team == s["team_id"]), "roster_class"] = "returning"
    s.loc[prev_team.notna() & (prev_team != s["team_id"]), "roster_class"] = "transfer"
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["games", "rosters"])
    ap.add_argument("--out", default="availability_out")
    ap.add_argument("--state", default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--hours-ahead", type=float, default=30.0)
    ap.add_argument("--teams-limit", type=int, default=0, help="validation runs only")
    a = ap.parse_args()
    st = Path(a.state) if a.state else None
    if a.mode == "games":
        res = capture_games(Path(a.out), st, a.hours_ahead)
    else:
        teams = current_d1_teams()[: a.teams_limit] if a.teams_limit else None
        res = capture_rosters(Path(a.out), st, a.full, teams)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
