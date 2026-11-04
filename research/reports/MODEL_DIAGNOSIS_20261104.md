# Why the champion trails the market on spreads and totals (2026-11-04, discovery)

121 finished games with a frozen pregame projection (champion `pure-0.5.0`) and a final score, compared with the
market's own implied median margin/total (interpolated from the contract ladder, last pre-tip quote).
Reproduce with `cbb_edge.kalshi.research.challenger.build_games` plus the contract ladders in the panel archive.

| Question | Evidence (champion pure-0.5.0) | Verdict |
|---|---|---|
| Are margin point estimates biased? | bias -0.24 pts, 90% [-2.5, +1.8], RMSE 14.4 | No |
| Is the margin spread understated? | standardised-error SD 1.15 (ideal 1.0); within-1sd 64% (68% expected); 1.34 for |margin| > 22 | Yes, ~15% overconfident, worse in blowouts |
| Are totals biased? | +3.6 pts, 90% [+1.0, +6.2]; terciles +6.7 / +5.1 / -0.8 (low-total games worst) | Yes: model total level too low |
| Is the market's total closer? | market median bias -2.0; model minus market totals -5.6 pts on average | Yes |
| Point estimates vs market (same games) | margin MSE gap +17.0 [-3.5, +36.6]; total +15.4 [-21.9, +55.3] | Market ahead, not yet significant |
| Is it projection staleness? | projections are 1.7-23 h old (median 3.2 h); corr(age, gap) = 0.004 | No |
| Is it non-stationary? | totals bias +1.1 in the earliest 72 games vs +3.6 overall; model-minus-market totals -2.4 (Nov 2) vs -6.1 (Nov 3) | Yes: scoring level is drifting away from the model's prior |

So the defect is mostly a **scoring-level (pace/total) error that grows through the first week**, plus mild
margin over-confidence. It is not staleness and not a margin bias.

## Challenger `calib-0.5.0-v1` (shadow, out-of-sample only)
Calibration layer on the frozen projections: `total_bias +1.09`, `margin_sd_scale 1.053`, `total_sd_scale 1.100`,
fitted on the earliest 72 games (fit window ends 2026-11-03T01:00Z). Published only for games tipping later.
Out-of-sample paired Brier on 46 games after the fit window (champion -> challenger, market in brackets):
game winner 0.0902 -> 0.0881 (0.0800), spread 0.1639 -> 0.1632 (0.1414), total 0.1816 -> 0.1801 (0.1639).
Changes are -0.0021, -0.0006 [-0.0014, +0.0001], -0.0015 [-0.0056, +0.0023]: none significant, and the market
gap stays large (spread +0.022 [+0.010, +0.036]). **Not promoted; the champion is unchanged.**

Why it is weak: a static layer fit on the first days under-corrects a drifting level. A walk-forward version
(each game uses only games finished before its tip, shrunk toward zero) is the principled next challenger, but
only 13 games currently have >= 15 finished games before tip, so it cannot be tested yet.
