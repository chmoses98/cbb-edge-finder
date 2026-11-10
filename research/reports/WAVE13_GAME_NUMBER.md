# Wave 13 — orientation identity, exported inputs, hierarchical level challenger (2026-11-10)

**Decision: NOT IMPROVED** (EXPLORATORY_HISTORICAL; prospective games: 0). RESEARCH_ONLY; nothing promoted; PR #46 / Wave 12 protocol, report and evidence are unchanged. Protocol and decision rule: `research/hypotheses/WAVE13.md` (committed before any number below existed).

## 1. Orientation identity (Priority 1)

`cbb_edge/data/ids/orientation.py` decides, per game and BEFORE scoring, whether the schedule's home/away order equals the projection's by canonical team id: `SAME`, `SWAPPED` (same two teams reversed on a neutral site: scores are mapped onto the projected teams), or `UNVERIFIED` (unresolved id, different team set, missing ids, reversal at a non-neutral site → excluded, never guessed). Archived projections and schedule rows are not rewritten. ESPN lines are oriented by the same identity.

Audit on the scored window: {'SAME': 359, 'SWAPPED': 4}; excluded (unverifiable): 0; swapped and correctly remapped: `[401909694, 401918053, 401919029, 401921704]` — the four Wave 12 games, now scored correctly instead of excluded (Wave 12's 359 + 4 = 363 scored games). ESPN lines: {'SAME': 416, 'SWAPPED': 3}. Regression tests: `tests/test_orientation.py` (the four games, fail-closed cases).

## 2. Exported modelling inputs (Priority 2)

New prospective records now carry an additive `model_inputs` block (`cbb_edge/app/model_inputs.py`, tests `tests/test_model_inputs.py`): per team game number, games and possessions seen, expected tempo and tempo effect, efficiency league mean / offense / defense effects, pace and efficiency prior-vs-current weight and effective sample (basis `ridge_diagonal_approx`, stated), pace/efficiency posterior SD from within-team noise of the current-season games before `as_of`, days since last game, data freshness (`info_cutoff_utc`, `info_rows`). Missing values are `null` with a reason (e.g. the prior-season rating value and the exact posterior covariance are not exposed by the engine state rows). Old records are not back-filled, so **none of these fields exist for the evaluated window**; the live path was unit-tested on synthetic frames only (the data lake is not available in this environment), and a failure in the block is recorded as `missing`, never blocks a projection.

## 3. Level challengers (Priority 3)

`wf13-hier-level-0.5.0-v1`: pooled level + shrunk group deviations for team game 1 / 2 / 3+ (`n0=30`, `n_tau=100`, fixed in advance), no SD rescale, margin untouched. Eligible games (all forecasters defined, ESPN line oriented): **242** on 7 dates: {'2026-11-03': 19, '2026-11-04': 10, '2026-11-05': 43, '2026-11-06': 59, '2026-11-07': 48, '2026-11-08': 29, '2026-11-09': 34}. All numbers are exploratory (WAVE13.md §1).

| forecaster | margin MAE | margin RMSE | margin bias | total MAE | total RMSE | total bias | Brier | log loss | margin cover90 | total cover90 |
|---|---|---|---|---|---|---|---|---|---|---|
| pure-0.2.0 (incumbent) | 9.67 | 12.42 | 1.39 | 13.65 | 16.90 | 2.17 | 0.1304 | 0.4016 | 0.90 | 0.90 |
| pure-0.5.0 | 9.25 | 11.81 | 0.53 | 13.83 | 16.95 | 2.82 | 0.1244 | 0.3803 | 0.91 | 0.91 |
| pure-0.5.0+roster | 9.19 | 11.57 | -1.01 | 13.84 | 16.96 | 2.80 | 0.1220 | 0.3679 | 0.92 | 0.91 |
| Wave 12 level-only | 9.25 | 11.81 | 0.53 | 13.67 | 16.77 | 0.06 | 0.1244 | 0.3803 | 0.91 | 0.90 |
| **Wave 13 hierarchical** | 9.25 | 11.81 | 0.53 | 13.76 | 16.81 | 0.44 | 0.1244 | 0.3803 | 0.91 | 0.90 |
| ablation: independent groups | 9.25 | 11.81 | 0.53 | 13.82 | 16.84 | 1.38 | 0.1244 | 0.3803 | 0.91 | 0.92 |
| Wave 13 on roster base | 9.19 | 11.57 | -1.01 | 13.78 | 16.83 | 0.54 | 0.1220 | 0.3679 | 0.92 | 0.90 |
| ESPN line (benchmark) | 8.43 | 10.77 | 0.02 | 13.10 | 16.14 | -0.31 | – | – | – | – |

Paired differences on identical games (negative = first-named better; 90% game-bootstrap interval):

| comparison | margin |e| | total |e| | total e² | log loss |
|---|---|---|---|---|
| Wave 13 − pure-0.5.0 | +0.00 [+0.00, +0.00] | -0.07 [-0.32, +0.19] | -4.8 [-13.8, +4.2] | +0.0000 [+0.0000, +0.0000] |
| Wave 13 − Wave 12 level-only | +0.00 [+0.00, +0.00] | +0.09 [+0.01, +0.17] | +1.5 [-1.0, +4.0] | +0.0000 [+0.0000, +0.0000] |
| Wave 13 − roster | +0.05 [-0.25, +0.36] | -0.07 [-0.32, +0.18] | -5.0 [-14.1, +3.9] | +0.0124 [+0.0001, +0.0246] |
| Wave 13 − pure-0.2.0 | -0.42 [-0.63, -0.21] | +0.11 [-0.16, +0.38] | -2.9 [-12.8, +6.9] | -0.0213 [-0.0301, -0.0129] |
| Wave 13 − ESPN line | +0.82 [+0.46, +1.18] | +0.67 [+0.27, +1.09] | +22.2 [+8.6, +37.0] | – |
| Wave 12 level-only − pure-0.5.0 | +0.00 [+0.00, +0.00] | -0.16 [-0.44, +0.12] | -6.3 [-16.2, +3.5] | +0.0000 [+0.0000, +0.0000] |
| independent groups − hierarchical | +0.00 [+0.00, +0.00] | +0.06 [-0.08, +0.20] | +1.1 [-3.7, +6.1] | +0.0000 [+0.0000, +0.0000] |
| Wave 13 on roster − roster | +0.00 [+0.00, +0.00] | -0.05 [-0.29, +0.19] | -4.5 [-13.2, +4.0] | +0.0000 [+0.0000, +0.0000] |

### Game-number slices (team game = min games seen + 1) and dates

**Team game number** — total MAE / bias

| Team game number | n | pure-0.5.0 | Wave 12 level-only | Wave 13 | ESPN | Wave 13 − 0.5.0 total |e| |
|---|---|---|---|---|---|---|
| team_game_1 | 88 | 13.97 / 3.92 | 13.86 / 1.22 | 13.87 / 0.97 | 13.30 / 0.36 | -0.10 [-0.61, +0.42] |
| team_game_2 | 134 | 13.76 / 2.97 | 13.40 / 0.23 | 13.59 / 0.96 | 12.76 / -0.06 | -0.16 [-0.46, +0.15] |
| team_game_3+ | 20 | 13.71 / -3.00 | 14.72 / -6.24 | 14.45 / -5.43 | 14.45 / -4.90 | +0.73 [-0.06, +1.52] |

**Date (ET)** — total MAE / bias

| Date (ET) | n | pure-0.5.0 | Wave 12 level-only | Wave 13 | ESPN | Wave 13 − 0.5.0 total |e| |
|---|---|---|---|---|---|---|
| 2026-11-03 | 19 | 11.92 / -3.81 | 13.08 / -6.87 | 13.19 / -7.06 | 11.34 / -5.08 | +1.27 [+0.20, +2.29] |
| 2026-11-04 | 10 | 16.96 / 8.63 | 15.60 / 6.35 | 15.55 / 6.35 | 15.30 / 4.50 | -1.41 [-2.32, -0.42] |
| 2026-11-05 | 43 | 14.42 / 1.41 | 14.35 / -1.11 | 14.21 / -0.77 | 14.22 / -2.45 | -0.21 [-0.73, +0.34] |
| 2026-11-06 | 59 | 13.01 / 4.63 | 12.49 / 2.27 | 12.95 / 3.17 | 12.35 / 1.14 | -0.06 [-0.44, +0.31] |
| 2026-11-07 | 48 | 14.52 / 5.21 | 13.95 / 2.33 | 14.04 / 2.48 | 13.25 / 1.73 | -0.49 [-1.10, +0.16] |
| 2026-11-08 | 29 | 14.74 / 5.87 | 14.45 / 2.86 | 14.41 / 3.08 | 13.29 / 3.19 | -0.33 [-1.15, +0.50] |
| 2026-11-09 | 34 | 12.90 / -2.51 | 13.58 / -5.89 | 13.47 / -5.48 | 12.91 / -4.71 | +0.57 [-0.25, +1.32] |

Final fitted state (329 finished games; group counts [208, 115, 6]): raw group means per possession [0.0549, 0.0539, -0.0624], shrunk levels [0.05, 0.0473, 0.034]. Team game 3+ has very few games, so its raw mean (opposite sign) is barely allowed to move its level — by design. This is not evidence of a stable or causal game-number effect.

## Prospective validation

Games with tip ≥ `2026-11-10T21:00:00+00:00` that meet the same eligibility: **0**. IMPROVED requires ≥150 on ≥5 dates (WAVE13.md §5). Re-run `scripts/research/run_wave13.py` on later archives to populate it; the rule is a deterministic function of the immutable archives.

## Decision

| criterion | met |
|---|---|
| no_worse_than_wave12_level_only | **no** |
| prospective_dates_ge_5 | **no** |
| prospective_games_ge_150 | **no** |
| total_mae_lower_vs_0.5.0_ci_excludes_0 | **no** |

**NOT IMPROVED.** Under the preregistered rule the hierarchical rule's total MAE is +0.091 [+0.015, +0.171] versus Wave 12 level-only (worse, interval excludes 0) and -0.067 [-0.316, +0.190] versus pure-0.5.0 (interval includes 0). Its total bias (0.44) is also larger than level-only's (0.06): the four-parameter ridge shrinks the *sum* of pooled level and group deviation more than Wave 12's single level does, so it under-corrects the dominant groups while only partly protecting the thin group. The independent-groups ablation is not better. The hierarchy therefore buys no accuracy; **Wave 12 level-only remains the better level baseline**, and the hyperparameters were not tuned after seeing this (a retune would need a new protocol and genuinely future games). Margin and winner metrics are identical to pure-0.5.0 by construction (level only).

## 4. Market-coverage foundation (Priority 4)

**Audit of existing infrastructure.** `team_score_joint.py` fits team-score variances and the home/away covariance from independent settled games (shadow, unvalidated); `period_forecast.py` gives a first-half MEAN share only (no variance); `kalshi/research/target_means.py` exposes team-total means only; the contract table marks half, team-total, overtime, race and prop contracts unmodelled. Nothing there gives coherent full-game team-score probabilities from frozen records.

**Implemented** `cbb_edge/model/score_distribution.py`: one bivariate normal over (home, away) from the frozen margin, total and their SDs, assuming uncorrelated total and margin errors. By construction mean and variance recompose exactly into total and margin, team-total / spread / total / moneyline probabilities come from the same distribution, ladders are monotone, and it equals the existing contract pricer on WINNER / MARGIN / TOTAL (`tests/test_score_distribution.py`, incl. Monte Carlo). Halves, other periods, overtime and players return `Unmodeled(reason)`: no half or player distribution is fabricated.

**Check against realised results** (242 games, pure-0.5.0): implied team-score SD 10.38 vs empirical 10.74 (home) / 9.73 (away); implied home/away error correlation 0.32 vs empirical 0.34; 90% team-score interval coverage 0.90; correlation of total error and margin error 0.10 (90% CI [-0.003, 0.202]) — the uncorrelated assumption is borderline-supported (the interval just reaches 0), so team-total outputs stay `SHADOW_UNVALIDATED`, are not wired into the contract table, and no market result is claimed for them.

## Reproduce

```bash
# same archive checkouts as Wave 12 (projections-archive, schedule-archive, espn-lines-archive)
python scripts/research/run_wave13.py --projections $WORK/proj --schedule $WORK/sched --espn $WORK/espn --out research/wave13
python scripts/research/render_wave13_report.py research/wave13 research/reports/WAVE13_GAME_NUMBER.md
```
Committed outputs are the 2026-11-10 snapshot; archives are append-only so later runs include later games.

