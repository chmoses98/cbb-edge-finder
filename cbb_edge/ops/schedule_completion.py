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
PROV_COLS = ["schedule_source", "source_observed_at"]


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


def complete(
    sdv: pd.DataFrame, espn: pd.DataFrame, season: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """SDV rows unchanged (``schedule_source`` SDV) + ESPN rows for games SDV lacks
    (``ESPN_FALLBACK``), with a report of every exclusion and disagreement."""
    s = sdv.copy()
    s["schedule_source"], s["source_observed_at"] = SDV, None
    rep: dict[str, Any] = {"season": season, "sdv_games": int(len(s)), "fallback_games": 0,
                           "excluded": [], "material_disagreements": []}  # fmt: skip
    if season < FIRST_FALLBACK_SEASON or espn is None or not len(espn):
        return s, rep
    e = latest(espn)
    e = e[pd.to_numeric(e["season"], errors="coerce") == season]
    sdv_ids = set(s["game_id"].astype("int64"))
    shared = e[e["game_id"].isin(sdv_ids)]
    cmp = compare(s[s["game_id"].isin(set(shared["game_id"]))], shared)
    if len(cmp):
        bad = cmp[cmp["material"] & (cmp["result"] == "different")]
        rep["material_disagreements"] = bad.to_dict("records")
        rep["shared_games"] = int(shared["game_id"].nunique())
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
        if pd.notna(r.get("home_id")) and pd.notna(r.get("away_id")):
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
    fb = frame[frame["schedule_source"] == ESPN_FALLBACK]
    fb.to_parquet(out, index=False)
    out.with_suffix(".report.json").write_text(json.dumps(rep, indent=1, default=str))
    return frame, rep


def fallback_rows_for_silver(season: int) -> pd.DataFrame | None:
    """The fallback rows written by this run (``completed_schedule``), or None."""
    if season < FIRST_FALLBACK_SEASON:
        return None
    p = completion_path(season)
    return pd.read_parquet(p) if p.exists() else None


def source_map(frame: pd.DataFrame) -> dict[int, dict[str, Any]]:
    """ESPN game id -> its schedule source (and, for a fallback game, the ESPN row)."""
    out: dict[int, dict[str, Any]] = {}
    for r in frame.to_dict("records"):
        g = int(r["game_id"])
        if r.get("schedule_source") == ESPN_FALLBACK:
            row = {c: r.get(c) for c in ROW_COLS}
            row["observed_at"], row["source"] = r.get("source_observed_at"), SOURCE
            out[g] = {"schedule_source": ESPN_FALLBACK,
                      "source_observed_at": r.get("source_observed_at"), "row": row}  # fmt: skip
        else:
            out[g] = {"schedule_source": SDV, "source_observed_at": None}
    return out
