"""Wave 11 FULL OPENING-WINDOW DRY RUN (Nov 1-9, 2026): SDV-native and ESPN-fallback
games through the whole production chain (sandbox; synthetic outcomes; never evidence).

    python scripts/prospective/dry_run_w11.py --rosters <roster-archive> \
        --schedule-archive <schedule-archive> --sandbox DIR

* The schedule universe is the REAL current one: the SDV 2026-27 file plus the archived
  ESPN rows (``schedule-archive``), completed by ``cbb_edge.ops.schedule_completion``.
* Every regular projection slot from Oct 31 21:10 to Nov 9 21:10 UTC runs the
  PRODUCTION step (``refresh_and_project.project_all``: every active version +
  P-ROSTER-1, the Wave 10 live game-state window, Wave 11 provenance) into a sandbox
  git repository that plays ``projections-archive`` (commit time = simulated push).
* Simulated clock: each TBD game gets a SYNTHETIC actual tip (seeded); 70 % of them are
  "announced" two days before. Live observations at every run follow that clock (pre
  until the actual tip, then in progress / final), so a started game is never projected.
* SDV catch-up (J): at ``T2`` SDV "publishes" every fallback game tipping after T2, in
  SDV's own flattening of the same ESPN payload; later runs read SDV for them.
* Settlement: SYNTHETIC finals (pure noise) through the production results path
  (``score_proster.results_and_schedule`` on the completed final schedule), then the
  prospective scorer + pre-tip gate (``prospective_score.score``).

Synthetic outcomes exist only to drive the code: nothing here is research evidence and
nothing is written to a production archive. Writes ``<sandbox>/dry_run_w11_report.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "prospective"))

from dry_run import git, new_archive  # noqa: E402
from refresh_and_project import project_all  # noqa: E402
from score_proster import results_and_schedule  # noqa: E402

from cbb_edge.data.http import data_dir  # noqa: E402
from cbb_edge.data.silver import build as silver  # noqa: E402
from cbb_edge.ops import schedule_completion as sc  # noqa: E402
from cbb_edge.ops import schedule_state as ss  # noqa: E402
from cbb_edge.rosters import membership  # noqa: E402
from cbb_edge.rosters import prospective_score as ps  # noqa: E402

SEASON = 2027
WIN = ("2026-11-01", "2026-11-09")  # ET dates
T2 = pd.Timestamp("2026-11-04T12:00:00Z")  # SDV catches up
SETTLE = pd.Timestamp("2026-11-10T12:40:00Z")
SHA = "drysha0000000000000000000000000000000000"


def slots() -> list[pd.Timestamp]:
    out, t = [], pd.Timestamp("2026-10-31T21:10:00Z")
    while t <= pd.Timestamp("2026-11-09T21:10:00Z"):
        out.append(t)
        t += pd.Timedelta(hours=7) if t.hour == 14 else pd.Timedelta(hours=17)
    return out


def sim_clock(espn: pd.DataFrame, seed: int = 11) -> pd.DataFrame:
    """Per game: actual tip and when (if ever) a TBD time gets announced (SYNTHETIC)."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in espn.to_dict("records"):
        listed = pd.Timestamp(r["start_date"]).tz_convert("UTC")
        if bool(r["time_valid"]):
            rows.append({"game_id": r["game_id"], "actual": listed, "announce_at": None})
            continue
        day = listed.tz_convert(ss.ET).normalize()
        actual = (day + pd.Timedelta(hours=int(rng.integers(12, 22)))).tz_convert("UTC")
        ann = actual - pd.Timedelta(days=2) if rng.random() < 0.7 else None
        rows.append({"game_id": r["game_id"], "actual": actual, "announce_at": ann})
    return pd.DataFrame(rows).set_index("game_id")


def espn_at(espn: pd.DataFrame, clock: pd.DataFrame, now: pd.Timestamp,
            stale: dict[int, tuple[pd.Timestamp, dict]] | None = None) -> pd.DataFrame:  # fmt: skip
    """ESPN rows as the scoreboard would show them at ``now`` (time announcements,
    game state; ``stale``: game id -> (until, fields) an earlier matchup ESPN showed
    before ``until``)."""
    e = espn.copy()
    for g, (until, fields) in (stale or {}).items():
        if now < until:
            for c, v in fields.items():
                e.loc[e["game_id"] == g, c] = v
    for i, r in e.iterrows():
        c = clock.loc[r["game_id"]]
        if c["announce_at"] is not None and pd.notna(c["announce_at"]) and now >= c["announce_at"]:
            e.at[i, "start_date"] = e.at[i, "date"] = c["actual"].strftime("%Y-%m-%dT%H:%MZ")
            e.at[i, "time_valid"] = True
            e.at[i, "status_type_short_detail"] = "7:00 PM EST"
        if now >= c["actual"]:
            done = now >= c["actual"] + pd.Timedelta(hours=2)
            e.at[i, "status_type_name"] = "STATUS_FINAL" if done else "STATUS_IN_PROGRESS"
            e.at[i, "status_type_state"] = "post" if done else "in"
            e.at[i, "status_type_completed"] = bool(done)
    e["observed_at"] = now + pd.Timedelta(minutes=1)
    return e


def live_obs(e: pd.DataFrame) -> list[dict]:
    return [{"espn_game_id": int(r["game_id"]), "observed_at": r["observed_at"].isoformat(),
             "source": "espn_scoreboard", "start_utc": pd.Timestamp(r["start_date"]).isoformat(),
             "date_et": pd.Timestamp(r["start_date"]).tz_convert(ss.ET).date().isoformat(),
             "time_valid": bool(r["time_valid"]),
             "time_state": ss.time_state(bool(r["time_valid"]), r["start_date"],
                                         r["status_type_short_detail"]),
             "state": r["status_type_state"], "status_name": r["status_type_name"],
             "short_detail": r["status_type_short_detail"], "home_espn": int(r["home_id"]),
             "away_espn": int(r["away_id"])} for r in e.to_dict("records")]  # fmt: skip


def as_sdv(rows: pd.DataFrame, sdv: pd.DataFrame) -> pd.DataFrame:
    """SDV's own flattening of the same ESPN rows (SDV columns + dtypes)."""
    x = sc._as_sdv_types(rows[sc.ROW_COLS].copy(), sdv)
    for c in sdv.columns:
        if c not in x:
            x[c] = None
    return x[sdv.columns]


def rebuild_2027(frame: pd.DataFrame) -> None:
    """Silver for the current season from this run's completed schedule, through the
    production path (the completion file read by ``silver.load_schedule``)."""
    p = sc.completion_path(SEASON)
    p.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(p, index=False)
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    prev = g[g["season"] == SEASON - 1]
    prev_d1 = set(prev.loc[prev["home_is_d1"], "home_espn_id"].astype(int)) | set(
        prev.loc[prev["away_is_d1"], "away_espn_id"].astype(int))  # fmt: skip
    g27, _, _ = silver.build_season(SEASON, prev_d1)
    g = pd.concat([g[g["season"] != SEASON], g27], ignore_index=True)
    for c in ("tournament_id", "venue_id", "home_conference_id", "away_conference_id", "periods"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g.to_parquet(data_dir() / "silver" / "games.parquet", index=False)


def copy_stage(stage: Path, arch: Path, now: pd.Timestamp) -> tuple[int, int]:
    """The workflow's append step: copy new files only, never overwrite, commit at push."""
    written = skipped = 0
    for f in sorted(stage.rglob("*")):
        if not f.is_file():
            continue
        dst = arch / "projections" / f.relative_to(stage)
        if dst.exists():
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        written += 1
    shutil.rmtree(stage)
    if written:
        git(arch, "add", "-A")
        git(
            arch,
            "commit",
            "-q",
            "-m",
            f"run {now}",
            when=(now + pd.Timedelta(minutes=6)).isoformat(),
        )
    return written, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rosters", type=Path, required=True)
    ap.add_argument("--schedule-archive", type=Path, required=True)
    ap.add_argument("--sandbox", type=Path, required=True)
    ap.add_argument("--max-runs", type=int, default=99)
    a = ap.parse_args()
    if a.sandbox.exists():
        shutil.rmtree(a.sandbox)
    a.sandbox.mkdir(parents=True)
    # the local working copies this dry run overwrites, restored at the end
    sil = data_dir() / "silver" / "games.parquet"
    bronze = data_dir() / "bronze" / silver.BRONZE / silver.local_rel("schedules", SEASON)
    backup = {sil: sil.read_bytes(), bronze: bronze.read_bytes()}
    comp_p = sc.completion_path(SEASON)
    try:
        rep = run(a)
    finally:
        for p, b in backup.items():
            p.write_bytes(b)
        comp_p.unlink(missing_ok=True)
        comp_p.with_suffix(".report.json").unlink(missing_ok=True)
    txt = json.dumps(rep, indent=1, default=str)
    (a.sandbox / "dry_run_w11_report.json").write_text(txt)
    print(txt)


def run(a: argparse.Namespace) -> dict:
    rep: dict = {"note": "SYNTHETIC DRY RUN - production code, simulated clock, sandbox archive; "
                 "synthetic outcomes and synthetic schedule staleness, never research evidence"}  # fmt: skip
    sdv_real = pd.read_parquet(
        data_dir() / "bronze" / silver.BRONZE / silver.local_rel("schedules", SEASON)
    )
    espn = sc.latest(sc.load_rows(a.schedule_archive))
    espn = espn[pd.to_numeric(espn["season"], errors="coerce") == SEASON].reset_index(drop=True)
    d1 = set(membership.members(SEASON)["team_id"].dropna())
    from cbb_edge.data.ids.teams import canonical_from_espn_in

    known = sc.canonical_universe(sdv_real, espn, SEASON, WIN[0], WIN[1], d1)
    known_ids = set(known["game_id"].astype(int))
    sdv_ids = set(sdv_real["game_id"].astype(int))
    frame0, rep0 = sc.complete(sdv_real, espn, SEASON)
    f0 = frame0.set_index("game_id")
    clock = sim_clock(pd.concat([espn, as_sdv(sdv_real[~sdv_real["game_id"].isin(espn["game_id"])], sdv_real)
                                 .assign(observed_at=pd.Timestamp("2026-10-06T00:00Z"))], ignore_index=True))  # fmt: skip

    # ---------------- scenarios (deterministic picks inside the canonical universe)
    def recf(g: int) -> list[str]:
        v = f0.loc[g, "reconciled_fields"] if g in f0.index else ""
        return json.loads(v) if v else []

    sdv_in = sorted(known_ids & sdv_ids)
    exact = [g for g in sdv_in if not recf(g) and bool(f0.loc[g, "time_valid"])]
    # D-I teams with no game on a given ET date (a "stale opponent" that collides with nothing)
    day_of = {int(g): known.set_index("game_id").loc[g, "date_et"] for g in known_ids}
    playing: dict[str, set[int]] = {}
    for r in frame0.to_dict("records"):
        d = sc._et_date(r["start_date"])
        playing.setdefault(d, set()).update({int(r["home_id"]), int(r["away_id"])})
    d1_espn = sorted({int(e) for e in pd.concat([frame0["home_id"], frame0["away_id"]]).dropna()
                      if int(e) > 0 and canonical_from_espn_in(int(e), SEASON) in d1})  # fmt: skip
    used_spare: set[int] = set()

    def spare(g: int) -> int:
        d = day_of[g]
        busy = playing.get(d, set()) | playing.get(str((pd.Timestamp(d) - pd.Timedelta(days=1)).date()), set()) \
            | playing.get(str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()), set())  # fmt: skip
        t = next(x for x in d1_espn if x not in busy and x not in used_spare)
        used_spare.add(t)
        return t

    sc_ = {}
    sc_["pure_sdv_no_disagreement"] = exact[0]
    sc_["sdv_tip_fresher_on_espn"] = next(g for g in sdv_in if "tip" in recf(g))
    sw = [g for g in sdv_in if "teams" in recf(g)
          and json.loads(f0.loc[g, "reconciliation"])["_teams"]["kind"] == "orientation_swap"]  # fmt: skip
    if sw:
        sc_["sdv_home_away_disagreement (real)"] = sw[0]
    tr = [g for g in sdv_in if "tournament_id" in recf(g)]
    if tr:
        sc_["sdv_tournament_id_fresher (real)"] = tr[0]
    sdv0 = sdv_real.copy()
    inj = {"sdv_opponent_change (SDV stale)": exact[1], "sdv_neutral_site_stale": exact[2],
           "sdv_conference_flag_stale": exact[3]}  # fmt: skip
    ix = {int(g): i for i, g in zip(sdv0.index, sdv0["game_id"], strict=True)}
    g = inj["sdv_opponent_change (SDV stale)"]
    sdv0.at[ix[g], "away_id"] = spare(g)
    sdv0.at[ix[g], "away_location"] = "Stale Opponent"
    g = inj["sdv_neutral_site_stale"]
    sdv0.at[ix[g], "neutral_site"] = not bool(sdv0.at[ix[g], "neutral_site"])
    g = inj["sdv_conference_flag_stale"]
    sdv0.at[ix[g], "conference_competition"] = not bool(sdv0.at[ix[g], "conference_competition"])
    sc_.update(inj)
    fb_in = sorted(known_ids - sdv_ids)
    sc_["espn_fallback_game"] = fb_in[0]
    tbd_in = [
        g
        for g in sorted(known_ids)
        if not bool(espn.set_index("game_id")["time_valid"].get(g, True))
    ]
    sc_["tbd_game"] = tbd_in[0]
    # matchups that change on ESPN over time (SDV keeps the stale one): before any
    # projection, between two pre-tip projections, after the last pre-tip projection
    sl = slots()
    stale: dict[int, tuple[pd.Timestamp, dict]] = {}
    ann = [
        g
        for g in exact[4:]
        if pd.Timestamp(f0.loc[g, "start_date"]) > pd.Timestamp("2026-11-03T00:00Z")
    ]

    def pre_slots(g: int) -> list[pd.Timestamp]:
        tip = clock.loc[g, "actual"]
        return [t for t in sl if tip - pd.Timedelta(hours=30) < t < tip]

    y1 = ann[0]
    y2 = next(g for g in ann[1:] if len(pre_slots(g)) >= 2)
    y3 = next(g for g in ann[1:] if g != y2 and len(pre_slots(g)) >= 1)
    for g, until in (
        (y1, sl[0] - pd.Timedelta(hours=1)),  # corrected before any run
        (y2, pre_slots(y2)[-1] - pd.Timedelta(minutes=30)),  # between runs
        (y3, clock.loc[y3, "actual"] - pd.Timedelta(minutes=30)),
    ):  # after last run
        t = spare(g)
        stale[g] = (until, {"away_id": t, "away_location": "Stale Opponent"})
        sdv0.at[ix[g], "away_id"] = t  # SDV still lists the old matchup
        sdv0.at[ix[g], "away_location"] = "Stale Opponent"
    sc_["matchup_changes_before_any_projection"] = y1
    sc_["matchup_changes_after_a_projection_snapshot"] = y2
    sc_["matchup_changes_after_the_last_pre_tip_projection"] = y3
    sdv0 = sc._as_sdv_types(sdv0, sdv_real)

    fb_ids0 = known_ids - sdv_ids | (set(espn["game_id"]) - sdv_ids)
    sdv_t2 = pd.concat([sdv0, as_sdv(espn[espn["game_id"].isin(fb_ids0) & espn["game_id"].map(
        lambda g: clock.loc[g, "actual"] > T2)], sdv0)], ignore_index=True)  # fmt: skip
    rep["universe"] = {"canonical_known_d1_games_nov1_9_et": len(known_ids),
                       "in_sdv_at_start": len(known_ids & sdv_ids),
                       "espn_only_at_start": len(known_ids - sdv_ids),
                       "includes_401920686_uconn_wagner": 401920686 in known_ids,
                       "sdv_catch_up_at_T2": T2.isoformat(),
                       "games_sdv_adds_at_T2": int(len(sdv_t2) - len(sdv0))}  # fmt: skip

    arch = new_archive(a.sandbox / "w11")
    runs = []
    for k, now in enumerate(sl[: a.max_runs]):
        sdv_now = sdv_t2 if now >= T2 else sdv0
        e_now = espn_at(espn, clock, now, stale)
        frame, crep = sc.complete(sdv_now, e_now, SEASON)
        rebuild_2027(frame)
        live = live_obs(
            e_now[pd.to_datetime(e_now["start_date"], utc=True) <= now + pd.Timedelta(hours=40)]
        )
        stage = a.sandbox / f"stage_{k}"
        out, failed = project_all(SEASON, now, 30.0, stage, str(a.rosters), None, SHA,
                                  "dryrosterarchivecommit", None, live, sc.source_map(frame))  # fmt: skip
        written, _ = copy_stage(stage, arch, now)
        r = crep.get("reconciliation") or {}
        runs.append({"now": now.isoformat(), "fallback_rows": crep["fallback_games"],
                     "reconciled_sdv_rows": r.get("reconciled_games"), "files": written,
                     "window": out.get("_schedule_window"), "failed": failed,
                     "sources": out.get("_schedule_sources")})  # fmt: skip
        print(json.dumps(runs[-1], default=str), flush=True)
        if k == 3:  # duplicate workflow execution: the same slot again, same inputs
            stage = a.sandbox / f"stage_{k}_dup"
            project_all(SEASON, now, 30.0, stage, str(a.rosters), None, SHA,
                        "dryrosterarchivecommit", None, live, sc.source_map(frame))  # fmt: skip
            w2, s2 = copy_stage(stage, arch, now)
            rep["duplicate_execution"] = {"slot": now.isoformat(), "files_written": w2,
                                          "files_skipped_existing": s2}  # fmt: skip
    rep["runs"] = runs

    # settlement: SYNTHETIC finals through the production results path
    recs = ps.load_records(arch, SEASON)
    rng = np.random.default_rng(5)
    final_e = espn_at(espn, clock, SETTLE, stale)
    for i, r in final_e.iterrows():
        if r["status_type_completed"]:
            m, t = rng.normal(0, 12), 140 + rng.normal(0, 15)
            final_e.at[i, "home_score"], final_e.at[i, "away_score"] = (
                round((t + m) / 2),
                round((t - m) / 2),
            )
    fin = final_e.set_index("game_id")
    sdv_final = sdv_t2.copy()
    for i, r in sdv_final.iterrows():
        g = int(r["game_id"])
        if g in fin.index and fin.loc[g, "status_type_completed"]:
            for c in ("home_score", "away_score", "status_type_name", "status_type_state",
                      "status_type_completed", "start_date", "date", "time_valid"):  # fmt: skip
                sdv_final.at[i, c] = fin.loc[g, c]
    sdv_final = sc._as_sdv_types(sdv_final, sdv0)
    frame_f, rep_f = sc.complete(sdv_final, final_e, SEASON)
    res, sched = results_and_schedule(frame_f)
    sched = sched.copy()
    sched["tip"] = [clock.loc[g, "actual"] if g in clock.index else t
                    for g, t in zip(sched["espn_game_id"], sched["tip"], strict=True)]  # fmt: skip
    sched["time_state"] = [ss.ANNOUNCED if g in clock.index and pd.notna(clock.loc[g, "announce_at"])
                           or s0 == ss.ANNOUNCED else s0
                           for g, s0 in zip(sched["espn_game_id"], sched["time_state"], strict=True)]  # fmt: skip
    exp = sched[sched["espn_game_id"].isin(known_ids) & (sched["tip"] < SETTLE)][["espn_game_id"]]
    obs = ss.load_obs(arch / "projections")
    frames, summ = ps.score(recs, res, None, a.rosters, None,
                            sched[["espn_game_id", "home_team_id", "away_team_id", "tip", "time_state"]],
                            SEASON, d1, committed=ps.git_first_commit_times(arch),
                            committed_roster=ps.git_first_commit_times(a.rosters),
                            projections_root=arch, expected=exp, schedule_obs=obs)  # fmt: skip
    gate = frames["integrity_gate"]
    gate = gate[gate["espn_game_id"].isin(known_ids)]
    gi = gate.set_index("espn_game_id")
    base = [r for r in recs if r["model"]["version"] == ps.BASE]
    rost = [r for r in recs if r["model"]["version"] == ps.ROSTER]
    pg = frames["paired_games"]
    pgw = pg[pg["espn_game_id"].isin(known_ids)] if len(pg) else pg

    def by_src(ids: set[int]) -> dict[str, int]:
        return {"SDV_native": len(ids & sdv_ids), "ESPN_fallback_at_start": len(ids - sdv_ids),
                "total": len(ids)}  # fmt: skip

    rep["stages"] = {
        "canonical_known": by_src(known_ids),
        "in_completed_schedule": by_src(known_ids & set(frame_f["game_id"].astype(int))),
        "projected_base": by_src(known_ids & {int(r["game"]["espn_game_id"]) for r in base}),
        "projected_p_roster_1": by_src(known_ids & {int(r["game"]["espn_game_id"]) for r in rost}),
        "settled": by_src(known_ids & set(res["espn_game_id"].astype(int))),
        "gate_valid": by_src(set(gate.loc[gate["status"] == "VALID", "espn_game_id"].astype(int))),
        "scored_pairs": by_src(set(pgw.loc[pgw["gate_status"] == "VALID", "espn_game_id"].astype(int))),
    }  # fmt: skip
    rep["gate"] = gate["status"].value_counts().to_dict()
    rep["not_valid"] = gate.loc[gate["status"] != "VALID"].to_dict("records")
    recs_by = {}
    for r in base:
        recs_by.setdefault(int(r["game"]["espn_game_id"]), []).append(r)
    rep["scenarios"] = {}
    for name, g in sc_.items():
        rs = sorted(recs_by.get(g, []), key=lambda r: r["prospective"]["as_of"])
        rep["scenarios"][name] = {
            "espn_game_id": g, "schedule_source_at_start": "SDV" if g in sdv_ids else "ESPN_FALLBACK",
            "base_records": len(rs),
            "record_matchups": [f"{r['home']['team_id']} v {r['away']['team_id']}" for r in rs],
            "record_reconciled_fields": sorted({f for r in rs for f in (r.get("schedule") or {}).get("reconciled_fields", [])}),
            "record_sources": sorted({(r.get("schedule") or {}).get("source") or "" for r in rs}),
            "final_matchup": " v ".join(map(str, sched.set_index("espn_game_id").loc[g, ["home_team_id", "away_team_id"]])),
            "gate": None if g not in gi.index else gi.loc[g, "status"],
            "reason": None if g not in gi.index else gi.loc[g, "reasons"],
        }  # fmt: skip
    proj_src = {}
    for r in base:
        proj_src.setdefault(int(r["game"]["espn_game_id"]), set()).add(
            (r.get("schedule") or {}).get("source")
        )
    switched = {g for g, v in proj_src.items() if {"ESPN_FALLBACK", "SDV"} <= v}
    rep["catch_up"] = {
        "games_projected_from_fallback_then_sdv": len(switched),
        "paired_rows_unique_per_game": bool(pgw["espn_game_id"].is_unique) if len(pgw) else True,
        "their_gate": gi.reindex(sorted(switched))["status"].value_counts().to_dict(),
        "archived_files_mutated_or_deleted": git(arch, "log", "--diff-filter=MD", "--name-only", "--format=").split(),
        "schedule_rows_files": len(list((arch / "projections").rglob("schedule_rows/*.jsonl"))),
    }  # fmt: skip
    rep["tbd"] = {
        "tbd_games_in_universe": len(tbd_in),
        "never_announced": sum(1 for g in tbd_in if pd.isna(clock.loc[g, "announce_at"])),
        "records_made_at_or_after_actual_tip": sum(
            1 for r in recs if int(r["game"]["espn_game_id"]) in clock.index
            and pd.Timestamp(r["prospective"]["as_of"]) >= clock.loc[int(r["game"]["espn_game_id"]), "actual"]),
    }  # fmt: skip
    rep["final_reconciliation"] = {k: (v if not isinstance(v, list) else len(v))
                                   for k, v in (rep_f.get("reconciliation") or {}).items()}  # fmt: skip
    return rep


if __name__ == "__main__":
    main()
