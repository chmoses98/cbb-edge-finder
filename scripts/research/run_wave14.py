"""Wave 14: audit model_inputs, verify archive integrity, evaluate eligible prospective games (read-only)."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from cbb_edge.model import pw_level as pw
from cbb_edge.research import freeze_provenance as fp
from cbb_edge.research import wave1 as w
from cbb_edge.research import wave13 as w13
from cbb_edge.research import wave14 as w14


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projections", required=True, type=Path)
    ap.add_argument("--schedule", required=True, type=Path)
    ap.add_argument("--espn", type=Path, help="espn-lines-archive checkout (benchmark only)")
    ap.add_argument(
        "--provenance",
        type=Path,
        default=Path("research/wave14/freeze_provenance.json"),
        help="OUTPUT: regenerated from --projections git history + --evidence (fail closed)",
    )
    ap.add_argument(
        "--evidence",
        type=Path,
        default=Path("research/wave14/provenance_evidence.json"),
        help="saved GitHub Actions job records (server-side step times)",
    )
    ap.add_argument(
        "--fetch-evidence",
        metavar="OWNER/REPO",
        help="append newer job records from the GitHub REST API first (needs GITHUB_TOKEN)",
    )
    ap.add_argument(
        "--crosscheck", type=Path, default=Path("research/wave14/outcome_crosscheck.json")
    )
    ap.add_argument("--out", type=Path, default=Path("research/wave14"))
    ap.add_argument("--report", type=Path, default=Path("research/reports/WAVE14_PRIOR_WEIGHT.md"))
    a = ap.parse_args()
    frozen = {v: w.load_frozen(a.projections, v) for v in w14.VERSIONS}
    base = frozen[pw.BASE_VERSION]
    inputs = w14.load_inputs(a.projections)
    cov = w14.attach_inputs(base, inputs)
    finals, orient = w13.load_finals_oriented(a.schedule, base)
    ev = json.loads(a.evidence.read_text()) if a.evidence.exists() else {"jobs": []}
    if a.fetch_evidence:
        new = fp.fetch_evidence(
            a.fetch_evidence,
            w14.PROSPECTIVE_FROM[:10],
            known_run_ids={j["run_id"] for j in ev.get("jobs") or []},
            token=os.environ.get("GITHUB_TOKEN"),
        )
        print(
            {k: new[k] for k in ("runs_listed", "runs_read")}, len(new["jobs"]), "new job records"
        )
        ev = {**ev, "source": new["source"], "fetched_at": new["fetched_at"]}
        ev["jobs"] = fp.merge_evidence(ev, new["jobs"])
        a.evidence.write_text(json.dumps(ev, indent=1) + "\n")
    prov = fp.build(a.projections, ev, w.parse_ts(w14.PROSPECTIVE_FROM))  # type: ignore[arg-type]
    a.provenance.parent.mkdir(parents=True, exist_ok=True)
    a.provenance.write_text(json.dumps(prov, indent=1) + "\n")
    pushed = w14.freeze_pushed_at(frozen, w14.record_manifests(a.projections), prov)
    rows, funnel = w14.build_rows(frozen, finals, pushed=pushed)
    mk_audit: dict = {"espn_archive": None}
    if a.espn is not None:
        market, orient_mk = w13.orient_market(w.load_espn_lines(a.espn), base)
        mk_audit = {"orientation": orient_mk, "eligible_rows": w14.attach_market(rows, market)}
    cut = w.parse_ts(w14.PROSPECTIVE_FROM)
    post = [g for g in base.values() if g["as_of"] >= cut]  # type: ignore[operator]
    last = [g for g in base.values() if g["pbar"] is not None and g["game_id"] in finals]
    state = pw.fit([{"x": g["pbar"] * g["poss"], "total_err": finals[g["game_id"]]["home"] + finals[g["game_id"]]["away"] - g["total"]} for g in last])  # fmt: skip
    res = {
        "prospective_from": w14.PROSPECTIVE_FROM,
        "archive_integrity": w14.verify_manifests(a.projections),
        "input_audit": w14.input_audit(a.projections),
        "input_validity_pure050_games": dict(cov["issues"]),
        "prior_weight_reliability": w14.reliability(base, inputs),
        "orientation_audit": {k: orient[k] for k in ("status", "excluded")},
        "eligibility_funnel": funnel,
        "verdict": w14.verdict(rows),
        "summary_eligible": w14.summarize(rows),
        "descriptive_contrasts_NOT_VERDICT": w14.descriptive_contrasts(rows) if rows else {},
        "market_benchmark": {"audit": mk_audit, "summary": w14.market_summary(rows)},
        "freeze_provenance_manifests": sorted(k for k in prov if not k.startswith("_")),
        "freeze_provenance_unverified": prov["_unverified"],
        "pending_finals_diagnostic": w14.pending_finals(base, finals, a.schedule),
        "outcome_crosscheck": _crosscheck(a.crosscheck, rows),
        "post_boundary_records": {
            "games": len(post),
            "with_final": sum(g["game_id"] in finals for g in post),
            "tips_by_et_date": dict(sorted(Counter(w.et_date(g["tip"]) for g in post).items())),
        },
        "eligible_games": [
            {
                "game_id": r["game_id"],
                "date": r["date"],
                "tip": r["tip"],
                "as_of": r["as_of"],
                "pushed_by": pushed[r["game_id"]]["pushed_by"],
                "final_proj_frame": [r["actual_margin"], r["actual_total"]],
                "orientation": finals[r["game_id"]]["orientation"],
                "pbar": r["pbar"],
                "beta": r["beta"],
                "n_train": r["n_train"],
                "total_err": {
                    k: r[k]["total_err"] for k in (*w14.FORECASTERS, w14.MARKET) if k in r
                },
            }
            for r in rows
        ],  # fmt: skip
        "beta_state_now_all_valid_input_finished_games_NOT_EVALUATION": state,
        "n_valid_input_games_with_final": len(last),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "wave14_results.json").write_text(
        json.dumps(res, indent=1, sort_keys=True, default=str) + "\n"
    )
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(render(res))
    print(res["verdict"]["status"], funnel)


def _crosscheck(path: Path, rows: list) -> dict:
    """Graded finals re-observed later (``outcome_crosscheck.json``): how many match / are missing."""
    if not path.exists():
        return {"file": None}
    d = json.loads(path.read_text())
    got = {g["game_id"]: g for g in d["games"]}
    by = Counter(
        "not_rechecked" if r["game_id"] not in got
        else "match" if (got[r["game_id"]]["home"] - got[r["game_id"]]["away"], got[r["game_id"]]["home"] + got[r["game_id"]]["away"]) == (r["actual_margin"], r["actual_total"])
        else "MISMATCH"
        for r in rows
    )  # fmt: skip
    return {"file": str(path), "fetched_at": d.get("fetched_at"), "graded_finals": dict(by)}


PENDING_CLASSES = ("capture_lag", "tip_after_last_capture", "no_final_after_expected_end")


def _ci(c: dict) -> str:
    return f"{c['diff']:+.3f} [{c['lo']:+.3f}, {c['hi']:+.3f}]"


def render(r: dict) -> str:
    v, f = r["verdict"], r["eligibility_funnel"]
    ia, pb = r["input_audit"], r["post_boundary_records"]
    lines = [
        "# Wave 14 - prior-weight scoring-level challenger (prospective)", "",
        "Generated by `scripts/research/run_wave14.py`; protocol `research/hypotheses/WAVE14.md`. RESEARCH_ONLY. "
        "Nothing is promoted; no production model, default or prediction is changed.", "",
        f"## Status: **{v['status']}**", "",
        f"Eligible games: {v['n_games']} on {v['n_dates']} dates (floor {v['floor']['games']} games / {v['floor']['dates']} dates). "
        f"Prospective boundary {r['prospective_from']}.", "",
        "### Against the preregistered decision rule (WAVE14.md section 6)", "",
        "| criterion | required | now |", "|---|---|---|",
        f"| sample floor | >= {v['floor']['games']} games on >= {v['floor']['dates']} ET dates | {v['n_games']} games on {v['n_dates']} date(s): NOT MET |"
        if v["n_games"] < v["floor"]["games"] or v["n_dates"] < v["floor"]["dates"] else
        f"| sample floor | >= {v['floor']['games']} games on >= {v['floor']['dates']} ET dates | {v['n_games']} / {v['n_dates']}: met |",
        "| total MAE vs pure-0.5.0 | 90% date-clustered upper bound < 0 | not evaluated (below floor) |" if "checks" not in v else
        f"| total MAE vs pure-0.5.0 | upper bound < 0 | {v['checks']['total_mae_improves_vs_pure050']} |",
        "| total MAE vs Wave 12 level-only | upper bound <= +0.10 | not evaluated (below floor) |" if "checks" not in v else
        f"| total MAE vs Wave 12 level-only | upper bound <= +0.10 | {v['checks']['no_regression_vs_w12_level']} |",
        "| margin MAE / log loss guards | upper bounds <= +0.10 / +0.005 | not evaluated (below floor) |" if "checks" not in v else
        f"| margin MAE / log loss guards | upper bounds <= +0.10 / +0.005 | {v['checks']['margin_and_calibration_guards']} |",
        "", "Even IMPROVED would be exploratory-prospective only; promotion stays governed by `research/hypotheses/WAVE4.md`.", "",
        "## Eligibility funnel (pure-0.5.0 games, latest frozen record before tip)", "", "| stage | games |", "|---|---|",
        *[f"| {k} | {n} |" for k, n in sorted(f.items())], "",
        f"Post-boundary records (as_of >= boundary): {pb['games']} games, {pb['with_final']} with an archived, orientation-verified final; "
        f"tips by ET date {pb['tips_by_et_date']}.", "",
        "## Freeze provenance", "",
        "A game is graded only if every compared record (pure-0.2.0, pure-0.5.0, roster) has `as_of` < tip AND sits in a hashed "
        "manifest whose push to `origin/projections-archive` is proven before the tip by GitHub server-side Actions step "
        f"timestamps (`research/wave14/freeze_provenance.json`, regenerated on every run by `cbb_edge.research.freeze_provenance` "
        "from the archive git history and the saved job records in `research/wave14/provenance_evidence.json`; the job's head_sha "
        f"must equal the manifest code_sha and its append-step window must contain the archive commit; manifests verified: {', '.join(r['freeze_provenance_manifests']) or 'none'}). "
        "Missing evidence excludes the game (`freeze_time_not_provable`). This check is stricter than registration and was added "
        "2026-11-13 (automated the same day); it can only remove games.", "",
        f"Unverified post-boundary manifests (records excluded): {r['freeze_provenance_unverified'] or 'none'}.", "",
        "## Games awaiting an archived final (diagnostic only; never changes eligibility)", "",
        f"Schedule archive last written {r['pending_finals_diagnostic']['schedule_archive_last_observed_at']}. "
        "`capture_lag` = the game tipped before the last archive write, but that write came less than 3 h after the tip, before it could "
        "normally have finished (the next schedule observation run captures it); `tip_after_last_capture` = not yet played at the "
        "last write; `no_final_after_expected_end` = archive written after the expected end with no final (needs a look).", "",
        "| ET date | " + " | ".join(PENDING_CLASSES) + " |", "|---|" + "---|" * len(PENDING_CLASSES),
        *[f"| {d} | " + " | ".join(str(c.get(k, 0)) for k in PENDING_CLASSES) + " |"
          for d, c in r["pending_finals_diagnostic"]["by_et_date"].items()],
        "", f"Needs attention: {r['pending_finals_diagnostic']['needs_attention'] or 'none'}", "",
        f"Outcome cross-check (graded finals re-observed from the public ESPN scoreboard after the archive capture; same "
        f"provider, not an independent organisation): {r['outcome_crosscheck']}", "",
    ]  # fmt: skip
    if r["eligible_games"]:
        lines += [
            "| game | ET date | as_of | pushed by | tip | final (margin, total) | pbar | beta (n train) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += [f"| {e['game_id']} | {e['date']} | {str(e['as_of'])[:19]} | {str(e['pushed_by'])[:19]} | {str(e['tip'])[:19]} | "
                  f"{e['final_proj_frame'][0]:+d}, {e['final_proj_frame'][1]} | {e['pbar']:.3f} | {e['beta']:+.4f} ({e['n_train']}) |" for e in r["eligible_games"]]  # fmt: skip
        lines.append("")
    if r["summary_eligible"]:
        lines += [
            "## Eligible-game metrics (identical games)", "",
            "| forecaster | n | total MAE | total bias | margin MAE | log loss | Brier |", "|---|---|---|---|---|---|---|",
        ]  # fmt: skip
        lines += [f"| {k} | {int(s['n'])} | {s['total_mae']:.3f} | {s['total_bias']:+.3f} | {s['margin_mae']:.3f} | {s['logloss']:.4f} | {s['brier']:.4f} |" for k, s in r["summary_eligible"].items()]  # fmt: skip
        lines += ["", "## Matched-game differences (a - b; negative = a better). DESCRIPTIVE, not the verdict", "",
                  "90% bootstrap, 4000 reps. Date-clustered is the protocol interval; with one ET date it has one cluster and "
                  "collapses to the point estimate, so it carries no uncertainty information. Game-level treats games as "
                  "independent (too narrow when same-day errors correlate).", "",
                  "| contrast | n | date-clustered | game-level |", "|---|---|---|---|"]  # fmt: skip
        lines += [f"| {k} | {int(c['game_level']['n'])} | {_ci(c['date_clustered'])} | {_ci(c['game_level'])} |" for k, c in r["descriptive_contrasts_NOT_VERDICT"].items() if c["game_level"]["n"] > 0]  # fmt: skip
        lines.append("")
    mb = r["market_benchmark"]
    lines += ["## Market benchmark (ESPN/DraftKings pre-tip line; benchmark only, never an input)", "",
              f"Audit: {mb['audit']}", ""]  # fmt: skip
    if mb["summary"]:
        lines += [
            "| forecaster | n | total MAE | total bias | margin MAE | margin bias |",
            "|---|---|---|---|---|---|",
        ]
        lines += [f"| {k} | {int(s['n'])} | {s['total_mae']:.3f} | {s['total_bias']:+.3f} | {s['margin_mae']:.3f} | {s['margin_bias']:+.3f} |" for k, s in mb["summary"].items()]  # fmt: skip
        lines += [
            "",
            "The line has no moneyline in these snapshots, so no market log loss/Brier is computed.",
            "",
        ]
    lines += [
        "## model_inputs coverage by manifest (games with inputs / games, per version)", "",
        "| manifest | code | pure-0.2.0 | pure-0.3.0 | pure-0.4.0 | pure-0.5.0 | pure-0.5.0_roster |", "|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for k, m in list(ia["manifests"].items())[-8:]:
        c = [f"{m['by_version'].get(x, [0, 0, 0])[1]}/{m['by_version'].get(x, [0, 0, 0])[0]}" for x in ("pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0", "pure-0.5.0_roster")]  # fmt: skip
        lines.append(f"| {k} | {m['code_sha']} | " + " | ".join(c) + " |")
    bs = r["beta_state_now_all_valid_input_finished_games_NOT_EVALUATION"]
    lines += ["", f"Archive integrity: {r['archive_integrity']}", "", f"Input validity (pure-0.5.0 games): {r['input_validity_pure050_games']}",
              "", f"Prior-weight reliability: {r['prior_weight_reliability']}", "",
              f"Orientation audit (finals): {r['orientation_audit']['status']}; excluded {len(r['orientation_audit']['excluded'])}.", "",
              f"beta using every valid-input game with an archived final (NOT an evaluation; n={bs.get('n_games')}): "
              f"{bs.get('beta')} (raw {bs.get('raw_beta')}).", ""]  # fmt: skip
    if v.get("reason"):
        lines += [f"Verdict reason: {v['reason']}", ""]
    if "contrasts" in v:
        lines += [
            "## Verdict contrasts (challenger - comparator; date-clustered 90% bootstrap)",
            "",
        ]
        lines += [f"- {k}: {c['diff']:+.3f} [{c['lo']:+.3f}, {c['hi']:+.3f}] (n={int(c['n'])}, dates={int(c['n_dates'])})" for k, c in v["contrasts"].items()]  # fmt: skip
        lines += ["", f"Checks: {v['checks']}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
