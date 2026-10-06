"""Opening-day readiness, opening-week observability and alert conditions (Wave 9).

Operational only: nothing here predicts, tunes or changes anything. It answers, from
the archives and the schedule, whether every upcoming game will be captured correctly,
and it fails LOUDLY (non-zero exit, ``CRITICAL`` alerts) when a prospective observation
is lost or its evidence is broken. It never manufactures a missing projection.

* ``readiness``     per team with a game in the window: next game, roster confidence,
                    valid expected rotation, identity sufficiency, baseline projection
                    possible, P-ROSTER-1 expected (input substitution / continuity
                    correction, by the frozen overlay's own rules), currently
                    unscorable and why;
* ``observability`` per game in [now - 3 d, now + 7 d]: projection captured (per
                    required version, pre-tip), roster snapshot captured, confidence,
                    P-ROSTER-1 eligible, pre-tip gate, settled, score written;
* ``alerts``        the explicit failure states (``ALERTS``).

    python -m cbb_edge.ops.readiness --rosters R --projections P [--scores S]
        [--from 2026-11-02T00:00:00Z] [--days 7] --out ops_out
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cbb_edge.ops import cadence

ALERTS = {
    "TIPPED_WITHOUT_PRE_TIP_PROJECTION": "CRITICAL",  # a required version never projected it
    "OPENING_GAME_MISSED": "CRITICAL",  # a team's first game lost: cannot be reconstructed
    "POST_TIP_SNAPSHOT_SELECTED": "CRITICAL",
    "HASH_MISMATCH": "CRITICAL",
    "ARCHIVE_FILE_MUTATED": "CRITICAL",
    "DUPLICATE_RECORD_DIFFERS": "CRITICAL",
    "SCORER_NOT_RUNNING": "CRITICAL",  # in season, no scoreboard for > 36 h
    "SETTLED_GAME_NEVER_SCORED": "CRITICAL",  # final > 36 h ago, still not VALID/INVALID
    "EXPECTED_PROJECTION_MISSING": "WARNING",  # tips within 6 h, a version has no record
    "TEAM_ID_UNRESOLVED": "WARNING",  # a scheduled D-I member without a canonical id
    "WORKFLOW_STALE": "WARNING",  # a regular slot has been owed for > 3 h
    "UNRESOLVED_IDENTITY_MATERIAL": "WARNING",  # a team's unresolved names could carry > 10 min
    "TBD_GAME_UNPROTECTED": "WARNING",  # TBD time, placeholder passed, no fresh live evidence
    "TBD_START_UNPROVABLE": "WARNING",  # gate could not prove a TBD record pre-start
    # Wave 10: a D-I vs D-I game the live ESPN scoreboard lists but the projection
    # schedule source (SDV) does not: it cannot be projected, and nothing else sees it
    "GAME_MISSING_FROM_SCHEDULE_SOURCE": "WARNING",  # more than 30 h ahead
    "GAME_MISSING_FROM_SCHEDULE_SOURCE_IMMINENT": "CRITICAL",  # within 30 h, or started
    # Wave 11 (schedule completeness): "schedule source" = SDV + the ESPN fallback, so the
    # two codes above now mean a game absent from BOTH projection sources
    "SCHEDULE_RECONCILIATION_AMBIGUOUS": "WARNING",  # same teams + date, different id (fail closed)
    "SCHEDULE_DUPLICATE_GAME": "WARNING",  # two ESPN-only ids for one matchup (fail closed)
    "SCHEDULE_FALLBACK_ROW_INCOMPLETE": "WARNING",  # ESPN row lacks a required field (fail closed)
    "SCHEDULE_SOURCE_DISAGREEMENT": "WARNING",  # SDV and ESPN differ on a material field (SDV kept)
    "SCHEDULE_IDENTITY_DISAGREEMENT": "WARNING",  # SDV and ESPN list different teams (SDV kept)
    "SCHEDULE_IDENTITY_DISAGREEMENT_IMMINENT": "CRITICAL",  # ... on the teams, within 30 h
    "SCHEDULE_ORIENTATION_DISAGREEMENT": "WARNING",  # same teams, home / away swapped (SDV kept)
    # Wave 11 amendment: shared games are field-reconciled to ESPN's current observation;
    # matchup / orientation corrections stay visible (the other fields: audit counts only)
    "SCHEDULE_IDENTITY_RECONCILED": "WARNING",  # SDV's opponent was stale: ESPN's teams used
    "SCHEDULE_ORIENTATION_RECONCILED": "WARNING",  # SDV's home / away was stale: ESPN's used
    "FALLBACK_GAME_DISAPPEARED": "WARNING",  # an ESPN-fallback game no longer listed by ESPN
    "FALLBACK_GAME_NO_SNAPSHOT_NEAR_TIP": "CRITICAL",  # fallback game tips within 6 h, no record
}
COMPLETION_REASON = {"ambiguous_reconciliation": "SCHEDULE_RECONCILIATION_AMBIGUOUS",
                     "teams_not_determined": None,  # bracket placeholder: not a game yet
                     "duplicate_scheduled_game": "SCHEDULE_DUPLICATE_GAME",
                     "missing_required_field": "SCHEDULE_FALLBACK_ROW_INCOMPLETE"}  # fmt: skip
SOURCE_HORIZON = pd.Timedelta(hours=30)
LIVE_FRESH = pd.Timedelta(hours=2)
STALE_GRACE = pd.Timedelta(hours=3)


def tip_tbd(tip: pd.Timestamp) -> bool:
    """ESPN lists a game whose time is not set at 00:00 US/Eastern of its date. The frozen
    projection step only projects games whose LISTED tip is in the future, so such a
    game's last projection chance is the run before that midnight (the 21:10 UTC slot
    and the catch-up ticks to 04:40 UTC); the gate still judges against the real tip."""
    et = _ts(tip).tz_convert("America/New_York")
    return et.hour == 0 and et.minute == 0


def _ts(x: object) -> pd.Timestamp:
    return cadence._ts(x)


def latest_truth(rosters: Path, before: pd.Timestamp | None = None):  # noqa: ANN201
    fs = sorted(Path(rosters).rglob("truth/*/*/*/*_records.jsonl"))
    if before is not None:
        fs = [f for f in fs if _ts(f.name.split("_")[0]) < before]
    if not fs:
        return None
    f = fs[-1]
    stamp = f.name.split("_")[0]
    recs = pd.read_json(f, lines=True, dtype={"player_id": str})
    teams = pd.read_json(f.with_name(f"{stamp}_teams.json"))
    return stamp, recs, teams


def team_eligibility(
    rosters: Path, season: int, before: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Per team, P-ROSTER-1 eligibility exactly as ``overlay.roster_overlay`` decides it
    for a game-1 projection made from the latest snapshot (read-only reuse)."""
    from cbb_edge.app import checkpoints
    from cbb_edge.rosters import overlay
    from cbb_edge.rosters import rotation as _rot

    t = latest_truth(rosters, before)
    if t is None:
        return pd.DataFrame(columns=["team_id"])
    stamp, recs, teams = t
    spec = overlay.load_spec()
    conf = teams.set_index("team_id")["roster_confidence"].to_dict()
    rot = overlay.expected_rotation(recs, season, teams)
    cont = overlay.continuity(rot, season).set_index("team_id")
    sane = _rot.sanity(rot)
    sane_ok = set(sane.loc[sane["ok"], "team_id"]) if len(sane) else set()
    pre = checkpoints.Checkpoint(spec["base_version"], season - 1).preseason().set_index("team_id")["ret_min"]  # fmt: skip
    cov = teams.set_index("team_id").get("official_identity_coverage")
    rows = []
    for tid in sorted(set(teams["team_id"]) | set(rot["team_id"])):
        c = conf.get(tid, "UNKNOWN")
        trusted = c in overlay.TRUSTED and tid in sane_ok
        ok_a = trusted and tid in cont.index
        exp = float(pre.get(tid, np.nan))
        tc = float(cont.loc[tid, "truth_cont"]) if tid in cont.index else np.nan
        ok_b = ok_a and c == "CONFIRMED" and np.isfinite(tc) and np.isfinite(exp)
        rows.append({
            "team_id": tid, "truth_snapshot": stamp, "roster_confidence": c,
            "confidence_reason": teams.set_index("team_id")["confidence_reason"].get(tid),
            "valid_expected_rotation": tid in sane_ok,
            "identity_coverage": None if cov is None or pd.isna(cov.get(tid)) else float(cov.get(tid)),
            "identity_sufficient": c in ("CONFIRMED", "LIKELY"),
            "proster_input_substitution": bool(ok_a),
            "proster_continuity_correction": bool(ok_b),
            "preseason_expected_returning": None if not np.isfinite(exp) else exp,
        })  # fmt: skip
    return pd.DataFrame(rows)


def projection_capable(season: int) -> set[str]:
    """Teams the frozen pipeline can project: registry teams the season-boundary
    checkpoint holds, plus teams that entered D-I after it (engine new-team rule)."""
    from cbb_edge.app import checkpoints
    from cbb_edge.data.ids.teams import _registry

    reg = _registry()
    ck = checkpoints.Checkpoint("pure-0.5.0", season - 1)
    end = ck.engine(sorted(reg["team_id"]))
    return set(end.team_ids) | set(reg.loc[reg["first_d1_season"] > season - 1, "team_id"])


def _records(projections: Path | None, season: int) -> pd.DataFrame:
    rows = []
    if projections is None or not Path(projections).exists():
        return pd.DataFrame(columns=["version", "espn_game_id", "as_of", "tip", "truth_snapshot"])
    for f in Path(projections).rglob("*.json"):
        if "manifests" in f.parts:
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        g = r.get("game") if isinstance(r, dict) else None
        if not g or g.get("season") != season:
            continue
        rows.append({"version": r.get("model", {}).get("version"), "espn_game_id": int(g["espn_game_id"]),
                     "as_of": _ts(r["prospective"]["as_of"]), "tip": _ts(g["start_time_utc"]),
                     "truth_snapshot": (r.get("roster") or {}).get("truth_snapshot")})  # fmt: skip
    return pd.DataFrame(rows, columns=["version", "espn_game_id", "as_of", "tip", "truth_snapshot"])


def _latest_gate(scores: Path | None) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    last = cadence.scores_last(scores) if scores else None
    if scores is None or not (Path(scores) / "LATEST").exists():
        return pd.DataFrame(columns=["espn_game_id", "status", "reasons"]), last
    d = Path(scores) / (Path(scores) / "LATEST").read_text().strip()
    p = d / "integrity_gate.csv"
    g = (
        pd.read_csv(p)
        if p.exists()
        else pd.DataFrame(columns=["espn_game_id", "status", "reasons"])
    )
    g["reasons"] = g["reasons"].fillna("")
    return g, last


def live_only_games(sched: pd.DataFrame, schedule_obs: pd.DataFrame | None,
                    season: int) -> pd.DataFrame:  # fmt: skip
    """Games on the live ESPN scoreboard (latest observation) that the projection
    schedule source does not list, with canonical team ids (``in_schedule_source``
    False). Postponed / cancelled games are left out."""
    from cbb_edge.data.ids.teams import canonical_from_espn_in
    from cbb_edge.ops import schedule_state as ss

    if schedule_obs is None or not len(schedule_obs):
        return pd.DataFrame()
    live = schedule_obs[schedule_obs["source"] == "espn_scoreboard"]
    live = live[~live["espn_game_id"].isin(set(sched["espn_game_id"].astype(int)))]
    if not len(live):
        return pd.DataFrame()
    last = live.sort_values("observed_at").groupby("espn_game_id").tail(1)
    last = last[~last["status_name"].isin(ss.NOT_PLAYED)]

    def tid(e: object) -> str | None:
        return None if e is None or e != e else canonical_from_espn_in(int(e), season)

    return pd.DataFrame({
        "espn_game_id": last["espn_game_id"].astype(int).to_numpy(),
        "home_team_id": [tid(e) for e in last["home_espn"]],
        "away_team_id": [tid(e) for e in last["away_espn"]],
        "tip": pd.to_datetime(last["start_utc"], utc=True).to_numpy(),
        "status": last["status_name"].to_numpy(), "time_state": last["time_state"].to_numpy(),
        "in_schedule_source": False,
    })  # fmt: skip


def build(sched: pd.DataFrame, rosters: Path, projections: Path | None, scores: Path | None,
          now: pd.Timestamp, start: pd.Timestamp, days: float, season: int,
          versions: list[str], d1: set[str], members_espn: set[int] | None = None,
          identity_exposure: dict[str, float] | None = None,
          schedule_obs: pd.DataFrame | None = None) -> dict[str, Any]:  # fmt: skip
    from cbb_edge.ops import schedule_state as ss

    end = ss.et_window_end(start, days)  # Wave 11: US Eastern calendar days (DST-aware)
    completion = dict(sched.attrs.get("completion") or {})
    sched = sched.copy()
    sched["in_schedule_source"] = True
    if "schedule_source" not in sched:
        sched["schedule_source"] = "SDV"
    missing = live_only_games(sched, schedule_obs, season)
    if len(missing):
        sched = pd.concat([sched, missing], ignore_index=True)
    sched["d1_game"] = sched["home_team_id"].isin(d1) & sched["away_team_id"].isin(d1)
    if "time_state" not in sched:
        sched["time_state"] = ss.ANNOUNCED
    # Wave 10: when did each game (possibly) start? announced tip; else the first live
    # observation showing it started; else not yet (a TBD placeholder is NOT a start)
    live = (schedule_obs[schedule_obs["source"] == "espn_scoreboard"]
            if schedule_obs is not None and len(schedule_obs) else pd.DataFrame())  # fmt: skip
    first_started, last_live, last_pre = {}, {}, {}
    if len(live):
        for gid, x in live.groupby("espn_game_id"):
            st = x[[s in ("in", "post") and n not in ss.NOT_PLAYED
                    for s, n in zip(x["state"], x["status_name"], strict=True)]]  # fmt: skip
            pr = x[
                [ss.not_started(s, n) for s, n in zip(x["state"], x["status_name"], strict=True)]
            ]
            if len(st):
                first_started[int(gid)] = st["observed_at"].min()
            if len(pr):
                last_pre[int(gid)] = pr["observed_at"].max()
            last_live[int(gid)] = x["observed_at"].max()
    never = pd.Timestamp.max.tz_localize("UTC")
    sched["eff_tip"] = [g.tip if g.time_state == ss.ANNOUNCED
                        else first_started.get(int(g.espn_game_id), never)
                        for g in sched.itertuples(index=False)]  # fmt: skip
    sched["eff_tip"] = pd.to_datetime(sched["eff_tip"], utc=True) if len(sched) else pd.Series(
        dtype="datetime64[ns, UTC]")  # fmt: skip
    sched["started"] = sched["eff_tip"] <= now
    elig = team_eligibility(rosters, season, before=min(now, start) if start > now else now)
    el = elig.set_index("team_id") if len(elig) else pd.DataFrame()
    capable = projection_capable(season)
    recs = _records(projections, season)
    gate, last_score = _latest_gate(scores)
    gi = gate.set_index("espn_game_id") if len(gate) else gate
    if len(recs):
        et = sched.set_index("espn_game_id")["eff_tip"]
        recs["eff_tip"] = [
            et.get(g, t) for g, t in zip(recs["espn_game_id"], recs["tip"], strict=True)
        ]
        pre = recs[recs["as_of"] < recs["eff_tip"]]
    else:
        pre = recs
    have = set(zip(pre["version"], pre["espn_game_id"], strict=True)) if len(pre) else set()

    # ---- readiness (per team with a game in the window)
    win = sched[(sched["tip"] >= start) & (sched["tip"] < end)
                & ~sched["status"].isin(["STATUS_CANCELED"])]  # fmt: skip
    first_tip = pd.concat([sched[["home_team_id", "tip"]].set_axis(["team_id", "tip"], axis=1),
                           sched[["away_team_id", "tip"]].set_axis(["team_id", "tip"], axis=1)]
                          ).dropna().groupby("team_id")["tip"].min()  # fmt: skip
    teams_rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        for g in win.itertuples(index=False):
            tid = getattr(g, f"{side}_team_id")
            if tid is None or (isinstance(tid, float) and np.isnan(tid)):
                continue
            teams_rows.append({"team_id": tid, "tip": g.tip, "espn_game_id": g.espn_game_id,
                               "opponent": getattr(g, f"{opp}_team_id"), "d1_game": g.d1_game})  # fmt: skip
    tr = pd.DataFrame(teams_rows)
    ready = []
    if len(tr):
        for tid, x in tr.sort_values("tip").groupby("team_id"):
            nxt = x.iloc[0]
            e = el.loc[tid] if len(el) and tid in el.index else None
            why = []
            if tid not in d1:
                why.append("not a 2026-27 D-I member")
            if not nxt["d1_game"]:
                why.append("next game vs non-D-I opponent (outside the experiment)")
            if tid not in capable:
                why.append("frozen pipeline cannot project the team")
            if e is None:
                why.append("no roster truth row for the team (no P-ROSTER-1 record)")
            ready.append({
                "team_id": tid, "next_game": int(nxt["espn_game_id"]), "next_tip": nxt["tip"].isoformat(),
                "opponent": nxt["opponent"], "first_game_of_season": bool(nxt["tip"] == first_tip.get(tid)),
                "games_in_window": int(len(x)), "next_tip_tbd": tip_tbd(nxt["tip"]),
                "roster_confidence": None if e is None else e["roster_confidence"],
                "valid_expected_rotation": None if e is None else bool(e["valid_expected_rotation"]),
                "identity_sufficient": None if e is None else bool(e["identity_sufficient"]),
                "identity_coverage": None if e is None else e["identity_coverage"],
                "baseline_projection_possible": tid in capable and tid in d1,
                "proster_input_substitution": None if e is None else bool(e["proster_input_substitution"]),
                "proster_continuity_correction": None if e is None else bool(e["proster_continuity_correction"]),
                "currently_unscorable": bool(why), "why": "; ".join(why),
            })  # fmt: skip
    ready_df = pd.DataFrame(ready)

    # ---- observability (per game, [now - 3 d, now + 7 d] or the requested window)
    o_start = min(start, now - pd.Timedelta(days=3))
    ow = sched[(sched["tip"] >= o_start) & (sched["tip"] < max(end, now + pd.Timedelta(days=7)))]
    obs = []
    for g in ow.itertuples(index=False):
        gid = int(g.espn_game_id)
        got = {v: (v, gid) in have for v in versions}
        rr = pre[(pre["espn_game_id"] == gid) & pre["truth_snapshot"].notna()] if len(pre) else pre
        st = gi.loc[gid, "status"] if len(gi) and gid in gi.index else None
        conf = [el.loc[t, "roster_confidence"] if len(el) and t in el.index else None
                for t in (g.home_team_id, g.away_team_id)]  # fmt: skip
        elig_g = any(bool(el.loc[t, "proster_input_substitution"]) for t in (g.home_team_id, g.away_team_id)
                     if len(el) and t in el.index)  # fmt: skip
        obs.append({
            "espn_game_id": gid, "tip": g.tip.isoformat(), "home": g.home_team_id, "away": g.away_team_id,
            "status": g.status, "in_experiment": bool(g.d1_game), "tip_tbd": tip_tbd(g.tip),
            "time_state": g.time_state, "tipped": bool(g.started),
            "live_state_last_seen": None if gid not in last_live else last_live[gid].isoformat(),
            **{f"projection:{v}": got[v] for v in versions},
            "roster_snapshot": rr["truth_snapshot"].max() if len(rr) else None,
            "roster_confidence": "/".join(str(c) for c in conf),
            "proster_eligible": elig_g, "gate": st,
            "settled": g.status == "STATUS_FINAL", "score_written": st in ("VALID", "INVALID"),
        })  # fmt: skip
    obs_df = pd.DataFrame(obs)

    # ---- alerts
    alerts: list[dict[str, Any]] = []

    def alert(code: str, **kw: Any) -> None:
        alerts.append({"code": code, "severity": ALERTS[code], **kw})

    in_season = now.month in cadence.SEASON_MONTHS
    past = sched[sched["d1_game"] & sched["started"] & ~sched["status"].isin(
        ["STATUS_CANCELED", "STATUS_POSTPONED"])]  # fmt: skip
    for g in past.itertuples(index=False):
        miss = [v for v in versions if (v, int(g.espn_game_id)) not in have]
        if miss:
            first = any(g.tip == first_tip.get(t) for t in (g.home_team_id, g.away_team_id))
            alert("OPENING_GAME_MISSED" if first else "TIPPED_WITHOUT_PRE_TIP_PROJECTION",
                  espn_game_id=int(g.espn_game_id), tip=g.tip.isoformat(), missing=miss)  # fmt: skip
        st = gi.loc[int(g.espn_game_id)] if len(gi) and int(g.espn_game_id) in gi.index else None
        if (g.status == "STATUS_FINAL" and g.tip < now - pd.Timedelta(hours=36) and not miss
                and (st is None or st["status"] in ("PENDING",))):  # fmt: skip
            alert("SETTLED_GAME_NEVER_SCORED", espn_game_id=int(g.espn_game_id))
    soon = sched[sched["d1_game"] & ~sched["started"] & (sched["tip"] <= now + pd.Timedelta(hours=6))
                 & ((sched["tip"] > now) | (sched["time_state"] != ss.ANNOUNCED))]  # fmt: skip
    for g in soon.itertuples(index=False):
        miss = [v for v in versions if (v, int(g.espn_game_id)) not in have]
        if miss:
            alert("EXPECTED_PROJECTION_MISSING", espn_game_id=int(g.espn_game_id),
                  tip=g.tip.isoformat(), missing=miss)  # fmt: skip
    for code, keys in (("POST_TIP_SNAPSHOT_SELECTED", ("truth_snapshot_not_before",)),
                       ("HASH_MISMATCH", ("hash_mismatch", "replaced_after_projection")),
                       ("ARCHIVE_FILE_MUTATED", ("archived_file_mutated",)),
                       ("DUPLICATE_RECORD_DIFFERS", ("duplicate_record_differs",))):  # fmt: skip
        for r in gate.itertuples(index=False):
            if any(k in str(r.reasons) for k in keys):
                alert(code, espn_game_id=int(r.espn_game_id), reasons=str(r.reasons))
    for root, name in ((projections, "projections-archive"), (rosters, "roster-archive")):
        from cbb_edge.rosters import pretip_gate

        mut = pretip_gate.git_mutated_paths(root)
        for p in sorted(mut or [])[:50]:
            if p.endswith(".json") and ("projections/" in p or "truth/" in p or "official/" in p) \
                    and "latest" not in p and "state/" not in p:  # fmt: skip
                alert("ARCHIVE_FILE_MUTATED", archive=name, path=p)
    if in_season and (last_score is None or now - last_score > pd.Timedelta(hours=36)):
        alert(
            "SCORER_NOT_RUNNING",
            last_scoreboard=None if last_score is None else last_score.isoformat(),
        )
    if members_espn is not None:
        sched_espn = set(sched.get("home_espn", pd.Series(dtype=int)).dropna().astype(int)) | set(
            sched.get("away_espn", pd.Series(dtype=int)).dropna().astype(int))  # fmt: skip
        for e in sorted((members_espn & sched_espn) if sched_espn else set()):
            from cbb_edge.data.ids.teams import canonical_from_espn_in

            if canonical_from_espn_in(e, season) is None:
                alert("TEAM_ID_UNRESOLVED", espn_team_id=int(e))
    if in_season and projections is not None:
        lm = cadence.last_manifest(projections)
        s = cadence.last_slot(now, cadence.PROJECTION_SLOTS)
        if s is not None and (lm is None or lm < s) and now - s > STALE_GRACE:
            alert("WORKFLOW_STALE", workflow="prospective-projections", owed_since=s.isoformat())
    for t, m in sorted((identity_exposure or {}).items()):
        if m > 10:
            alert("UNRESOLVED_IDENTITY_MATERIAL", team_id=t, minutes_at_stake=round(m, 1))
    tbd_now = sched[sched["d1_game"] & (sched["time_state"] != ss.ANNOUNCED) & ~sched["started"]
                    & (sched["tip"] <= now) & ~sched["status"].isin(["STATUS_CANCELED"])]  # fmt: skip
    for g in tbd_now.itertuples(index=False):
        seen = last_live.get(int(g.espn_game_id))
        if seen is None or now - seen > LIVE_FRESH:
            alert("TBD_GAME_UNPROTECTED", espn_game_id=int(g.espn_game_id), date_placeholder=g.tip.isoformat(),
                  last_live_observation=None if seen is None else seen.isoformat())  # fmt: skip
    for r in gate.itertuples(index=False):
        if "tbd_start_unprovable" in str(r.reasons):
            alert("TBD_START_UNPROVABLE", espn_game_id=int(r.espn_game_id))
    src = sched[sched["d1_game"] & ~sched["in_schedule_source"].astype(bool)
                & (sched["tip"] >= now - pd.Timedelta(hours=36))]  # fmt: skip
    near = src[src["started"] | (src["tip"] <= now + SOURCE_HORIZON)]
    for g in near.itertuples(index=False):
        alert("GAME_MISSING_FROM_SCHEDULE_SOURCE_IMMINENT", espn_game_id=int(g.espn_game_id),
              tip=g.tip.isoformat(), home=g.home_team_id, away=g.away_team_id)  # fmt: skip
    far = src[~src["espn_game_id"].isin(near["espn_game_id"])]
    if len(far):
        alert("GAME_MISSING_FROM_SCHEDULE_SOURCE", n_games=int(len(far)),
              first_tip=far["tip"].min().isoformat(),
              espn_game_ids=sorted(int(x) for x in far["espn_game_id"])[:25])  # fmt: skip
    # ---- Wave 11: schedule completeness (independent of roster readiness)
    excl = {int(e["game_id"]): e for e in completion.get("excluded", [])}
    for gid, e in sorted(excl.items()):
        code = COMPLETION_REASON.get(e["reason"], "SCHEDULE_FALLBACK_ROW_INCOMPLETE")
        if code:
            alert(code, espn_game_id=gid,
                  **{k: v for k, v in e.items() if k not in ("game_id", "reason")})  # fmt: skip
    tips = sched.set_index("espn_game_id")["tip"] if len(sched) else pd.Series(dtype=object)
    for a in (completion.get("reconciliation") or {}).get("ambiguous", []):
        alert("SCHEDULE_RECONCILIATION_AMBIGUOUS", espn_game_id=int(a["game_id"]),
              collides_with=a.get("collides_with"), action="excluded (fail closed)")  # fmt: skip
    for d in completion.get("material_disagreements", []):
        gid = int(d["game_id"])
        t = tips.get(gid)
        near = t is not None and pd.notna(t) and t <= now + SOURCE_HORIZON
        if d.get("resolution", "unresolved_sdv_kept") == "reconciled_to_espn":
            if d["field"] == "teams":
                alert("SCHEDULE_ORIENTATION_RECONCILED" if d.get("result") == "orientation_swap"
                      else "SCHEDULE_IDENTITY_RECONCILED", espn_game_id=gid, sdv=d.get("sdv"),
                      espn=d.get("espn"))  # fmt: skip
            continue  # other reconciled fields: audit counts (completeness section)
        if d.get("resolution") == "ambiguous_excluded":
            continue
        if d["field"] == "teams" and d.get("result") == "orientation_swap":
            code = "SCHEDULE_ORIENTATION_DISAGREEMENT"
        elif d["field"] in ("teams", "season"):
            code = (
                "SCHEDULE_IDENTITY_DISAGREEMENT_IMMINENT"
                if near
                else "SCHEDULE_IDENTITY_DISAGREEMENT"
            )
        else:
            code = "SCHEDULE_SOURCE_DISAGREEMENT"
        alert(code, espn_game_id=gid, field=d["field"], sdv=d.get("sdv"), espn=d.get("espn"))
    fb = sched[sched["schedule_source"] == "ESPN_FALLBACK"]
    if len(live) and len(fb):
        lt = live.groupby("date_et")["observed_at"].max()  # each date's latest full fetch
        last = live.groupby("espn_game_id")["observed_at"].max()
        for g in fb.itertuples(index=False):
            d = g.tip.tz_convert(ss.ET).date().isoformat() if pd.notna(g.tip) else None
            seen = last.get(int(g.espn_game_id))
            if d in lt.index and (seen is None or lt[d] - seen > pd.Timedelta(minutes=30)):
                alert("FALLBACK_GAME_DISAPPEARED", espn_game_id=int(g.espn_game_id),
                      last_listed=None if seen is None else seen.isoformat(),
                      latest_fetch_of_date=lt[d].isoformat())  # fmt: skip
    for g in fb[
        fb["d1_game"] & ~fb["started"] & (fb["tip"] <= now + pd.Timedelta(hours=6))
    ].itertuples(index=False):
        miss = [v for v in versions if (v, int(g.espn_game_id)) not in have]
        if miss:
            alert("FALLBACK_GAME_NO_SNAPSHOT_NEAR_TIP", espn_game_id=int(g.espn_game_id),
                  tip=g.tip.isoformat(), missing=miss)  # fmt: skip
    games_df = game_readiness(
        sched, win, have, versions, el, capable, now, last_live, last_pre, pre
    )
    return {"now": now.isoformat(), "window": [start.isoformat(), end.isoformat()],
            "readiness": ready_df, "observability": obs_df, "alerts": alerts,
            "eligibility": elig, "games": games_df, "completion": completion}  # fmt: skip


def game_readiness(sched: pd.DataFrame, win: pd.DataFrame, have: set, versions: list[str],
                   el: pd.DataFrame, capable: set[str], now: pd.Timestamp,
                   last_live: dict, last_pre: dict, pre: pd.DataFrame) -> pd.DataFrame:  # fmt: skip
    """Per game in the window (Wave 10, opening-week readiness): tip-time state, a valid
    pre-game snapshot available now, baseline possible, P-ROSTER-1 eligible, roster
    status, and whether it is currently at risk of becoming unscorable (and why)."""
    from cbb_edge.ops import schedule_state as ss

    rows = []
    w = sched[sched["espn_game_id"].isin(win["espn_game_id"])]
    for g in w.itertuples(index=False):
        gid = int(g.espn_game_id)
        teams = (g.home_team_id, g.away_team_id)
        conf = [
            el.loc[t, "roster_confidence"] if len(el) and t in el.index else None for t in teams
        ]
        snap = all((v, gid) in have for v in versions)
        risk = []
        if g.d1_game and not g.in_schedule_source:
            risk.append("listed on the live ESPN scoreboard but absent from both projection "
                        "schedule sources (SDV and the ESPN fallback): cannot be projected")  # fmt: skip
        if not g.d1_game:
            risk.append("not a D-I vs D-I game (outside the experiment)")
        elif not all(t in capable for t in teams):
            risk.append("a team the frozen pipeline cannot project")
        if g.d1_game and any(c is None for c in conf):
            risk.append("a team without a roster truth row (no P-ROSTER-1 record)")
        hrs = (g.tip - now).total_seconds() / 3600
        if g.d1_game and not snap and not g.started and hrs <= 30 and g.time_state == ss.ANNOUNCED:
            risk.append("inside the 30 h window without a snapshot for every version")
        if g.d1_game and g.time_state != ss.ANNOUNCED and not g.started and g.tip <= now:
            seen = last_live.get(gid)
            if seen is None or now - seen > LIVE_FRESH:
                risk.append("TBD time, placeholder passed, no fresh live game-state evidence")
        if g.d1_game and g.time_state != ss.ANNOUNCED and snap and len(pre):
            last_rec = pre.loc[pre["espn_game_id"] == gid, "as_of"].max()
            lp = last_pre.get(gid)
            if lp is None or lp < last_rec:
                risk.append("TBD time: no live 'pre' observation after the latest snapshot yet")
        rows.append({
            "espn_game_id": gid, "listed_tip": g.tip.isoformat(), "time_state": g.time_state,
            "home": g.home_team_id, "away": g.away_team_id, "in_experiment": bool(g.d1_game),
            "in_schedule_source": bool(g.in_schedule_source),
            "schedule_source": (g.schedule_source if g.in_schedule_source
                                else "ABSENT_FROM_BOTH"),
            "reconciled_fields": rf if isinstance(rf := getattr(g, "reconciled_fields", ""), str) else "",  # fmt: skip
            "pre_game_snapshot_available": snap,
            "baseline_projection_possible": bool(g.d1_game and all(t in capable for t in teams)),
            "proster_eligible": any(bool(el.loc[t, "proster_input_substitution"]) for t in teams
                                    if len(el) and t in el.index),
            "roster_status": "/".join(str(c) for c in conf), "at_risk": bool(risk),
            "why": "; ".join(risk),
        })  # fmt: skip
    return pd.DataFrame(rows)


def markdown(r: dict[str, Any]) -> str:
    rd, ob, al = r["readiness"], r["observability"], r["alerts"]
    crit = [a for a in al if a["severity"] == "CRITICAL"]
    L = [f"# Prospective readiness / observability — {r['now']}", "",
         f"Window: {r['window'][0]} → {r['window'][1]}. Operational report: nothing here "
         "predicts or tunes anything.", "",
         f"**ALERTS: {len(crit)} CRITICAL, {len(al) - len(crit)} WARNING**", ""]  # fmt: skip
    for a in al[:60]:
        L.append(f"* `{a['severity']}` **{a['code']}** — " + ", ".join(
            f"{k}={v}" for k, v in a.items() if k not in ("code", "severity")))  # fmt: skip
    L.append("")
    if len(rd):
        n = len(rd)
        conf = rd["roster_confidence"].fillna("NO TRUTH ROW").value_counts().to_dict()
        L += ["## 1-8. Readiness (teams with a game in the window)", "",
              "| question | answer |", "|---|---|",
              f"| 1. teams with a game in the window | {n} |",
              f"| 2. roster confidence | {', '.join(f'{k} {v}' for k, v in conf.items())} |",
              f"| 3. valid expected rotation | {int(rd['valid_expected_rotation'].fillna(False).sum())} |",
              f"| 4. identities sufficient (CONFIRMED / LIKELY) | {int(rd['identity_sufficient'].fillna(False).sum())} |",
              f"| 5. baseline projection possible | {int(rd['baseline_projection_possible'].sum())} |",
              f"| 6. P-ROSTER-1 input substitution / continuity correction | "
              f"{int(rd['proster_input_substitution'].fillna(False).sum())} / "
              f"{int(rd['proster_continuity_correction'].fillna(False).sum())} |",
              f"| 7. currently unscorable | {int(rd['currently_unscorable'].sum())} |",
              f"| next game's tip time still TBD in ESPN (00:00 ET placeholder) | "
              f"{int(rd['next_tip_tbd'].sum())} |", ""]  # fmt: skip
        bad = rd[rd["currently_unscorable"]]
        L += ["### 8. Why unscorable", ""] + [f"* `{x.team_id}` (next game {x.next_game}): {x.why}"
                                             for x in bad.itertuples()] + [""]  # fmt: skip
    gm = r.get("games")
    if gm is not None and len(gm):
        ex = gm[gm["in_experiment"]]
        comp = r.get("completion") or {}
        exc = pd.Series([e["reason"] for e in comp.get("excluded", [])], dtype=object)
        L += ["## Schedule completeness (Wave 11: SDV first, ESPN fallback when absent)", "",
              "| measure | games |", "|---|---|",
              f"| season schedule: SDV rows | {comp.get('sdv_games', '–')} |",
              f"| season schedule: ESPN-fallback rows (absent from SDV) | {comp.get('fallback_games', '–')} |",
              f"| ESPN rows excluded (fail closed) | {len(exc)} |",
              *[f"| — {k} | {v} |" for k, v in exc.value_counts().items()],
              f"| shared SDV/ESPN games | {(comp.get('reconciliation') or {}).get('shared_games', comp.get('shared_games', '–'))} |",
              f"| — exact match | {(comp.get('reconciliation') or {}).get('exact_match', '–')} |",
              f"| — field-reconciled to ESPN (game stays SDV-native) | {(comp.get('reconciliation') or {}).get('reconciled_games', '–')} |",
              *[f"| —— {k} | {v} |" for k, v in sorted(((comp.get('reconciliation') or {}).get('by_group') or {}).items())],
              *[f"| —— teams: {k} | {v} |" for k, v in sorted(((comp.get('reconciliation') or {}).get('teams_kind') or {}).items())],
              f"| — unresolved (ESPN row not a valid observation; SDV kept) | {len((comp.get('reconciliation') or {}).get('unresolved', []))} |",
              f"| — ambiguous (excluded, fail closed) | {len((comp.get('reconciliation') or {}).get('ambiguous', []))} |",
              f"| window D-I games absent from BOTH sources | {int((~gm.loc[gm['in_experiment'], 'in_schedule_source']).sum())} |",
              ""]  # fmt: skip
        L += ["## Opening-week games (Wave 10: tip-time state)", "",
              "| measure | games |", "|---|---|",
              f"| games total (D-I vs D-I / all) | {len(ex)} / {len(gm)} |",
              f"| announced tip | {int((ex['time_state'] == 'ANNOUNCED').sum())} |",
              f"| TBD / placeholder / unknown | {int((ex['time_state'] != 'ANNOUNCED').sum())} |",
              f"| schedule source: SDV | {int((ex['schedule_source'] == 'SDV').sum())} |",
              f"| schedule source: ESPN fallback (absent from SDV) | {int((ex['schedule_source'] == 'ESPN_FALLBACK').sum())} |",
              f"| on the live scoreboard but ABSENT from both projection sources | {int((~ex['in_schedule_source']).sum())} |",
              f"| valid pre-game snapshot available now | {int(ex['pre_game_snapshot_available'].sum())} |",
              f"| baseline projection possible | {int(ex['baseline_projection_possible'].sum())} |",
              f"| P-ROSTER-1 eligible (a side with input substitution) | {int(ex['proster_eligible'].sum())} |",
              f"| roster status (both sides CONFIRMED) | {int((ex['roster_status'] == 'CONFIRMED/CONFIRMED').sum())} |",
              f"| currently at risk of becoming unscorable | {int(ex['at_risk'].sum())} |", ""]  # fmt: skip
        why = ex.loc[ex["at_risk"], "why"].str.split("; ").explode().value_counts()
        L += [f"* {k}: {v}" for k, v in why.items()] + [""]
    if len(ob):
        vcols = [c for c in ob.columns if c.startswith("projection:")]
        L += ["## Opening-week observability (per game)", "",
              "TBD = ESPN has not set the tip time (00:00 ET placeholder). After the placeholder "
              "passes, the game is projected only while the live scoreboard shows it not started.", "",
              "| tip | game | home | away | in exp. | " + " | ".join(c.split(":")[1] for c in vcols)
              + " | roster snapshot | confidence | P-ROSTER-1 eligible | gate | settled | scored |",
              "|" + "---|" * (11 + len(vcols))]  # fmt: skip
        for x in ob.sort_values("tip").head(400).to_dict("records"):
            L.append(f"| {x['tip'][:16]}{' TBD' if x['tip_tbd'] else ''} | {x['espn_game_id']} | {x['home']} | {x['away']} | "
                     f"{'yes' if x['in_experiment'] else 'no'} | "
                     + " | ".join("✓" if x[c] else "–" for c in vcols)
                     + f" | {x['roster_snapshot'] or '–'} | {x['roster_confidence']} | "
                     f"{'yes' if x['proster_eligible'] else 'no'} | {x['gate'] or '–'} | "
                     f"{'yes' if x['settled'] else 'no'} | {'yes' if x['score_written'] else 'no'} |")  # fmt: skip
    return "\n".join(L) + "\n"


def main() -> None:
    from cbb_edge.data.ids.teams import authoritative_members
    from cbb_edge.ops import schedule_state as ss
    from cbb_edge.rosters import membership

    ap = argparse.ArgumentParser()
    ap.add_argument("--rosters", type=Path, required=True)
    ap.add_argument("--projections", type=Path, default=None)
    ap.add_argument("--scores", type=Path, default=None)
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--from-date", default=None, help="first US Eastern date (YYYY-MM-DD)")
    ap.add_argument("--sdv-file", type=Path, default=None,
                    help="frozen SDV schedule snapshot (reproducible as-of runs)")  # fmt: skip
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--now", default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--identity", type=Path, default=None, help="pretip_diagnostics JSON")
    ap.add_argument("--schedule-archive", type=Path, nargs="*", default=[])
    a = ap.parse_args()
    now = _ts(a.now) if a.now else pd.Timestamp(datetime.now(UTC))
    sched = cadence.schedule_frame(a.season, now.strftime("%Y%m%dT%H%M%SZ"),
                                   [*a.schedule_archive, a.projections],
                                   sdv_frame=pd.read_parquet(a.sdv_file) if a.sdv_file else None)  # fmt: skip
    obs = ss.load_obs(*a.schedule_archive, a.projections)
    # before the season opener the report previews opening week, from the first tip in
    # EITHER source (Wave 10: SDV can lag the live scoreboard)
    tips = pd.concat([sched["tip"], live_only_games(sched, obs, a.season).get(
        "tip", pd.Series(dtype="datetime64[ns, UTC]"))])  # fmt: skip
    opener = pd.to_datetime(tips, utc=True).min() if len(tips) else now
    # Wave 11: windows are US Eastern calendar days (the canonical opening-week universe)
    start = (_ts(a.start) if a.start else ss.et_midnight(a.from_date) if a.from_date
             else max(now, ss.et_midnight(opener.tz_convert(ss.ET).date().isoformat())))  # fmt: skip
    d1 = set(membership.members(a.season)["team_id"].dropna())
    versions = cadence.required_versions(True)
    exposure = None
    if a.identity and a.identity.exists():
        exposure = json.loads(a.identity.read_text()).get("identity_impact", {}).get("per_team")
    r = build(sched, a.rosters, a.projections, a.scores, now, start, a.days, a.season, versions,
              d1, set(authoritative_members(a.season) or []), exposure, obs)  # fmt: skip
    a.out.mkdir(parents=True, exist_ok=True)
    r["readiness"].to_csv(a.out / "readiness.csv", index=False)
    r["observability"].to_csv(a.out / "observability.csv", index=False)
    r["games"].to_csv(a.out / "games.csv", index=False)
    (a.out / "alerts.json").write_text(json.dumps(r["alerts"], indent=1, default=str))
    (a.out / "readiness.md").write_text(markdown(r))
    crit = [x for x in r["alerts"] if x["severity"] == "CRITICAL"]
    print(json.dumps({"now": r["now"], "teams": len(r["readiness"]), "games": len(r["observability"]),
                      "critical": len(crit), "warning": len(r["alerts"]) - len(crit)}))  # fmt: skip
    if crit:
        raise SystemExit(f"{len(crit)} CRITICAL alert(s): see alerts.json")  # fail loudly


if __name__ == "__main__":
    main()
