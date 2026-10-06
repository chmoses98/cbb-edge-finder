"""Publish the CBB app root (``edge_finder.app.v1``) from the archive checkouts.

    python -m cbb_edge.app.sift_app --season 2027 \\
        --projections arch/projections-archive --rosters arch/roster-archive \\
        --scores arch/prospective-scores --schedule-archive arch/schedule-archive \\
        --kalshi arch/kalshi-archive --out site/app/latest

Idempotent: the same archives at the same clock produce the same publication. On any
failure the previous publication stays (last-known-good) and only ``health.json`` is
rewritten to say the latest attempt failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import APP_BRANCH, REPO, SPORT  # noqa: F401  (also puts the vendored contract on the path)
from . import inputs as I
from .selection import ts

ACTIVE = Path(__file__).resolve().parents[3] / "models" / "pure" / "active.json"
GAME_FAMILIES = {"GAME_WINNER", "SPREAD", "TOTAL", "TEAM_TOTAL", "HALF"}


def active_models() -> dict:
    """The frozen roles (``models/pure/active.json``), read as data: importing the projection
    module would pull in the model stack, which the publisher never needs."""
    return json.loads(ACTIVE.read_text())


def kalshi_games(cap: I.KalshiCapture | None, games: pd.DataFrame) -> dict[str, list[dict]]:
    """CBB game id -> the raw captured game-level markets that map to it EXACTLY
    (``cbb_edge.kalshi.mapping``: ticker date + resolved teams + a unique scheduled game)."""
    if cap is None or not len(games):
        return {}
    from cbb_edge.kalshi.mapping import map_market

    out: dict[str, list[dict]] = {}
    for raw in cap.markets:
        if raw.get("family") not in GAME_FAMILIES:
            continue
        gid, why = map_market(raw.get("market") or {}, games)
        if gid is not None and why == "ok":
            out.setdefault(f"G{int(gid)}", []).append(raw)
    return out


def load_world(a: argparse.Namespace, now: pd.Timestamp):  # noqa: ANN201
    from cbb_edge.data.ids.teams import _registry
    from cbb_edge.rosters import membership

    from .build import World, games_frame

    if a.schedule_parquet:
        sched = pd.read_parquet(a.schedule_parquet)
        rep_path = Path(a.schedule_parquet).with_suffix(".report.json")
        report = json.loads(rep_path.read_text()) if rep_path.exists() else {}
    else:
        from cbb_edge.ops.schedule_completion import completed_schedule

        sa = Path(a.schedule_archive) if a.schedule_archive else None
        sched, report = completed_schedule(a.season, now.strftime("%Y%m%dT%H%M%SZ"), roots=[sa])
        sched = sched[pd.to_numeric(sched["season"], errors="coerce") == a.season]
    obs = I.latest_schedule_observation(Path(a.schedule_archive) if a.schedule_archive else None)
    w = World(
        now=now, season=a.season, schedule=sched, schedule_report=report,
        members=membership.members(a.season), team_names=_registry().reset_index(drop=True),
        records=I.load_records(Path(a.projections) if a.projections else None, a.season),
        manifests=I.load_manifests(Path(a.projections) if a.projections else None),
        active=active_models(),  # read, never written
        truth=I.load_truth(Path(a.rosters) if a.rosters else None, now),
        scoreboard=I.load_scoreboard(Path(a.scores) if a.scores else None),
        kalshi=I.load_kalshi(Path(a.kalshi) if a.kalshi else None, now),
        code_sha=os.environ.get("GITHUB_SHA") or a.code_sha,
        commits={k: I.git_head(Path(p)) if p else None for k, p in (
            ("projections_archive", a.projections), ("roster_archive", a.rosters),
            ("scores_archive", a.scores), ("schedule_archive", a.schedule_archive),
            ("kalshi_archive", a.kalshi))},
        schedule_observed_at=I.stamp_iso(obs) if obs else None,
    )  # fmt: skip
    if w.kalshi is not None:
        g, _ = games_frame(w)
        if len(g):
            frame = pd.DataFrame({
                "game_id": g["espn_game_id"], "home_team_id": g["home"], "away_team_id": g["away"],
                "game_date_et": pd.to_datetime(g["date_et"]).dt.date})  # fmt: skip
            w.kalshi_games = kalshi_games(w.kalshi, frame)
    return w


def publish(w, out: Path) -> dict:  # noqa: ANN001
    from edge_finder_contract import publish as PUB
    from edge_finder_contract import research as R

    from .build import build

    b = build(w)
    PUB.publish(root=out, sport=SPORT, run_id=b.run_id, generated_at=b.health["generated_at"],
                documents=b.documents, source_repo=REPO, source_branch=APP_BRANCH,
                commit_sha=w.code_sha, model_version=w.active["incumbent"], health=b.health)  # fmt: skip
    R.publish_explorer(app_root=out, sport=SPORT, run_id=b.run_id, generated_at=b.health["generated_at"],
                       documents=b.explorer,
                       quality=R.quality(status="RESEARCH", source="cbb-edge-finder archives",
                                         generated_at=w.now, production=True,
                                         limitations=["prospectively frozen research system; no betting authority"]),
                       as_of=w.now, commit_sha=w.code_sha, base_manifest_run_id=b.run_id)  # fmt: skip
    problems = PUB.verify_published(out) + R.verify_explorer(out)
    if problems:
        raise RuntimeError(f"published tree does not verify: {problems[:5]}")
    return b.summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--projections", default=None)
    ap.add_argument("--rosters", default=None)
    ap.add_argument("--scores", default=None)
    ap.add_argument("--schedule-archive", default=None)
    ap.add_argument("--kalshi", default=None)
    ap.add_argument(
        "--schedule-parquet", default=None, help="a completed schedule (offline / tests)"
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--now", default=None, help="publication clock (UTC); default now")
    ap.add_argument("--code-sha", default=None)
    a = ap.parse_args(argv)
    now = ts(a.now) if a.now else ts(datetime.now(UTC)).floor("s")
    out = Path(a.out)
    try:
        w = load_world(a, now)
        summary = publish(w, out)
    except Exception as e:  # last-known-good: keep the tree, say the attempt failed
        if os.environ.get("CBB_APP_DEBUG"):
            raise
        _fail(out, now, e)
        print(json.dumps({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps({"status": "PUBLISHED", **summary}, default=str))
    return 0


def _fail(out: Path, now: pd.Timestamp, e: Exception) -> None:
    from edge_finder_contract import health as H
    from edge_finder_contract import ids
    from edge_finder_contract import publish as PUB

    man = PUB.read_manifest(out)
    run_id = (
        man["run_id"] if man else ids.run_id(SPORT, REPO, "failed", generated_at=now.isoformat())
    )
    prev = json.loads((out / "health.json").read_text()) if (out / "health.json").exists() else None
    h = H.build_health(sport=SPORT, run_id=run_id, bet_authority="RESEARCH_ONLY", last_market_capture=None,
                       last_model_generated=(prev or {}).get("last_model_generated"),
                       last_successful_run=(prev or {}).get("last_successful_run"),
                       payload_run_id=run_id if man else None, payload_available=man is not None,
                       export_failed=True, market_required=False, model_required=False,
                       router_applicable=False, settlement_applicable=False, now=now,
                       errors=[f"app publication failed: {type(e).__name__}"])  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    PUB.write_health_only(out, h)


if __name__ == "__main__":
    sys.exit(main())
