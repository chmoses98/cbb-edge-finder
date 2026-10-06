"""Schedule completeness (Wave 11): ESPN scoreboard rows as a FALLBACK for games the
SportsDataverse (SDV) schedule does not list yet.

Why. SDV's 2026-27 schedule lagged ESPN: on 2026-10-06, 249 of the 356 Nov 1-9 D-I vs
D-I games ESPN lists were absent from SDV (every one with an ESPN id above SDV's
maximum). The projection pipeline reads SDV only, so those games could never be
projected (research/reports/WAVE10.md §7).

What. SDV's schedule IS a flattening of the same ESPN scoreboard API (same game ids,
same fields), so a game SDV lacks can be written in SDV's own schema from ESPN's payload.

Policy (research/hypotheses/WAVE11.md, fixed before any 2026-27 game):

* **SDV first.** A game in SDV keeps its SDV row unchanged; ESPN never overwrites it.
  Material disagreements on shared games are reported (``diagnostics``), never applied.
* **ESPN only when absent.** An ESPN row is used only when its ``game_id`` is absent
  from SDV, every required field is present, and no SDV game (or other ESPN-only game)
  lists the same two teams on the same ET date under a different id (ambiguous
  reconciliation: fail closed, reported).
* **Provenance.** Every row carries ``schedule_source`` (``SDV`` / ``ESPN_FALLBACK``)
  and, for fallback rows, the ESPN ``observed_at`` it came from.
* **Prospective only.** Applies to seasons >= ``FIRST_FALLBACK_SEASON``; historical
  schedules are never touched.
* **Catch-up.** Once SDV lists a game, SDV's row wins on the next read; the game id is
  the same, so no new game exists and earlier records keep their own provenance.

ESPN rows are archived append-only on ``schedule-archive`` (``rows/...``), so every
fallback row a projection used can be reproduced from archived data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from cbb_edge.ops.schedule_state import ET

FIRST_FALLBACK_SEASON = 2027
SDV, ESPN_FALLBACK = "SDV", "ESPN_FALLBACK"
SOURCE = "espn_scoreboard"

# the SDV schedule columns read downstream (silver load_schedule, cadence.schedule_frame,
# score_proster.schedule), in SDV's own names and semantics
ROW_COLS = [
    "game_id", "season", "season_type", "date", "start_date", "time_valid", "neutral_site",
    "conference_competition", "tournament_id", "notes_headline", "venue_id",
    "venue_full_name", "venue_address_city", "venue_address_state", "home_id", "away_id",
    "home_location", "away_location", "home_conference_id", "away_conference_id",
    "home_score", "away_score", "status_period", "status_type_name", "status_type_state",
    "status_type_completed", "status_type_short_detail",
]  # fmt: skip
REQUIRED = ["game_id", "season", "season_type", "date", "start_date", "time_valid",
            "neutral_site", "conference_competition", "home_id", "away_id",
            "status_type_name", "status_type_completed"]  # fmt: skip
# fields whose disagreement on a shared game is operationally meaningful
MATERIAL = ["season", "season_type", "home_id", "away_id", "neutral_site",
            "conference_competition", "tournament_id", "status_type_name"]  # fmt: skip
PROV_COLS = ["schedule_source", "source_observed_at", "reconciled_fields", "reconciliation"]
# Wave 11 amendment: mutable schedule-only fields an SDV-native current-season row takes
# from ESPN's latest valid observation of the SAME game id (field-level reconciliation;
# every one validated identical in semantics on the 1,391 completed 2025-26 games).
# Groups move together: the two teams carry their names and conference ids; the tip
# carries its validity and status detail (the TBD state).
RECONCILE_GROUPS = {
    "teams": ["home_id", "away_id", "home_location", "away_location", "home_conference_id",
              "away_conference_id"],
    "tip": ["date", "start_date", "time_valid", "status_type_short_detail"],
    "neutral_site": ["neutral_site"],
    "conference_competition": ["conference_competition"],
    "tournament_id": ["tournament_id"],
    "season_type": ["season_type"],
    "notes": ["notes_headline"],
    "venue": ["venue_id", "venue_full_name", "venue_address_city", "venue_address_state"],
}  # fmt: skip
# never reconciled: identity (game_id, season) and game state / results (status, scores,
# period): an SDV game's state and settlement stay SDV's; the live game-state gate
# (Wave 10) reads ESPN state directly
NOT_RECONCILED = ["game_id", "season", "status_type_name", "status_type_state",
                  "status_type_completed", "home_score", "away_score", "status_period"]  # fmt: skip


# --------------------------------------------------------------------------- parse
def _f(x: Any) -> float | None:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def espn_rows(js: dict[str, Any], observed_at: str) -> list[dict[str, Any]]:
    """One SDV-schema row per scoreboard event (SDV flattens the same payload)."""
    out = []
    for ev in (js or {}).get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st = comp.get("status") or ev.get("status") or {}
        typ = st.get("type") or {}
        side = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        notes = comp.get("notes") or []
        season = ev.get("season") or {}

        def team(k: str, key: str, s: dict = side) -> Any:
            c = s.get(k) or {}
            return c.get("id") if key == "id" else (c.get("team") or {}).get(key)

        def score(k: str, s: dict = side) -> float | None:
            c = s.get(k) or {}
            v = c.get("score")
            return _f(v.get("value") if isinstance(v, dict) else v)

        row = {
            "game_id": int(ev["id"]),
            "season": season.get("year"),
            "season_type": season.get("type"),
            "date": ev.get("date"),
            "start_date": comp.get("startDate") or comp.get("date") or ev.get("date"),
            "time_valid": comp.get("timeValid", ev.get("timeValid")),
            "neutral_site": comp.get("neutralSite"),
            "conference_competition": comp.get("conferenceCompetition"),
            "tournament_id": _f(comp.get("tournamentId")),
            "notes_headline": (notes[0].get("headline") if notes else "") or "",
            "venue_id": _f(venue.get("id")),
            "venue_full_name": venue.get("fullName"),
            "venue_address_city": addr.get("city"),
            "venue_address_state": addr.get("state"),
            "home_id": None if team("home", "id") is None else int(team("home", "id")),
            "away_id": None if team("away", "id") is None else int(team("away", "id")),
            "home_location": team("home", "location"),
            "away_location": team("away", "location"),
            "home_conference_id": _f(team("home", "conferenceId")),
            "away_conference_id": _f(team("away", "conferenceId")),
            "home_score": score("home"),
            "away_score": score("away"),
            "status_period": _f(st.get("period")),
            "status_type_name": typ.get("name"),
            "status_type_state": typ.get("state"),
            "status_type_completed": typ.get("completed"),
            "status_type_short_detail": typ.get("shortDetail"),
            "observed_at": observed_at,
            "source": SOURCE,
        }
        out.append(row)
    return out


# ------------------------------------------------------------------------- archive
def _norm(v: Any) -> str | None:
    return None if v is None or (isinstance(v, float) and v != v) else str(v)


def thin_rows(rows: list[dict[str, Any]], prior: pd.DataFrame) -> list[dict[str, Any]]:
    """Keep a game's first row and every row that changes any schedule field."""
    last: dict[int, tuple] = {}
    if prior is not None and len(prior):
        for r in prior.sort_values("observed_at").to_dict("records"):
            last[int(r["game_id"])] = tuple(_norm(r.get(c)) for c in ROW_COLS)
    return [
        r for r in rows if last.get(int(r["game_id"])) != tuple(_norm(r.get(c)) for c in ROW_COLS)
    ]


def write_rows(root: Path, rows: list[dict[str, Any]], stamp: str) -> Path | None:
    if not rows:
        return None
    p = Path(root) / "rows" / stamp[:4] / stamp[4:6] / stamp[6:8] / f"{stamp}_espn_schedule.jsonl"
    if p.exists():
        raise FileExistsError(p)  # append-only
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows))
    return p


def load_rows(*roots: Path | None) -> pd.DataFrame:
    """Every archived ESPN schedule row (``rows/`` on schedule-archive, ``schedule_rows/``
    next to a projection run's records)."""
    recs = []
    for root in roots:
        if root is None or not Path(root).exists():
            continue
        for f in sorted(Path(root).rglob("*.jsonl")):
            if "rows" not in f.parts and "schedule_rows" not in f.parts:
                continue
            recs += [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    d = pd.DataFrame(recs, columns=[*ROW_COLS, "observed_at", "source"])
    if len(d):
        d["observed_at"] = pd.to_datetime(d["observed_at"], utc=True)
        d["game_id"] = d["game_id"].astype("int64")
        d = d.drop_duplicates(["game_id", "observed_at"]).sort_values(["game_id", "observed_at"])
    return d


def latest(rows: pd.DataFrame) -> pd.DataFrame:
    """The most recent ESPN row per game (the archive's current knowledge)."""
    if rows is None or not len(rows):
        return pd.DataFrame(columns=[*ROW_COLS, "observed_at", "source"])
    return rows.sort_values("observed_at").groupby("game_id").tail(1).reset_index(drop=True)


# ------------------------------------------------------------------------ complete
def _et_date(x: Any) -> str | None:
    try:
        return pd.Timestamp(x).tz_convert(ET).date().isoformat()
    except (TypeError, ValueError):
        return None


def _same(a: Any, b: Any, field: str) -> str:
    """equal / representation (same value, different encoding) / different."""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return "equal"
    if field in ("date", "start_date"):
        try:
            return "equal" if pd.Timestamp(a) == pd.Timestamp(b) else "different"
        except (TypeError, ValueError):
            return "different"
    fa, fb = _f(a), _f(b)
    if fa is not None and fb is not None and fa == fb:
        return "representation"
    if {str(a).lower(), str(b).lower()} <= {"true", "1", "1.0"} or {
        str(a).lower(), str(b).lower()} <= {"false", "0", "0.0"}:  # fmt: skip
        return "representation"
    if na in (None, "", "nan") and nb in (None, "", "nan"):
        return "representation"
    return "different"


def compare(sdv: pd.DataFrame, espn: pd.DataFrame) -> pd.DataFrame:
    """Per shared game and field: equal / representation / different (+ values)."""
    e = latest(espn).set_index("game_id")
    rows = []
    for r in sdv.to_dict("records"):
        g = int(r["game_id"])
        if g not in e.index:
            continue
        x = e.loc[g]
        for c in ROW_COLS[1:]:
            if c not in r:
                continue
            rows.append({"game_id": g, "field": c, "result": _same(r[c], x[c], c),
                         "sdv": _norm(r[c]), "espn": _norm(x[c]),
                         "material": c in MATERIAL})  # fmt: skip
    return pd.DataFrame(rows, columns=["game_id", "field", "result", "sdv", "espn", "material"])


def _valid_espn(x: dict[str, Any]) -> list[str]:
    """Why an ESPN row cannot be trusted as the current observation ([] = valid)."""
    miss = [
        c for c in REQUIRED if x.get(c) is None or (isinstance(x.get(c), float) and x[c] != x[c])
    ]
    if miss:
        return [f"missing:{','.join(miss)}"]
    if int(x["home_id"]) <= 0 or int(x["away_id"]) <= 0:
        return ["teams_not_determined"]
    return []


def reconcile(s: pd.DataFrame, shared: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Field-level reconciliation of SDV-native current-season rows against ESPN's latest
    valid observation of the same game id (``RECONCILE_GROUPS``). The game stays SDV-native
    (``schedule_source`` SDV); each corrected field is recorded with SDV's and ESPN's
    values and the ESPN observation time. An ESPN row that is not a valid current
    observation leaves the SDV row as is (``unresolved``, reported). A reconciled matchup
    that collides with another game's (same two teams, same ET date) is excluded: fail
    closed (``ambiguous``)."""
    s = s.copy()
    for c in ("reconciled_fields", "reconciliation"):
        s[c] = ""
    rep: dict[str, Any] = {"shared_games": int(shared["game_id"].nunique()) if len(shared) else 0,
                           "exact_match": 0, "reconciled_games": 0, "by_group": {},
                           "teams_kind": {"orientation_swap": 0, "different_teams": 0},
                           "unresolved": [], "ambiguous": []}  # fmt: skip
    if not len(shared):
        return s, rep
    e = shared.set_index("game_id")
    idx = {int(g): i for i, g in zip(s.index, s["game_id"], strict=True)}
    touched: list[int] = []
    for gid in sorted(set(e.index) & set(idx)):
        x = e.loc[gid].to_dict() | {"game_id": gid}
        i = idx[gid]
        diff = {}
        for grp, cols in RECONCILE_GROUPS.items():
            if any(_same(s.at[i, c], x.get(c), c) == "different" for c in cols if c in s.columns):
                diff[grp] = cols
        if not diff:
            rep["exact_match"] += 1
            continue
        bad = _valid_espn(x)
        if bad:
            rep["unresolved"].append({"game_id": gid, "reason": bad[0], "groups": sorted(diff)})
            continue
        audit = {}
        for grp, cols in diff.items():
            for c in cols:
                if c in s.columns and _same(s.at[i, c], x.get(c), c) == "different":
                    audit[c] = {"sdv": _norm(s.at[i, c]), "espn": _norm(x.get(c))}
            rep["by_group"][grp] = rep["by_group"].get(grp, 0) + 1
        if "teams" in diff:
            a = (_norm(s.at[i, "home_id"]), _norm(s.at[i, "away_id"]))
            b = (_norm(x["home_id"]), _norm(x["away_id"]))
            kind = ("team_metadata" if a == b  # same teams: conference id / name refreshed
                    else "orientation_swap" if a == b[::-1] else "different_teams")  # fmt: skip
            rep["teams_kind"][kind] = rep["teams_kind"].get(kind, 0) + 1
            audit["_teams"] = {
                "kind": kind,
                "sdv": f"{a[0]} vs {a[1]}",
                "espn": f"{b[0]} vs {b[1]}",
            }
        new = pd.DataFrame([{c: x.get(c) for g in diff.values() for c in g if c in s.columns}])
        new = _as_sdv_types(new, s)
        for c in new.columns:
            s.at[i, c] = new.at[0, c]
        s.at[i, "reconciled_fields"] = json.dumps(sorted(diff))
        s.at[i, "reconciliation"] = json.dumps(audit, sort_keys=True)
        s.at[i, "source_observed_at"] = pd.Timestamp(x["observed_at"]).isoformat()
        rep["reconciled_games"] += 1
        touched.append(gid)
    # fail closed: a reconciled matchup that collides with another game (either id kept
    # would duplicate the matchup)
    keys: dict[tuple, list[int]] = {}
    for r in s.to_dict("records"):
        if (
            pd.notna(r.get("home_id"))
            and pd.notna(r.get("away_id"))
            and min(int(r["home_id"]), int(r["away_id"])) > 0
        ):
            keys.setdefault((frozenset((int(r["home_id"]), int(r["away_id"]))), _et_date(r["date"])),
                            []).append(int(r["game_id"]))  # fmt: skip
    drop = set()
    for ids in keys.values():
        if len(ids) > 1:
            for g in ids:
                if g in touched:
                    drop.add(g)
                    rep["ambiguous"].append({"game_id": g, "collides_with": sorted(set(ids) - {g})})
    if drop:
        s = s[~s["game_id"].isin(drop)].reset_index(drop=True)
    return s, rep


def complete(
    sdv: pd.DataFrame, espn: pd.DataFrame, season: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """SDV rows unchanged (``schedule_source`` SDV) + ESPN rows for games SDV lacks
    (``ESPN_FALLBACK``), with a report of every exclusion and disagreement."""
    s = sdv.copy()
    s["schedule_source"], s["source_observed_at"] = SDV, None
    s["reconciled_fields"], s["reconciliation"] = "", ""
    rep: dict[str, Any] = {"season": season, "sdv_games": int(len(s)), "fallback_games": 0,
                           "excluded": [], "material_disagreements": [], "shared_games": 0}  # fmt: skip
    if season < FIRST_FALLBACK_SEASON or espn is None or not len(espn):
        return s, rep
    e = latest(espn)
    e = e[pd.to_numeric(e["season"], errors="coerce") == season]
    sdv_ids = set(s["game_id"].astype("int64"))
    shared = e[e["game_id"].isin(sdv_ids)]
    cmp = compare(s[s["game_id"].isin(set(shared["game_id"]))], shared)
    if len(cmp):
        bad = cmp[cmp["material"] & (cmp["result"] == "different")
                  & ~cmp["field"].isin(["home_id", "away_id"])]  # fmt: skip
        rep["material_disagreements"] = bad.to_dict("records")
        rep["shared_games"] = int(shared["game_id"].nunique())
    # team identity per shared game: same / orientation_swap / different_teams
    ei = shared.set_index("game_id")
    for r in s[s["game_id"].isin(set(ei.index))].to_dict("records"):
        x = ei.loc[int(r["game_id"])]
        a, b = (
            (_norm(r["home_id"]), _norm(r["away_id"])),
            (_norm(x["home_id"]), _norm(x["away_id"])),
        )
        if a == b or None in a or None in b:
            continue
        kind = "orientation_swap" if a == b[::-1] else "different_teams"
        rep["material_disagreements"].append(
            {"game_id": int(r["game_id"]), "field": "teams", "result": kind,
             "sdv": f"{a[0]} vs {a[1]}", "espn": f"{b[0]} vs {b[1]}", "material": True})  # fmt: skip
    s, rrep = reconcile(s, shared)
    rep["reconciliation"] = rrep
    # the pre-reconciliation disagreements stay in the audit, each marked with whether the
    # production row now carries ESPN's value
    unres = {u["game_id"] for u in rrep["unresolved"]}
    amb = {u["game_id"] for u in rrep["ambiguous"]}
    for d in rep["material_disagreements"]:
        g = int(d["game_id"])
        d["resolution"] = ("ambiguous_excluded" if g in amb else "unresolved_sdv_kept"
                           if g in unres else "reconciled_to_espn")  # fmt: skip
    cand = e[~e["game_id"].isin(sdv_ids)].copy()
    # same two teams on the same ET date under a different id (either orientation)
    key = lambda h, a, d: (frozenset((int(h), int(a))), d)  # noqa: E731
    sdv_keys = {}
    for r in s.to_dict("records"):
        if pd.notna(r.get("home_id")) and pd.notna(r.get("away_id")):
            sdv_keys[key(r["home_id"], r["away_id"], _et_date(r["date"]))] = int(r["game_id"])
    keep = []
    cand_keys: dict[tuple, list[int]] = {}
    for r in cand.to_dict("records"):
        if pd.notna(r.get("home_id")) and pd.notna(r.get("away_id")) and min(
                int(r["home_id"]), int(r["away_id"])) > 0:  # fmt: skip
            cand_keys.setdefault(key(r["home_id"], r["away_id"], _et_date(r["date"])), []).append(
                int(r["game_id"]))  # fmt: skip
    for r in cand.to_dict("records"):
        g = int(r["game_id"])
        miss = [
            c
            for c in REQUIRED
            if r.get(c) is None or (isinstance(r.get(c), float) and r[c] != r[c])
        ]
        if miss:
            rep["excluded"].append({"game_id": g, "reason": "missing_required_field",
                                    "fields": miss})  # fmt: skip
            continue
        if int(r["home_id"]) <= 0 or int(r["away_id"]) <= 0:
            # ESPN's bracket placeholder ("TBD" teams, ids -1 / -2): not a game yet
            rep["excluded"].append({"game_id": g, "reason": "teams_not_determined"})
            continue
        k = key(r["home_id"], r["away_id"], _et_date(r["date"]))
        if k in sdv_keys:
            rep["excluded"].append({"game_id": g, "reason": "ambiguous_reconciliation",
                                    "sdv_game_id": sdv_keys[k]})  # fmt: skip
            continue
        if len(cand_keys.get(k, [])) > 1:
            rep["excluded"].append({"game_id": g, "reason": "duplicate_scheduled_game",
                                    "espn_game_ids": sorted(cand_keys[k])})  # fmt: skip
            continue
        keep.append(r)
    fb = pd.DataFrame(keep, columns=[*ROW_COLS, "observed_at", "source"])
    if len(fb):
        fb["schedule_source"] = ESPN_FALLBACK
        fb["reconciled_fields"], fb["reconciliation"] = "", ""
        fb["source_observed_at"] = pd.to_datetime(fb["observed_at"], utc=True).map(
            lambda t: t.isoformat())  # fmt: skip
        fb = fb.drop(columns=["observed_at", "source"])
        fb = _as_sdv_types(fb, s)
        s = pd.concat([s, fb], ignore_index=True)
    rep["fallback_games"] = int(len(fb))
    return s, rep


def _as_sdv_types(fb: pd.DataFrame, s: pd.DataFrame) -> pd.DataFrame:
    """Cast fallback rows to the SDV file's dtypes (so downstream code sees one schema)."""
    for c in fb.columns:
        if c not in s.columns or c in PROV_COLS:
            continue
        dt = s[c].dtype
        try:
            if pd.api.types.is_bool_dtype(dt):
                fb[c] = fb[c].map(lambda v: bool(v) if v is not None and v == v else False)
            elif pd.api.types.is_integer_dtype(dt):
                fb[c] = pd.to_numeric(fb[c], errors="coerce").fillna(0).astype(dt)
            elif pd.api.types.is_float_dtype(dt):
                fb[c] = pd.to_numeric(fb[c], errors="coerce").astype(dt)
            else:
                fb[c] = fb[c].map(
                    lambda v: None if v is None or (isinstance(v, float) and v != v) else str(v)
                )
        except (TypeError, ValueError):
            pass
    return fb


# ------------------------------------------------------------------------ live use
def completion_path(season: int) -> Path:
    from cbb_edge.data.http import data_dir

    return (
        data_dir() / "bronze" / "schedule_completion" / f"mbb_schedule_completion_{season}.parquet"
    )


def completed_schedule(season: int, stamp: str, roots: list[Path | None] | None = None,
                       fresh: list[dict[str, Any]] | None = None,
                       sdv_frame: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:  # fmt: skip
    """SDV live schedule + ESPN fallback (archived rows under ``roots`` + this run's
    ``fresh`` rows). Writes the fallback rows to ``completion_path`` (read by the silver
    build) and the report next to it. Returns (SDV-schema frame, report)."""
    if sdv_frame is None:
        from cbb_edge.data.bronze import sportsdataverse as sdv

        p = sdv.download_live("schedules", season, stamp)
        sdv_frame = pd.read_parquet(p) if p is not None else pd.DataFrame(columns=ROW_COLS)
    rows = load_rows(*(roots or []))
    if fresh:
        f = pd.DataFrame(fresh, columns=[*ROW_COLS, "observed_at", "source"])
        f["observed_at"] = pd.to_datetime(f["observed_at"], utc=True)
        rows = pd.concat([rows, f], ignore_index=True) if len(rows) else f
    frame, rep = complete(sdv_frame, rows, season)
    out = completion_path(season)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)  # the whole completed season schedule (silver input)
    out.with_suffix(".report.json").write_text(json.dumps(rep, indent=1, default=str))
    return frame, rep


def completed_rows_for_silver(season: int) -> pd.DataFrame | None:
    """This run's completed current-season schedule (``completed_schedule``): SDV rows
    (field-reconciled) + ESPN-fallback rows, in SDV's schema. None for any historical
    season or when no prospective run wrote one."""
    if season < FIRST_FALLBACK_SEASON:
        return None
    p = completion_path(season)
    return pd.read_parquet(p) if p.exists() else None


def source_map(frame: pd.DataFrame) -> dict[int, dict[str, Any]]:
    """ESPN game id -> its schedule provenance: source, and for a fallback or reconciled
    game the ESPN observation time, the reconciled fields and the ESPN row used."""
    out: dict[int, dict[str, Any]] = {}
    for r in frame.to_dict("records"):
        g = int(r["game_id"])
        rec = json.loads(r["reconciled_fields"]) if r.get("reconciled_fields") else []
        src = r.get("schedule_source") or SDV
        d: dict[str, Any] = {"schedule_source": src, "source_observed_at": r.get("source_observed_at"),
                             "reconciled_fields": rec}  # fmt: skip
        if src == ESPN_FALLBACK or rec:
            row = {c: r.get(c) for c in ROW_COLS}
            row["observed_at"], row["source"] = r.get("source_observed_at"), SOURCE
            d["row"] = row
            if rec:
                d["reconciliation"] = json.loads(r["reconciliation"])
        out[g] = d
    return out


def canonical_universe(sdv: pd.DataFrame, espn: pd.DataFrame | None, season: int,
                       first_et: str, last_et: str, d1_team_ids: set[str]) -> pd.DataFrame:  # fmt: skip
    """THE known D-I vs D-I games of US Eastern dates ``first_et`` .. ``last_et``
    (inclusive), as of the given SDV snapshot and ESPN rows: every game id either source
    lists, with ESPN's latest valid observation for teams and tip (else SDV's). One row
    per game: game_id, home_id, away_id, start, date_et, in_sdv. Readiness and the dry run
    both count this universe (Wave 11 amendment)."""
    from cbb_edge.data.ids.teams import canonical_from_espn_in

    rows: dict[int, dict] = {}
    for r in sdv.to_dict("records"):
        rows[int(r["game_id"])] = {"home_id": r["home_id"], "away_id": r["away_id"],
                                   "start": r["start_date"], "in_sdv": True}  # fmt: skip
    if espn is not None and len(espn):
        e = latest(espn)
        e = e[pd.to_numeric(e["season"], errors="coerce") == season]
        for x in e.to_dict("records"):
            if _valid_espn(x):
                continue
            g = int(x["game_id"])
            rows[g] = {"home_id": x["home_id"], "away_id": x["away_id"], "start": x["start_date"],
                       "in_sdv": g in rows and rows[g]["in_sdv"]}  # fmt: skip
    d = pd.DataFrame([{"game_id": g, **v} for g, v in rows.items()])
    if not len(d):
        return pd.DataFrame(columns=["game_id", "home_id", "away_id", "start", "date_et", "in_sdv"])
    d["date_et"] = d["start"].map(_et_date)

    def tid(e: Any) -> str | None:
        return (
            None if e is None or e != e or int(e) <= 0 else canonical_from_espn_in(int(e), season)
        )

    d1 = d["home_id"].map(tid).isin(d1_team_ids) & d["away_id"].map(tid).isin(d1_team_ids)
    return (
        d[d1 & d["date_et"].between(first_et, last_et)]
        .sort_values("game_id")
        .reset_index(drop=True)
    )
