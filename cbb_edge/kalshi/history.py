"""Immutable market-by-market CBB research panel, joined AS OF each Kalshi capture.

No odds-based inference, model refit, bet authorization, or hindsight projections.
Every market in a snapshot gets one row (including unmapped futures and unknowns).
Rows for uniquely mapped games carry ALL eligible frozen projection versions that
existed at the capture timestamp; market-specific win/cover probabilities are NOT
inferred from unrelated projections. Live/post-tip observations are distinguished.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cbb_edge.app.sift_app import inputs as I
from cbb_edge.app.sift_app import selection as S
from cbb_edge.app.sift_app.build import World, clock_of, games_frame
from cbb_edge.kalshi.mapping import map_raw
from cbb_edge.kalshi.semantics import parse_contract, probability

SCHEMA = "cbb-kalshi-model-panel-v2"


def _projections(
    game: dict[str, Any],
    records: list[dict[str, Any]],
    w: World,
    at: pd.Timestamp,
    reorient: bool = True,
) -> dict[str, Any]:
    """Frozen projections usable for this game. A record for the SAME teams listed home/away reversed
    on a neutral site (verified by canonical team id) is reframed into the schedule's frame - the frame
    ``parse_contract`` / ``settle`` use for ``subject_side`` - so contract probabilities point the right
    way; anything else that changed identity is skipped. ``reorient=False`` is the legacy behaviour
    (every identity change skipped), kept only for the before/after comparison."""
    from cbb_edge.data.ids.orientation import reframe_projection

    selected = S.select(records, clock_of(game), at, S.roles(w.active))
    out: dict[str, Any] = {}
    reoriented: list[str] = []
    for version, choice in selected.chosen.items():
        p = choice.record.get("projection") or {}
        if version in selected.identity_changed:
            if not (reorient and version in selected.reorientable):
                continue
            p = reframe_projection(selected.orientation[version], p)
            reoriented.append(version)
        out[version] = {
            "role": choice.role,
            "as_of": choice.as_of.isoformat(),
            "archive_path": choice.record.get("_path"),
            "sha256": choice.record.get("_sha256"),
            "home_points": p.get("home_score"),
            "away_points": p.get("away_score"),
            "margin": p.get("margin"),
            "margin_sd": p.get("margin_sd"),
            "total": p.get("total"),
            "total_sd": p.get("total_sd"),
            "home_win_prob": p.get("home_win_prob"),
            "possessions": p.get("possessions"),
        }
    return {
        "state": selected.state,
        "versions": out,
        "rejected_version_count": len(selected.rejected),
        "identity_changed_versions": [v for v in selected.identity_changed if v not in reoriented],
        "reoriented_versions": sorted(reoriented),
        "conflicting_versions": selected.conflicts,
    }


def build_panel(w: World, out: Path) -> dict[str, Any]:
    """Create an immutable, per-capture research partition; never overwrite a prior run."""
    cap = w.kalshi
    if cap is None:
        raise ValueError("No archived Kalshi snapshot at this publication clock")
    stamp = S.ts(cap.captured_at)
    source_name = Path(cap.file).name.replace(".jsonl.gz", "")
    partition = out / "panels" / stamp.strftime("%Y/%m/%d") / f"{source_name}.panel.jsonl.gz"
    summary_path = partition.with_name(partition.name.replace(".jsonl.gz", ".summary.json"))
    if partition.exists():
        if not summary_path.exists():
            raise FileExistsError(f"Panel exists without summary: {partition}")
        return json.loads(summary_path.read_text())

    games, _ = games_frame(w)
    if len(games):
        frame = pd.DataFrame(
            {
                "game_id": games["espn_game_id"],
                "home_team_id": games["home"],
                "away_team_id": games["away"],
                "game_date_et": pd.to_datetime(games["date_et"]).dt.date,
            }
        )
    else:
        frame = pd.DataFrame(columns=["game_id", "home_team_id", "away_team_id", "game_date_et"])
    game_by_id: dict[int, dict[str, Any]] = {
        int(r["espn_game_id"]): {str(k): v for k, v in r.items()} for r in games.to_dict("records")
    }
    records_by_id: dict[int, list[dict[str, Any]]] = {}
    for rec in w.records:
        gid = (rec.get("game") or {}).get("espn_game_id")
        if gid is not None:
            records_by_id.setdefault(int(gid), []).append(rec)

    matchup_cache: dict[tuple[str, str], tuple[int | None, str]] = {}
    model_cache: dict[int, dict[str, Any]] = {}
    reasons: Counter[str] = Counter()
    phases: Counter[str] = Counter()
    linked_with_projection = 0
    priced = 0
    series_counts: Counter[str] = Counter()
    mapped_series: Counter[str] = Counter()
    parse_status: Counter[str] = Counter()
    pretip_with_projection = 0
    partition.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(partition, "wt", encoding="utf-8") as fh:
        for raw in cap.markets:
            market = raw.get("market") or {}
            event = raw.get("event") or {}
            gid, reason = map_raw(raw, frame, matchup_cache)
            reasons[reason] += 1
            series_counts[str(raw.get("series_ticker"))] += 1
            if reason == "ok":
                mapped_series[str(raw.get("series_ticker"))] += 1
            game = game_by_id.get(gid) if gid is not None else None
            if game is None or gid is None:
                phase = "UNMAPPED"
                projection = None
            else:
                tip = S.ts(game["start"])
                phase = (
                    "PRETIP"
                    if game["time_state"] == "ANNOUNCED" and stamp < tip
                    else "IN_PLAY_OR_POSTTIP"
                    if game["time_state"] == "ANNOUNCED"
                    else "TIP_UNVERIFIED"
                )
                if gid not in model_cache:
                    model_cache[gid] = _projections(game, records_by_id.get(gid, []), w, stamp)
                projection = model_cache[gid]
                if projection["versions"]:
                    linked_with_projection += 1
                    if phase == "PRETIP":
                        pretip_with_projection += 1
            phases[phase] += 1
            parsed: dict[str, Any] | None = None
            probs: dict[str, Any] | None = None
            if game is not None and gid is not None:
                parsed = parse_contract(
                    str(raw.get("series_ticker") or ""),
                    market,
                    game.get("home"),
                    game.get("away"),
                )
                probs = {}
                if projection is not None:
                    for version, proj in projection["versions"].items():
                        p, method = probability(parsed, proj)
                        probs[version] = {"probability": p, "method_or_gap": method}
                        if p is not None:
                            priced += 1
                    parse_status[str(parsed["status"])] += 1
            row = {
                "schema_version": SCHEMA,
                "captured_at": cap.captured_at,
                "source_snapshot": cap.file,
                "kalshi_ticker": market.get("ticker"),
                "kalshi_event_ticker": market.get("event_ticker"),
                "series_ticker": raw.get("series_ticker"),
                "family": raw.get("family"),
                "event_title": event.get("title"),
                "market_title": market.get("title"),
                "yes_sub_title": market.get("yes_sub_title"),
                "status": market.get("status"),
                "result": market.get("result"),
                "yes_bid_dollars": market.get("yes_bid_dollars"),
                "yes_ask_dollars": market.get("yes_ask_dollars"),
                "no_bid_dollars": market.get("no_bid_dollars"),
                "no_ask_dollars": market.get("no_ask_dollars"),
                "last_price_dollars": market.get("last_price_dollars"),
                "yes_bid_size_fp": market.get("yes_bid_size_fp"),
                "yes_ask_size_fp": market.get("yes_ask_size_fp"),
                "volume_fp": market.get("volume_fp"),
                "open_interest_fp": market.get("open_interest_fp"),
                "floor_strike": market.get("floor_strike"),
                "cap_strike": market.get("cap_strike"),
                "strike_type": market.get("strike_type"),
                "close_time": market.get("close_time"),
                "mapping_reason": reason,
                "espn_game_id": gid,
                "canonical_game_id": f"G{gid}" if gid is not None else None,
                "game_start_utc": S.ts(game["start"]).isoformat() if game else None,
                "market_phase": phase,
                "models_as_of_capture": projection,
                "contract_semantics": parsed,
                "market_specific_model_probability": probs,
            }
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    summary = {
        "schema_version": SCHEMA,
        "captured_at": cap.captured_at,
        "source_snapshot": cap.file,
        "file": str(partition.relative_to(out)),
        "market_contracts": len(cap.markets),
        "mapped_contracts": reasons["ok"],
        "linked_with_projection": linked_with_projection,
        "pretip_with_projection": pretip_with_projection,
        "by_mapping_reason": dict(reasons),
        "by_series": dict(series_counts),
        "mapped_by_series": dict(mapped_series),
        "contract_parse_status": dict(parse_status),
        "contracts_with_model_probability": priced,
        "by_market_phase": dict(phases),
        "distinct_mapped_games": len(model_cache),
        "projection_rule": "only archived prospective records with as_of <= capture and provably pre-tip",
        "market_probability_rule": "per-version probability only for validated payoff parsers (full-game winner/spread/total) using the frozen model's own distribution; else null with explicit gap",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def pending_snapshots(root: Path, out: Path) -> list[Path]:
    """Newest missing source snapshots first, keeping old ones in the backfill queue.

    Production must join the opening-night prices before spending many runs on the
    historical backlog. Existing immutable partitions are never rebuilt or overwritten.
    """
    files = sorted(root.glob("snapshots/**/kalshi_cbb_*.jsonl.gz"), reverse=True)
    pending: list[Path] = []
    for f in files:
        name = f.name.replace(".jsonl.gz", "")
        stamp = f.name.split("_")[-1].split(".")[0]
        at = S.ts(pd.Timestamp(stamp))
        dest = out / "panels" / at.strftime("%Y/%m/%d") / f"{name}.panel.jsonl.gz"
        if not dest.exists():
            pending.append(f)
    return pending


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--projections", required=True)
    ap.add_argument("--rosters", default=None)
    ap.add_argument("--scores", default=None)
    ap.add_argument("--schedule-archive", default=None)
    ap.add_argument("--schedule-parquet", default=None)
    ap.add_argument("--kalshi", required=True)
    ap.add_argument("--code-sha", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--all-missing", action="store_true")
    ap.add_argument("--max-partitions", type=int, default=12)
    args = ap.parse_args()
    from cbb_edge.app.sift_app.__main__ import load_world

    w = load_world(args, S.ts(datetime.now(UTC)))
    out = Path(args.out)
    if not args.all_missing:
        print(json.dumps(build_panel(w, out), sort_keys=True))
        return
    root = Path(args.kalshi)
    pending = pending_snapshots(root, out)
    created = []
    for f in pending[: args.max_partitions]:
        summary_path = f.with_name(f.name.replace(".jsonl.gz", ".summary.json"))
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        captured = summary.get("captured_at") or (rows[0].get("captured_at") if rows else None)
        if not captured:
            raise ValueError(f"Missing capture timestamp for {f}")
        w.kalshi = I.KalshiCapture(captured, str(f.relative_to(root)), rows, summary)
        created.append(build_panel(w, out))
        if len(created) >= args.max_partitions:
            break
    print(
        json.dumps(
            {"created": created, "remaining": max(0, len(pending) - len(created))}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
