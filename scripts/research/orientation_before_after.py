"""Before/after comparison of the orientation integration on the complete archive (RESEARCH ONLY).

OLD = the production code at ``--baseline-ref`` (loaded from git, unmodified); NEW = the working tree.
Identical inputs go through both; archives are only read.

    CBB_DATA_DIR=<lake with bronze schedules> python scripts/research/orientation_before_after.py \
        --projections A/projections-archive --rosters A/roster-archive --schedule A/schedule-archive \
        --espn A/espn-lines-archive --panel A/kalshi-panel-archive --now 2026-11-10T12:00:00Z \
        --baseline-ref b3203a31 --out research/orientation

Proves (written to ``orientation_comparison.json``):
  A. scoreboard: every game other than the verified neutral-site reversals scores IDENTICALLY
     (every column of paired_games, every integrity-gate row, every summary figure that is not a
     function of the reversed games); the reversals change from UNSCORABLE to scored with the result
     mapped onto the projected teams;
  B. fail closed: schedule inputs perturbed in memory (non-neutral reversal, different team,
     unresolved id) leave the game UNSCORABLE in both old and new code;
  C. Kalshi path: frozen-projection selection per game old vs new (identical except the reversals,
     which are reframed into the schedule frame), Kalshi settlement of every settled panel contract
     unchanged and in agreement with Kalshi's own result, and model probabilities for the reversed
     games now point the right way.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "prospective"))


def git_show(ref: str, rel: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:{rel}"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout


def load_old_module(ref: str, rel: str, name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__file__ = str(REPO / rel)  # path constants resolve to the real repo
    mod.__dict__["__name__"] = name
    sys.modules[name] = mod
    exec(compile(git_show(ref, rel), str(REPO / rel), "exec"), mod.__dict__)
    return mod


def old_projections_fn(ref: str, old_sel: types.ModuleType) -> Any:
    """The ORIGINAL ``_projections`` from history.py at ``ref`` (extracted verbatim), bound to the
    original selection module."""
    src = git_show(ref, "cbb_edge/kalshi/history.py")
    node = next(
        n
        for n in ast.parse(src).body
        if isinstance(n, ast.FunctionDef) and n.name == "_projections"
    )
    ns: dict[str, Any] = {"S": old_sel, "pd": pd, "Any": Any, "World": object}

    def old_clock_of(row: dict[str, Any]) -> Any:
        return old_sel.GameClock(int(row["espn_game_id"]), row["start"], row["time_state"], row["state"],
                                 row["status_name"], bool(row["completed"]), row["home"], row["away"])  # fmt: skip

    ns["clock_of"] = old_clock_of
    exec("from __future__ import annotations\n" + ast.get_source_segment(src, node), ns)
    return ns["_projections"]


# ------------------------------------------------------------------------------- A / B scoreboard
def scoreboard_inputs(a: argparse.Namespace) -> dict[str, Any]:
    import score_proster as SP

    from cbb_edge.ops import schedule_state
    from cbb_edge.rosters import membership
    from cbb_edge.rosters import prospective_score as ps

    now = pd.Timestamp(a.now)
    recs = ps.load_records(a.projections, 2027)
    res, sched = SP.schedule(2027, now.strftime("%Y%m%dT%H%M%SZ"), [a.schedule, a.projections])
    d1 = set(membership.members(2027)["team_id"].dropna())
    return {
        "recs": recs, "res": res, "sched": sched, "d1": d1, "now": now,
        "mkt": SP.market(a.espn, sched), "expected": SP.expected_games(sched, d1, now),
        "committed": ps.git_first_commit_times(a.projections),
        "committed_roster": ps.git_first_commit_times(a.rosters),
        "obs": schedule_state.load_obs(a.schedule, a.projections),
    }  # fmt: skip


def run_score(mod: Any, inp: dict[str, Any], a: argparse.Namespace, games: pd.DataFrame, **kw: Any):
    return mod.score(
        inp["recs"], inp["res"], inp["mkt"], a.rosters, pd.DataFrame(), games, 2027, inp["d1"],
        committed=inp["committed"], committed_roster=inp["committed_roster"],
        projections_root=a.projections, expected=inp["expected"], schedule_obs=inp["obs"], **kw,
    )  # fmt: skip


def frames_equal(
    old: pd.DataFrame, new: pd.DataFrame, drop: list[str], key: str, exclude: set[int]
) -> dict:
    if old.empty or new.empty:
        return {"identical": old.empty and new.empty, "rows_old": len(old), "rows_new": len(new)}
    o = (
        old[~old[key].isin(exclude)]
        .drop(columns=[c for c in drop if c in old])
        .sort_values(key)
        .reset_index(drop=True)
    )
    n = (
        new[~new[key].isin(exclude)]
        .drop(columns=[c for c in drop if c in new])
        .sort_values(key)
        .reset_index(drop=True)
    )
    same_cols = list(o.columns) == list(n.columns)
    return {"identical": bool(same_cols and o.equals(n)), "rows_compared": len(o), "columns": len(o.columns),
            "columns_equal": same_cols}  # fmt: skip


def scoreboard(a: argparse.Namespace, old_ps: Any, new_ps: Any) -> dict[str, Any]:
    inp = scoreboard_inputs(a)
    games = inp["sched"][
        ["espn_game_id", "home_team_id", "away_team_id", "tip", "time_state", "neutral"]
    ]
    old_games = games.drop(columns=["neutral"])  # the old code never read it
    f_old, s_old = run_score(old_ps, inp, a, old_games)
    f_new, s_new = run_score(new_ps, inp, a, games)
    pre = new_ps.pregame(inp["recs"], None)
    checks = new_ps.orientation_checks(pre, games)
    swapped = sorted(g for g, c in checks.items() if c.status.value == "SWAPPED")
    unverified = {int(g): c.reason for g, c in checks.items() if c.status.value == "UNVERIFIED"}
    pg_o, pg_n = f_old["paired_games"], f_new["paired_games"]
    gate_o = f_old["integrity_gate"].set_index("espn_game_id")
    gate_n = f_new["integrity_gate"].set_index("espn_game_id")
    changed_gate = sorted(int(g) for g in gate_o.index.union(gate_n.index)
                          if (gate_o.status.get(g), gate_o.reasons.get(g)) != (gate_n.status.get(g), gate_n.reasons.get(g)))  # fmt: skip
    out: dict[str, Any] = {
        "records_read": len(inp["recs"]),
        "completed_games": int(len(inp["res"])),
        "reversed_neutral_games": swapped,
        "unverified_identity_games": unverified,
        "gate_rows_that_differ": changed_gate,
        "gate_changes": {
            int(g): {
                "old": [gate_o.status.get(g), gate_o.reasons.get(g)],
                "new": [gate_n.status.get(g), gate_n.reasons.get(g)],
            }
            for g in changed_gate
        },  # fmt: skip
        "paired_games": frames_equal(pg_o, pg_n, ["orientation"], "espn_game_id", set(swapped)),
        "integrity_gate_unaffected_rows": frames_equal(
            f_old["integrity_gate"], f_new["integrity_gate"], [], "espn_game_id", set(swapped)
        ),  # fmt: skip
        "team_games_unaffected": frames_equal(
            f_old["team_games"], f_new["team_games"], [], "espn_game_id", set(swapped)
        ),  # fmt: skip
        "gate_counts_old": s_old["gate"]["counts"],
        "gate_counts_new": s_new["gate"]["counts"],
        "settled_paired_games_old": s_old["settled_paired_games"],
        "settled_paired_games_new": s_new["settled_paired_games"],  # fmt: skip
    }
    for g in swapped:
        po = pg_o[pg_o.espn_game_id == g]
        pn = pg_n[pg_n.espn_game_id == g]
        res = inp["res"].set_index("espn_game_id").result_margin.get(g)
        out.setdefault("reversed_games_detail", {})[int(g)] = {
            "schedule_margin_for_schedule_home": res,
            "old_in_paired_games": bool(len(po)),
            "new_result_margin_for_projected_home": float(pn.result_margin.iloc[0]) if len(pn) else None,
            "new_base_margin": float(pn.base_margin.iloc[0]) if len(pn) else None,
            "new_base_err": float(pn.base_err.iloc[0]) if len(pn) else None,
            "new_gate": pn.gate_status.iloc[0] if len(pn) else None,
            "new_gate_reasons": pn.gate_reasons.iloc[0] if len(pn) else None,
        }  # fmt: skip
    # B. fail closed: perturb schedule inputs in memory for real games, old AND new code
    perturb: dict[str, Any] = {}
    plain = [g for g in pg_n.espn_game_id if g not in swapped][:1]
    cases: list[tuple[str, int, dict[str, Any]]] = []
    if swapped:
        cases.append(("reversed_game_marked_non_neutral", swapped[0], {"neutral": False}))
        cases.append(("reversed_game_neutral_unknown", swapped[0], {"neutral": None}))
    if plain:
        other = next(t for t in sorted(inp["d1"]) if t not in (games.set_index("espn_game_id").loc[plain[0], ["home_team_id", "away_team_id"]].tolist()))  # fmt: skip
        cases.append(("different_away_team", plain[0], {"away_team_id": other}))
        cases.append(("unresolved_schedule_team_id", plain[0], {"away_team_id": None}))
        cases.append(
            ("projected_game_reversed_at_non_neutral_site", plain[0], {"__reverse__": True})
        )
    for name, gid, change in cases:
        recs_ = games.to_dict("records")  # plain python rows: no dtype coercion surprises
        row = next(x for x in recs_ if x["espn_game_id"] == gid)
        if change.get("__reverse__"):
            row["home_team_id"], row["away_team_id"] = row["away_team_id"], row["home_team_id"]
            row["neutral"] = False
        else:
            row.update(change)
        gm = pd.DataFrame(recs_, columns=list(games.columns))
        gm["neutral"] = pd.Series([x["neutral"] for x in recs_], dtype=object, index=gm.index)
        r: dict[str, Any] = {}
        for tag, mod, gframe, kw in (
            ("old", old_ps, gm.drop(columns=["neutral"]), {}),
            ("new", new_ps, gm, {}),
        ):
            fr, _ = run_score(mod, inp, a, gframe, **kw)
            row = fr["integrity_gate"].set_index("espn_game_id")
            r[tag] = {"status": row.status.get(gid), "reasons": row.reasons.get(gid),
                      "in_scored_pairs": bool(gid in set(fr["paired_games"].query("gate_status == 'VALID'").espn_game_id))}  # fmt: skip
        perturb[name] = {"game": int(gid), **r}
    out["fail_closed_perturbations"] = perturb
    return out


# ------------------------------------------------------------------------------- C Kalshi
def kalshi(a: argparse.Namespace, old_sel: Any, ref: str) -> dict[str, Any]:
    from cbb_edge.app.sift_app import selection as S
    from cbb_edge.app.sift_app.__main__ import load_world
    from cbb_edge.app.sift_app.build import games_frame
    from cbb_edge.data.ids.orientation import check_record
    from cbb_edge.kalshi import history as H
    from cbb_edge.kalshi.semantics import probability, settle

    old_proj = old_projections_fn(ref, old_sel)
    ns = argparse.Namespace(season=2027, schedule_archive=str(a.schedule), schedule_parquet=None,
                            projections=str(a.projections), rosters=None, scores=None, kalshi=None, code_sha=None)  # fmt: skip
    w = load_world(ns, pd.Timestamp(a.now))
    games, _ = games_frame(w)
    by_game: dict[int, list] = {}
    for r in w.records:
        by_game.setdefault(int((r.get("game") or {}).get("espn_game_id")), []).append(r)
    n = diff = 0
    differing: dict[int, Any] = {}
    for g in games.to_dict("records"):
        recs = by_game.get(int(g["espn_game_id"]))
        if not recs:
            continue
        at = pd.Timestamp(g["start"]) - pd.Timedelta(minutes=1)
        o = old_proj(g, recs, w, at)
        nw = H._projections(g, recs, w, at)
        n += 1
        o_cmp = {k: v for k, v in o.items()}
        n_cmp = {k: v for k, v in nw.items() if k != "reoriented_versions"}
        if o_cmp != n_cmp:
            diff += 1
            differing[int(g["espn_game_id"])] = {
                "old_versions": sorted(o["versions"]), "new_versions": sorted(nw["versions"]),
                "old_identity_changed": o["identity_changed_versions"], "new_identity_changed": nw["identity_changed_versions"],
                "reoriented": nw.get("reoriented_versions"),
            }  # fmt: skip
    # settlement + probabilities on the panel archive
    swapped = {gid for gid, d in differing.items() if d["reoriented"]}
    scores = {int(g["espn_game_id"]): (int(g["home_score"]), int(g["away_score"])) for g in games.to_dict("records")
              if g["completed"] and g["home_score"] is not None}  # fmt: skip
    agree = dis = notchk = 0
    agree_sw = dis_sw = 0
    last: dict[str, dict[str, Any]] = {}
    for pth in sorted(a.panel.glob("panels/**/*.panel.jsonl.gz")):
        with gzip.open(pth, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                gid, sem, res = r.get("espn_game_id"), r.get("contract_semantics"), r.get("result")
                if gid is None or sem is None:
                    continue
                gid = int(gid)
                if res in ("yes", "no") and gid in scores:
                    exp, _ = settle(sem, *scores[gid])
                    if exp is None:
                        notchk += 1
                    elif exp == res:
                        agree += 1
                        agree_sw += gid in swapped
                    else:
                        dis += 1
                        dis_sw += gid in swapped
                if gid in swapped and r.get("market_phase") == "PRETIP":
                    last[r["kalshi_ticker"]] = r
    # probabilities for the reversed games: reframed projections vs the (wrong-direction) raw ones
    brier = {"reframed": [], "raw_unframed": [], "stored_in_panel": 0}
    for r in last.values():
        gid = int(r["espn_game_id"])
        gdict = next(x for x in games.to_dict("records") if int(x["espn_game_id"]) == gid)
        tip = pd.Timestamp(gdict["start"])
        sel = S.select(
            by_game[gid], H.clock_of(gdict), pd.Timestamp(r["captured_at"]), S.roles(w.active)
        )
        sem, res = r["contract_semantics"], r.get("result")
        if res not in ("yes", "no") or sem.get("status") != "parsed" or sem.get("period") != "FULL":
            continue
        brier["stored_in_panel"] += sum(1 for v in (r.get("market_specific_model_probability") or {}).values() if v.get("probability") is not None)  # fmt: skip
        for ver in sel.reorientable:
            rec = sel.chosen[ver].record
            from cbb_edge.data.ids.orientation import reframe_projection

            proj = rec["projection"]
            y = 1.0 if res == "yes" else 0.0
            for key, p in (
                ("reframed", reframe_projection(sel.orientation[ver], proj)),
                ("raw_unframed", proj),
            ):
                pr, _ = probability(sem, p)
                if pr is not None and tip > pd.Timestamp(r["captured_at"]):
                    brier[key].append((pr - y) ** 2)
    _ = check_record
    return {
        "games_with_frozen_records_compared": n,
        "games_where_old_and_new_selection_differ": diff,
        "differing_games": differing,
        "settlement_all_settled_panel_contracts": {
            "agree": agree,
            "disagree": dis,
            "not_checkable": notchk,
            "agree_on_reversed_games": agree_sw,
            "disagree_on_reversed_games": dis_sw,
        },  # fmt: skip
        "reversed_games_probability_brier": {
            k: (sum(v) / len(v) if isinstance(v, list) and v else None)
            for k, v in brier.items()
            if k != "stored_in_panel"
        }
        | {
            "n_contracts": len(brier["reframed"]),
            "stored_nonnull_probabilities_in_old_panel": brier["stored_in_panel"],
        },  # fmt: skip
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for k in ("projections", "rosters", "schedule", "espn", "panel", "out"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    ap.add_argument("--now", required=True)
    ap.add_argument("--baseline-ref", required=True)
    a = ap.parse_args()
    old_ps = load_old_module(
        a.baseline_ref, "cbb_edge/rosters/prospective_score.py", "old_prospective_score"
    )
    old_sel = load_old_module(a.baseline_ref, "cbb_edge/app/sift_app/selection.py", "old_selection")
    from cbb_edge.rosters import prospective_score as new_ps

    res = {
        "baseline_ref": a.baseline_ref,
        "now": a.now,
        "archive_heads": {
            k: subprocess.run(
                ["git", "-C", str(getattr(a, k)), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            for k in ("projections", "rosters")
        },  # fmt: skip
        "scoreboard": scoreboard(a, old_ps, new_ps),
        "kalshi": kalshi(a, old_sel, a.baseline_ref),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "orientation_comparison.json").write_text(
        json.dumps(res, indent=1, sort_keys=True, default=str) + "\n"
    )
    print(json.dumps(res, indent=1, sort_keys=True, default=str)[:6000])


if __name__ == "__main__":
    main()
