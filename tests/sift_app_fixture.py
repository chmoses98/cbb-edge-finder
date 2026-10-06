"""Synthetic archive checkouts for the CBB app publisher (TEST DATA ONLY).

Builds a projections archive, a roster-truth snapshot, a prospective scoreboard and a
completed schedule in the exact on-disk shapes production writes (records through
``cbb_edge.app.sift`` dataclasses + the ``prospective`` / ``schedule`` / ``roster`` blocks
``scripts/prospective/refresh_and_project.py`` and ``rosters/overlay.py`` stamp), for real
D-I teams. Numbers are synthetic. Nothing here is ever published to ``app-data``.

    python -m tests.sift_app_fixture --variant season --out /tmp/cbb-fixture

writes ``<out>/app/latest`` (used by Sift's end-to-end tests) plus the archives under
``<out>/archives``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from cbb_edge.app.sift import (
    Freshness,
    GameRef,
    ModelRef,
    Projection,
    SiftProjection,
    TeamRatings,
    TeamRef,
    validate,
)

SEASON = 2027
SYNTHETIC = "SYNTHETIC TEST FIXTURE — not real CBB data"
NOW_SEASON = "2026-11-02T18:00:00Z"
NOW_PRESEASON = "2026-10-20T15:00:00Z"
VERSIONS = ["pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0"]
ROSTER_V = "pure-0.5.0+roster"
TEAMS = {  # team_id: (espn id, display name, location, abbreviation)
    "T0014": (26, "UCLA Bruins", "UCLA", "UCLA"), "T0213": (2250, "Gonzaga Bulldogs", "Gonzaga", "GONZ"),
    "T0147": (314, "Iona Gaels", "Iona", "IONA"), "T0208": (2230, "Fordham Rams", "Fordham", "FOR"),
    "T0175": (2057, "Belmont Bruins", "Belmont", "BEL"), "T0197": (2181, "Drake Bulldogs", "Drake", "DRKE"),
    "T0128": (275, "Wisconsin Badgers", "Wisconsin", "WIS"), "T0161": (356, "Illinois Fighting Illini", "Illinois", "ILL"),
    "T0069": (150, "Duke Blue Devils", "Duke", "DUKE"), "T0220": (2305, "Kansas Jayhawks", "Kansas", "KU"),
    "T0123": (261, "Vermont Catamounts", "Vermont", "UVM"), "T0021": (43, "Yale Bulldogs", "Yale", "YALE"),
    "T0106": (235, "Memphis Tigers", "Memphis", "MEM"), "T0112": (248, "Houston Cougars", "Houston", "HOU"),
    "T0303": (2633, "Tennessee Volunteers", "Tennessee", "TENN"), "T0031": (57, "Florida Gators", "Florida", "FLA"),
    "T0215": (2272, "High Point Panthers", "High Point", "HPU"), "T0226": (2335, "Liberty Flames", "Liberty", "LIB"),
    "T0270": (2509, "Purdue Boilermakers", "Purdue", "PUR"), "T0019": (41, "UConn Huskies", "UConn", "CONN"),
    "T0045": (87, "Notre Dame Fighting Irish", "Notre Dame", "ND"), "T0100": (222, "Villanova Wildcats", "Villanova", "VILL"),
    "T0047": (96, "Kentucky Wildcats", "Kentucky", "UK"), "T0072": (153, "North Carolina Tar Heels", "North Carolina", "UNC"),
    "T0155": (333, "Alabama Crimson Tide", "Alabama", "ALA"), "T0001": (2, "Auburn Tigers", "Auburn", "AUB"),
    "T0329": (2752, "Xavier Musketeers", "Xavier", "XAV"), "T0126": (269, "Marquette Golden Eagles", "Marquette", "MARQ"),
}  # fmt: skip
CONFIDENCE = {"T0123": "STALE", "T0106": "CONFLICTED", "T0147": "LIKELY", "T0175": "UNKNOWN"}
STRENGTH = {  # synthetic team strength (points per 100 above average), tempo
    "T0220": (14, 69), "T0069": (16, 68), "T0128": (9, 63), "T0161": (11, 70), "T0175": (2, 70),
    "T0197": (5, 64), "T0123": (3, 62), "T0021": (1, 66), "T0106": (8, 71), "T0112": (15, 63),
    "T0303": (13, 64), "T0031": (12, 70), "T0215": (1, 68), "T0226": (4, 65), "T0270": (13, 66),
    "T0019": (15, 66), "T0045": (6, 66), "T0100": (7, 65), "T0047": (11, 71), "T0072": (10, 72),
    "T0155": (12, 74), "T0001": (13, 70), "T0329": (8, 68), "T0126": (10, 69), "T0014": (11, 66),
    "T0213": (14, 70), "T0147": (0, 69), "T0208": (-2, 67),
}  # fmt: skip
FIRST = ["Jalen", "Marcus", "Tyler", "Isaiah", "Caleb", "Darius", "Ethan", "Malik", "Owen", "Jordan",
         "Elijah", "Cam"]  # fmt: skip
LAST = ["Brooks", "Carter", "Ellis", "Foster", "Hayes", "Jenkins", "Mitchell", "Porter", "Reed",
        "Sutton", "Turner", "Wallace"]  # fmt: skip

# scenario: (espn id, away, home, start UTC, time_valid, state, completed, scores, neutral,
#            source, reconciled, versions, venue)
GAMES = [
    (900000001, "T0014", "T0213", "2026-11-07T03:00:00Z", True, "pre", False, None, False, "SDV", [], [], "McCarthey Athletic Center"),
    (900000002, "T0147", "T0208", "2026-11-08T05:00:00Z", False, "pre", False, None, False, "SDV", [], [], "Rose Hill Gym"),
    (900000003, "T0175", "T0197", "2026-11-03T00:00:00Z", True, "pre", False, None, False, "SDV", [], ["pure-0.2.0"], "Knapp Center"),
    (900000004, "T0128", "T0161", "2026-11-03T01:00:00Z", True, "pre", False, None, False, "SDV", [], VERSIONS, "State Farm Center"),
    (900000005, "T0069", "T0220", "2026-11-03T01:30:00Z", True, "pre", False, None, False, "SDV", [], VERSIONS + [ROSTER_V], "Allen Fieldhouse"),
    (900000006, "T0123", "T0021", "2026-11-02T23:30:00Z", True, "pre", False, None, False, "SDV", [], VERSIONS + [ROSTER_V], "John J. Lee Amphitheater"),
    (900000007, "T0106", "T0112", "2026-11-03T02:00:00Z", True, "pre", False, None, False, "SDV", [], VERSIONS + [ROSTER_V], "Fertitta Center"),
    (900000008, "T0031", "T0303", "2026-11-03T02:30:00Z", True, "pre", False, None, True, "SDV", [], ["pure-0.2.0", "pure-0.5.0"], "Spectrum Center"),
    (900000009, "T0215", "T0226", "2026-11-03T04:59:00Z", True, "pre", False, None, True, "ESPN_FALLBACK", [], VERSIONS, "Liberty Arena"),
    (900000010, "T0270", "T0019", "2026-11-03T00:30:00Z", True, "pre", False, None, False, "SDV", ["teams"], VERSIONS, "Gampel Pavilion"),
    (900000011, "T0045", "T0100", "2026-11-01T14:30:00Z", True, "post", True, (68, 71), True, "SDV", [], VERSIONS + [ROSTER_V], "Palazzo dello Sport"),
    (900000012, "T0047", "T0072", "2026-11-02T00:00:00Z", True, "post", True, (80, 77), False, "SDV", ["teams"], VERSIONS + [ROSTER_V], "Dean E. Smith Center"),
    (900000013, "T0155", "T0001", "2026-11-02T01:00:00Z", True, "post", True, (84, 90), False, "SDV", [], [], "Neville Arena"),
    (900000014, "T0329", "T0126", "2026-11-03T16:00:00Z", True, "pre", False, None, False, "SDV", [], [], "Fiserv Forum"),
]  # fmt: skip


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def ratings(t: str, shift: float = 0.0) -> TeamRatings:
    s, tempo = STRENGTH[t]
    base = 105.0
    k = (s + shift) / 15.0
    return TeamRatings(
        adj_off=base + 0.55 * (s + shift), adj_def=base - 0.45 * (s + shift), adj_tempo=float(tempo),
        four_factors={"efg_off": 50 + 3 * k, "efg_def": 50 - 2.5 * k, "to_off": 17 - 1.5 * k,
                      "to_def": 17 + 1.2 * k, "orb_off": 30 + 2 * k, "orb_def": 30 - 2 * k,
                      "ftr_off": 32 + 2 * k, "ftr_def": 32 - 2 * k, "fg2_off": 51 + 3 * k,
                      "fg2_def": 51 - 3 * k, "fg3_off": 34 + 1.5 * k, "fg3_def": 34 - 1.2 * k,
                      "fg3a_rate_off": 38 + (tempo - 67) * 0.3, "fg3a_rate_def": 38.5},
    )  # fmt: skip


def record(gid: int, away: str, home: str, start: str, neutral: bool, version: str, as_of: str,
           *, source: str = "SDV", reconciled: list[str] | None = None, shift: float = 0.0,
           live: dict | None = None) -> dict[str, Any]:  # fmt: skip
    vi = VERSIONS.index(version) if version in VERSIONS else 3
    sh, sa = STRENGTH[home][0], STRENGTH[away][0]
    poss = (STRENGTH[home][1] + STRENGTH[away][1]) / 2.0
    margin = (sh - sa) * poss / 100.0 + (0.0 if neutral else 3.2) + 0.35 * vi + shift
    total = 2 * poss * 1.06 + 0.4 * vi
    hs, as_ = (total + margin) / 2, (total - margin) / 2
    import math

    wp = 1 / (1 + math.exp(-0.155 * margin))
    rec = SiftProjection(
        game=GameRef(f"G{gid}", gid, SEASON, pd.Timestamp(start).isoformat(),
                     "neutral" if neutral else "home"),
        home=TeamRef(home, TEAMS[home][0], TEAMS[home][1], None),
        away=TeamRef(away, TEAMS[away][0], TEAMS[away][1], None),
        projection=Projection(poss, hs / poss, as_ / poss, hs, as_, margin, total, wp,
                              11.6 - 0.1 * vi, 17.5),
        model=ModelRef("cbb-pure", version, "PURE", "research"),
        freshness=Freshness(pd.Timestamp(as_of).isoformat(), 0, 0, 0, ["sportsdataverse_releases"]),
        ratings={"home": ratings(home), "away": ratings(away)},
        generated_at=pd.Timestamp(as_of).isoformat(),
    ).to_dict()  # fmt: skip
    rec["prospective"] = {
        "as_of": pd.Timestamp(as_of).isoformat(), "code_version": "0.2.0", "code_sha": "ebe89a7b2e85ea81bd21bb93be289612a6baf8aa",
        "model_sha256": hashlib.sha256(version.encode()).hexdigest(),
        "reconstruction": {"mode": "checkpoint", "boundary": 2026},
        "role": "incumbent" if version == "pure-0.2.0" else "challenger",
        "spread_cover_prob_fn": "Phi((margin - line) / margin_sd)",
    }  # fmt: skip
    rec["schedule"] = {"source": source, "source_observed_at": "2026-10-30T06:00:00+00:00" if source != "SDV" or reconciled else None,
                       "reconciled_fields": reconciled or [], "reconciliation": None,
                       "listed_start": rec["game"]["start_time_utc"], "window": "listed", "live": live}  # fmt: skip
    validate(rec)
    return rec


def rotation(t: str, n: int = 10) -> list[dict[str, Any]]:
    mins = [34.1, 32.5, 30.2, 28.0, 25.4, 18.6, 14.1, 9.8, 5.2, 2.1][:n]
    cls = ["returning", "transfer", "returning", "first_d1", "transfer", "returning", "first_d1",
           "transfer", "first_d1", "returning"]  # fmt: skip
    out = []
    for i, m in enumerate(mins):
        out.append({"player_id": f"P9{t[1:]}{i:02d}", "share": round(m / 40, 4), "class": cls[i],
                    "minutes": m, "p_rotation": 0.9 if m > 15 else 0.4, "expected_starter": i < 5,
                    "usage_role": "primary" if i < 5 else "role"})  # fmt: skip
    return out


def roster_block(rec: dict, stamp: str, *, confs: dict[str, str]) -> dict[str, Any]:
    sides = {}
    adj_b = 0.0
    for side in ("home", "away"):
        t = rec[side]["team_id"]
        conf = confs.get(t, "CONFIRMED")
        trusted = conf in ("CONFIRMED", "LIKELY", "CONFLICTED")
        corr = conf == "CONFIRMED"
        sides[side] = {
            "team_id": t, "roster_confidence": conf, "games_seen": 0, "overlay_applied": trusted,
            "continuity_correction_applied": corr, "expected_returning_share": 0.48,
            "truth_cont": 0.41 if trusted else None, "tr_prev": 1.2, "first_d1": 3.0,
            "proj_min_returning": 92.0, "proj_min_transfer": 71.0, "proj_min_unseen": 37.0,
            "expected_rotation": [{k: p[k] for k in ("player_id", "share", "minutes", "class")}
                                  for p in rotation(t, 8)] if trusted else [],
            "player_block_off": None,
        }  # fmt: skip
        if corr:
            adj_b += 0.8 if side == "home" else -0.5
    base = rec["projection"]["margin"]
    a = 0.6 if any(s["overlay_applied"] for s in sides.values()) else 0.0
    m = base + a + adj_b
    p = rec["projection"]
    p["margin"] = m
    p["home_score"], p["away_score"] = (p["total"] + m) / 2, (p["total"] - m) / 2
    import math

    p["home_win_prob"] = 1 / (1 + math.exp(-0.155 * m))
    return {"component": "P-ROSTER-1 (PROSPECTIVE_ONLY)", "spec_sha256": "f" * 64, "truth_snapshot": stamp,
            "margin_base": base, "total_base": p["total"], "adjustment_a_input_substitution": a,
            "adjustment_b_continuity": adj_b, "adjustment_total": a + adj_b,
            "uncertainty_margin_sd": p["margin_sd"], "sides": sides,
            "truth_archive_commit": "f20c13b5e2d5a560734b4cf5a34b3be91f8a805d",
            "truth_files_sha256": {"truth_records": "0" * 64}}  # fmt: skip


def write_truth(root: Path, stamp: str, *, variant: str = "a") -> None:
    d = root / "truth" / stamp[:4] / stamp[4:6] / stamp[6:8]
    teams, prs, recs, san = [], [], [], []
    for t in TEAMS:
        conf = CONFIDENCE.get(t, "CONFIRMED")
        teams.append({"team_id": t, "n_listed": 15, "n_confirmed": 13 if conf == "CONFIRMED" else 0,
                      "n_likely": 13 if conf == "LIKELY" else 0, "n_conflicted": 1 if conf == "CONFLICTED" else 0,
                      "n_stale": 2 if conf != "STALE" else 15, "n_unknown": 0, "n_returning": 6,
                      "n_returning_after_gap": 0, "n_transfer": 5, "n_first_d1": 4,
                      "n_class_label_conflict": 1, "fresh_groups": ["espn", "school"] if conf == "CONFIRMED" else (["espn"] if conf in ("LIKELY", "CONFLICTED") else []),
                      "n_dropped": 2, "official_identity_coverage": 1.0 if conf != "UNKNOWN" else 0.4,
                      "roster_confidence": conf,
                      "confidence_reason": {"CONFIRMED": "independent_fresh_groups", "LIKELY": "single_fresh_group",
                                            "CONFLICTED": "independent_fresh_groups", "STALE": "no_fresh_majority",
                                            "UNKNOWN": "official_roster_unidentified"}[conf]})  # fmt: skip
        rot = rotation(t)
        if variant == "b":  # a LATER capture changes the rotation: earlier records must not follow
            rot = [
                dict(p, minutes=round(p["minutes"] * 0.5, 1)) if i == 0 else p
                for i, p in enumerate(rot)
            ]
        prs.append({"team_id": t, "as_of": stamp, "roster_confidence": conf, "truth_cont": 0.41,
                    "tr_prev": 1.2, "first_d1": 3.0, "proj_min_returning": 92.0,
                    "proj_min_transfer": 71.0, "proj_min_unseen": 37.0, "expected_rotation": rot})  # fmt: skip
        san.append({"team_id": t, "minutes_total": 200.0, "n_players": 10, "n_rotation_10min": 7,
                    "starters": 5, "ok": conf != "STALE"})  # fmt: skip
        for i, p in enumerate(rot):
            recs.append({"player_id": p["player_id"], "team_id": t, "name": f"{FIRST[i]} {LAST[(i + int(t[1:])) % 12]}",
                         "classification": p["class"], "position": "GFC"[i % 3],
                         "last_team": "T0147" if p["class"] == "transfer" else None,
                         "status": "CONFIRMED"})  # fmt: skip
    _w(d / f"{stamp}_teams.json", json.dumps(teams))
    _w(d / f"{stamp}_proster_state.json", json.dumps(prs))
    _w(d / f"{stamp}_records.jsonl", "".join(json.dumps(r) + "\n" for r in recs))
    _w(d / f"{stamp}_rotation_sanity.jsonl", "".join(json.dumps(r) + "\n" for r in san))
    allrows = [{"team_id": t, "adjustment": round(((int(t[1:]) % 9) - 4) * 0.7, 2),
                "expected_returning_share": 0.48, "truth_returning_share": 0.41}
               for t in TEAMS if CONFIDENCE.get(t, "CONFIRMED") == "CONFIRMED"]  # fmt: skip
    _w(d / f"{stamp}_continuity_audit.json", json.dumps({"confirmed_teams": len(allrows), "mean": -0.3,
                                                         "median": -0.2, "abs_max": 2.8, "large": [],
                                                         "all": allrows}))  # fmt: skip


def schedule_frame(variant: str) -> pd.DataFrame:
    rows = []
    for gid, away, home, start, tv, state, done, sc, neu, src, rec, _v, venue in GAMES:
        if variant == "preseason":
            state, done, sc = "pre", False, None
        ts = pd.Timestamp(start)
        rows.append({
            "game_id": gid, "season": SEASON, "season_type": 2, "date": ts.strftime("%Y-%m-%dT%H:%MZ"),
            "start_date": ts.strftime("%Y-%m-%dT%H:%MZ"), "time_valid": tv, "neutral_site": neu,
            "conference_competition": False, "tournament_id": None,
            "notes_headline": "Eternal City Tip-Off" if gid == 900000011 else "",
            "venue_id": 1.0, "venue_full_name": venue, "venue_address_city": "Rome" if gid == 900000011 else "City",
            "venue_address_state": "Italy" if gid == 900000011 else "ST",
            "home_id": TEAMS[home][0], "away_id": TEAMS[away][0],
            "home_location": TEAMS[home][2], "away_location": TEAMS[away][2],
            "home_conference_id": 1.0, "away_conference_id": 2.0,
            "home_score": sc[1] if sc else 0, "away_score": sc[0] if sc else 0,
            "status_period": 2.0 if done else 0.0,
            "status_type_name": "STATUS_FINAL" if done else "STATUS_SCHEDULED",
            "status_type_state": state, "status_type_completed": done,
            "status_type_short_detail": "Final" if done else ("TBD" if not tv else ts.strftime("%m/%d - %I:%M %p")),
            "home_logo": f"https://a.espncdn.com/i/teamlogos/ncaa/500/{TEAMS[home][0]}.png",
            "away_logo": f"https://a.espncdn.com/i/teamlogos/ncaa/500/{TEAMS[away][0]}.png",
            "schedule_source": src, "source_observed_at": "2026-10-30T06:00:00+00:00" if src != "SDV" or rec else None,
            "reconciled_fields": json.dumps(rec) if rec else "",
            "reconciliation": json.dumps({"_teams": {"kind": "orientation_swap"}}) if rec else "",
        })  # fmt: skip
    return pd.DataFrame(rows)


def build_archives(out: Path, variant: str = "season") -> dict[str, Any]:
    out = Path(out)
    arch = out / "archives"
    pa, ra, sa, sc = (arch / x for x in ("projections-archive", "roster-archive", "schedule-archive",
                                         "prospective-scores"))  # fmt: skip
    s1, s2 = "20261101T120000Z", "20261102T160000Z"
    write_truth(ra, "20261015T120000Z")
    if variant == "season":
        write_truth(ra, s1)
        write_truth(ra, s2, variant="b")  # captured AFTER the 14:10 records below
    files = {}
    if variant == "season":
        for gid, away, home, start, _tv, _st, done, _sc, neu, src, rec_, versions, _ven in GAMES:
            tip = pd.Timestamp(start)
            as_of = (tip - pd.Timedelta(hours=16)).floor("h") + pd.Timedelta(minutes=10)
            for v in versions:
                base_v = v.replace("+roster", "")
                h, a = (
                    (away, home) if gid == 900000012 else (home, away)
                )  # 12: matchup later swapped
                r = record(
                    gid, a, h, start, neu, base_v, as_of.isoformat(), source=src, reconciled=rec_
                )
                if v == ROSTER_V:
                    r["model"]["version"] = ROSTER_V
                    r["prospective"]["role"] = "challenger_roster_overlay"
                    snap = (
                        s1 if as_of > pd.Timestamp(s1) else "20261015T120000Z"
                    )  # truth before as_of
                    r["roster"] = roster_block(r, snap, confs=CONFIDENCE)
                files.update(_put(pa, r))
                if gid == 900000011 and v == "pure-0.2.0":
                    late = record(
                        gid,
                        a,
                        h,
                        start,
                        neu,
                        v,
                        (tip + pd.Timedelta(hours=2)).isoformat(),
                        source=src,
                        shift=25.0,
                    )  # a POST-TIP record: never shown
                    files.update(_put(pa, late))
        _w(pa / "projections" / "manifests" / "20261102T141000Z.json",
           json.dumps({"as_of": "2026-11-02T14:10:00+00:00", "code_sha": "ebe89a7b2e85ea81bd21bb93be289612a6baf8aa",
                       "roster_archive_commit": "f20c13b5e2d5a560734b4cf5a34b3be91f8a805d", "files": files}))  # fmt: skip
    else:
        _w(pa / "projections" / "manifests" / "20261020T141000Z.json",
           json.dumps({"as_of": "2026-10-20T14:10:00+00:00", "code_sha": "ebe89a7b2e85ea81bd21bb93be289612a6baf8aa",
                       "roster_archive_commit": "f20c13b5e2d5a560734b4cf5a34b3be91f8a805d", "files": {}}))  # fmt: skip
    stamp = "2026-11-02T170000Z" if variant == "season" else "2026-10-20T143000Z"
    d = sc / "scores" / "2026" / stamp[5:7] / stamp
    if variant == "season":
        g1 = {"N": 24, "base": {"MAE": 8.41, "RMSE": 10.62, "bias": -0.37, "log_loss": 0.55},
              "roster": {"MAE": 8.12, "RMSE": 10.31, "bias": -0.11, "log_loss": 0.54},
              "incumbent": {"MAE": 8.77, "RMSE": 11.02, "bias": 0.42, "log_loss": 0.56},
              "delta_MAE": -0.29, "delta_RMSE": -0.31, "pct_games_improved": 0.54,
              "paired_abs_change_ci90_day_bootstrap": None}  # fmt: skip
        summary = {"note": SYNTHETIC, "synthetic": True, "settled_paired_games": 24,
                   "headline": {"game_1": g1, "game_2": {"N": 0}, "game_3": {"N": 0}},
                   "gate": {"enforced": True, "counts": {"VALID": 24, "UNSCORABLE": 1},
                            "reasons": {"schedule_identity_changed": 1}},
                   "versions": {"base": "pure-0.5.0", "incumbent": "pure-0.2.0", "roster": ROSTER_V},
                   "protocol": "research/hypotheses/WAVE7.md section 7 (locked)"}  # fmt: skip
        _w(d / "integrity_gate.csv", "espn_game_id,status,reasons\n900000011,VALID,\n"
           "900000012,UNSCORABLE,schedule_identity_changed\n900000013,UNSCORABLE,"
           "no_pre_tip_record:pure-0.5.0;no_pre_tip_record:pure-0.5.0+roster\n")  # fmt: skip
    else:
        summary = {"note": "no settled game with both base and P-ROSTER-1 pregame records yet",
                   "settled_paired_games": 0, "gate": {"enforced": True, "counts": {}, "reasons": {}},
                   "versions": {"base": "pure-0.5.0", "incumbent": "pure-0.2.0", "roster": ROSTER_V},
                   "protocol": "research/hypotheses/WAVE7.md section 7 (locked)"}  # fmt: skip
    _w(d / "summary.json", json.dumps(summary))
    _w(sc / "LATEST", f"scores/2026/{stamp[5:7]}/{stamp}\n")
    obs = "20261102T170000Z" if variant == "season" else "20261020T140000Z"
    _w(sa / "obs" / obs[:4] / obs[4:6] / obs[6:8] / f"{obs}_espn_scoreboard.jsonl", "")
    sched = arch / "schedule.parquet"
    schedule_frame(variant).to_parquet(sched, index=False)
    _w(sched.with_suffix(".report.json"), json.dumps({
        "season": SEASON, "sdv_games": 13, "fallback_games": 1, "excluded": [],
        "reconciliation": {"reconciled_games": 2}}))  # fmt: skip
    return {"projections": pa, "rosters": ra, "scores": sc, "schedule_archive": sa,
            "schedule_parquet": sched, "now": NOW_SEASON if variant == "season" else NOW_PRESEASON}  # fmt: skip


def _put(pa: Path, r: dict) -> dict[str, str]:
    v = r["model"]["version"]
    stamp = r["prospective"]["as_of"].replace(":", "").replace("+0000", "Z")
    base = pa / "projections" if v == "pure-0.2.0" else pa / "projections" / v.replace("+", "_")
    rel = (
        Path(str(SEASON))
        / r["game"]["start_time_utc"][:10]
        / r["game"]["game_id"]
        / f"{stamp}.json"
    )
    blob = json.dumps(r, sort_keys=True, allow_nan=False)
    _w(base / rel, blob)
    key = str((base / rel).relative_to(pa / "projections"))
    return {key: hashlib.sha256(blob.encode()).hexdigest()}


def publish_fixture(out: Path, variant: str = "season") -> dict[str, Any]:
    from cbb_edge.app.sift_app.__main__ import main

    a = build_archives(out, variant)
    argv = ["--season", str(SEASON), "--projections", str(a["projections"]), "--rosters", str(a["rosters"]),
            "--scores", str(a["scores"]), "--schedule-archive", str(a["schedule_archive"]),
            "--schedule-parquet", str(a["schedule_parquet"]), "--out", str(Path(out) / "app" / "latest"),
            "--now", a["now"], "--code-sha", "fixture000000"]  # fmt: skip
    rc = main(argv)
    if rc != 0:
        raise RuntimeError("fixture publication failed")
    return a


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["season", "preseason"], default="season")
    ap.add_argument("--out", required=True)
    x = ap.parse_args()
    publish_fixture(Path(x.out), x.variant)
