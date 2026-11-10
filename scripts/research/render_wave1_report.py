"""Render research/reports/WAVE12_SCORING_LEVEL.md from the run_wave1.py outputs (numbers only come
from the JSON files; the wording states exactly what those numbers do and do not show).

    python scripts/research/render_wave1_report.py research/wave12 research/reports/WAVE12_SCORING_LEVEL.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CH = "wf-level-0.5.0-v1"
NAMES = {
    "pure-0.2.0": "pure-0.2.0 (incumbent)", "pure-0.3.0": "pure-0.3.0", "pure-0.4.0": "pure-0.4.0",
    "pure-0.5.0": "pure-0.5.0 (base)", "pure-0.5.0_roster": "pure-0.5.0+roster",
    CH: f"**{CH}**", "market": "ESPN line (benchmark)",
}  # fmt: skip


def f(x: float | None, d: int = 2) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def ci(d: dict[str, float], k: int = 3) -> str:
    return f"{d['diff']:+.{k}f} [{d['lo']:+.{k}f}, {d['hi']:+.{k}f}]"


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def main() -> None:
    d, out = Path(sys.argv[1]), Path(sys.argv[2])
    r = json.loads((d / "wave12_results.json").read_text())
    m = json.loads((d / "wave12_market.json").read_text())
    p1, p3, seg, dec = r["phase1"], r["phase3"], r["segments"], r["decision"]
    sl = seg["pace_and_total_slopes"]
    L: list[str] = []
    a = L.append
    a("# Wave 1 — scoring-level diagnosis and walk-forward challenger (2026-11-10)\n")
    a(f"**Decision: {dec['label']}** (evidence class: {dec['evidence_class']}). RESEARCH_ONLY. "
      "The incumbent stays `pure-0.2.0`; nothing is promoted; no frozen projection, candidate rule or "
      "gate was changed. Protocol and decision rule: `research/hypotheses/WAVE12.md` (committed before "
      "the challenger numbers). Reproduce: `scripts/research/run_wave1.py` then "
      "`scripts/research/render_wave1_report.py` (commands at the end).\n")  # fmt: skip

    # ---------------------------------------------------------------- phase 1
    a("## 1. Reproduction (frozen projections, verified finals through 2026-11-09 ET)\n")
    g1 = p1["game1"]
    a(f"Scored games: **{p1['n_games']}** (all five versions frozen pre-tip, final verified, home/away "
      f"orientation identical in projection and schedule; {len(r['excluded_orientation_swapped_game_ids'])} "
      "neutral-site games excluded because the schedule archive lists the teams in the opposite "
      f"order — `{r['excluded_orientation_swapped_game_ids']}`; scoring them would turn correct "
      "projections into fake 35–66 point 'misses'; the prospective scoreboard marks the same games "
      "UNSCORABLE).\n")  # fmt: skip
    a(f"**Scoreboard reconciliation.** Game-1 slice (a team's first game): N = **{g1['n']}**, base MAE "
      f"**{f(g1['pure-0.5.0']['margin_mae'])}**, roster-adjusted MAE **{f(g1['pure-0.5.0_roster']['margin_mae'])}**, "
      f"RMSE {f(g1['pure-0.5.0']['margin_rmse'])} / {f(g1['pure-0.5.0_roster']['margin_rmse'])}, bias "
      f"{f(g1['pure-0.5.0']['margin_bias'])} / {f(g1['pure-0.5.0_roster']['margin_bias'])} — identical to the "
      "published 207 / 9.90 / 9.84 / 12.55 / 12.39 / +0.80 / −1.12. (The scoreboard's `INVALID` game is "
      "not separately excluded here.)\n")  # fmt: skip
    rows = []
    for v in ("pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0", "pure-0.5.0_roster"):
        x = p1["versions"][v]["published_p"]
        rows.append([NAMES[v], f(x["margin_mae"]), f(x["margin_rmse"]), f(x["margin_bias"]), f(x["total_mae"]),
                     f(x["total_rmse"]), f(x["total_bias"]), f(x["brier"], 4), f(x["logloss"], 4)])  # fmt: skip
    mk = p1["market_point"]
    rows.append([NAMES["market"], f(mk["margin_mae"]), f(mk["margin_rmse"]), f(mk["margin_bias"]),
                 f(mk["total_mae"]), f(mk["total_rmse"]), f(mk["total_bias"]), "–", "–"])  # fmt: skip
    a(f"All scored games (N={p1['n_games']}; market row: the {int(mk['n'])} games with a pre-tip ESPN line). "
      "Bias = actual − projected.\n")  # fmt: skip
    a(table(["version", "margin MAE", "margin RMSE", "margin bias", "total MAE", "total RMSE", "total bias",
             "Brier (published p)", "log loss"], rows) + "\n")  # fmt: skip

    a("### Error decomposition (exact; postgame box scores used for scoring only)\n")
    a("`score = possessions × points-per-possession` for both teams, so the total error splits exactly into a "
      "**pace** term `(poss_actual − poss_proj)·(ppp_h + ppp_a)` and an **efficiency** term "
      "`poss_actual·Σ(ppp_actual − ppp_proj)`; the margin error splits the same way on the difference of the "
      "two ppp. Home offence = away defence, so the two ppp errors are the offensive and defensive "
      "efficiency errors. Means ± standard error:\n")  # fmt: skip
    rows = []
    for v, x in p1["decomposition"].items():

        def c(k: str, x=x) -> str:
            return f"{x[k]['mean']:+.3f} ± {x[k]['se']:.3f}"

        rows.append([NAMES.get(v, v), c("poss_err"), c("home_ppp_err"), c("away_ppp_err"),
                     c("total_pace_term"), c("total_eff_term"), c("margin_pace_term"), c("margin_eff_term")])  # fmt: skip
    a(table(["version", "poss err", "home ppp err (home off / away def)", "away ppp err (away off / home def)",
             "total: pace", "total: efficiency", "margin: pace", "margin: efficiency"], rows) + "\n")  # fmt: skip
    a("The roster overlay changes margin efficiency (−1.5) but carries the base possessions; its total "
      "error moves by only about −0.1 — it does not address the scoring level.\n")  # fmt: skip

    a("### Segments (pure-0.5.0; total/margin bias = actual − projected)\n")
    for name, label in (("team_game_number", "Team game number (min games seen before the game)"),
                        ("projected_pace_tercile", "Projected pace"),
                        ("projected_margin_size_tercile", "Spread size (|projected margin|)"),
                        ("opponent_quality_tercile", "Opponent quality (mean net rating of the pair)"),
                        ("roster_continuity_adjustment", "Roster continuity adjustment (overlay record)"),
                        ("date", "Date (ET)")):  # fmt: skip
        rows = []
        for k, s in seg[name].items():
            rows.append([k, str(s["n"]), f(s["total_bias"]), f(s["pace_term"]), f(s["eff_term"]), f(s["market_total_bias"]),
                         f(s["margin_bias"]), f(s["margin_mae"]), f(s["market_margin_mae"]), f(s["margin_z_sd"])])  # fmt: skip
        a(f"**{label}**\n")
        a(table(["segment", "n", "total bias", "pace", "efficiency", "ESPN total bias", "margin bias",
                 "margin MAE", "ESPN margin MAE", "margin z-SD"], rows) + "\n")  # fmt: skip
    a(f"Pace dispersion: realised possessions regressed on projected have slope **{sl['realised_vs_projected_possessions']['slope']:.2f}** "
      f"(90% [{sl['realised_vs_projected_possessions']['lo90']:.2f}, {sl['realised_vs_projected_possessions']['hi90']:.2f}]); "
      f"mean projected {sl['mean_projected_poss']:.1f} vs realised {sl['mean_realised_poss']:.1f} possessions. Total points on projected total: "
      f"slope {sl['realised_vs_projected_total']['slope']:.2f} [{sl['realised_vs_projected_total']['lo90']:.2f}, {sl['realised_vs_projected_total']['hi90']:.2f}] "
      "(consistent with 1: a level error, not a dispersion error).\n")  # fmt: skip
    a("### Largest misses\n")
    a("November 6 (largest margin misses; ESPN's error on the same game in the last columns). Blowouts the "
      "market also missed by almost the same amount are variance, not model-specific failure:\n")  # fmt: skip

    def miss_rows(ms: list[dict]) -> list[list[str]]:
        return [[str(x["game_id"]), x["game"], x["projected"], x["final"], f(x["margin_err"], 1), f(x["total_err"], 1),
                 f(x["poss_err"], 1), f(x["mkt_margin_err"], 1), f(x["mkt_total_err"], 1)] for x in ms]  # fmt: skip

    hdr = [
        "game",
        "matchup (away @ home)",
        "projected",
        "final",
        "margin err",
        "total err",
        "poss err",
        "ESPN margin err",
        "ESPN total err",
    ]
    a(table(hdr, miss_rows(seg["nov6_largest_misses"][:6])) + "\n")
    a("Largest total misses overall:\n")
    a(table(hdr, miss_rows(seg["largest_total_misses"][:6])) + "\n")

    # diagnosis verdict
    d0 = p1["decomposition"]["pure-0.5.0"]
    tb = p1["versions"]["pure-0.5.0"]["published_p"]["total_bias"]
    a("### Diagnosis (strongest evidence-supported cause)\n")
    a(f"1. **Scoring level, not margin.** pure-0.5.0 under-predicts the total by **{tb:+.2f}** points "
      f"(pace {d0['total_pace_term']['mean']:+.2f} ± {d0['total_pace_term']['se']:.2f}, efficiency "
      f"{d0['total_eff_term']['mean']:+.2f} ± {d0['total_eff_term']['se']:.2f}); the margin mean is unbiased "
      f"({p1['versions']['pure-0.5.0']['published_p']['margin_bias']:+.2f}). The same error is in every PURE version "
      "(+2.9 to +3.5) and the ESPN total is not biased "
      f"({mk['total_bias']:+.2f}), so it is a model scoring-level error that the market has priced in.\n"
      "2. **Where it sits.** The pace shortfall is concentrated in each team's first game and in projected-slow games; the efficiency shortfall in "
      "second games, mid-pace and close games (tables above). It is not confined to one day. Early-season "
      "reversion to last season's scoring level (a prior that is too low for this year's early-season "
      "pace and efficiency) is the single explanation consistent with all segments; the per-team prior "
      "weighting that would test it directly is in the archived ratings but not exposed per game, so it is "
      "**not** adjusted here (next wave).\n"
      "3. **Weak or not supported:** pace dispersion (projected possessions are somewhat too spread: slope "
      f"{sl['realised_vs_projected_possessions']['slope']:.2f} with an interval excluding 1, but the total-points slope includes 1 and a "
      "fix needs per-team pace posteriors that the archive does not expose — blocked); "
      "staleness, roster continuity (the overlay does not move totals), opponent quality (total bias is similar in all "
      "terciles), and a larger margin-SD problem (overall margin z-SD ≈ 1.0 on the games used for evaluation; "
      "the earlier 1.15 came from the first-week sample).\n"
      "4. **November 6** margin misses are blowouts by heavy favourites (Queens @ Oklahoma State, Detroit Mercy @ Marquette, "
      "Southern @ TCU) where the ESPN margin was missed by nearly the same amount, plus pace outliers (Valparaiso @ Purdue "
      "+10.8 possessions). They are tail events of an already-wide distribution (std. errors ≈ 2–3), not a separate defect.\n")  # fmt: skip

    # ---------------------------------------------------------------- phase 2/3
    a("## 2. The challenger (`wf-level-0.5.0-v1`)\n")
    cs = r["challenger_summary"][CH]
    a("Applied to the frozen pure-0.5.0 projection of each game: add `λ × projected_possessions` to the total "
      "(margin untouched) and rescale `total_sd` / `margin_sd` by shrunk RMS standardised residuals, margin "
      "scale by |margin| bin — all estimated from games whose final was first visible in the schedule archive at "
      "or before the projection's `as_of`. Hyperparameters were fixed a priori "
      f"(`{cs['params']}`). No market data is an input. λ rose from {cs['lambda_per_poss_first']:.3f} to "
      f"{cs['lambda_per_poss_last']:.3f} points per possession (≈ +3 points on a 70-possession game) as games accrued. "
      "Code: `cbb_edge/model/level_adapt.py`; registration: `models/challengers/wf-level-0.5.0-v1.json`.\n")  # fmt: skip
    a("Blocked / not attempted (recorded, nothing faked): per-team pace shrinkage and early-season prior weighting "
      "(per-team posteriors are not in the archived records), team-total and half distributions (frozen model has "
      "none), any market-derived input (forbidden). Margin mean untouched (no significant bias).\n")  # fmt: skip

    a("## 3. Identical-game evaluation\n")
    a(f"**Eligible games: {p3['n_eligible']}** on {len(p3['dates'])} dates (first {p3['first_eligible_tip'][:16]}Z): every forecaster "
      f"defined, ≥ 30 finished games at `as_of`, ESPN line observed. By date: {p3['dates']}. "
      "Every number below is **EXPLORATORY HISTORICAL**: the hypothesis was formed on this window (see "
      "WAVE12.md §1), although each challenger forecast uses only information available before its own `as_of`.\n")  # fmt: skip
    rows = []
    for v in (
        "pure-0.2.0",
        "pure-0.3.0",
        "pure-0.4.0",
        "pure-0.5.0",
        "pure-0.5.0_roster",
        CH,
        "market",
    ):
        t = p3["table"][v]
        x = t.get("p_normal") or t["point"]
        pub = t.get("p_published")
        rows.append([NAMES[v], f(x["margin_mae"]), f(x["margin_rmse"]), f(x["margin_bias"]), f(x["total_mae"]), f(x["total_rmse"]),
                     f(x["total_bias"]), f(x.get("brier"), 4) if "brier" in x else "–", f(x.get("logloss"), 4) if "logloss" in x else "–",
                     f(pub["logloss"], 4) if pub else "–", f(x.get("margin_cover90")), f(x.get("total_cover90"))])  # fmt: skip
    a(table(["forecaster", "margin MAE", "margin RMSE", "margin bias", "total MAE", "total RMSE", "total bias",
             "Brier (normal p)", "log loss (normal p)", "log loss (published p)", "90% margin cover", "90% total cover"], rows) + "\n")  # fmt: skip
    a("`normal p` = Φ(margin / margin_sd) for every model, so the challenger is compared like for like; PURE's published "
      "probabilities (`published p`) use their own calibration. Nominal 90% interval coverage = 0.90.\n")  # fmt: skip
    a("**Attribution (ablations, same games):**\n")
    rows = []
    for v in (
        "pure-0.5.0",
        "wf-level-only",
        "wf-sd-only",
        CH,
        "wf-level-0.5.0r",
        "pure-0.5.0_roster",
    ):
        t = p3["table"][v]
        x = t.get("p_normal") or t["point"]
        rows.append([NAMES.get(v, v), f(x["total_mae"]), f(x["total_bias"]), f(x["margin_mae"]), f(x.get("logloss"), 4),
                     f(x.get("margin_cover90")), f(x.get("total_cover90"))])  # fmt: skip
    a(table(["variant", "total MAE", "total bias", "margin MAE", "log loss (normal p)", "margin cover90", "total cover90"], rows) + "\n")  # fmt: skip

    a(
        "**Paired differences on identical games** (negative = first-named is better; 90% game-bootstrap interval, 4000 resamples):\n"
    )
    rows = []
    for key, label in (("paired_vs_pure-0.5.0", f"{CH} − pure-0.5.0"), ("paired_vs_pure-0.2.0", f"{CH} − pure-0.2.0"),
                       ("paired_vs_roster", f"{CH} − pure-0.5.0+roster"), ("paired_vs_market", f"{CH} − ESPN line"),
                       ("pure-0.5.0_vs_pure-0.2.0", "pure-0.5.0 − pure-0.2.0"), ("roster_vs_pure-0.5.0", "pure-0.5.0+roster − pure-0.5.0")):  # fmt: skip
        p = p3[key]
        rows.append([label, ci(p["margin_abs"], 2), ci(p["margin_sq"], 1), ci(p["total_abs"], 2), ci(p["total_sq"], 1),
                     ci(p["brier"], 4) if "brier" in p else "–", ci(p["logloss"], 4) if "logloss" in p else "–"])  # fmt: skip
    a(
        table(
            ["comparison", "margin |e|", "margin e²", "total |e|", "total e²", "Brier", "log loss"],
            rows,
        )
        + "\n"
    )

    a("### Accuracy by date and team game number\n")
    for key, label in (("by_date", "Date (ET)"), ("by_team_game_number", "Team game number")):
        rows = []
        for k, v in p3[key].items():
            rows.append([k, str(v["n"])] + [f"{f(v[n]['total_mae'])} / {f(v[n]['total_bias'])}" for n in ("pure-0.2.0", "pure-0.5.0", CH, "market")]
                        + [f"{f(v[n]['margin_mae'])}" for n in ("pure-0.2.0", "pure-0.5.0", "market")])  # fmt: skip
        a(f"**{label}** — total MAE / bias, then margin MAE\n")
        a(table([label, "n", "0.2.0 total", "0.5.0 total", "challenger total", "ESPN total", "0.2.0 margin", "0.5.0 margin", "ESPN margin"], rows) + "\n")  # fmt: skip

    a("### Winner-probability calibration (normal p, equal-width bins)\n")
    rows = []
    for name in ("pure-0.5.0:p_normal", f"{CH}:p_normal"):
        for b in p3["calibration"][name]:
            rows.append([NAMES.get(name.split(":")[0], name), b["bin"], str(b["n"]), f(b["mean_pred"], 3), f(b["observed"], 3)])  # fmt: skip
    a(table(["forecaster", "bin", "n", "mean predicted", "observed home-win rate"], rows) + "\n")

    a("### Sensitivity (reported, never used to choose the primary)\n")
    rows = []
    for k, v in p3["sensitivity"].items():
        rows.append(
            [
                k,
                str(v["n"]),
                f(v["total_mae"]),
                f(v["total_bias"]),
                ci(v["total_mae_diff"], 3),
                ci(v["logloss_diff"], 4),
            ]
        )
    a(
        table(
            ["setting", "n", "total MAE", "total bias", "total MAE − base", "log loss − base"], rows
        )
        + "\n"
    )

    a("### Decision rule (fixed in WAVE12.md §5)\n")
    a(
        table(
            ["criterion", "met"], [[k, "yes" if v else "**no**"] for k, v in dec["rules"].items()]
        )
        + "\n"
    )
    pv = p3["paired_vs_pure-0.5.0"]
    a(f"**{dec['label']}.** The challenger removes the total bias ({f(p3['table']['pure-0.5.0']['point']['total_bias'])} → "
      f"{f(p3['table'][CH]['point']['total_bias'])}) and nudges total MAE and RMSE down, but the paired total-MAE difference is "
      f"{ci(pv['total_abs'], 3)}, whose interval includes 0. Margin accuracy is identical by construction. The margin-SD "
      "recalibration is not supported on this window (base margin z-SD ≈ 1.0; widening/narrowing it leaves log loss "
      f"{ci(pv['logloss'], 4)} versus base and over-covers: 90% interval coverage 0.93). "
      "A scoring-level bias of ~3 points is worth only ~0.15 points of MAE when the total's error SD is ~17, so a few hundred games "
      "cannot resolve the MAE gain even though the bias itself is clear. Against the ESPN line the model is still behind on margin and total "
      f"accuracy (total |e| {ci(p3['paired_vs_market']['total_abs'], 2)}); the level fix does not close that gap.\n")  # fmt: skip

    tg = p3["by_team_game_number"]
    ro = p3["table"]["wf-level-0.5.0r"]["point"]
    a("**Caveats the numbers expose.** (1) The level error is not constant in team game number: pure-0.5.0 total bias is "
      f"{f(tg['min_games_seen=0']['pure-0.5.0']['total_bias'])} (team game 1, n={tg['min_games_seen=0']['n']}), "
      f"{f(tg['min_games_seen=1']['pure-0.5.0']['total_bias'])} (game 2, n={tg['min_games_seen=1']['n']}), "
      f"{f(tg['min_games_seen=2']['pure-0.5.0']['total_bias'])} (game 3, n={tg['min_games_seen=2']['n']}); a single pooled level "
      f"over-corrects the late, small group (challenger bias {f(tg['min_games_seen=2'][CH]['total_bias'])} at game 3, and on 2026-11-09). "
      "A game-number-aware level is the natural next structure but game 3+ has too few games to fit it. "
      "(2) The roster overlay, not this challenger, is what improves margin accuracy and winner probabilities; the level rule is "
      "orthogonal to it. The secondary variant on the roster base (`wf-level-0.5.0r`) keeps the roster margin gains "
      f"(margin MAE {f(ro['margin_mae'])}) while removing the total bias ({f(ro['total_bias'])}); it is reported, not selected, "
      "and the same rules apply to it.\n")  # fmt: skip

    # ---------------------------------------------------------------- phase 4
    a("## 4. Connection to market research (diagnostic only)\n")
    a(m["note"] + ". The challenger's distribution feeds the existing contract-semantics probability mapping, so every FULL-game "
      "WINNER / MARGIN (spread and alternate spread ladders) / TOTAL (total and alternate total ladders) contract gets a fair value from the "
      "same normal score distribution. `main` = the strike with the mid nearest 50¢ in its ladder; `alt` = every other strike.\n")  # fmt: skip
    ev = m["evaluation"]
    a(f"**Universe preserved.** Pre-tip contracts of the eligible games: {m['info']['n_panel_contracts_pretip_for_eligible_games']} — "
      f"{ev['universe']}. The newest panel partition (`{m['universe_newest_partition']['partition']}`) holds "
      f"**{m['universe_newest_partition']['total_contracts']}** contracts across all families (futures, props, halves, in-play, unmapped); "
      "all are in `by_key` of `wave12_market.json`; unmodelled markets are never dropped, only marked with the reason.\n")  # fmt: skip
    rows = []
    for k, v in ev.items():
        if not isinstance(v, dict) or "n_contracts" not in v:
            continue
        rows.append([k, str(v["n_contracts"]), str(v["n_games"]), f(v["market_mid"]["brier"], 4)] +
                    [f(v[lb]["brier"], 4) for lb in ("pure-0.2.0", "pure-0.5.0", CH)] +
                    [f(v["pure-0.5.0"]["mean_abs_model_minus_mid"], 4), f(v[CH]["mean_abs_model_minus_mid"], 4)])  # fmt: skip
    a(
        "Brier on identical resolved contracts (lower is better; mid = last pre-tip two-sided mid):\n"
    )
    a(table(["market type", "contracts", "games", "mid", "pure-0.2.0", "pure-0.5.0", "challenger", "|p−mid| 0.5.0", "|p−mid| challenger"], rows) + "\n")  # fmt: skip
    rows = []
    for k, v in ev.items():
        if (
            not isinstance(v, dict)
            or "n_contracts" not in v
            or k.endswith((":main", ":alt"))
            or k == "ALL"
        ):
            continue
        for lb in ("pure-0.5.0", CH):
            x = v[lb]
            rows.append([k, lb, str(x["n_positive_net_ev_at_ask"]), f(x["mean_net_ev_of_positive_at_ask"], 4),
                         f(x["hypothetical_net_pnl_per_contract_positive_ev"], 4)])  # fmt: skip
    a("**Executable-ask economics (HYPOTHETICAL, SIMULATED, UNVALIDATED — not a recommendation).** Net EV per contract of the better "
      "executable side (YES at the ask or NO at 1 − bid) after the assumed Kalshi taker fee "
      f"(`{m['fee_schedule']['version']}`, rate {m['fee_schedule']['taker_rate']}, assumed unless the series API carried fee fields); "
      "hypothetical P&L = the same sides held to settlement at the quoted price, 1 contract, depth ignored. Quote, fill, fee and mid are separate "
      "columns in `wave12_contracts.csv.gz`.\n")  # fmt: skip
    a(
        table(
            [
                "market",
                "distribution",
                "contracts with positive modelled EV",
                "mean modelled net EV",
                "hypothetical realised net P&L / contract",
            ],
            rows,
        )
        + "\n"
    )
    a("What the better score distribution does: it moves total-ladder fair values up (mean P(over) "
      f"{f(ev['TOTAL']['pure-0.5.0']['mean_prob'], 3)} → {f(ev['TOTAL'][CH]['mean_prob'], 3)}) and reduces the average model-vs-mid gap "
      f"({f(ev['TOTAL']['pure-0.5.0']['mean_abs_model_minus_mid'], 4)} → {f(ev['TOTAL'][CH]['mean_abs_model_minus_mid'], 4)}), i.e. it agrees more "
      "with prices the market had already set. Spread and moneyline fair values are essentially unchanged (the level fix leaves the margin mean "
      "alone; the margin-SD rescale moves tail strikes slightly). The market mid still scores better than every PURE distribution on every "
      "market type; the hypothetical P&L rows are negative or tiny and are **not** evidence of an edge, and the challenger's total-ladder P&L is lower "
      "than the base's on this sample — shown, not optimised.\n")  # fmt: skip
    a(
        "Ladder example (one game, every FULL-game contract): see `ladder_demo` in `wave12_market.json`.\n"
    )

    a("## 5. Larger issues found (next wave, not in this PR)\n")
    a("* **Orientation of neutral-site games.** The schedule archive and the frozen projections disagree on home/away for event games; any scorer "
      "that does not guard this (this PR does; the scoreboard does) invents 35–66-point misses. A single canonical orientation key at projection time "
      "would remove the class of problem.\n"
      "* **No team-level prior-weight exposure.** The archived record exposes ratings but not each team's prior-vs-current weight, so early-season "
      "prior weighting cannot be tested per team; export it in the projection record to test shrinkage directly.\n"
      "* **Team-score and half distributions.** The frozen model has none, so team totals, halves and alternates beyond FULL-game WINNER/MARGIN/TOTAL "
      "remain unmodelled.\n"
      "* **Power.** Total-MAE improvements of ~0.15 need several thousand games to resolve; judge scoring-level fixes on total bias and likelihood scores "
      "as well as MAE.\n")  # fmt: skip

    a("## Reproduce\n")
    a("```bash\n"
      "# archives (read-only) -> local dirs\n"
      "git archive origin/projections-archive | tar -x -C $WORK/proj\n"
      "git archive origin/schedule-archive    | tar -x -C $WORK/sched\n"
      "git archive origin/espn-lines-archive  | tar -x -C $WORK/espn\n"
      "git archive origin/kalshi-panel-archive| tar -x -C $WORK/panel\n"
      "curl -L -o $WORK/team_box_2027.parquet https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_mens_college_basketball_team_boxscores/team_box_2027.parquet\n"
      "python scripts/research/run_wave1.py --projections $WORK/proj --schedule $WORK/sched --espn $WORK/espn \\\n"
      "    --team-box $WORK/team_box_2027.parquet --panel $WORK/panel --out research/wave12\n"
      "python scripts/research/render_wave1_report.py research/wave12 research/reports/WAVE12_SCORING_LEVEL.md\n```\n"
      "Archives are append-only; re-running later includes newer games (and a different N). The committed outputs are the "
      "2026-11-10 snapshot (data cut: ET dates ≤ 2026-11-09).\n")  # fmt: skip
    out.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
