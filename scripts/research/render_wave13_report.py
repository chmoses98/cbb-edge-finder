"""Render research/reports/WAVE13_GAME_NUMBER.md from run_wave13.py output (numbers only from the JSON).

python scripts/research/render_wave13_report.py research/wave13 research/reports/WAVE13_GAME_NUMBER.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

W13, W12L = "wf13-hier-level-0.5.0-v1", "wf-level-only"
NAMES = {
    "pure-0.2.0": "pure-0.2.0 (incumbent)", "pure-0.5.0": "pure-0.5.0", "pure-0.5.0_roster": "pure-0.5.0+roster",
    W12L: "Wave 12 level-only", W13: "**Wave 13 hierarchical**", "wf13-independent": "ablation: independent groups",
    "wf13r": "Wave 13 on roster base", "market": "ESPN line (benchmark)",
}  # fmt: skip


def f(x, d=2):
    return "–" if x is None else f"{x:.{d}f}"


def ci(p, d=3):
    return f"{p['diff']:+.{d}f} [{p['lo']:+.{d}f}, {p['hi']:+.{d}f}]"


def table(h, rows):
    return "\n".join(
        ["| " + " | ".join(h) + " |", "|" + "|".join("---" for _ in h) + "|"]
        + ["| " + " | ".join(r) + " |" for r in rows]
    )


def main() -> None:
    d, out = Path(sys.argv[1]), Path(sys.argv[2])
    r = json.loads((d / "wave13_results.json").read_text())
    e, dec, au = r["exploratory"], r["decision"], r["orientation_audit"]
    L = []
    a = L.append
    a(
        "# Wave 13 — orientation identity, exported inputs, hierarchical level challenger (2026-11-10)\n"
    )
    a(f"**Decision: {dec['label']}** ({dec['evidence_class']}). RESEARCH_ONLY; nothing promoted; PR #46 / Wave 12 "
      "protocol, report and evidence are unchanged. Protocol and decision rule: `research/hypotheses/WAVE13.md` "
      "(committed before any number below existed).\n")  # fmt: skip
    a("## 1. Orientation identity (Priority 1)\n")
    a("`cbb_edge/data/ids/orientation.py` decides, per game and BEFORE scoring, whether the schedule's home/away order equals the "
      "projection's by canonical team id: `SAME`, `SWAPPED` (same two teams reversed on a neutral site: scores are mapped onto the "
      "projected teams), or `UNVERIFIED` (unresolved id, different team set, missing ids, reversal at a non-neutral site → excluded, never "
      "guessed). Archived projections and schedule rows are not rewritten. ESPN lines are oriented by the same identity.\n")  # fmt: skip
    a(f"Audit on the scored window: {au['status']}; excluded (unverifiable): {len(au['excluded'])}; swapped and correctly remapped: "
      f"`{au['swapped']}` — the four Wave 12 games, now scored correctly instead of excluded (Wave 12's 359 + 4 = {r['scored_games_total']} scored games). "
      f"ESPN lines: {r['market_orientation_audit']}. Regression tests: `tests/test_orientation.py` (the four games, fail-closed cases).\n")  # fmt: skip
    a("## 2. Exported modelling inputs (Priority 2)\n")
    a("New prospective records now carry an additive `model_inputs` block (`cbb_edge/app/model_inputs.py`, tests `tests/test_model_inputs.py`): per team "
      "game number, games and possessions seen, expected tempo and tempo effect, efficiency league mean / offense / defense effects, pace and "
      "efficiency prior-vs-current weight and effective sample (basis `ridge_diagonal_approx`, stated), pace/efficiency posterior SD from "
      "within-team noise of the current-season games before `as_of`, days since last game, data freshness (`info_cutoff_utc`, `info_rows`). Missing values are "
      "`null` with a reason (e.g. the prior-season rating value and the exact posterior covariance are not exposed by the engine state rows). Old "
      "records are not back-filled, so **none of these fields exist for the evaluated window**; the live path was unit-tested on synthetic frames only "
      "(the data lake is not available in this environment), and a failure in the block is recorded as `missing`, never blocks a projection.\n")  # fmt: skip
    a("## 3. Level challengers (Priority 3)\n")
    a(f"`{W13}`: pooled level + shrunk group deviations for team game 1 / 2 / 3+ (`n0=30`, `n_tau=100`, fixed in advance), no SD rescale, margin untouched. "
      f"Eligible games (all forecasters defined, ESPN line oriented): **{e['n']}** on {len(e['dates'])} dates: {e['dates']}. "
      "All numbers are exploratory (WAVE13.md §1).\n")  # fmt: skip
    rows = []
    for n in (
        "pure-0.2.0",
        "pure-0.5.0",
        "pure-0.5.0_roster",
        W12L,
        W13,
        "wf13-independent",
        "wf13r",
        "market",
    ):
        t = e["table"][n]
        x = t.get("p_normal") or t["point"]
        rows.append([NAMES[n], f(x["margin_mae"]), f(x["margin_rmse"]), f(x["margin_bias"]), f(x["total_mae"]), f(x["total_rmse"]), f(x["total_bias"]),
                     f(x.get("brier"), 4) if "brier" in x else "–", f(x.get("logloss"), 4) if "logloss" in x else "–",
                     f(x.get("margin_cover90")) if "margin_cover90" in x else "–", f(x.get("total_cover90")) if "total_cover90" in x else "–"])  # fmt: skip
    a(
        table(
            [
                "forecaster",
                "margin MAE",
                "margin RMSE",
                "margin bias",
                "total MAE",
                "total RMSE",
                "total bias",
                "Brier",
                "log loss",
                "margin cover90",
                "total cover90",
            ],
            rows,
        )
        + "\n"
    )
    a(
        "Paired differences on identical games (negative = first-named better; 90% game-bootstrap interval):\n"
    )
    rows = []
    for k, lab in (("paired_vs_pure-0.5.0", "Wave 13 − pure-0.5.0"), ("paired_vs_wave12_level_only", "Wave 13 − Wave 12 level-only"),
                   ("paired_vs_roster", "Wave 13 − roster"), ("paired_vs_incumbent", "Wave 13 − pure-0.2.0"), ("paired_vs_market", "Wave 13 − ESPN line"),
                   ("wave12_level_only_vs_pure-0.5.0", "Wave 12 level-only − pure-0.5.0"), ("independent_vs_hierarchical", "independent groups − hierarchical"),
                   ("wave13r_vs_roster", "Wave 13 on roster − roster")):  # fmt: skip
        p = e[k]
        rows.append(
            [
                lab,
                ci(p["margin_abs"], 2),
                ci(p["total_abs"], 2),
                ci(p["total_sq"], 1),
                ci(p["logloss"], 4) if "logloss" in p else "–",
            ]
        )
    a(table(["comparison", "margin |e|", "total |e|", "total e²", "log loss"], rows) + "\n")
    a("### Game-number slices (team game = min games seen + 1) and dates\n")
    for key, lab in (("by_team_game_number", "Team game number"), ("by_date", "Date (ET)")):
        rows = []
        for k, v in e["slices"][key].items():
            rows.append([k, str(v["n"])] + [f"{f(v[n]['total_mae'])} / {f(v[n]['total_bias'])}" for n in ("pure-0.5.0", W12L, W13, "market")] + [ci(v["paired_total_abs_w13_vs_0.5.0"], 2)])  # fmt: skip
        a(f"**{lab}** — total MAE / bias\n")
        a(
            table(
                [
                    lab,
                    "n",
                    "pure-0.5.0",
                    "Wave 12 level-only",
                    "Wave 13",
                    "ESPN",
                    "Wave 13 − 0.5.0 total |e|",
                ],
                rows,
            )
            + "\n"
        )
    s = r["state_first_last"]["state_last"]
    a(f"Final fitted state ({s['n_games']} finished games; group counts {s['group_counts']}): raw group means per possession "
      f"{[None if x is None else round(x, 4) for x in s['raw_group_mean_per_poss']]}, shrunk levels {[round(x, 4) for x in s['lambda_per_poss_by_group']]}. "
      "Team game 3+ has very few games, so its raw mean (opposite sign) is barely allowed to move its level — by design. This is not evidence of a "
      "stable or causal game-number effect.\n")  # fmt: skip
    pr = r["prospective"]
    a(f"## Prospective validation\n\nGames with tip ≥ `{pr['from']}` that meet the same eligibility: **{pr['n']}**. IMPROVED requires ≥150 on ≥5 dates "
      "(WAVE13.md §5). Re-run `scripts/research/run_wave13.py` on later archives to populate it; the rule is a deterministic function of the immutable archives.\n")  # fmt: skip
    a("## Decision\n")
    a(
        table(
            ["criterion", "met"], [[k, "yes" if v else "**no**"] for k, v in dec["rules"].items()]
        )
        + "\n"
    )
    p12, p5 = e["paired_vs_wave12_level_only"], e["paired_vs_pure-0.5.0"]
    a(f"**{dec['label']}.** Under the preregistered rule the hierarchical rule's total MAE is {ci(p12['total_abs'], 3)} versus Wave 12 level-only "
      f"(worse, interval excludes 0) and {ci(p5['total_abs'], 3)} versus pure-0.5.0 (interval includes 0). Its total bias "
      f"({f(e['table'][W13]['point']['total_bias'])}) is also larger than level-only's ({f(e['table'][W12L]['point']['total_bias'])}): "
      "the four-parameter ridge shrinks the *sum* of pooled level and group deviation more than Wave 12's single level does, so it under-corrects "
      "the dominant groups while only partly protecting the thin group. The independent-groups ablation is not better. The hierarchy therefore buys no accuracy; "
      "**Wave 12 level-only remains the better level baseline**, and the hyperparameters were not tuned after seeing this (a retune would need a new protocol "
      "and genuinely future games). Margin and winner metrics are identical to pure-0.5.0 by construction (level only).\n")  # fmt: skip
    c = r["score_distribution_coherence"]
    a("## 4. Market-coverage foundation (Priority 4)\n")
    a("**Audit of existing infrastructure.** `team_score_joint.py` fits team-score variances and the home/away covariance from independent settled games (shadow, "
      "unvalidated); `period_forecast.py` gives a first-half MEAN share only (no variance); `kalshi/research/target_means.py` exposes team-total means only; the contract "
      "table marks half, team-total, overtime, race and prop contracts unmodelled. Nothing there gives coherent full-game team-score probabilities from frozen records.\n")  # fmt: skip
    a("**Implemented** `cbb_edge/model/score_distribution.py`: one bivariate normal over (home, away) from the frozen margin, total and their SDs, assuming uncorrelated "
      "total and margin errors. By construction mean and variance recompose exactly into total and margin, team-total / spread / total / moneyline probabilities come from "
      "the same distribution, ladders are monotone, and it equals the existing contract pricer on WINNER / MARGIN / TOTAL (`tests/test_score_distribution.py`, incl. Monte Carlo). "
      "Halves, other periods, overtime and players return `Unmodeled(reason)`: no half or player distribution is fabricated.\n")  # fmt: skip
    a(f"**Check against realised results** ({c['n_games']} games, pure-0.5.0): implied team-score SD {f(c['implied_team_score_sd_mean'])} vs empirical "
      f"{f(c['empirical_home_score_sd'])} (home) / {f(c['empirical_away_score_sd'])} (away); implied home/away error correlation {f(c['implied_corr_home_away_errors'])} vs "
      f"empirical {f(c['empirical_corr_home_away_errors'])}; 90% team-score interval coverage {f(c['team_score_90pct_interval_coverage'])}; correlation of total error and "
      f"margin error {f(c['corr_total_err_margin_err'])} (90% CI [{f(c['corr_total_err_margin_err_ci90'][0], 3)}, {f(c['corr_total_err_margin_err_ci90'][1], 3)}]) — the "
      "uncorrelated assumption is borderline-supported (the interval just reaches 0), so team-total outputs stay `SHADOW_UNVALIDATED`, are not wired into the "
      "contract table, and no market result is claimed for them.\n")  # fmt: skip
    a("## Reproduce\n")
    a("```bash\n"
      "# same archive checkouts as Wave 12 (projections-archive, schedule-archive, espn-lines-archive)\n"
      "python scripts/research/run_wave13.py --projections $WORK/proj --schedule $WORK/sched --espn $WORK/espn --out research/wave13\n"
      "python scripts/research/render_wave13_report.py research/wave13 research/reports/WAVE13_GAME_NUMBER.md\n```\n"
      "Committed outputs are the 2026-11-10 snapshot; archives are append-only so later runs include later games.\n")  # fmt: skip
    out.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
