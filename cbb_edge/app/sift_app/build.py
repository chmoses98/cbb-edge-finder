"""Build the CBB ``edge_finder.app.v1`` publication (v1 files + the research explorer).

Pure translation of archived outputs into the generic contract. Every number shown comes
from an archived record or snapshot and keeps its provenance:

* schedule        the Wave 11 completed schedule (SDV first, ESPN fallback, field-reconciled)
* projections     archived ``sift-cbb-projection-1.x`` records chosen by ``selection.py``
* ratings         the opponent-adjusted ratings stored IN those records (never recomputed)
* roster          the archived roster-truth snapshot (confidence, rotation, continuity)
* research status the published prospective scoreboard (gate verdicts, preregistered summaries)
* markets         the read-only Kalshi capture, exact-key mapped to games, never joined to a model

Rankings and percentiles are the contract's arithmetic over those stored values.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from edge_finder_contract import board as B
from edge_finder_contract import build as C
from edge_finder_contract import health as H
from edge_finder_contract import ids
from edge_finder_contract import performance as P
from edge_finder_contract import research as R
from edge_finder_contract.freshness import Thresholds
from edge_finder_contract.validate import validate
from scipy.stats import norm

from cbb_edge.ops.schedule_state import ANNOUNCED, ET, time_state

from . import APP_BRANCH, REPO, SPORT
from . import selection as S
from .inputs import KalshiCapture, Scoreboard, Truth, stamp_iso

LEAGUE = "NCAA D-I"
SOURCE_GAME = "cbb_game_id"  # canonical "G" + ESPN event id
SOURCE_TEAM = "cbb_team_id"  # canonical T####
ROLE_ORDER = [S.INCUMBENT, S.SHADOW, S.ROSTER_OVERLAY]
AUTHORITY = {S.INCUMBENT: "RESEARCH_ONLY", S.SHADOW: "SHADOW", S.ROSTER_OVERLAY: "SHADOW"}
RESEARCH_BACK_DAYS = 21  # completed games keep their event research this long
BOARD_BACK_DAYS = 3
BOARD_AHEAD_DAYS = 7
MODEL_THRESHOLDS = Thresholds(14 * 3600, 30 * 3600)  # two scheduled runs a day + catch-up
TRUTH_THRESHOLDS = Thresholds(26 * 3600, 72 * 3600)
SCHEDULE_THRESHOLDS = Thresholds(26 * 3600, 72 * 3600)
SCORER_THRESHOLDS = Thresholds(26 * 3600, 72 * 3600)
TRUSTED = ("CONFIRMED", "LIKELY", "CONFLICTED")  # rosters/overlay.py: rotation may be used

CONFIDENCE_TEXT = {
    "CONFIRMED": "Official current roster available, or two independent current sources agree.",
    "LIKELY": "One current source lists the roster; not independently confirmed.",
    "CONFLICTED": "Current sources place at least one player on more than one team.",
    "STALE": "No current-season roster source; only older or copied listings.",
    "UNKNOWN": "The official roster could not be matched to player identities.",
}
REASON_TEXT = {
    "independent_fresh_groups": "two independent current sources agree",
    "official_fresh": "the school or NCAA current roster is available",
    "single_fresh_group": "a single current source lists the roster",
    "no_fresh_majority": "no current-season source lists this roster",
    "official_roster_unidentified": "the official listing could not be matched to player ids",
}
CLASS_TEXT = {"returning": "Returning", "returning_after_gap": "Returning (after a gap)",
              "transfer": "Transfer", "first_d1": "First D-I season", "unknown": "Unknown"}  # fmt: skip


def iso(x: Any) -> str | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return S.ts(x).strftime("%Y-%m-%dT%H:%M:%SZ")


def _s(x: Any) -> str | None:
    """A schedule string field; NaN / empty -> None."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s or None


def _f(x: Any, nd: int = 4) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


# ===================================================================== metric definitions
@dataclass(frozen=True)
class MetricDef:
    slug: str
    name: str
    short: str
    desc: str
    category: str
    unit: str | None
    stat_type: str
    higher: bool | None
    source: str  # "ratings" | "roster" | "projection"
    key: str  # field in the source block
    entity: str = "TEAM"
    adjusted: bool = True


def _ff(x: str, side: str, name: str, short: str, higher: bool | None, what: str) -> MetricDef:
    return MetricDef(
        f"adj_{x}_{side}", f"Adjusted {name} ({'offense' if side == 'off' else 'defense allowed'})",
        f"{short} {'O' if side == 'off' else 'D'}",
        f"{what} {'by the team' if side == 'off' else 'by opponents against the team'}, "
        "opponent-adjusted inside the model fit (vs an average D-I opponent).",
        "four_factors" if x in ("efg", "to", "orb", "ftr") else "shooting", "%", "PERCENT", higher,
        "ratings", f"{x}_{side}")  # fmt: skip


METRICS: list[MetricDef] = [
    MetricDef(
        "adj_off",
        "Adjusted offensive efficiency",
        "Adj O",
        "Points scored per 100 possessions against an average D-I defense, opponent-adjusted "
        "inside the model fit.",
        "efficiency",
        "pts/100",
        "RATING",
        True,
        "ratings",
        "adj_off",
    ),
    MetricDef(
        "adj_def",
        "Adjusted defensive efficiency",
        "Adj D",
        "Points allowed per 100 possessions against an average D-I offense, opponent-adjusted "
        "inside the model fit. Lower is better.",
        "efficiency",
        "pts/100",
        "RATING",
        False,
        "ratings",
        "adj_def",
    ),
    MetricDef(
        "adj_tempo",
        "Adjusted tempo",
        "Tempo",
        "Possessions per 40 minutes against an average-tempo opponent. A style measure, not "
        "good or bad.",
        "tempo",
        "poss/40",
        "RATING",
        None,
        "ratings",
        "adj_tempo",
    ),
    _ff("efg", "off", "effective FG%", "eFG%", True, "Effective field-goal percentage"),
    _ff("efg", "def", "effective FG%", "eFG%", False, "Effective field-goal percentage"),
    _ff("to", "off", "turnover rate", "TO%", False, "Turnovers per 100 possessions"),
    _ff("to", "def", "turnover rate", "TO%", True, "Turnovers per 100 possessions"),
    _ff("orb", "off", "offensive rebound rate", "OR%", True, "Share of own missed shots rebounded"),
    _ff(
        "orb",
        "def",
        "offensive rebound rate",
        "OR%",
        False,
        "Share of missed shots rebounded by the offense",
    ),
    _ff("ftr", "off", "free-throw rate", "FTR", True, "Free-throw attempts per field-goal attempt"),
    _ff(
        "ftr", "def", "free-throw rate", "FTR", False, "Free-throw attempts per field-goal attempt"
    ),
    _ff("fg2", "off", "2-point FG%", "2P%", True, "Two-point field-goal percentage"),
    _ff("fg2", "def", "2-point FG%", "2P%", False, "Two-point field-goal percentage"),
    _ff("fg3", "off", "3-point FG%", "3P%", True, "Three-point field-goal percentage"),
    _ff("fg3", "def", "3-point FG%", "3P%", False, "Three-point field-goal percentage"),
    _ff(
        "fg3a_rate",
        "off",
        "3-point attempt rate",
        "3PA rate",
        None,
        "Three-point attempts per field-goal attempt (shot profile)",
    ),
    _ff(
        "fg3a_rate",
        "def",
        "3-point attempt rate",
        "3PA rate",
        None,
        "Three-point attempts per field-goal attempt (shot profile)",
    ),
    MetricDef(
        "returning_minutes_share",
        "Returning minutes share",
        "Ret. min",
        "Share of last season's minutes played by players on this season's roster (roster "
        "truth). Not a rating and not opponent-adjusted.",
        "roster",
        "share",
        "PERCENT",
        None,
        "roster",
        "truth_cont",
        adjusted=False,
    ),
    MetricDef(
        "expected_returning_minutes",
        "Expected minutes to returning players",
        "Ret. exp",
        "Of 200 team minutes, the expected pregame share for players returning to this team "
        "(expected rotation from roster and prior participation evidence).",
        "roster",
        "min/200",
        "COUNT",
        None,
        "roster",
        "proj_min_returning",
        adjusted=False,
    ),
    MetricDef(
        "expected_transfer_minutes",
        "Expected minutes to incoming transfers",
        "Transfer",
        "Of 200 team minutes, the expected pregame share for D-I transfers.",
        "roster",
        "min/200",
        "COUNT",
        None,
        "roster",
        "proj_min_transfer",
        adjusted=False,
    ),
    MetricDef(
        "expected_first_d1_minutes",
        "Expected minutes to first-D-I players",
        "First D-I",
        "Of 200 team minutes, the expected pregame share for players with no prior D-I "
        "participation (freshmen and newcomers from outside D-I).",
        "roster",
        "min/200",
        "COUNT",
        None,
        "roster",
        "proj_min_unseen",
        adjusted=False,
    ),
]
PROJ_METRICS = [
    MetricDef(
        "proj_margin",
        "Projected margin (home − away)",
        "Margin",
        "Archived pre-tip projected home margin.",
        "projection",
        "pts",
        "SCORE",
        None,
        "projection",
        "margin",
        entity="EVENT",
        adjusted=False,
    ),
    MetricDef(
        "proj_total",
        "Projected total",
        "Total",
        "Archived pre-tip projected total points.",
        "projection",
        "pts",
        "SCORE",
        None,
        "projection",
        "total",
        entity="EVENT",
        adjusted=False,
    ),
    MetricDef(
        "proj_home_win_prob",
        "Projected home win probability",
        "Home win",
        "Archived pre-tip home win probability (model logistic on the projected margin).",
        "projection",
        None,
        "PROBABILITY",
        None,
        "projection",
        "home_win_prob",
        entity="EVENT",
        adjusted=False,
    ),
    MetricDef(
        "proj_possessions",
        "Projected possessions",
        "Poss",
        "Archived pre-tip projected possessions.",
        "projection",
        "poss",
        "COUNT",
        None,
        "projection",
        "possessions",
        entity="EVENT",
        adjusted=False,
    ),
]
RATING_METRICS = [m for m in METRICS if m.source == "ratings"]
ROSTER_METRICS = [m for m in METRICS if m.source == "roster"]
MATCHUP_PAIRS = [  # (offense metric, defense metric it faces, plain label)
    ("adj_off", "adj_def", "Efficiency"),
    ("adj_efg_off", "adj_efg_def", "Shooting (eFG%)"),
    ("adj_to_off", "adj_to_def", "Turnovers"),
    ("adj_orb_off", "adj_orb_def", "Offensive rebounding"),
    ("adj_ftr_off", "adj_ftr_def", "Free throws"),
    ("adj_fg2_off", "adj_fg2_def", "2-point shooting"),
    ("adj_fg3_off", "adj_fg3_def", "3-point shooting"),
    ("adj_fg3a_rate_off", "adj_fg3a_rate_def", "3-point attempt rate"),
]


def mid(slug: str) -> str:
    return ids.metric_id(SPORT, slug)


# ===================================================================== inputs bundle
@dataclass
class World:
    now: pd.Timestamp
    season: int
    schedule: pd.DataFrame  # completed schedule (SDV schema + provenance)
    schedule_report: dict[str, Any]
    members: pd.DataFrame  # D-I members of the season (team_id, espn_team_id, conference, school)
    team_names: pd.DataFrame  # teams.csv
    records: list[dict[str, Any]]
    manifests: list[dict[str, Any]]
    active: dict[str, Any]
    truth: Truth | None
    scoreboard: Scoreboard | None
    kalshi: KalshiCapture | None
    code_sha: str | None = None
    commits: dict[str, str | None] = field(default_factory=dict)
    schedule_observed_at: str | None = None
    kalshi_games: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # gid -> raw


# ===================================================================== schedule -> games
STATUS_MAP = {"pre": "SCHEDULED", "in": "LIVE", "post": "FINAL"}


def _event_status(state: Any, name: Any, completed: Any) -> str:
    n = str(name or "")
    if "POSTPONED" in n:
        return "POSTPONED"
    if "CANCEL" in n:
        return "CANCELLED"
    if bool(completed):
        return "FINAL"
    return STATUS_MAP.get(str(state or ""), "UNKNOWN")


def games_frame(w: World) -> tuple[pd.DataFrame, dict[str, int]]:
    """D-I vs D-I games of the season (the experiment's universe), one row per game."""
    e2t = {int(e): t for e, t in zip(w.members["espn_team_id"], w.members["team_id"], strict=True)}
    s = w.schedule
    rows, dropped = [], {"non_d1_opponent": 0}
    for r in s.to_dict("records"):
        h, a = e2t.get(int(r["home_id"])), e2t.get(int(r["away_id"]))
        if h is None or a is None:
            dropped["non_d1_opponent"] += 1
            continue
        start = S.ts(r["start_date"])
        tstate = time_state(r.get("time_valid"), start, r.get("status_type_short_detail"))
        rec = _s(r.get("reconciled_fields")) or ""
        rows.append({
            "espn_game_id": int(r["game_id"]), "gid": f"G{int(r['game_id'])}",
            "home": h, "away": a, "home_espn": int(r["home_id"]), "away_espn": int(r["away_id"]),
            "start": start, "time_state": tstate,
            "date_et": start.tz_convert(ET).date().isoformat(),
            "state": _s(r.get("status_type_state")), "status_name": _s(r.get("status_type_name")),
            "completed": bool(r.get("status_type_completed")),
            "home_score": _f(r.get("home_score"), 0), "away_score": _f(r.get("away_score"), 0),
            "neutral": bool(r.get("neutral_site")),
            "conference_game": bool(r.get("conference_competition")),
            "notes": _s(r.get("notes_headline")),
            "venue": _s(r.get("venue_full_name")), "city": _s(r.get("venue_address_city")),
            "region": _s(r.get("venue_address_state")),
            "schedule_source": _s(r.get("schedule_source")) or "SDV",
            "source_observed_at": _s(r.get("source_observed_at")),
            "reconciled_fields": json.loads(rec) if rec else [],
            "home_logo": _s(r.get("home_logo")), "away_logo": _s(r.get("away_logo")),
        })  # fmt: skip
    g = pd.DataFrame(rows)
    for c in g.columns:  # pandas string columns hold NaN for missing: keep None in records
        if g[c].dtype == object or pd.api.types.is_string_dtype(g[c]):
            g[c] = g[c].astype(object).where(g[c].notna(), None)
    if len(g):
        g = g.sort_values(["start", "espn_game_id"]).reset_index(drop=True)
        for c in ("home_score", "away_score"):
            g.loc[~g["completed"], c] = None
    return g, dropped


def windows(g: pd.DataFrame, now: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """(research_from, board_from, board_to). Preseason the board shows the opening week
    (the first seven days from the first scheduled game) so the slate is never empty."""
    lo = now - pd.Timedelta(days=BOARD_BACK_DAYS)
    hi = now + pd.Timedelta(days=BOARD_AHEAD_DAYS)
    up = g[(g["start"] >= now - pd.Timedelta(hours=6)) & ~g["completed"]] if len(g) else g
    if len(up):
        first = pd.Timestamp(up["date_et"].min()).tz_localize(ET).tz_convert("UTC")
        hi = max(hi, first + pd.Timedelta(days=BOARD_AHEAD_DAYS))
    return now - pd.Timedelta(days=RESEARCH_BACK_DAYS), lo, hi


# ===================================================================== identities
def team_pid(tid: str) -> str:
    return ids.participant_id(SPORT, "TEAM", SOURCE_TEAM, tid)


def event_eid(gid: str) -> str:
    return ids.event_id(SPORT, SOURCE_GAME, gid)


def team_directory(w: World, g: pd.DataFrame) -> dict[str, dict[str, Any]]:
    reg = w.team_names.set_index("team_id")
    logos: dict[str, str] = {}
    for side in ("home", "away"):
        for t, lg in zip(g[side], g[f"{side}_logo"], strict=True) if len(g) else []:
            if lg and t not in logos:
                logos[t] = lg
    out = {}
    for m in w.members.to_dict("records"):
        t = m["team_id"]
        row = reg.loc[t] if t in reg.index else None
        name = str(row["espn_display_name"]) if row is not None else str(m["school"])
        short = str(row["espn_abbreviation"]) if row is not None and isinstance(
            row["espn_abbreviation"], str) else None  # fmt: skip
        loc = str(row["espn_location"]) if row is not None and isinstance(
            row["espn_location"], str) else name  # fmt: skip
        out[t] = {
            "team_id": t, "pid": team_pid(t), "name": name, "short": short, "location": loc,
            "espn": int(m["espn_team_id"]), "conference": m.get("conference") or None,
            "school": m.get("school"), "logo": logos.get(t),
        }  # fmt: skip
    return out


def participant(team: dict[str, Any]) -> dict[str, Any]:
    return C.participant(
        sport=SPORT, participant_type="TEAM", source=SOURCE_TEAM, source_id=team["team_id"],
        display_name=team["name"], short_name=team["short"],
        source_ids={"espn_team_id": team["espn"]},
        metadata={"conference": team["conference"], "school": team["school"],
                  "location": team["location"], "logo_url": team["logo"]},
    )  # fmt: skip


# ===================================================================== projections
def clock_of(row: dict[str, Any]) -> S.GameClock:
    return S.GameClock(int(row["espn_game_id"]), row["start"], row["time_state"], row["state"],
                       row["status_name"], bool(row["completed"]), row["home"], row["away"])  # fmt: skip


def model_row(c: S.Choice) -> dict[str, Any]:
    r = c.record
    p, pr, f = r["projection"], r.get("prospective") or {}, r.get("freshness") or {}
    sch = r.get("schedule") or {}
    ro = r.get("roster") or {}
    md, sd = p.get("margin"), p.get("margin_sd")
    td, tsd = p.get("total"), p.get("total_sd")

    def rng(mu: Any, s: Any, q: float) -> list[float] | None:
        if mu is None or not s:
            return None
        z = float(norm.ppf(0.5 + q / 2))
        return [round(float(mu) - z * float(s), 1), round(float(mu) + z * float(s), 1)]

    return {
        "version": c.version, "role": c.role, "role_label": S.ROLE_LABEL[c.role],
        "model_name": (r.get("model") or {}).get("name"), "arm": (r.get("model") or {}).get("arm"),
        "as_of": iso(pr.get("as_of")), "info_cutoff": iso(f.get("info_cutoff_utc")),
        "pretip_basis": c.basis,
        "home_team_id": r["home"]["team_id"], "away_team_id": r["away"]["team_id"],
        "home_score": _f(p.get("home_score"), 2), "away_score": _f(p.get("away_score"), 2),
        "margin": _f(md, 2), "total": _f(td, 2), "possessions": _f(p.get("possessions"), 2),
        "home_ppp": _f(p.get("home_ppp")), "away_ppp": _f(p.get("away_ppp")),
        "home_win_prob": _f(p.get("home_win_prob")), "margin_sd": _f(sd, 2), "total_sd": _f(tsd, 2),
        # deterministic ranges of the frozen normal margin / total distribution
        "margin_range_50": rng(md, sd, 0.5), "margin_range_80": rng(md, sd, 0.8),
        "total_range_50": rng(td, tsd, 0.5), "total_range_80": rng(td, tsd, 0.8),
        "games_seen": {"home": f.get("home_games_seen"), "away": f.get("away_games_seen")},
        "info_games": f.get("info_games"),
        "provenance": {
            "archive_path": r.get("_path"), "record_sha256": r.get("_sha256"),
            "code_sha": pr.get("code_sha"), "code_version": pr.get("code_version"),
            "model_sha256": pr.get("model_sha256"), "role_at_capture": pr.get("role"),
            "reconstruction": pr.get("reconstruction"), "schema_version": r.get("schema_version"),
            "roster_archive_commit": ro.get("truth_archive_commit"),
            "truth_snapshot": ro.get("truth_snapshot"),
            "schedule_source": sch.get("source"), "schedule_window": sch.get("window"),
            "schedule_listed_start": iso(sch.get("listed_start")),
            "schedule_reconciled_fields": sch.get("reconciled_fields") or [],
            "live_observation": sch.get("live"),
        },
    }  # fmt: skip


def proster_block(c: S.Choice, w: World, teams: dict[str, dict]) -> dict[str, Any] | None:
    ro = c.record.get("roster")
    if not ro:
        return None
    names = w.truth.names if w.truth else {}
    sides = {}
    for side in ("home", "away"):
        si = (ro.get("sides") or {}).get(side) or {}
        sides[side] = {
            "team_id": si.get("team_id"), "roster_confidence": si.get("roster_confidence"),
            "games_seen": si.get("games_seen"),
            "input_substitution_active": bool(si.get("overlay_applied")),
            "continuity_correction_active": bool(si.get("continuity_correction_applied")),
            "returning_minutes_share": _f(si.get("truth_cont")),
            "expected_returning_share": _f(si.get("expected_returning_share")),
            "first_d1_expected_to_play": _f(si.get("first_d1"), 1),
            "incoming_transfer_prev_share": _f(si.get("tr_prev")),
            "minutes": {k: _f(si.get(f"proj_min_{k}"), 1) for k in ("returning", "transfer", "unseen")},
            "expected_rotation": [rotation_player(p, names, teams) for p in si.get("expected_rotation") or []],
        }  # fmt: skip
    return {
        "component": ro.get("component"), "truth_snapshot": ro.get("truth_snapshot"),
        "truth_snapshot_at": stamp_iso(ro.get("truth_snapshot")),
        "truth_archive_commit": ro.get("truth_archive_commit"), "spec_sha256": ro.get("spec_sha256"),
        "margin_base": _f(ro.get("margin_base"), 2), "total_base": _f(ro.get("total_base"), 2),
        "adjustment_input_substitution": _f(ro.get("adjustment_a_input_substitution"), 2),
        "adjustment_continuity": _f(ro.get("adjustment_b_continuity"), 2),
        "adjustment_total": _f(ro.get("adjustment_total"), 2), "sides": sides,
    }  # fmt: skip


def rotation_player(
    p: dict[str, Any], names: dict[str, dict], teams: dict[str, dict]
) -> dict[str, Any]:
    n = names.get(p["player_id"]) or {}
    cls = p.get("class") or n.get("classification") or "unknown"
    last = n.get("last_team")
    prior = teams.get(last, {}).get("name") if last and cls == "transfer" else None
    return {
        "player_id": p["player_id"], "name": n.get("name"), "position": n.get("position"),
        "minutes": _f(p.get("minutes"), 1) if p.get("minutes") is not None else _f(40 * float(p.get("share", 0)), 1),
        "class": cls, "class_label": CLASS_TEXT.get(cls, cls),
        "prior_team": prior,
        "expected_starter": p.get("expected_starter"),
    }  # fmt: skip


# ===================================================================== roster (truth)
def team_roster(t: str, w: World, teams: dict[str, dict]) -> dict[str, Any]:
    tr = w.truth
    if tr is None:
        return {
            "available": False,
            "confidence": "UNKNOWN",
            "explanation": "No roster-truth snapshot.",
        }
    row = tr.teams[tr.teams["team_id"] == t]
    if row.empty:
        return {"available": False, "confidence": "UNKNOWN",
                "explanation": "This team is in no roster-truth snapshot yet.",
                "snapshot": tr.stamp, "snapshot_at": stamp_iso(tr.stamp)}  # fmt: skip
    x = row.iloc[0].to_dict()
    conf = str(x["roster_confidence"])
    ps = tr.proster.get(t) or {}
    sane = tr.sanity.get(t) or {}
    valid = conf in TRUSTED and bool(sane.get("ok"))
    why_not = None
    if not valid:
        why_not = ("rotation failed its structural checks (players, 200 minutes, departures)"
                   if conf in TRUSTED else f"roster confidence {conf}: no rotation is built")  # fmt: skip
    rot = sorted(ps.get("expected_rotation") or [], key=lambda p: -float(p.get("minutes") or 0))
    au = tr.audit.get(t) or {}
    return {
        "available": True, "snapshot": tr.stamp, "snapshot_at": stamp_iso(tr.stamp),
        "confidence": conf, "explanation": CONFIDENCE_TEXT.get(conf, conf),
        "reason": x.get("confidence_reason"),
        "reason_text": REASON_TEXT.get(str(x.get("confidence_reason")), x.get("confidence_reason")),
        "official_identity_coverage": _f(x.get("official_identity_coverage"), 3),
        "fresh_sources": list(x.get("fresh_groups") or []),
        "counts": {k: int(x.get(f"n_{k}") or 0) for k in (
            "listed", "confirmed", "likely", "conflicted", "stale", "unknown", "returning",
            "returning_after_gap", "transfer", "first_d1", "dropped", "class_label_conflict")},
        "continuity": {
            "returning_minutes_share": _f(ps.get("truth_cont")),
            "expected_returning_share": _f(au.get("expected_returning_share")),
            "incoming_transfer_prev_share": _f(ps.get("tr_prev")),
            "first_d1_expected_to_play": _f(ps.get("first_d1"), 1),
            "minutes": {"returning": _f(ps.get("proj_min_returning"), 1),
                        "transfer": _f(ps.get("proj_min_transfer"), 1),
                        "first_d1": _f(ps.get("proj_min_unseen"), 1)},
            "game1_continuity_correction": _f(au.get("adjustment"), 2),
            "audit_snapshot": tr.audit_stamp,
        },
        "rotation_valid": valid, "rotation_note": why_not,
        "rotation_sanity": {k: sane.get(k) for k in ("ok", "n_players", "n_rotation_10min",
                                                     "minutes_total", "starters")} if sane else None,
        "expected_rotation": [rotation_player(p, tr.names, teams) for p in rot
                              if float(p.get("minutes") or 0) > 0] if valid else [],
    }  # fmt: skip


# ===================================================================== the publication
@dataclass
class Built:
    run_id: str
    documents: dict[str, dict]  # v1 (kind -> doc; event_detail/<id>)
    explorer: list[dict]
    health: dict
    summary: dict[str, Any]


def _quality(status: str, w: World, source: str, limits: list[str], **kw: Any) -> dict:
    return R.quality(status=status, source=source, generated_at=w.now, production=True,
                     limitations=limits, methodology_version="sift-cbb-app-1", **kw)  # fmt: skip


def build(w: World) -> Built:
    now = w.now
    gen = iso(now)
    run_id = ids.run_id(SPORT, REPO, f"sift-app-{now.strftime('%Y%m%dT%H%M%SZ')}", generated_at=gen)
    g, dropped = games_frame(w)
    teams = team_directory(w, g)
    research_from, board_from, board_to = windows(g, now)
    frozen = S.roles(w.active)
    by_game: dict[int, list[dict]] = {}
    for r in w.records:
        by_game.setdefault(int(r["game"]["espn_game_id"]), []).append(r)

    # ---- selection for every D-I game (cheap; only games with records carry anything)
    sel: dict[int, S.Selection] = {}
    for row in g.to_dict("records"):
        sel[row["espn_game_id"]] = S.select(
            by_game.get(row["espn_game_id"], []), clock_of(row), now, frozen
        )

    # ---- team ratings: each team's newest archived incumbent pregame rating
    ratings: dict[str, dict[str, Any]] = {}
    inc = w.active["incumbent"]
    for r in sorted(
        w.records, key=lambda r: S.ts((r.get("prospective") or {}).get("as_of") or "1970")
    ):
        if (r.get("model") or {}).get("version") != inc or not (r.get("prospective") or {}).get(
            "as_of"
        ):
            continue
        if S.ts(r["prospective"]["as_of"]) > now:
            continue
        for side in ("home", "away"):
            rt = (r.get("ratings") or {}).get(side)
            if rt:
                ratings[r[side]["team_id"]] = {
                    "as_of": iso(r["prospective"]["as_of"]), "version": inc,
                    "games_seen": (r.get("freshness") or {}).get(f"{side}_games_seen"),
                    "event": f"G{int(r['game']['espn_game_id'])}", **_flat_ratings(rt)}  # fmt: skip

    # ---- rankings
    rankings: dict[str, dict] = {}
    pid_to_tid = {tm["pid"]: t for t, tm in teams.items()}
    team_obs: dict[str, list[dict]] = {t: [] for t in teams}
    universe = f"NCAA D-I men's teams, {w.season - 1}-{str(w.season)[2:]}"
    r_window = R.window("SEASON", label="LATEST_PREGAME")
    t_window = R.window("SEASON", label="PRESEASON_ROSTER")
    rq = _quality("PARTIAL", w, "projections-archive (incumbent pre-tip records)",
                  ["each team's value is its newest archived pre-tip rating; as-of times differ by team",
                   "teams without an archived projection are not ranked"],
                  data_as_of=max((v["as_of"] for v in ratings.values()), default=None),
                  coverage=f"{len(ratings)} of {len(teams)} D-I teams", sample_size=len(ratings))  # fmt: skip
    tq = None
    if w.truth is not None:
        tq = _quality("RESEARCH", w, f"roster-archive truth snapshot {w.truth.stamp}",
                      ["expected rotation from roster and prior participation evidence, not a lineup",
                       "teams whose roster confidence is STALE or UNKNOWN, or whose rotation failed its "
                       "checks, are not ranked"],
                      data_as_of=w.truth.as_of, coverage=f"roster truth {w.truth.stamp}")  # fmt: skip
    for m in METRICS:
        vals = []
        for t, tm in teams.items():
            if m.source == "ratings":
                v = (ratings.get(t) or {}).get(m.key)
            else:
                ps = (w.truth.proster.get(t) if w.truth else None) or {}
                ok = _roster_rankable(t, w)
                v = ps.get(m.key) if ok else None
            v = _f(v)
            if v is not None:  # NaN (e.g. no prior-season minutes) is "no value", never zero
                vals.append({"entity_id": tm["pid"], "display_name": tm["name"], "short_name": tm["short"],
                             "value": round(float(v), 4), "path": R.team_path(tm["pid"])})  # fmt: skip
        if len(vals) < 2:
            continue
        q = rq if m.source == "ratings" else tq
        rk = R.ranking(sport=SPORT, metric_id=mid(m.slug), universe_label=universe, entity_type="TEAM",
                       window=r_window if m.source == "ratings" else t_window, as_of=now,
                       higher_is_better=m.higher, values=vals, run_id=run_id, generated_at=gen,
                       quality=q, season=f"{w.season - 1}-{str(w.season)[2:]}",
                       links=[R.link(rel="METRIC", target_kind="metric_registry", label=m.name,
                                     target_id=mid(m.slug), path=R.app_path(R.METRICS_NAME))])  # fmt: skip
        rankings[m.slug] = rk
        for e in rk["entries"]:
            t = e["entity_id"]
            # as of: the team's own archived rating time, or the roster-truth snapshot
            obs_asof = ((ratings.get(pid_to_tid[t]) or {}).get("as_of") if m.source == "ratings"
                        else w.truth.as_of if w.truth else now) or now  # fmt: skip
            team_obs.setdefault(t, []).append(R.observation(
                sport=SPORT, metric_id=mid(m.slug), entity_id=t, entity_type="TEAM", value=e["value"],
                adjusted_value=e["value"] if m.adjusted else None, unit=m.unit,
                window=rk["window"], as_of=obs_asof, source=q["source"],
                quality_status=q["status"], context=R.context_from_ranking(rk, t),
            ))  # fmt: skip

    # ---- events (board window) and research (research window)
    in_board = g[(g["start"] >= board_from) & (g["start"] <= board_to)] if len(g) else g
    in_research = g[(g["start"] >= research_from) & (g["start"] <= board_to)] if len(g) else g
    events_all: dict[int, dict] = {}

    def event_for(row: dict[str, Any]) -> dict:
        gid = row["espn_game_id"]
        if gid in events_all:
            return events_all[gid]
        s_ = sel[gid]
        h, a = teams[row["home"]], teams[row["away"]]
        prim = s_.primary(ROLE_ORDER)
        ext = {"cbb": {
            "cbb_game_id": row["gid"], "espn_game_id": gid, "date_et": row["date_et"],
            "time_state": row["time_state"], "tbd": row["time_state"] != ANNOUNCED,
            "site": "neutral" if row["neutral"] else "home", "neutral_site": row["neutral"],
            "conference_game": row["conference_game"], "event_name": row["notes"],
            "schedule_source": row["schedule_source"], "reconciled_fields": row["reconciled_fields"],
            "projection_state": s_.state, "projection_message": s_.message,
            "primary": _compact(model_row(prim)) if prim else None,
            "models": sorted(c.version for c in s_.chosen.values()),
            "roster_confidence": {"home": _conf(row["home"], w), "away": _conf(row["away"], w)},
            "integrity": _integrity(gid, s_, w, bool(row["completed"])),
            "result": ({"home_score": row["home_score"], "away_score": row["away_score"]}
                       if row["completed"] and row["home_score"] is not None else None),
            "conferences": {"home": h["conference"], "away": a["conference"]},
        }}  # fmt: skip
        venue = ", ".join(x for x in (row["venue"], row["city"], row["region"]) if x) or None
        ev = C.event(
            sport=SPORT, source=SOURCE_GAME, source_id=row["gid"], start_time_utc=row["start"],
            participants=[participant(a), participant(h)], home_participant=h["pid"],
            away_participant=a["pid"], league=LEAGUE, season=f"{w.season - 1}-{str(w.season)[2:]}",
            competition=row["notes"] or ("Conference" if row["conference_game"] else "Non-conference"),
            status=_event_status(row["state"], row["status_name"], row["completed"]),
            start_time_source=("espn_scoreboard (fallback)" if row["schedule_source"] == "ESPN_FALLBACK"
                               else "sportsdataverse schedule (ESPN)"),
            start_time_confidence="SCHEDULED" if row["time_state"] == ANNOUNCED else "PLACEHOLDER",
            venue=venue, source_ids={"espn_event_id": gid},
            schedule_updated_at=w.schedule_observed_at or None, last_updated_at=now, extensions=ext,
        )  # fmt: skip
        events_all[gid] = ev
        return ev

    board_rows = in_board.to_dict("records") if len(g) else []
    events = [event_for(r) for r in board_rows]

    # ---- markets: exact-key mapped Kalshi game contracts of board events (never priced)
    markets = []
    if w.kalshi is not None:
        ev_by_gid = {e["extensions"]["cbb"]["cbb_game_id"]: e for e in events}
        for gid, raws in sorted(w.kalshi_games.items()):
            ev = ev_by_gid.get(gid)
            if ev is None:
                continue
            for raw in raws:
                m = _market(raw, ev, teams, w.kalshi)
                if m is not None:
                    markets.append(m)
    mk_by_event: dict[str, list[dict]] = {}
    for m in markets:
        mk_by_event.setdefault(m["event_id"], []).append(m)

    # ---- explorer: event research
    docs: list[dict] = []
    ev_research_ids: dict[int, str] = {}
    rkpath = {slug: R.ranking_path(rk["ranking_id"]) for slug, rk in rankings.items()}
    for row in in_research.to_dict("records") if len(g) else []:
        ev = event_for(row)
        doc = _event_research(row, ev, sel[row["espn_game_id"]], w, teams, rankings, run_id, gen,
                              mk_by_event.get(ev["event_id"], []))  # fmt: skip
        docs.append(doc)
        ev_research_ids[row["espn_game_id"]] = ev["event_id"]

    # ---- explorer: team profiles
    games_by_team: dict[str, list[dict]] = {t: [] for t in teams}
    for row in g.to_dict("records") if len(g) else []:
        for side, opp in (("home", "away"), ("away", "home")):
            games_by_team[row[side]].append(row | {"_side": side, "_opp": row[opp]})
    for t, tm in teams.items():
        docs.append(_team_profile(t, tm, w, teams, games_by_team[t], team_obs.get(tm["pid"], []),
                                  rankings, rkpath, sel, ev_research_ids, ratings.get(t), run_id, gen))  # fmt: skip
    docs.extend(rankings.values())

    # ---- metric registry, capabilities, search
    docs.append(_registry(w, run_id, gen, rankings))
    docs.append(_capabilities(w, run_id, gen, docs, rankings, markets, sel))
    docs.append(_search(teams, events_all, ev_research_ids, rankings, run_id, gen, w))

    # ---- v1 bundle
    health = _health(w, run_id, gen, g, sel, markets, rankings)
    v1: dict[str, dict] = {}
    v1["events"] = C.collection("events", SPORT, run_id, gen, events)
    v1["markets"] = C.collection("markets", SPORT, run_id, gen, markets)
    for k in ("model_prices", "recommendations", "theses", "wagers", "settlements"):
        v1[k] = C.collection(k, SPORT, run_id, gen, [])
    run = C.run(sport=SPORT, repo=REPO, completed_at=now, scope="app_publication",
                native_run_id=f"sift-app-{now.strftime('%Y%m%dT%H%M%SZ')}", commit_sha=w.code_sha,
                model_version=inc, events_processed=len(events), markets_discovered=len(markets),
                data_sources=["projections-archive", "roster-archive", "schedule-archive",
                              "prospective-scores", "kalshi-archive", "sportsdataverse schedule"],
                input_freshness={"schedule": w.schedule_observed_at,
                                 "roster_truth": stamp_iso(w.truth.stamp) if w.truth else None,
                                 "projections": w.manifests[-1]["as_of"] if w.manifests else None,
                                 "scoreboard": stamp_iso(w.scoreboard.stamp) if w.scoreboard else None,
                                 "markets": w.kalshi.captured_at if w.kalshi else None},
                warnings=[f"{v} games vs non-D-I opponents are outside the experiment and not published"
                          for k, v in dropped.items() if v and k == "non_d1_opponent"],
                source_ids={"app_branch": APP_BRANCH})  # fmt: skip
    if run["run_id"] != run_id:
        run["run_id"] = run_id
    v1["runs"] = C.collection("runs", SPORT, run_id, gen, [run])
    v1["performance"] = P.build_performance(
        sport=SPORT, run_id=run_id, generated_at=gen, wagers=[], settlements=[], markets=markets,
        notes=["CBB is a research system: no recommendations and no wagers are published."])  # fmt: skip
    board = B.build_board(sport=SPORT, run_id=run_id, generated_at=gen, events=events, markets=markets,
                          model_prices=[], recommendations=[], wagers=[], health=health, now=now)  # fmt: skip
    for item in board["items"]:  # the board's model time = the archived pre-tip record shown
        ext = next(e for e in events if e["event_id"] == item["event_id"])["extensions"]["cbb"]
        if ext["primary"]:
            item["model_generated_at"] = ext["primary"]["as_of"]
        flags = [f for f in item["health_flags"] if f != "START_TIME_PLACEHOLDER"]
        flags += {"PROJECTED": ["PROSPECTIVE_PROJECTION"], "PENDING_WINDOW": ["PROJECTION_PENDING"],
                  "AWAITING_CAPTURE": ["PROJECTION_AWAITING_CAPTURE"],
                  "UNAVAILABLE": ["NO_PRETIP_PROJECTION"]}[ext["projection_state"]]  # fmt: skip
        if ext["tbd"]:
            flags.append("START_TIME_TBD")
        if ext["neutral_site"]:
            flags.append("NEUTRAL_SITE")
        if ext["schedule_source"] == "ESPN_FALLBACK":
            flags.append("SCHEDULE_ESPN_FALLBACK")
        if ext["integrity"]["status"] in ("UNSCORABLE", "INVALID"):
            flags.append(ext["integrity"]["status"])
        item["health_flags"] = flags
    validate(board, "board")
    v1["board"] = board
    for ev in events:
        v1[f"event_detail/{ev['event_id']}"] = B.build_event_detail(
            sport=SPORT, run_id=run_id, generated_at=gen, event=ev, markets=markets, model_prices=[],
            recommendations=[], theses=[], wagers=[], settlements=[],
            context={"note": "CBB research publication: projections live in the event research "
                             "document; no model prices, recommendations or wagers."},
            data_freshness=next(b["data_freshness"] for b in board["items"] if b["event_id"] == ev["event_id"]),
        )  # fmt: skip
    summary = {
        "run_id": run_id, "games_d1": int(len(g)), "board_events": len(events),
        "research_events": len(ev_research_ids), "teams": len(teams), "markets": len(markets),
        "rankings": len(rankings), "records_read": len(w.records),
        "projected_games": sum(1 for s_ in sel.values() if s_.state == S.PROJECTED),
        "dropped": dropped, "board_window": [iso(board_from), iso(board_to)],
        "overall_status": health["overall_status"],
    }  # fmt: skip
    return Built(run_id, v1, docs, health, summary)


def _flat_ratings(rt: dict[str, Any]) -> dict[str, float | None]:
    out = {k: _f(rt.get(k)) for k in ("adj_off", "adj_def", "adj_tempo")}
    for k, v in (rt.get("four_factors") or {}).items():
        out[k] = _f(v)
    return out


def _roster_rankable(t: str, w: World) -> bool:
    tr = w.truth
    if tr is None or t not in tr.proster:
        return False
    row = tr.teams[tr.teams["team_id"] == t]
    conf = str(row.iloc[0]["roster_confidence"]) if len(row) else "UNKNOWN"
    return conf in TRUSTED and bool((tr.sanity.get(t) or {}).get("ok"))


def _conf(t: str, w: World) -> str:
    if w.truth is None:
        return "UNKNOWN"
    row = w.truth.teams[w.truth.teams["team_id"] == t]
    return str(row.iloc[0]["roster_confidence"]) if len(row) else "UNKNOWN"


def _compact(m: dict[str, Any]) -> dict[str, Any]:
    return {k: m[k] for k in ("version", "role", "role_label", "as_of", "home_score", "away_score",
                              "margin", "total", "home_win_prob", "possessions", "margin_sd",
                              "total_sd")}  # fmt: skip


def _integrity(gid: int, s_: S.Selection, w: World, completed: bool) -> dict[str, Any]:
    """The scoreboard's pre-tip gate verdict (read, never recomputed). A settled game the
    scoreboard has not reached yet is NOT_SCORED; an unsettled one is PENDING."""
    gate = (w.scoreboard.gate.get(gid) if w.scoreboard else None) or {}
    status = gate.get("status") or ("NOT_SCORED" if completed else "PENDING")
    reasons = S.reason_text(gate.get("reasons", ""))
    if s_.identity_changed and status not in ("UNSCORABLE", "INVALID"):
        reasons.append("the archived projection is for a different matchup or home/away than the "
                       "current schedule")  # fmt: skip
    return {"status": status, "text": S.GATE_TEXT.get(status), "reasons": reasons,
            "identity_changed_versions": s_.identity_changed, "conflicting_versions": s_.conflicts,
            "post_tip_records_ignored": sum(1 for r in s_.rejected if r["reason"] != "no_prospective_provenance"),
            "scoreboard": w.scoreboard.path if w.scoreboard else None}  # fmt: skip


def _market(
    raw: dict[str, Any], ev: dict, teams: dict[str, dict], cap: KalshiCapture
) -> dict | None:
    m = raw.get("market") or {}
    tk = m.get("ticker")
    if not tk:
        return None
    side, pid = None, None
    home, away = ev["home_participant"], ev["away_participant"]
    sub = str(m.get("yes_sub_title") or "")
    for p in ev["participants"]:
        if sub and sub.lower() in (p["display_name"].lower(), (p["short_name"] or "").lower(),
                                   str(p["metadata"].get("location") or "").lower()):  # fmt: skip
            pid = p["participant_id"]
            side = "HOME" if pid == home else "AWAY" if pid == away else None
    status = {"active": "OPEN", "closed": "CLOSED", "settled": "SETTLED", "finalized": "SETTLED",
              "initialized": "UNOPENED", "inactive": "UNOPENED"}.get(str(m.get("status")), "UNKNOWN")  # fmt: skip
    try:
        return C.market(
            sport=SPORT, kalshi_ticker=tk, market_family=raw.get("family") or "unknown",
            yes_description=m.get("title") or f"YES on {tk}", source="kalshi-archive (read-only capture)",
            event_id=ev["event_id"], kalshi_event_ticker=m.get("event_ticker"),
            kalshi_series_ticker=raw.get("series_ticker"), participant_id=pid, side=side,
            line=m.get("floor_strike"), yes_bid=m.get("yes_bid_dollars"), yes_ask=m.get("yes_ask_dollars"),
            no_bid=m.get("no_bid_dollars"), no_ask=m.get("no_ask_dollars"),
            last_price=m.get("last_price_dollars"), volume=m.get("volume_fp"),
            open_interest=m.get("open_interest_fp"), market_status=status,
            close_time_utc=m.get("close_time"), captured_at=cap.captured_at,
            raw_market_reference=f"kalshi-archive/{cap.file}",
        )  # fmt: skip
    except (ValueError, TypeError):
        return None


def _matchup(
    rec: dict | None,
    rankings: dict[str, dict],
    teams: dict[str, dict],
    home: str,
    away: str,
    as_of: Any,
    run_id: str,
) -> list[dict]:
    """Each team's opponent-adjusted pregame ratings from the shown record, side by side. A
    league rank is attached only when the published ranking holds exactly this value."""
    if not rec or not rec.get("ratings"):
        return []
    rows = []
    vals = {s: _flat_ratings(rec["ratings"][s]) for s in ("home", "away")}
    for m in RATING_METRICS:
        obs = {}
        for side, t in (("home", home), ("away", away)):
            v = vals[side].get(m.key)
            if v is None:
                obs[side] = None
                continue
            pid = teams[t]["pid"]
            rk = rankings.get(m.slug)
            ctx = R.context_from_ranking(rk, pid) if rk else None
            if ctx is not None:
                e = next(x for x in rk["entries"] if x["entity_id"] == pid)
                if abs(e["value"] - v) > 1e-6:
                    ctx = None  # the team's newest rating differs: no rank for this pregame value
            obs[side] = R.observation(
                sport=SPORT, metric_id=mid(m.slug), entity_id=pid, entity_type="TEAM", value=v,
                adjusted_value=v, unit=m.unit, window=R.window("GAME", label="PREGAME"), as_of=as_of,
                source="projections-archive (pre-tip record ratings)", quality_status="RESEARCH",
                context=ctx)  # fmt: skip
        rows.append({"metric_id": mid(m.slug), "name": m.name, "home": obs["home"], "away": obs["away"],
                     "note": "opponent-adjusted pregame rating stored in the archived pre-tip record"})  # fmt: skip
    return rows


def _event_research(
    row: dict,
    ev: dict,
    s_: S.Selection,
    w: World,
    teams: dict[str, dict],
    rankings: dict[str, dict],
    run_id: str,
    gen: str,
    markets: list[dict],
) -> dict:
    h, a = teams[row["home"]], teams[row["away"]]
    models = [model_row(c) for c in sorted(s_.chosen.values(),
                                           key=lambda c: (ROLE_ORDER.index(c.role), c.version))]  # fmt: skip
    prim = s_.primary(ROLE_ORDER)
    projections, dists = [], []
    for c, m in zip(sorted(s_.chosen.values(), key=lambda c: (ROLE_ORDER.index(c.role), c.version)),
                    models, strict=True):  # fmt: skip
        auth = AUTHORITY[c.role]
        for slug, val, unit, fair in (("proj_margin", m["margin"], "pts (home − away)", None),
                                      ("proj_total", m["total"], "pts", None),
                                      ("proj_home_win_prob", m["home_win_prob"], "probability", m["home_win_prob"])):  # fmt: skip
            projections.append({"model_price_id": None, "market_id": None, "event_id": ev["event_id"],
                                "metric_id": mid(slug), "fair_probability": fair, "market_probability": None,
                                "edge": None, "projection_value": val, "projection_unit": unit,
                                "lower_bound": None, "upper_bound": None, "generated_at": m["as_of"],
                                "run_id": None, "model_version": c.version, "research_only": True,
                                "authority": auth, "quality_status": "RESEARCH"})  # fmt: skip
        for slug, mu, sd, lab in (
            ("proj_margin", m["margin"], m["margin_sd"], "Home margin"),
            ("proj_total", m["total"], m["total_sd"], "Total points"),
        ):
            if mu is None or not sd:
                continue
            q = {
                f"p{int(p * 100):02d}": round(mu + float(norm.ppf(p)) * sd, 2)
                for p in (0.1, 0.25, 0.5, 0.75, 0.9)
            }
            dists.append({"market_id": None, "metric_id": mid(slug), "entity_id": ev["event_id"],
                          "label": f"{lab} · {c.version} ({S.ROLE_LABEL[c.role]})", "quantiles": q, "mean": mu,
                          "stdev": sd, "samples": None, "run_id": None, "generated_at": m["as_of"],
                          "source": "normal(margin, margin_sd) of the frozen model, archived pre-tip",
                          "quality_status": "RESEARCH"})  # fmt: skip
    # roster: the shown P-ROSTER record's pregame state; else current truth for an upcoming
    # game (labelled as such); never a later snapshot for a game that has started
    roster_rec = next((c for c in s_.chosen.values() if c.role == S.ROSTER_OVERLAY), None)
    pro = proster_block(roster_rec, w, teams) if roster_rec else None
    started = clock_of(row).started(w.now)
    if pro is not None:
        basis = "pretip_record"
    elif not started:
        basis = "current_truth"
    else:
        basis = "none"
    roster = {"basis": basis,
              "basis_text": {"pretip_record": "Pregame roster state archived with the P-ROSTER-1 projection.",
                             "current_truth": "Current roster truth (no roster-overlay projection has been "
                                              "captured for this game yet).",
                             "none": "No pregame roster state was archived for this game; a later "
                                     "snapshot is not shown (it would be hindsight)."}[basis],
              "home": team_roster(row["home"], w, teams) if basis == "current_truth" else None,
              "away": team_roster(row["away"], w, teams) if basis == "current_truth" else None}  # fmt: skip
    ratings_rec = prim.record if prim else None
    matchup = _matchup(ratings_rec, rankings, teams, row["home"], row["away"],
                       prim.as_of if prim else w.now, run_id)  # fmt: skip
    notes = [s_.message]
    if row["time_state"] != ANNOUNCED:
        notes.append(f"Tip time not announced yet (TBD); listed date {row['date_et']} (ET).")
    if row["neutral"]:
        notes.append("Neutral site: no home-court edge in the model.")
    if not markets:
        notes.append("No executable Kalshi market is published for this game.")
    notes += packet_notes(models, pro, roster, h, a, w)
    ext = {"cbb": {
        **ev["extensions"]["cbb"],
        "models": models, "primary_version": prim.version if prim else None,
        "model_order_note": "Incumbent first. Shadow models and the roster overlay are research "
                            "comparisons; none is ranked above another before the preregistered "
                            "prospective evaluation.",
        "rejected_records": s_.rejected,
        "ratings_source": ({"version": prim.version, "as_of": iso(prim.as_of)} if prim and prim.record.get("ratings") else None),
        "matchup_pairs": [{"offense": o, "defense": d, "label": lab} for o, d, lab in MATCHUP_PAIRS],
        "roster": roster, "proster": pro,
        "venue": {"name": row["venue"], "city": row["city"], "region": row["region"], "neutral": row["neutral"]},
        "schedule": {"source": row["schedule_source"], "source_observed_at": row["source_observed_at"],
                     "reconciled_fields": row["reconciled_fields"],
                     "listed_start": iso(row["start"]), "time_state": row["time_state"],
                     "state": row["state"], "status_name": row["status_name"]},
        "markets_published": len(markets),
    }}  # fmt: skip
    ql = [
        "projections are research evidence from a prospectively frozen system (no betting authority)",
        "ratings and projections are those stored in the archived pre-tip record",
    ]
    quality = _quality("RESEARCH", w, "projections-archive + roster-archive + schedule", ql,
                       data_as_of=prim.as_of if prim else None)  # fmt: skip
    links = [R.link(rel="TEAM", target_kind="entity_profile", label=t["name"], target_id=t["pid"],
                    path=R.team_path(t["pid"])) for t in (a, h)]  # fmt: skip
    return R.event_research(
        sport=SPORT, run_id=run_id, generated_at=gen, event=ev, quality=quality,
        participants=[{"participant_id": a["pid"], "display_name": a["name"], "home_away": "AWAY",
                       "path": R.team_path(a["pid"])},
                      {"participant_id": h["pid"], "display_name": h["name"], "home_away": "HOME",
                       "path": R.team_path(h["pid"])}],
        matchup=matchup, projections=projections, distributions=dists,
        markets=[R.market_ref(m) for m in markets],
        context={"venue": ext["cbb"]["venue"], "notes": notes}, links=links, extensions=ext,
    )  # fmt: skip


def packet_notes(
    models: list[dict], pro: dict | None, roster: dict, h: dict, a: dict, w: World
) -> list[str]:
    """Plain-language evidence lines for the generic handicap packet (``context.notes``):
    every projection row with its archive time and role, roster confidence, the P-ROSTER-1
    state and the prospective sample. Evidence, never an instruction."""
    out = []
    hn, an = h["location"], a["location"]
    for m in models:
        if m["margin"] is None:
            continue
        lead = hn if m["margin"] >= 0 else an
        r80 = m["margin_range_80"]
        rng = f"; 80% model range {r80[0]:+.1f} to {r80[1]:+.1f}" if r80 else ""
        out.append(
            f"{m['role_label']} {m['version']} projection, archived pre-tip {m['as_of']} (research "
            f"evidence): {an} {m['away_score']:.1f}, {hn} {m['home_score']:.1f}; {lead} by "
            f"{abs(m['margin']):.1f} (model SD {m['margin_sd']}{rng}); total {m['total']:.1f} "
            f"(SD {m['total_sd']}); {m['possessions']:.1f} possessions; {hn} win probability "
            f"{100 * m['home_win_prob']:.0f}%."
        )  # fmt: skip
    if pro is not None:
        for side, team in (("home", h), ("away", a)):
            s = pro["sides"][side]
            out.append(
                f"P-ROSTER-1 roster overlay, {team['location']}: roster {s['roster_confidence']}; "
                f"input substitution {'active' if s['input_substitution_active'] else 'not applied'}; "
                f"continuity correction {'active' if s['continuity_correction_active'] else 'not applied'}"
                + (f"; returning-minutes share {100 * s['returning_minutes_share']:.0f}%"
                   if s["returning_minutes_share"] is not None else "") + "."
            )  # fmt: skip
        if pro["adjustment_total"] is not None:
            out.append(f"P-ROSTER-1 margin adjustment vs its frozen base: {pro['adjustment_total']:+.2f} "
                       "(input substitution + continuity correction).")  # fmt: skip
    elif roster.get("basis") == "current_truth":
        for side, team in (("home", h), ("away", a)):
            ro = roster.get(side) or {}
            out.append(f"Roster confidence {team['location']}: {ro.get('confidence', 'UNKNOWN')} — "
                       f"{ro.get('explanation', '')} (snapshot {ro.get('snapshot')}).")  # fmt: skip
    sb = w.scoreboard
    n1 = (((sb.summary.get("headline") or {}).get("game_1") or {}).get("N", 0)) if sb else 0
    out.append(f"Prospective evaluation: game-1 N = {n1}; no model is ranked above another before the "
               "preregistered evaluation, and no inference is drawn below the locked minimum sample.")  # fmt: skip
    return out


def _team_profile(
    t: str,
    tm: dict,
    w: World,
    teams: dict[str, dict],
    games: list[dict],
    obs: list[dict],
    rankings: dict[str, dict],
    rkpath: dict[str, str],
    sel: dict[int, S.Selection],
    ev_ids: dict[int, str],
    rating: dict | None,
    run_id: str,
    gen: str,
) -> dict:
    refs, opps = [], {}
    nxt = []
    for row in sorted(games, key=lambda r: (r["start"], r["espn_game_id"])):
        opp = teams[row["_opp"]]
        eid = ev_ids.get(row["espn_game_id"]) or event_eid(row["gid"])
        res = None
        if row["completed"] and row["home_score"] is not None:
            mine = row["home_score"] if row["_side"] == "home" else row["away_score"]
            theirs = row["away_score"] if row["_side"] == "home" else row["home_score"]
            res = {
                "for": mine,
                "against": theirs,
                "outcome": "W" if mine > theirs else "L" if mine < theirs else "T",
            }
        refs.append(R.game_ref(
            event_id=eid, start_time_utc=row["start"],
            status=_event_status(row["state"], row["status_name"], row["completed"]),
            opponent_id=opp["pid"], opponent_name=opp["name"],
            home_away="NEUTRAL" if row["neutral"] else row["_side"].upper(), result=res,
            competition=row["notes"] or ("Conference" if row["conference_game"] else "Non-conference"),
            path=R.event_path(eid) if row["espn_game_id"] in ev_ids else None))  # fmt: skip
        o = opps.setdefault(opp["pid"], {"participant_id": opp["pid"], "display_name": opp["name"],
                                         "event_ids": [], "path": R.team_path(opp["pid"])})  # fmt: skip
        o["event_ids"].append(eid)
        s_ = sel.get(row["espn_game_id"])
        if s_ is not None and not row["completed"] and len(nxt) < 3:
            nxt.append({"event_id": eid, "cbb_game_id": row["gid"], "start": iso(row["start"]),
                        "tbd": row["time_state"] != ANNOUNCED, "date_et": row["date_et"], "opponent": opp["name"],
                        "home_away": "NEUTRAL" if row["neutral"] else row["_side"].upper(),
                        "projection_state": s_.state,
                        "primary": _compact(model_row(p)) if (p := s_.primary(ROLE_ORDER)) else None,
                        "path": R.event_path(eid) if row["espn_game_id"] in ev_ids else None})  # fmt: skip
    roster = team_roster(t, w, teams)
    rk_refs = [{"ranking_id": rankings[m.slug]["ranking_id"], "metric_id": mid(m.slug),
                "window_label": rankings[m.slug]["window"]["label"], "split": None, "path": rkpath[m.slug]}
               for m in METRICS if m.slug in rankings]  # fmt: skip
    q = _quality("PARTIAL", w, "schedule + roster-archive + projections-archive",
                 ["ratings appear once the team has an archived pre-tip projection",
                  "roster state is the newest roster-truth snapshot"],
                 data_as_of=w.truth.as_of if w.truth else None)  # fmt: skip
    ext = {"cbb": {"team_id": t, "espn_team_id": tm["espn"], "conference": tm["conference"],
                   "logo_url": tm["logo"], "roster": roster, "ratings": rating,
                   "upcoming": nxt, "schedule_games": len(refs),
                   "completed_games": sum(1 for r in refs if r["result"])}}  # fmt: skip
    links = [R.link(rel="RANKING", target_kind="ranking", label=rankings[m.slug]["metric_id"],
                    target_id=rankings[m.slug]["ranking_id"], path=rkpath[m.slug])
             for m in METRICS if m.slug in rankings][:1]  # fmt: skip
    return R.entity_profile(
        sport=SPORT, run_id=run_id, generated_at=gen, entity=participant(tm), entity_type="TEAM",
        quality=q, season=f"{w.season - 1}-{str(w.season)[2:]}", league=LEAGUE, metrics=obs,
        rankings=rk_refs, games=refs, opponents=list(opps.values()), links=links, extensions=ext,
    )  # fmt: skip


def _registry(w: World, run_id: str, gen: str, rankings: dict[str, dict]) -> dict:
    out = []
    for m in METRICS + PROJ_METRICS:
        if m.source == "ratings":
            q = _quality("RESEARCH", w, "opponent-adjusted ratings stored in archived pre-tip records",
                         ["published only for teams with an archived projection",
                          "the prospective evaluation has not yet concluded (frozen protocol)"])  # fmt: skip
            src = "projections-archive (sift-cbb-projection-1.x ratings)"
        elif m.source == "roster":
            q = _quality(
                "RESEARCH",
                w,
                "roster-archive truth snapshots",
                ["expected rotation from roster and prior participation evidence, not a lineup"],
            )
            src = "roster-archive (P-ROSTER state)"
        else:
            q = _quality(
                "RESEARCH",
                w,
                "projections-archive",
                [
                    "archived pre-tip projections of a frozen research system; N = prospective sample"
                ],
            )
            src = "projections-archive"
        out.append(R.metric(
            sport=SPORT, slug=m.slug, name=m.name, short_name=m.short, description=m.desc,
            entity_type=m.entity, category=m.category, stat_type=m.stat_type, source=src, quality=q,
            freshness="FRESH" if m.slug in rankings or m.source == "projection" else "UNKNOWN",
            higher_is_better=m.higher, unit=m.unit,
            comparison_universe="NCAA D-I men's teams" if m.entity == "TEAM" else None,
            supports=R.supports(rank=m.entity == "TEAM", percentile=m.entity == "TEAM",
                                opponent_adjustment=m.adjusted, schedule_adjustment=m.adjusted,
                                home_away=m.source == "ratings"),
            windows=["LATEST_PREGAME"] if m.source == "ratings" else ["PRESEASON_ROSTER"] if m.source == "roster" else ["PREGAME"],
            methodology_version="sift-cbb-projection-1.0" if m.source != "roster" else "P-ROSTER-1 roster truth",
            update_frequency="per prospective run" if m.source != "roster" else "per roster capture",
            known_limitations=(["opponent-adjusted; compare only with other adjusted values"] if m.adjusted
                               else ["not opponent-adjusted"]),
            extensions={"cbb": {"source_field": m.key, "adjusted": m.adjusted, "group": m.source}},
        ))  # fmt: skip
    return R.metric_registry(sport=SPORT, run_id=run_id, generated_at=gen, metrics=out)


def _capabilities(
    w: World,
    run_id: str,
    gen: str,
    docs: list[dict],
    rankings: dict,
    markets: list,
    sel: dict[int, S.Selection],
) -> dict:
    team = next((d for d in docs if d["kind"] == "entity_profile"), None)
    ev = next((d for d in docs if d["kind"] == "event_research"), None)
    rk = next(iter(rankings.values()), None)
    path = lambda d: R.app_path(R.path_for(d)) if d else None  # noqa: E731
    projected = any(s_.state == S.PROJECTED for s_ in sel.values())
    rated = any(m.slug in rankings for m in RATING_METRICS)
    caps = []

    def cap(
        name: str,
        status: str,
        summary: str,
        evidence: list[str | None] | None = None,
        limits: list[str] | None = None,
        reasons: list[str] | None = None,
    ) -> None:
        ev_ = [e for e in (evidence or []) if e] if status in ("VERIFIED", "PARTIAL") else []
        if status in ("VERIFIED", "PARTIAL") and not ev_:
            status, limits = "UNAVAILABLE", None
        caps.append(R.capability(capability=name, status=status, summary=summary, evidence=ev_,
                                 limitations=limits or [], reasons=reasons or []))  # fmt: skip

    na = "UNAVAILABLE"
    cap(
        "team_profiles",
        "PARTIAL",
        "All D-I teams: schedule, roster truth, ratings once projected.",
        [path(team)],
        ["ratings appear only after a team's first archived projection"],
    )
    cap(
        "event_research",
        "PARTIAL",
        "Every D-I game in the research window, projected or pending.",
        [path(ev)],
        ["games outside the research window carry no event document"],
    )
    cap(
        "rankings",
        "PARTIAL" if rk else na,
        "Full D-I comparison universes for published metrics.",
        [path(rk)],
        ["ratings rank only teams with an archived projection"],
    )
    cap(
        "team_metrics",
        "PARTIAL" if rk else na,
        "Opponent-adjusted ratings and roster metrics.",
        [path(rk)],
        ["roster metrics are research evidence, not ratings"],
    )
    cap(
        "opponent_adjustment",
        "PARTIAL" if rated else na,
        "Ratings are opponent-adjusted inside the model fit."
        if rated
        else "Ratings publish with the first archived prospective projections.",
        [path(rankings.get("adj_off"))],
        ["newest archived pregame rating per team"],
    )
    cap(
        "advanced_stats",
        "PARTIAL" if rated else na,
        "Adjusted Four Factors and shooting splits.",
        [path(rankings.get("adj_efg_off"))],
        ["opponent-adjusted; from archived records"],
    )
    cap(
        "matchup_metrics",
        "PARTIAL" if projected else na,
        "Offense vs defense on adjusted ratings from the pre-tip record.",
        [path(ev)],
        ["shown only for games with an archived projection"],
    )
    cap(
        "raw_projections",
        "RESEARCH" if projected else na,
        "Archived pre-tip score, margin, total, possessions and win probability per frozen model.",
        reasons=["no game has entered the 30-hour capture window yet"] if not projected else [],
        limits=["research evidence from a frozen system with no betting authority"]
        if projected
        else None,
    )
    cap(
        "projection_distributions",
        "RESEARCH" if projected else na,
        "Normal margin / total uncertainty from each frozen model's SDs.",
        limits=["model uncertainty, not a guaranteed range"] if projected else None,
    )
    cap(
        "lineups",
        "RESEARCH" if w.truth else na,
        "Expected pregame rotation from roster and prior participation evidence (not a lineup).",
        limits=["not a confirmed starting lineup; teams without a valid rotation say so"]
        if w.truth
        else None,
    )
    cap(
        "opponents",
        "PARTIAL",
        "Each team's D-I opponents with links.",
        [path(team)],
        ["D-I opponents only"],
    )
    cap(
        "historical_accuracy",
        "RESEARCH" if w.scoreboard else na,
        "The preregistered prospective scoreboard (sample size first).",
        limits=["no inference below the locked minimum sample"] if w.scoreboard else None,
    )
    cap(
        "market_prices",
        "PARTIAL" if markets else na,
        "Read-only Kalshi game contracts mapped exactly to games."
        if markets
        else "No Kalshi game contract maps to a published game.",
        [path(ev)] if markets else None,
        ["captured quotes; never priced by the model"],
    )
    cap(
        "game_markets",
        "PARTIAL" if markets else na,
        "Kalshi game-level contracts.",
        [path(ev)] if markets else None,
        ["captured quotes; never priced by the model"],
    )
    cap("search", "VERIFIED", "Teams, games, metrics and rankings.", [R.app_path(R.SEARCH_NAME)])
    for name, why in (
        ("player_profiles", "no player pages are published for CBB"),
        ("player_metrics", "no player metrics are published for CBB"),
        ("player_props", "no CBB player props are published"),
        ("team_props", "no CBB team props are published"),
        ("team_game_logs", "game logs are not published by the CBB app"),
        ("historical_results", "results appear on team schedules once games are final"),
        ("schedule_strength", "not published"),
        ("recent_form_windows", "not published"),
        ("usage", "not published"),
        ("injuries", "availability is not published for CBB"),
        ("market_price_history", "no market history is published"),
        ("situational_splits", "not published"),
        ("play_by_play", "not published"),
        ("weather", "indoor sport"),
        ("venue_effects", "not published"),
        ("calibration", "prospective evaluation in progress"),
        ("clv", "no wagers"),
        ("wager_history", "no wagers: research only"),
        ("time_series", "not published yet"),
        ("comparisons", "not published"),
    ):
        cap(name, na, why.capitalize() + ".", reasons=[why])
    return R.capability_manifest(sport=SPORT, run_id=run_id, generated_at=gen, capabilities=caps,
                                 audit_date=w.now.date(),
                                 notes=["CBB: prospectively frozen research system; no recommendations, "
                                        "no wagers. Projections are archived before tip and never re-run."])  # fmt: skip


def _search(
    teams: dict,
    events: dict[int, dict],
    ev_ids: dict[int, str],
    rankings: dict,
    run_id: str,
    gen: str,
    w: World,
) -> dict:
    entries = []
    for tm in teams.values():
        entries.append(R.search_entry(id=tm["pid"], kind="TEAM", label=tm["name"], path=R.team_path(tm["pid"]),
                                      sport=SPORT, secondary=tm["conference"],
                                      aliases=[x for x in (tm["short"], tm["location"], tm["school"]) if x],
                                      league=LEAGUE))  # fmt: skip
    for gid, eid in ev_ids.items():
        ev = events[gid]
        names = {p["participant_id"]: p for p in ev["participants"]}
        lab = f"{names[ev['away_participant']]['display_name']} at {names[ev['home_participant']]['display_name']}"
        entries.append(R.search_entry(id=eid, kind="EVENT", label=lab, path=R.event_path(eid), sport=SPORT,
                                      secondary=ev["extensions"]["cbb"]["date_et"],
                                      aliases=[ev["extensions"]["cbb"]["cbb_game_id"]]))  # fmt: skip
    for slug, rk in rankings.items():
        m = next(x for x in METRICS if x.slug == slug)
        entries.append(R.search_entry(id=rk["ranking_id"], kind="RANKING", label=f"{m.name} ranking · NCAA D-I",
                                      path=R.ranking_path(rk["ranking_id"]), sport=SPORT,
                                      secondary=m.short, aliases=[m.short]))  # fmt: skip
    return R.search_index(sport=SPORT, run_id=run_id, generated_at=gen, entries=entries)


# ===================================================================== health
def _health(
    w: World,
    run_id: str,
    gen: str,
    g: pd.DataFrame,
    sel: dict[int, S.Selection],
    markets: list[dict],
    rankings: dict[str, dict] | None = None,
) -> dict:
    now = w.now
    last_manifest = w.manifests[-1] if w.manifests else None
    upcoming = g[~g["completed"] & (g["start"] > now)] if len(g) else g
    first = upcoming["start"].min() if len(upcoming) else None
    in_window = (
        int(((upcoming["start"] - now) <= pd.Timedelta(hours=S.CAPTURE_WINDOW_H)).sum())
        if len(upcoming)
        else 0
    )
    projected = sum(1 for s_ in sel.values() if s_.state == S.PROJECTED)
    started = int((g["completed"] | (g["start"] <= now)).sum()) if len(g) else 0
    season_live = projected > 0 or in_window > 0 or started > 0
    comp = {}
    comp["schedule"] = H.component(w.schedule_observed_at, thresholds=SCHEDULE_THRESHOLDS, now=now,
                                   detail=f"HEALTHY: {len(g)} D-I games ({w.schedule_report.get('sdv_games', 0)} "
                                          f"SDV-native, {w.schedule_report.get('fallback_games', 0)} ESPN fallback, "
                                          f"{(w.schedule_report.get('reconciliation') or {}).get('reconciled_games', 0)} "
                                          "field-reconciled)")  # fmt: skip
    tr = w.truth
    counts = tr.teams["roster_confidence"].value_counts().to_dict() if tr is not None else {}
    ok_share = (counts.get("CONFIRMED", 0) + counts.get("LIKELY", 0)) / max(1, sum(counts.values()))
    comp["roster_truth"] = H.component(
        tr.as_of if tr else None, thresholds=TRUTH_THRESHOLDS, now=now, required=True, degraded=ok_share < 0.8,
        detail=(f"{'HEALTHY' if ok_share >= 0.8 else 'PARTIAL'}: " + ", ".join(
            f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))) if tr else "UNAVAILABLE")  # fmt: skip
    comp["roster_archive"] = H.component(tr.as_of if tr else None, thresholds=TRUTH_THRESHOLDS, now=now,
                                         detail=f"commit {w.commits.get('roster_archive')}" if tr else None)  # fmt: skip
    pipe_detail = (f"HEALTHY: last prospective run {last_manifest['as_of']} "
                   f"({last_manifest['records']} records)") if last_manifest else "no prospective run yet"  # fmt: skip
    if not season_live:
        comp["prospective_pipeline"] = {"status": "NOT_APPLICABLE", "as_of": iso(last_manifest["as_of"]) if last_manifest else None,
                                        "age_seconds": None,
                                        "detail": pipe_detail + "; scheduled runs start in November"}  # fmt: skip
        comp["upcoming_projection"] = {"status": "NOT_APPLICABLE", "as_of": None, "age_seconds": None,
                                       "detail": f"WAITING_FOR_WINDOW: no D-I game tips in the next 30 h; "
                                                 f"first game {iso(first)}" if first is not None else "WAITING_FOR_WINDOW"}  # fmt: skip
    else:
        comp["prospective_pipeline"] = H.component(last_manifest["as_of"] if last_manifest else None,
                                                   thresholds=MODEL_THRESHOLDS, now=now, detail=pipe_detail)  # fmt: skip
        comp["upcoming_projection"] = {"status": "OK", "as_of": None, "age_seconds": None,
                                       "detail": f"{projected} games with an archived pre-tip projection; "
                                                 f"{in_window} games tip in the next 30 h"}  # fmt: skip
    comp["projection_archive"] = H.component(
        last_manifest["as_of"] if last_manifest else None, thresholds=MODEL_THRESHOLDS, now=now,
        required=season_live,
        applicable=season_live or last_manifest is not None,
        detail=f"{len(w.records)} archived records; append-only; commit {w.commits.get('projections_archive')}")  # fmt: skip
    if not season_live:
        comp["projection_archive"]["status"] = "OK" if last_manifest else "NOT_APPLICABLE"
    sb = w.scoreboard
    n1 = ((sb.summary.get("headline") or {}).get("game_1") or {}).get("N", 0) if sb else 0
    comp["prospective_scorer"] = H.component(stamp_iso(sb.stamp) if sb else None, thresholds=SCORER_THRESHOLDS,
                                             now=now, required=False,
                                             detail=(f"NO_DATA: game-1 N = {n1}" if not n1 else f"game-1 N = {n1}")
                                             if sb else "no scoreboard published")  # fmt: skip
    comp["schedule_archive"] = H.component(w.schedule_observed_at, thresholds=SCHEDULE_THRESHOLDS, now=now,
                                           detail=f"commit {w.commits.get('schedule_archive')}")  # fmt: skip
    model_required = season_live
    health = H.build_health(
        sport=SPORT, run_id=run_id, bet_authority="RESEARCH_ONLY",
        last_market_capture=w.kalshi.captured_at if (w.kalshi and markets) else None,
        last_model_generated=last_manifest["as_of"] if last_manifest and model_required else None,
        last_successful_run=now, payload_run_id=run_id, payload_available=True,
        commit_sha=w.code_sha, model_required=model_required, market_required=False,
        router_applicable=False, settlement_applicable=False,
        thresholds={"model": MODEL_THRESHOLDS}, extra_components=comp, now=now, generated_at=gen,
        warnings=([] if markets else ["Market research is not published for CBB yet: no Kalshi game "
                                      "contract maps to a published game."]),
        extensions={"cbb": {**_status_ext(w, g, sel, markets, first, in_window, season_live, counts),
                            "leaders": leaders(rankings or {})}},
    )  # fmt: skip
    health["components"]["market_data"]["detail"] = (
        f"{len(markets)} Kalshi game contracts mapped (read-only capture {w.kalshi.captured_at})"
        if markets and w.kalshi else
        "UNAVAILABLE: no Kalshi game contract maps to a published game (futures and season-win "
        "markets are not game markets)")  # fmt: skip
    if not model_required:
        health["components"]["model"]["detail"] = (
            "WAITING_FOR_WINDOW: no game has entered the 30-hour prospective capture window"
        )
    validate(health, "health")
    return health


LEADERS_N = 5


def leaders(rankings: dict[str, dict]) -> dict[str, Any]:
    """Presentation-only digest of the rankings this publication already contains: the top and
    bottom ``LEADERS_N`` entries of each, so the sport home can show the national picture without
    downloading every ranking. Same values, same ranks, same order as the ranking documents."""
    out = {}
    for m in METRICS:
        rk = rankings.get(m.slug)
        if rk is None:
            continue
        slim = [{k: e[k] for k in ("rank", "entity_id", "display_name", "short_name", "value", "percentile")}
                for e in rk["entries"]]  # fmt: skip
        out[m.slug] = {
            "metric_id": rk["metric_id"], "ranking_id": rk["ranking_id"], "name": m.name,
            "short_name": m.short, "unit": m.unit, "group": m.source, "adjusted": m.adjusted,
            "higher_is_better": rk["higher_is_better"], "universe_size": rk["universe"]["size"],
            "window": rk["window"]["label"], "mean": rk["summary"]["mean"],
            "top": slim[:LEADERS_N], "bottom": slim[-LEADERS_N:][::-1],
        }  # fmt: skip
    return out


def _status_ext(
    w: World,
    g: pd.DataFrame,
    sel: dict[int, S.Selection],
    markets: list[dict],
    first: Any,
    in_window: int,
    season_live: bool,
    counts: dict[str, int],
) -> dict[str, Any]:
    sb = w.scoreboard
    head = (sb.summary.get("headline") or {}) if sb else {}
    g1 = head.get("game_1") or {"N": 0}

    def slim(t: dict) -> dict:
        out = {"N": int(t.get("N", 0))}
        for k in ("base", "roster", "incumbent"):
            if t.get(k):
                out[k] = {x: _f(t[k].get(x)) for x in ("MAE", "RMSE", "bias")}
        for k in ("delta_MAE", "delta_RMSE", "pct_games_improved"):
            if t.get(k) is not None:
                out[k] = _f(t[k])
        ci = t.get("paired_abs_change_ci90_day_bootstrap")
        out["ci90"] = ci if isinstance(ci, list | dict) else None  # only above the locked minimum
        return out

    frozen = S.roles(w.active)
    models = [{"version": v, "role": r, "role_label": S.ROLE_LABEL[r]} for v, r in frozen.items()]
    models += [{"version": f"{v}+roster", "role": S.ROSTER_OVERLAY, "role_label": S.ROLE_LABEL[S.ROSTER_OVERLAY]}
               for v, r in frozen.items() if r == S.SHADOW and v == "pure-0.5.0"]  # fmt: skip
    states: dict[str, int] = {}
    for s_ in sel.values():
        states[s_.state] = states.get(s_.state, 0) + 1
    gate_counts = ((sb.summary.get("gate") or {}).get("counts") or {}) if sb else {}
    return {
        "research_status": "PRESEASON" if not season_live else "IN_SEASON",
        "season": f"{w.season - 1}-{str(w.season)[2:]}",
        "first_game_utc": iso(first) if first is not None else None,
        "games_in_capture_window": in_window, "projection_states": states,
        "models": models,
        "model_note": "pure-0.2.0 is the production incumbent. Challengers run in shadow; P-ROSTER-1 "
                      "is a prospective roster overlay on pure-0.5.0. No model is called better before "
                      "the preregistered evaluation (after the 2027 national championship game).",
        "prospective": {
            "scoreboard_stamp": sb.stamp if sb else None, "scoreboard_path": sb.path if sb else None,
            "protocol": (sb.summary.get("protocol") if sb else None),
            "versions": (sb.summary.get("versions") if sb else None),
            "game_1": slim(g1), "game_2": slim(head.get("game_2") or {"N": 0}),
            "game_3": slim(head.get("game_3") or {"N": 0}),
            "gate": gate_counts, "note": sb.summary.get("note") if sb else None,
            "min_n_for_inference": 20, "min_days_for_inference": 10,
            "inference_allowed": int(g1.get("N", 0)) >= 20,
        },
        "roster_readiness": {"counts": counts, "snapshot": w.truth.stamp if w.truth else None,
                             "snapshot_at": stamp_iso(w.truth.stamp) if w.truth else None,
                             "continuity_audit": (w.truth.audit.get("_summary") if w.truth else None)},
        "schedule": {"d1_games": int(len(g)), "sdv_games": w.schedule_report.get("sdv_games"),
                     "fallback_games": w.schedule_report.get("fallback_games"),
                     "reconciled_games": (w.schedule_report.get("reconciliation") or {}).get("reconciled_games"),
                     "excluded": len(w.schedule_report.get("excluded") or []),
                     "observed_at": w.schedule_observed_at},
        "markets": {"published": len(markets), "captured_at": w.kalshi.captured_at if w.kalshi else None,
                    "note": None if markets else "Market research is not published for CBB yet."},
        "capabilities": {
            "schedule": "AVAILABLE", "team_projections": "AVAILABLE" if season_live else "WAITING_FOR_WINDOW",
            "score_projection": "AVAILABLE", "margin_projection": "AVAILABLE",
            "total_projection": "AVAILABLE", "win_probability": "AVAILABLE",
            "opponent_adjusted_ratings": "AVAILABLE" if any(c.record.get("ratings") for s_ in sel.values() for c in s_.chosen.values()) else "WAITING_FOR_WINDOW",
            "roster_truth": "AVAILABLE" if w.truth else "UNAVAILABLE",
            "expected_rotation": "AVAILABLE_WHERE_VALID" if w.truth else "UNAVAILABLE",
            "prospective_evaluation": "AVAILABLE" if sb else "UNAVAILABLE",
            "player_props": "UNAVAILABLE", "recommendations": "UNAVAILABLE", "bets": "UNAVAILABLE",
            "game_scripting": "UNAVAILABLE",
            "live_kalshi_quotes": "AVAILABLE" if markets else "UNAVAILABLE",
        },
        "provenance": {"code_sha": w.code_sha, **{k: v for k, v in w.commits.items()},
                       "last_prospective_run": w.manifests[-1] if w.manifests else None},
    }  # fmt: skip
