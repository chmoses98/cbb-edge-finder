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


def espn_at(espn: pd.DataFrame, clock: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """ESPN rows as the scoreboard would show them at ``now`` (time announcements,
    game state)."""
    e = espn.copy()
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
    """Silver for the current season from this run's completed schedule (the production
    path: the completion file, then ``silver.build_season``), other seasons unchanged."""
    fb = frame[frame["schedule_source"] == sc.ESPN_FALLBACK]
    p = sc.completion_path(SEASON)
    p.parent.mkdir(parents=True, exist_ok=True)
    fb.to_parquet(p, index=False)
    sdv_rows = frame[frame["schedule_source"] == sc.SDV].drop(columns=sc.PROV_COLS)
    bronze = data_dir() / "bronze" / silver.BRONZE / silver.local_rel("schedules", SEASON)
    sdv_rows.to_parquet(bronze, index=False)
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    prev = g[g["season"] == SEASON - 1]
    prev_d1 = set(prev.loc[prev["home_is_d1"], "home_espn_id"].astype(int)) | set(
        prev.loc[prev["away_is_d1"], "away_espn_id"].astype(int))  # fmt: skip
    g27, _, _ = silver.build_season(SEASON, prev_d1)
    g = pd.concat([g[g["season"] != SEASON], g27], ignore_index=True)
    for c in ("tournament_id", "venue_id", "home_conference_id", "away_conference_id", "periods"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g.to_parquet(data_dir() / "silver" / "games.parquet", index=False)


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
                 "synthetic outcomes, never research evidence"}  # fmt: skip
    sdv0 = pd.read_parquet(
        data_dir() / "bronze" / silver.BRONZE / silver.local_rel("schedules", SEASON)
    )
    espn = sc.latest(sc.load_rows(a.schedule_archive))
    espn = espn[pd.to_numeric(espn["season"], errors="coerce") == SEASON].reset_index(drop=True)
    d1 = set(membership.members(SEASON)["team_id"].dropna())
    from cbb_edge.data.ids.teams import canonical_from_espn_in

    def is_d1(e: object) -> bool:
        return e is not None and e == e and canonical_from_espn_in(int(e), SEASON) in d1

    day = pd.to_datetime(espn["start_date"], utc=True).dt.tz_convert(ss.ET).dt.date.astype(str)
    espn_w = espn[(day >= WIN[0]) & (day <= WIN[1])]
    sday = pd.to_datetime(sdv0["start_date"], utc=True).dt.tz_convert(ss.ET).dt.date.astype(str)
    sdv_w = sdv0[(sday >= WIN[0]) & (sday <= WIN[1])]
    known = pd.concat(
        [espn_w[["game_id", "home_id", "away_id"]], sdv_w[["game_id", "home_id", "away_id"]]]
    )
    known = known.drop_duplicates("game_id")
    known = known[known["home_id"].map(is_d1) & known["away_id"].map(is_d1)]
    known_ids = set(known["game_id"].astype(int))
    clock = sim_clock(pd.concat([espn, as_sdv(sdv0[~sdv0["game_id"].isin(espn["game_id"])], sdv0)
                                 .assign(observed_at=pd.Timestamp("2026-10-06T00:00Z"))], ignore_index=True))  # fmt: skip
    fb_ids0 = set(espn["game_id"]) - set(sdv0["game_id"])
    sdv_t2 = pd.concat([sdv0, as_sdv(espn[espn["game_id"].isin(fb_ids0) & espn["game_id"].map(
        lambda g: clock.loc[g, "actual"] > T2)], sdv0)], ignore_index=True)  # fmt: skip
    rep["universe"] = {"known_d1_games_nov1_9": len(known_ids),
                       "in_sdv_at_start": len(known_ids & set(sdv0["game_id"].astype(int))),
                       "espn_only_at_start": len(known_ids - set(sdv0["game_id"].astype(int))),
                       "sdv_catch_up_at_T2": T2.isoformat(),
                       "games_sdv_adds_at_T2": int(len(sdv_t2) - len(sdv0))}  # fmt: skip

    arch = new_archive(a.sandbox / "w11")
    runs = []
    for k, now in enumerate(slots()[: a.max_runs]):
        sdv_now = sdv_t2 if now >= T2 else sdv0
        e_now = espn_at(espn, clock, now)
        frame, crep = sc.complete(sdv_now, e_now, SEASON)
        rebuild_2027(frame)
        live = live_obs(e_now[pd.to_datetime(e_now["start_date"], utc=True)
                              <= now + pd.Timedelta(hours=40)])  # fmt: skip
        stage = a.sandbox / f"stage_{k}"
        out, failed = project_all(SEASON, now, 30.0, stage, str(a.rosters), None, SHA,
                                  "dryrosterarchivecommit", None, live, sc.source_map(frame))  # fmt: skip
        written = 0
        for f in sorted(stage.rglob("*")):
            if not f.is_file():
                continue
            dst = arch / "projections" / f.relative_to(stage)
            if dst.exists():
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
        runs.append({"now": now.isoformat(), "fallback_rows": crep["fallback_games"],
                     "excluded": len(crep["excluded"]), "files": written,
                     "window": out.get("_schedule_window"), "failed": failed,
                     "records_from_fallback": (out.get("_schedule_sources") or {}).get(
                         "records_from_espn_fallback_games")})  # fmt: skip
        print(json.dumps(runs[-1], default=str), flush=True)
    rep["runs"] = runs

    # settlement: SYNTHETIC finals through the production results path
    recs = ps.load_records(arch, SEASON)
    rng = np.random.default_rng(5)
    final_e = espn_at(espn, clock, SETTLE)
    margins = {}
    for i, r in final_e.iterrows():
        if r["status_type_completed"]:
            m, t = rng.normal(0, 12), 140 + rng.normal(0, 15)
            final_e.at[i, "home_score"], final_e.at[i, "away_score"] = (
                round((t + m) / 2),
                round((t - m) / 2),
            )
            margins[int(r["game_id"])] = final_e.at[i, "home_score"] - final_e.at[i, "away_score"]
    sdv_final = sdv_t2.copy()
    for i, r in sdv_final.iterrows():
        g = int(r["game_id"])
        if g in margins:
            x = final_e[final_e["game_id"] == g].iloc[0]
            for c in ("home_score", "away_score", "status_type_name", "status_type_state",
                      "status_type_completed", "start_date", "date", "time_valid"):  # fmt: skip
                sdv_final.at[i, c] = x[c]
    sdv_final = sc._as_sdv_types(sdv_final, sdv0)
    frame_f, _ = sc.complete(sdv_final, final_e, SEASON)
    res, sched = results_and_schedule(frame_f)
    sched = sched.copy()
    sched["tip"] = [clock.loc[g, "actual"] if g in clock.index else t
                    for g, t in zip(sched["espn_game_id"], sched["tip"], strict=True)]  # fmt: skip
    sched["time_state"] = [ss.ANNOUNCED if g in clock.index and clock.loc[g, "announce_at"] is not None
                           and pd.notna(clock.loc[g, "announce_at"]) or s0 == ss.ANNOUNCED else s0
                           for g, s0 in zip(sched["espn_game_id"], sched["time_state"], strict=True)]  # fmt: skip
    win_ids = known_ids
    exp = sched[sched["espn_game_id"].isin(win_ids) & (sched["tip"] < SETTLE)][["espn_game_id"]]
    obs = ss.load_obs(arch / "projections")
    frames, summ = ps.score(recs, res, None, a.rosters, None,
                            sched[["espn_game_id", "home_team_id", "away_team_id", "tip", "time_state"]],
                            SEASON, d1, committed=ps.git_first_commit_times(arch),
                            committed_roster=ps.git_first_commit_times(a.rosters),
                            projections_root=arch, expected=exp, schedule_obs=obs)  # fmt: skip
    gate = frames["integrity_gate"]
    gate = gate[gate["espn_game_id"].isin(win_ids)]
    src_now = frame_f.set_index("game_id")["schedule_source"]
    base = [r for r in recs if r["model"]["version"] == ps.BASE]
    rost = [r for r in recs if r["model"]["version"] == ps.ROSTER]
    proj_src = {}
    for r in base:
        proj_src.setdefault(int(r["game"]["espn_game_id"]), set()).add(
            (r.get("schedule") or {}).get("source")
        )
    started_violations = [
        r["game"]["espn_game_id"] for r in recs
        if int(r["game"]["espn_game_id"]) in clock.index
        and pd.Timestamp(r["prospective"]["as_of"]) >= clock.loc[int(r["game"]["espn_game_id"]), "actual"]]  # fmt: skip
    mutated = git(arch, "log", "--diff-filter=MD", "--name-only", "--format=").split()
    pg = frames["paired_games"]
    pgw = pg[pg["espn_game_id"].isin(win_ids)] if len(pg) else pg
    sdv_ids0 = set(sdv0["game_id"].astype(int))

    def by_src(ids: set[int]) -> dict[str, int]:
        return {"SDV_native": len(ids & sdv_ids0), "ESPN_fallback_at_start": len(ids - sdv_ids0)}

    stages = {
        "known_d1_games": by_src(win_ids),
        "in_completed_schedule": by_src(win_ids & set(frame_f["game_id"].astype(int))),
        "projected_base": by_src(win_ids & {int(r["game"]["espn_game_id"]) for r in base}),
        "projected_p_roster_1": by_src(win_ids & {int(r["game"]["espn_game_id"]) for r in rost}),
        "settled": by_src(win_ids & set(res["espn_game_id"].astype(int))),
        "gate_valid": by_src(set(gate.loc[gate["status"] == "VALID", "espn_game_id"].astype(int))),
        "scored_pairs": by_src(set(pgw.loc[pgw["gate_status"] == "VALID", "espn_game_id"].astype(int)))
        if len(pgw) else {},
    }  # fmt: skip
    switched = {g for g, s in proj_src.items() if {"ESPN_FALLBACK", "SDV"} <= s}
    rep["stages"] = stages
    rep["gate"] = gate["status"].value_counts().to_dict()
    rep["gate_reasons"] = gate.loc[gate["reasons"] != "", "reasons"].value_counts().to_dict()
    rep["not_valid"] = gate.loc[gate["status"] != "VALID"].head(30).to_dict("records")
    rep["catch_up"] = {
        "games_projected_from_fallback_then_sdv": len(switched),
        "their_paired_rows": int(pgw["espn_game_id"].isin(switched).sum()) if len(pgw) else 0,
        "paired_rows_unique_per_game": bool(pgw["espn_game_id"].is_unique) if len(pgw) else True,
        "schedule_source_now_for_switched": src_now.reindex(sorted(switched)).value_counts().to_dict(),
        "archived_files_mutated_or_deleted": mutated,
        "fallback_records_keep_provenance": all(
            "ESPN_FALLBACK" in proj_src[g] for g in switched),
        "schedule_rows_archived": len(list((arch / "projections").rglob("schedule_rows/*.jsonl"))),
    }  # fmt: skip
    rep["tbd"] = {
        "records_made_at_or_after_actual_tip": len(started_violations),
        "tbd_games_known": int(sum(1 for g in win_ids if g in clock.index
                                   and clock.loc[g, "announce_at"] is None) +
                               sum(1 for g in win_ids if g in clock.index
                                   and clock.loc[g, "announce_at"] is not None
                                   and pd.notna(clock.loc[g, "announce_at"]))),
        "never_announced_games": int(sum(1 for g in win_ids if g in clock.index
                                         and pd.isna(clock.loc[g, "announce_at"])
                                         and not bool(espn.set_index("game_id")["time_valid"].get(g, True)))),
    }  # fmt: skip
    rep["scorer"] = {"game_1_N": (summ.get("primary") or {}).get("game_1", {}).get("N")}
    return rep


if __name__ == "__main__":
    main()
