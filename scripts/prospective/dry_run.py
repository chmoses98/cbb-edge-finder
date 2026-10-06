"""Wave 9 opening-day DRY RUN of the whole production chain (sandbox; never evidence).

    python scripts/prospective/dry_run.py --rosters <roster-archive checkout> --sandbox DIR

Runs the PRODUCTION code with a simulated clock against the real 2026-27 schedule and
the real archived roster truth, into a sandbox git repository that plays the
append-only ``projections-archive`` branch (commit times = simulated push times):

    schedule discovery -> pre-tip projection run(s) (``refresh_and_project.project_all``:
    every active version + P-ROSTER-1, run manifest) -> archive commit -> game settles
    (SYNTHETIC result + box score, seeded) -> prospective scorer + pre-tip gate ->
    scoreboard

then the operational scenarios (each on a copy of the sandbox): simultaneous games,
postponed, cancelled, no usable roster overlay, non-D-I opponent, West Florida,
neutral site, box score late, box score corrected, duplicate workflow execution,
retry after partial failure, archived file mutated, scorer idempotence.

The synthetic results exist only to drive the code. Nothing here is research
evidence, nothing is tuned from it, and nothing is written to a production archive.
Prints and writes ``<sandbox>/dry_run_report.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "prospective"))

from refresh_and_project import project_all  # noqa: E402

from cbb_edge.data.bronze.sportsdataverse import local_rel  # noqa: E402
from cbb_edge.data.http import data_dir  # noqa: E402
from cbb_edge.data.ids.teams import canonical_from_espn_in  # noqa: E402
from cbb_edge.data.silver.build import BRONZE  # noqa: E402
from cbb_edge.rosters import membership, pretip_gate  # noqa: E402
from cbb_edge.rosters import prospective_score as ps  # noqa: E402

SEASON = 2027
OPEN_RUNS = ("2026-11-01T21:10:00Z", "2026-11-02T14:10:00Z")
SETTLE = "2026-11-03T12:40:00Z"
WFL_RUN, WFL_SETTLE = "2027-01-15T21:10:00Z", "2027-01-17T12:40:00Z"


def ts(x: str) -> pd.Timestamp:
    return pd.Timestamp(x).tz_convert("UTC")


# ---------------------------------------------------------------- sandbox archive
def git(repo: Path, *a: str, when: str | None = None) -> str:
    env = dict(os.environ)
    if when:
        env |= {"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True,
                          text=True, env=env).stdout  # fmt: skip


def new_archive(root: Path) -> Path:
    arch = root / "projections-archive"
    arch.mkdir(parents=True)
    git(arch, "init", "-q")
    git(arch, "config", "user.email", "dry-run@example.invalid")
    git(arch, "config", "user.name", "dry-run")
    (arch / "README.md").write_text("SYNTHETIC DRY RUN SANDBOX - NOT RESEARCH EVIDENCE\n")
    git(arch, "add", "-A")
    git(arch, "commit", "-q", "-m", "init", when="2026-10-06T00:00:00Z")
    return arch


def projection_run(arch: Path, now: str, rosters: Path | None, *, push_delay_min: int = 6,
                   commit: bool = True) -> dict:  # fmt: skip
    """One production projection run at simulated ``now`` + the workflow's append step
    (copy new files only, refuse to overwrite, commit at push time)."""
    stage = arch.parent / f"stage_{now.replace(':', '')}_{np.random.default_rng().integers(1e9)}"
    out, failed = project_all(SEASON, ts(now), 30.0, stage, str(rosters) if rosters else None,
                              None, "drysha0000000000000000000000000000000000",
                              "dryrosterarchivecommit")  # fmt: skip
    written = skipped = 0
    for f in sorted(stage.rglob("*.json")):
        dst = arch / "projections" / f.relative_to(stage)
        if dst.exists():
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        written += 1
    shutil.rmtree(stage)
    if commit and written:
        git(arch, "add", "-A")
        push = (ts(now) + pd.Timedelta(minutes=push_delay_min)).isoformat()
        git(arch, "commit", "-q", "-m", f"prospective projections {now}", when=push)
    return {"now": now, "models": out, "failed": failed, "files_written": written,
            "files_skipped_existing": skipped}  # fmt: skip


# ----------------------------------------------------------------------- schedule
def schedule() -> pd.DataFrame:
    p = data_dir() / "bronze" / BRONZE / local_rel("schedules", SEASON)
    s = pd.read_parquet(p)
    out = pd.DataFrame({
        "espn_game_id": s["game_id"].astype(int),
        "home_espn": s["home_id"].astype("Int64"), "away_espn": s["away_id"].astype("Int64"),
        "home_team_id": [canonical_from_espn_in(e, SEASON) for e in s["home_id"]],
        "away_team_id": [canonical_from_espn_in(e, SEASON) for e in s["away_id"]],
        "home_name": s["home_location"], "away_name": s["away_location"],
        "tip": pd.to_datetime(s["start_date"], utc=True),
        "neutral": s["neutral_site"].fillna(False).astype(bool),
        "status": s["status_type_name"],
    })  # fmt: skip
    return out


def settle(sched: pd.DataFrame, recs: list[dict], until: pd.Timestamp, rosters: Path,
           skip: set[int] = frozenset(), seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:  # fmt: skip
    """SYNTHETIC results and box scores (seeded) for games that tipped before ``until``
    and have a base record. Box: the truth snapshot's CONFIRMED / LIKELY players of each
    team (played) + one never-listed player, minutes summing to 200."""
    base = {r["game"]["espn_game_id"]: r for r in recs if r["model"]["version"] == ps.BASE}
    done = sched[(sched["tip"] < until) & sched["espn_game_id"].isin(base)
                 & ~sched["espn_game_id"].isin(skip)
                 & ~sched["status"].isin(["STATUS_CANCELED", "STATUS_POSTPONED"])]  # fmt: skip
    rng = np.random.default_rng(seed)
    res, box = [], []
    tr = sorted((rosters / "truth").rglob("*_records.jsonl"))[-1]
    on = pd.read_json(tr, lines=True, dtype={"player_id": str})
    on = on[on["status"].isin(["CONFIRMED", "LIKELY"]) & on["player_id"].notna()]
    for g in done.itertuples(index=False):
        m = base[g.espn_game_id]["projection"]["margin"] + rng.normal(0, 11)
        tot = base[g.espn_game_id]["projection"]["total"] + rng.normal(0, 15)
        res.append({"espn_game_id": g.espn_game_id, "result_margin": float(round(m)),
                    "result_total": float(round(tot))})  # fmt: skip
        for t in (g.home_team_id, g.away_team_id):
            pl = on.loc[on["team_id"] == t, "player_id"].tolist()[:12] or [f"X{t}"]
            w = rng.dirichlet(np.ones(len(pl)))
            for i, (p, x) in enumerate(zip(pl, w, strict=True)):
                box.append({"espn_game_id": g.espn_game_id, "team_id": t, "player_id": p,
                            "minutes": float(200 * x), "starter": i < 5})  # fmt: skip
    return pd.DataFrame(res), pd.DataFrame(box)


def run_scorer(arch: Path, rosters: Path, sched: pd.DataFrame, res: pd.DataFrame,
               box: pd.DataFrame, now: pd.Timestamp, out: Path) -> dict:  # fmt: skip
    recs = ps.load_records(arch, SEASON)
    d1 = set(membership.members(SEASON)["team_id"].dropna())
    exp = sched[sched["home_team_id"].isin(d1) & sched["away_team_id"].isin(d1)
                & (sched["tip"] < now) & ~sched["status"].eq("STATUS_CANCELED")]  # fmt: skip
    frames, s = ps.score(
        recs, res, None, rosters, box, sched[["espn_game_id", "home_team_id", "away_team_id", "tip"]],
        SEASON, d1, committed=ps.git_first_commit_times(arch),
        committed_roster=ps.git_first_commit_times(rosters), projections_root=arch,
        expected=exp[["espn_game_id"]],
    )  # fmt: skip
    ps.write(out, frames, s, now.strftime("%Y%m%dT%H%M%SZ"))
    g = frames["integrity_gate"]
    return {"summary": s, "gate": g, "frames": frames}


def digest(d: Path) -> dict[str, str]:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest()[:16] for f in sorted(d.iterdir())}


# ----------------------------------------------------------------------- scenarios
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rosters", type=Path, required=True)
    ap.add_argument("--sandbox", type=Path, required=True)
    a = ap.parse_args()
    if a.sandbox.exists():
        shutil.rmtree(a.sandbox)
    a.sandbox.mkdir(parents=True)
    rep: dict = {"note": "SYNTHETIC DRY RUN - production code, simulated clock, sandbox "
                 "archive; results are synthetic and never research evidence"}  # fmt: skip
    sched = schedule()
    d1 = set(membership.members(SEASON)["team_id"].dropna())

    # 1. opening day: two scheduled pre-tip runs, then settlement, then the scorer
    arch = new_archive(a.sandbox / "opening")
    rep["runs"] = [projection_run(arch, t, a.rosters) for t in OPEN_RUNS]
    recs = ps.load_records(arch, SEASON)
    res, box = settle(sched, recs, ts(SETTLE), a.rosters)
    r1 = run_scorer(arch, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "score_1")
    g = r1["gate"]
    win = sched[(sched["tip"] > ts(OPEN_RUNS[0])) & (sched["tip"] <= ts(SETTLE))]
    rep["opening"] = {
        "games_in_window": int(len(win)),
        "d1_vs_d1": int((win["home_team_id"].isin(d1) & win["away_team_id"].isin(d1)).sum()),
        "non_d1_opponent_games_not_projected": win[~(win["home_team_id"].isin(d1)
                                                     & win["away_team_id"].isin(d1))][
            ["home_name", "away_name"]].astype(str).values.tolist(),
        "records": pd.Series([r["model"]["version"] for r in recs]).value_counts().to_dict(),
        "gate": g["status"].value_counts().to_dict(),
        "gate_reasons": g.loc[g["reasons"] != "", "reasons"].value_counts().to_dict(),
        "settled": int(len(res)),
        "game_1_N": r1["summary"].get("primary", {}).get("game_1", {}).get("N", 0),
        "neutral_site_games_valid": int(sched.set_index("espn_game_id").loc[
            g.loc[g["status"] == "VALID", "espn_game_id"], "neutral"].sum()),
        "overlay_confidence_valid": ps.overlay_confidence(
            r1["frames"]["paired_games"][r1["frames"]["paired_games"]["gate_status"] == "VALID"]
        ).value_counts().to_dict() if len(r1["frames"]["paired_games"]) else {},
    }  # fmt: skip
    # idempotence: the same inputs -> byte-identical outputs
    r1b = run_scorer(arch, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "score_1b")
    rep["scorer_idempotent"] = digest(a.sandbox / "score_1") == digest(a.sandbox / "score_1b")
    del r1b

    # 2. duplicate workflow execution (same clock): nothing new, scorer unchanged
    dup = projection_run(arch, OPEN_RUNS[1], a.rosters)
    r2 = run_scorer(arch, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "score_2")
    rep["duplicate_run"] = {"files_written": dup["files_written"],
                            "files_skipped_existing": dup["files_skipped_existing"],
                            "scoreboard_unchanged": digest(a.sandbox / "score_1")
                            == digest(a.sandbox / "score_2")}  # fmt: skip
    del r2

    # 3. box score missing at first, then arrives, then corrected
    r3a = run_scorer(arch, a.rosters, sched, res, box.iloc[0:0], ts(SETTLE), a.sandbox / "s3a")
    box2 = box.copy()
    box2.loc[box2.index[:3], "minutes"] += 1.0
    r3c = run_scorer(arch, a.rosters, sched, res, box2, ts(SETTLE), a.sandbox / "s3c")
    rep["box_late_and_corrected"] = {
        "valid_without_box": r3a["gate"]["status"].eq("VALID").sum().item(),
        "valid_with_box": r1["gate"]["status"].eq("VALID").sum().item(),
        "realized_false_inclusion_without_box": "false_inclusion_realized" in r3a["frames"],
        "realized_false_inclusion_with_box": "false_inclusion_realized" in r1["frames"],
        "game_1_metrics_unchanged_by_box": r3a["summary"].get("primary") == r1["summary"].get("primary")
        == r3c["summary"].get("primary"),
    }  # fmt: skip

    # 4. postponed / cancelled / result missing ("settled game never scores")
    v = r1["gate"].loc[r1["gate"]["status"] == "VALID", "espn_game_id"].tolist()
    if len(v) >= 3:
        s4 = sched.copy()
        s4.loc[s4["espn_game_id"] == v[0], "status"] = "STATUS_POSTPONED"
        s4.loc[s4["espn_game_id"] == v[1], "status"] = "STATUS_CANCELED"
        res4 = res[~res["espn_game_id"].isin(v[:3])]
        r4 = run_scorer(arch, a.rosters, s4, res4, box, ts(SETTLE), a.sandbox / "s4")
        gi = r4["gate"].set_index("espn_game_id")["status"]
        rep["postponed_cancelled_unsettled"] = {
            "postponed": gi.get(v[0], "absent"), "cancelled": gi.get(v[1], "absent"),
            "tipped_but_no_result": gi.get(v[2], "absent"),
        }  # fmt: skip

    # 5. no usable roster overlay: a run without the roster archive -> no P-ROSTER-1
    arch5 = new_archive(a.sandbox / "no_roster")
    projection_run(arch5, OPEN_RUNS[1], None)
    r5 = run_scorer(arch5, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "s5")
    rep["no_roster_overlay"] = {
        "gate": r5["gate"]["status"].value_counts().to_dict(),
        "reasons": r5["gate"]["reasons"].value_counts().head(3).to_dict(),
    }

    # 6. retry after partial failure: run 1 dies before the append step (nothing
    # committed), the retry run succeeds -> VALID, no duplicate, no reconstruction
    arch6 = new_archive(a.sandbox / "retry")
    projection_run(arch6, OPEN_RUNS[0], a.rosters, commit=False)  # crashed before push
    git(arch6, "reset", "-q", "--hard")
    git(arch6, "clean", "-qfd")
    projection_run(arch6, OPEN_RUNS[1], a.rosters)  # the retry / next tick
    r6 = run_scorer(arch6, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "s6")
    rep["retry_after_partial_failure"] = r6["gate"]["status"].value_counts().to_dict()

    # 7. archived file mutated after it was pushed -> INVALID, loudly
    arch7 = a.sandbox / "mutated" / "projections-archive"
    shutil.copytree(arch, arch7)
    f = next(p for p in sorted((arch7 / "projections").rglob("*.json"))
             if "manifests" not in p.parts and "roster" in str(p))  # fmt: skip
    body = json.loads(f.read_text())
    body["projection"]["margin"] += 3.0
    f.write_text(json.dumps(body, sort_keys=True))
    git(arch7, "add", "-A")
    git(arch7, "commit", "-q", "-m", "post-tip edit", when=SETTLE)
    r7 = run_scorer(arch7, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "s7")
    rep["mutated_file"] = r7["gate"].loc[r7["gate"]["status"] == "INVALID", "reasons"].tolist()[:2]

    # 8. a projection run that only happened AFTER tip (missed cron): UNSCORABLE
    arch8 = new_archive(a.sandbox / "missed")
    late = (win["tip"].min() + pd.Timedelta(minutes=30)).isoformat()
    projection_run(arch8, late, a.rosters)
    r8 = run_scorer(arch8, a.rosters, sched, res, box, ts(SETTLE), a.sandbox / "s8")
    rep["missed_pre_tip_run"] = {"run_at": late,
                                 "gate": r8["gate"]["status"].value_counts().to_dict()}  # fmt: skip

    # 9. West Florida (D-I from 2026-27): projected, P-ROSTER-1, settled, scored
    arch9 = new_archive(a.sandbox / "west_florida")
    projection_run(arch9, WFL_RUN, a.rosters)
    rec9 = ps.load_records(arch9, SEASON)
    res9, box9 = settle(sched, rec9, ts(WFL_SETTLE), a.rosters)
    r9 = run_scorer(arch9, a.rosters, sched, res9, box9, ts(WFL_SETTLE), a.sandbox / "s9")
    wfl = [r for r in rec9 if "T0374" in (r["home"]["team_id"], r["away"]["team_id"])]
    gids = {r["game"]["espn_game_id"] for r in wfl}
    rep["west_florida"] = {
        "records": sorted({r["model"]["version"] for r in wfl}),
        "gate": r9["gate"][r9["gate"]["espn_game_id"].isin(gids)]["status"].tolist(),
        "roster_confidence": [r["roster"]["sides"][s]["roster_confidence"] for r in wfl
                              if "roster" in r for s in ("home", "away")
                              if r["roster"]["sides"][s]["team_id"] == "T0374"],
    }  # fmt: skip
    rep["summary_headline_game_1"] = {k: r1["summary"]["primary"]["game_1"].get(k)
                                      for k in ("N",)} if r1["summary"].get("primary") else {}  # fmt: skip
    rep["gate_statuses"] = [pretip_gate.VALID, pretip_gate.INVALID, pretip_gate.UNSCORABLE,
                            pretip_gate.PENDING]  # fmt: skip
    txt = json.dumps(rep, indent=1, default=str)
    (a.sandbox / "dry_run_report.json").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
