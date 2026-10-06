"""Daily prospective run (GitHub Actions): refresh free inputs, rebuild silver, project.

1. completed seasons: cached bulk downloads (FREE_BULK);
2. current season: dated immutable live copies (FREE_BULK);
3. silver games / team_games / player_games, stints, shot profile;
4. current-season PBP player shot zones when an active model needs them (pure-0.5.0+);
5. PURE projections for games in the next ``--horizon-h`` hours -> append-only archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cbb_edge.app.prospective import (
    active_models,
    availability_overlay,
    load_model,
    project_window,
    write_archive,
)
from cbb_edge.availability.overlay import load_overrides
from cbb_edge.data.bronze import sportsdataverse as sdv
from cbb_edge.data.http import data_dir
from cbb_edge.data.silver.build import build as build_silver
from cbb_edge.features.pbp_shots import build as build_pbp_shots
from cbb_edge.features.shot_profile import build as build_shot
from cbb_edge.players.stints import build_season as build_stints

HIST = ("schedules", "team_box", "player_box", "team_crosswalk")
NCAA = ("ncaa_possessions", "ncaa_lineups")


_EVIDENCE: dict[str, dict[str, str | None]] = {}


def evidence_hashes(roster_dir: Path, truth_stamp: str | None) -> dict[str, str | None]:
    """sha256 of the truth snapshot and official-page files a P-ROSTER-1 record used."""
    from cbb_edge.rosters.prospective_score import evidence_files

    if not truth_stamp:
        return {}
    if truth_stamp not in _EVIDENCE:
        _EVIDENCE[truth_stamp] = {
            k: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
            for k, p in evidence_files(roster_dir, truth_stamp).items()
        }
    return _EVIDENCE[truth_stamp]


def write_manifest(out: Path, now: pd.Timestamp, code_sha: str | None,
                   roster_commit: str | None) -> Path | None:  # fmt: skip
    """Wave 9: one manifest per run, ``manifests/<stamp>.json``: sha256 of every record
    this run wrote, committed with them. The scorer's pre-tip gate requires each scored
    record to match its manifest entry (an archived file that later changed fails)."""
    files = {
        str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(out.rglob("*.json"))
        if f.parts[len(out.parts)] != "manifests"
    }
    # written also when no game is in the window: the run's heartbeat (cadence.py)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    p = out / "manifests" / f"{stamp}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"as_of": now.isoformat(), "code_sha": code_sha,
                             "roster_archive_commit": roster_commit, "files": files},
                            indent=1, sort_keys=True))  # fmt: skip
    return p


def project_all(
    season: int,
    now: pd.Timestamp,
    horizon_h: float,
    out_dir: Path,
    roster_dir: str | None,
    availability_dir: str | None,
    code_sha: str | None,
    roster_commit: str | None,
    only: set[tuple[str, int]] | None = None,
    live: list[dict] | None = None,
    sources: dict[int, dict] | None = None,
) -> tuple[dict, dict]:
    """Project every active version for games tipping in (now, now + horizon_h] and
    append them to ``out_dir`` (the production step; also driven by the Wave 9 dry run
    with a simulated clock). Silver must already be built. ``only``: catch-up mode
    (Wave 9) writes just these (version, espn_game_id) records, the ones a missed tick
    left without any pre-tip record. ``live``: this run's live ESPN scoreboard
    observations, fetched AFTER ``now`` (Wave 10): games shown started / postponed /
    cancelled are never projected; TBD-time games whose listed placeholder has passed
    are projected only while positively "pre" (``schedule_state.live_window``). None
    keeps the frozen window rule exactly. ``sources`` (Wave 11): per ESPN game id, the
    schedule source of its silver row (``SDV`` / ``ESPN_FALLBACK``, with the ESPN
    observation time and row for a fallback game), stamped on each record; the fallback
    rows behind this run's records are archived with them (``schedule_rows/``)."""
    from contextlib import nullcontext

    from cbb_edge.app.prospective import window_override
    from cbb_edge.ops import schedule_state

    win = None
    if live is not None:
        g = pd.read_parquet(data_dir() / "silver" / "games.parquet",
                            columns=["season", "game_id", "start_time_utc"])  # fmt: skip
        g = g[g["season"] == season]
        listed = pd.DataFrame({"espn_game_id": g["game_id"].astype(int),
                               "tip": pd.to_datetime(g["start_time_utc"], utc=True)})  # fmt: skip
        win = schedule_state.live_window(live, now, horizon_h, listed)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        p = out_dir / "schedule_obs" / f"{stamp}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(o, sort_keys=True, default=str) + "\n" for o in live))
    lv = {o["espn_game_id"]: o for o in (live or [])}
    used_rows: dict[int, dict] = {}

    def stamp_schedule(rs: list[dict]) -> list[dict]:
        """Provenance only: what the schedule said when this record was made."""
        for r in rs:
            gid = int(r["game"]["espn_game_id"])
            o = lv.get(gid)
            src = (sources or {}).get(gid) or {}
            if src.get("row"):  # fallback or field-reconciled: the ESPN row it used
                used_rows[gid] = src["row"]
            r["schedule"] = {
                "source": src.get("schedule_source", "SDV" if sources is not None else None),
                "source_observed_at": src.get("source_observed_at"),
                "reconciled_fields": src.get("reconciled_fields") or [],
                "reconciliation": src.get("reconciliation"),
                "listed_start": r["game"]["start_time_utc"],
                "window": "tbd_extra" if win and gid in win["extra"] else "listed",
                "live": None if o is None else {k: o[k] for k in (
                    "observed_at", "start_utc", "time_state", "state", "status_name")},
            }  # fmt: skip
        return rs

    def keep(rs: list[dict]) -> list[dict]:
        if only is None:
            return rs
        return [r for r in rs if (r["model"]["version"], int(r["game"]["espn_game_id"])) in only]

    ctx = window_override(win["extra"], win["exclude"]) if win is not None else nullcontext()
    with ctx:
        act = active_models()
        # incumbent + shadow challengers, each from its own frozen artifact; records of one
        # version never touch another's (separate archive paths, append-only)
        out = {}
        failed: dict[str, str] = {}
        for role, version in [("incumbent", act["incumbent"])] + [
            ("challenger", v) for v in act.get("challengers", [])
        ]:
            model = load_model(version)
            try:
                recs = project_window(season, now, horizon_h, model=model)
            except Exception as e:  # a challenger must never block the incumbent or others
                if role == "incumbent":
                    raise
                failed[version] = f"{type(e).__name__}: {e}"
                continue
            for r in recs:
                r["prospective"]["role"] = role
                r["prospective"]["code_sha"] = code_sha  # provenance only (Wave 8)
            out[version] = write_archive(stamp_schedule(keep(recs)), out_dir)
            if (
                role == "challenger"
                and roster_dir
                and "possession" in model.get("extra_blocks", [])
            ):
                from cbb_edge.rosters.overlay import roster_overlay

                try:  # P-ROSTER-1 (PROSPECTIVE_ONLY): base records are never touched
                    ro = roster_overlay(season, now, model, recs, Path(roster_dir), horizon_h)
                    for r in ro:
                        r["prospective"]["role"] = "challenger_roster_overlay"
                        r["prospective"]["code_sha"] = code_sha
                        r["roster"]["truth_archive_commit"] = roster_commit
                        # Wave 9: hashes of the exact pre-tip evidence this record used, so
                        # a later replacement of any snapshot file is detectable
                        r["roster"]["truth_files_sha256"] = evidence_hashes(
                            Path(roster_dir), r["roster"].get("truth_snapshot")
                        )
                    out[f"{version}+roster"] = write_archive(stamp_schedule(keep(ro)), out_dir)
                except Exception as e:  # noqa: BLE001
                    failed[f"{version}+roster"] = f"{type(e).__name__}: {e}"
            if role == "challenger" and availability_dir:
                over, when = load_overrides(Path(availability_dir), now)
                av = availability_overlay(season, now, model, recs, over, when, horizon_h)
                for r in av:
                    r["prospective"]["role"] = "challenger_availability_overlay"
                    r["prospective"]["code_sha"] = code_sha
                out[f"{version}+avail"] = write_archive(
                    stamp_schedule(av) if only is None else [], out_dir
                )
    if win is not None:
        failed_or_note = {"tbd_extra": sorted(win["extra"]), "live_excluded": sorted(win["exclude"]),
                          "unprotected_no_live_evidence": sorted(win["unprotected"])}  # fmt: skip
        out["_schedule_window"] = {k: len(v) for k, v in failed_or_note.items()}
    if used_rows:  # the exact ESPN rows behind this run's fallback records
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        p = out_dir / "schedule_rows" / f"{stamp}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n"
                             for _, r in sorted(used_rows.items())))  # fmt: skip
    if sources is not None:
        out["_schedule_sources"] = {
            "games_with_espn_rows": len(used_rows),
            "fallback_games": sum(1 for g in used_rows if (sources.get(g) or {}).get("schedule_source") == "ESPN_FALLBACK"),
            "reconciled_sdv_games": sum(1 for g in used_rows if (sources.get(g) or {}).get("reconciled_fields")),
        }  # fmt: skip
    write_manifest(out_dir, now, code_sha, roster_commit)
    return out, failed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--horizon-h", type=float, default=30.0)
    ap.add_argument("--out", default="projections_out")
    ap.add_argument(
        "--availability-dir",
        default=None,
        help="checked-out availability-archive (P-AVAIL overlay, challengers)",
    )
    ap.add_argument(
        "--roster-dir",
        default=None,
        help="checked-out roster-archive (P-ROSTER-1 overlay on pure-0.5.0)",
    )
    ap.add_argument(
        "--only-missing",
        default=None,
        help="catch-up mode: JSON list of 'version|espn_game_id' pairs (cbb_edge.ops.cadence)",
    )
    ap.add_argument("--schedule-archive", default=None,
                    help="schedule-archive checkout (Wave 11: archived ESPN fallback rows)")  # fmt: skip
    a = ap.parse_args()
    now = pd.Timestamp(datetime.now(UTC))
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    seasons = list(range(a.season - a.warmup, a.season + 1))
    # provenance (Wave 8): the code commit and the roster-archive commit each record was
    # built from. Added after validation; never an input to any projection.
    code_sha = os.environ.get("GITHUB_SHA")
    roster_commit = os.environ.get("CBB_ROSTER_ARCHIVE_COMMIT") or None
    for ds in HIST:
        sdv.download(ds, seasons[:-1])
        sdv.download_live(ds, a.season, stamp)
    for ds in NCAA:
        sdv.download(ds, list(range(a.season - 5, a.season)))
        sdv.download_live(ds, a.season, stamp)
    # Wave 11: complete the current season's schedule with ESPN-fallback rows for games
    # SDV does not list yet (SDV first; archived + freshly fetched ESPN rows)
    from cbb_edge.ops import schedule_completion, schedule_state

    raw, raw_failed = schedule_state.fetch_scoreboard_raw(
        schedule_state.window_dates(now, a.horizon_h, back_days=8), stamp
    )
    fresh = [r for js, at in raw for r in schedule_completion.espn_rows(js, at)]
    sched_full, completion = schedule_completion.completed_schedule(
        a.season, stamp, [Path(a.schedule_archive)] if a.schedule_archive else None, fresh
    )
    sources = schedule_completion.source_map(sched_full)
    build_silver(seasons, update_registry=False)
    games = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "team_espn_id", "athlete_espn_id", "player_name"],
    )
    for s in range(a.season - 5, a.season + 1):
        build_stints(s, games, pg)
    build_shot(list(range(a.season - 5, a.season + 1)))
    act = active_models()
    versions = [act["incumbent"], *act.get("challengers", [])]
    if any("possession" in load_model(v).get("extra_blocks", []) for v in versions):
        # pure-0.5.0+: player shot zones of the CURRENT season only (history comes from
        # the season-boundary checkpoint); free SDV release asset, basketball columns only
        if sdv.download_live("pbp", a.season, stamp) is not None:
            build_pbp_shots([a.season])
    only = None
    if a.only_missing:
        pairs = json.loads(Path(a.only_missing).read_text())
        only = {(p.split("|")[0], int(p.split("|")[1])) for p in pairs}
    # Wave 10: live game state, fetched now (after as_of): no projection for a game that
    # may have started; TBD-time games stay projectable while positively "pre"
    live, failed_dates = schedule_state.fetch_scoreboard(
        schedule_state.window_dates(now, a.horizon_h), stamp
    )
    out, failed = project_all(a.season, now, a.horizon_h, Path(a.out), a.roster_dir,
                              a.availability_dir, code_sha, roster_commit, only, live,
                              sources)  # fmt: skip
    out["_live_scoreboard"] = {"observations": len(live), "failed_dates": failed_dates}
    out["_schedule_completion"] = {k: completion.get(k) for k in (
        "sdv_games", "fallback_games", "shared_games")} | {
        "reconciled_sdv_games": (completion.get("reconciliation") or {}).get("reconciled_games"),
        "excluded": len(completion.get("excluded", [])),
        "material_disagreements": len(completion.get("material_disagreements", [])),
        "row_fetch_failed_dates": raw_failed}  # fmt: skip
    print(
        json.dumps(
            {"as_of": now.isoformat(), "inputs_stamp": stamp, "models": out, "failed": failed}
        )
    )
    # a failed challenger is reported in the summary; the workflow turns the run red
    # AFTER the healthy versions' records are appended to the archive


if __name__ == "__main__":
    main()
