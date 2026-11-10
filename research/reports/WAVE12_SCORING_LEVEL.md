# Wave 1 — scoring-level diagnosis and walk-forward challenger (2026-11-10)

**Decision: INSUFFICIENT EVIDENCE** (evidence class: EXPLORATORY_HISTORICAL). RESEARCH_ONLY. The incumbent stays `pure-0.2.0`; nothing is promoted; no frozen projection, candidate rule or gate was changed. Protocol and decision rule: `research/hypotheses/WAVE12.md` (committed before the challenger numbers). Reproduce: `scripts/research/run_wave1.py` then `scripts/research/render_wave1_report.py` (commands at the end).

## 1. Reproduction (frozen projections, verified finals through 2026-11-09 ET)

Scored games: **359** (all five versions frozen pre-tip, final verified, home/away orientation identical in projection and schedule; 4 neutral-site games excluded because the schedule archive lists the teams in the opposite order — `[401909694, 401918053, 401919029, 401921704]`; scoring them would turn correct projections into fake 35–66 point 'misses'; the prospective scoreboard marks the same games UNSCORABLE).

**Scoreboard reconciliation.** Game-1 slice (a team's first game): N = **207**, base MAE **9.90**, roster-adjusted MAE **9.84**, RMSE 12.55 / 12.39, bias 0.80 / -1.12 — identical to the published 207 / 9.90 / 9.84 / 12.55 / 12.39 / +0.80 / −1.12. (The scoreboard's `INVALID` game is not separately excluded here.)

All scored games (N=359; market row: the 359 games with a pre-tip ESPN line). Bias = actual − projected.

| version | margin MAE | margin RMSE | margin bias | total MAE | total RMSE | total bias | Brier (published p) | log loss |
|---|---|---|---|---|---|---|---|---|
| pure-0.2.0 (incumbent) | 10.03 | 12.78 | 1.29 | 14.09 | 17.48 | 3.32 | 0.1240 | 0.3869 |
| pure-0.3.0 | 9.70 | 12.31 | 0.84 | 13.92 | 17.23 | 2.75 | 0.1201 | 0.3723 |
| pure-0.4.0 | 9.72 | 12.32 | 0.65 | 14.01 | 17.29 | 2.90 | 0.1199 | 0.3725 |
| pure-0.5.0 (base) | 9.74 | 12.31 | 0.49 | 14.04 | 17.31 | 2.94 | 0.1203 | 0.3751 |
| pure-0.5.0+roster | 9.66 | 12.18 | -1.27 | 14.05 | 17.30 | 2.83 | 0.1186 | 0.3694 |
| ESPN line (benchmark) | 8.98 | 11.33 | 0.34 | 13.25 | 16.60 | -1.05 | – | – |

### Error decomposition (exact; postgame box scores used for scoring only)

`score = possessions × points-per-possession` for both teams, so the total error splits exactly into a **pace** term `(poss_actual − poss_proj)·(ppp_h + ppp_a)` and an **efficiency** term `poss_actual·Σ(ppp_actual − ppp_proj)`; the margin error splits the same way on the difference of the two ppp. Home offence = away defence, so the two ppp errors are the offensive and defensive efficiency errors. Means ± standard error:

| version | poss err | home ppp err (home off / away def) | away ppp err (away off / home def) | total: pace | total: efficiency | margin: pace | margin: efficiency |
|---|---|---|---|---|---|---|---|
| pure-0.2.0 (incumbent) | +0.596 ± 0.261 | +0.023 ± 0.008 | +0.007 ± 0.007 | +1.266 ± 0.544 | +2.056 ± 0.779 | +0.183 ± 0.064 | +1.104 ± 0.667 |
| pure-0.3.0 | +0.596 ± 0.261 | +0.015 ± 0.007 | +0.006 ± 0.007 | +1.272 ± 0.546 | +1.475 ± 0.770 | +0.180 ± 0.065 | +0.655 ± 0.643 |
| pure-0.4.0 | +0.596 ± 0.261 | +0.015 ± 0.007 | +0.008 ± 0.007 | +1.276 ± 0.546 | +1.621 ± 0.775 | +0.181 ± 0.066 | +0.468 ± 0.644 |
| pure-0.5.0 (base) | +0.596 ± 0.261 | +0.014 ± 0.007 | +0.010 ± 0.007 | +1.281 ± 0.546 | +1.655 ± 0.778 | +0.184 ± 0.067 | +0.301 ± 0.644 |
| pure-0.5.0+roster | +0.596 ± 0.261 | +0.001 ± 0.007 | +0.022 ± 0.007 | +1.283 ± 0.546 | +1.549 ± 0.779 | +0.208 ± 0.075 | -1.478 ± 0.635 |

The roster overlay changes margin efficiency (−1.5) but carries the base possessions; its total error moves by only about −0.1 — it does not address the scoring level.

### Segments (pure-0.5.0; total/margin bias = actual − projected)

**Team game number (min games seen before the game)**

| segment | n | total bias | pace | efficiency | ESPN total bias | margin bias | margin MAE | ESPN margin MAE | margin z-SD |
|---|---|---|---|---|---|---|---|---|---|
| min_games_seen=0 | 207 | 3.64 | 3.10 | 0.53 | -1.14 | 0.80 | 9.90 | 9.12 | 1.00 |
| min_games_seen=1 | 132 | 2.74 | -0.93 | 3.66 | -0.32 | 0.08 | 9.85 | 9.03 | 1.05 |
| min_games_seen=2 | 20 | -3.00 | -3.02 | 0.02 | -4.90 | -0.06 | 7.41 | 7.10 | 0.78 |

**Projected pace**

| segment | n | total bias | pace | efficiency | ESPN total bias | margin bias | margin MAE | ESPN margin MAE | margin z-SD |
|---|---|---|---|---|---|---|---|---|---|
| fast | 120 | 1.53 | 0.03 | 1.50 | -1.14 | 1.28 | 9.40 | 8.35 | 1.01 |
| mid | 120 | 3.02 | -0.25 | 3.28 | -1.17 | -1.11 | 9.73 | 9.30 | 0.98 |
| slow | 119 | 4.27 | 4.09 | 0.18 | -0.83 | 1.29 | 10.10 | 9.28 | 1.03 |

**Spread size (|projected margin|)**

| segment | n | total bias | pace | efficiency | ESPN total bias | margin bias | margin MAE | ESPN margin MAE | margin z-SD |
|---|---|---|---|---|---|---|---|---|---|
| close | 119 | 5.70 | 0.98 | 4.72 | 1.99 | -0.58 | 7.95 | 7.65 | 0.82 |
| lopsided | 120 | 2.11 | 2.75 | -0.63 | -2.37 | 1.51 | 10.92 | 9.96 | 1.08 |
| mid | 120 | 1.02 | 0.11 | 0.90 | -2.73 | 0.51 | 10.34 | 9.31 | 1.09 |

**Opponent quality (mean net rating of the pair)**

| segment | n | total bias | pace | efficiency | ESPN total bias | margin bias | margin MAE | ESPN margin MAE | margin z-SD |
|---|---|---|---|---|---|---|---|---|---|
| mid | 120 | 2.87 | 1.47 | 1.40 | -1.01 | 0.25 | 9.86 | 9.02 | 1.04 |
| strong | 120 | 3.83 | 1.59 | 2.24 | 0.04 | 2.52 | 10.59 | 9.27 | 1.06 |
| weak | 119 | 2.10 | 0.78 | 1.32 | -2.18 | -1.33 | 8.76 | 8.64 | 0.89 |

**Roster continuity adjustment (overlay record)**

| segment | n | total bias | pace | efficiency | ESPN total bias | margin bias | margin MAE | ESPN margin MAE | margin z-SD |
|---|---|---|---|---|---|---|---|---|---|
| no_continuity_adj | 7 | 1.05 | -2.10 | 3.15 | -0.79 | 0.23 | 10.12 | 9.50 | 1.07 |
| |adj|<3 | 221 | 3.04 | 0.68 | 2.35 | -0.66 | -0.72 | 9.80 | 8.95 | 1.02 |
| |adj|>=3 | 131 | 2.87 | 2.47 | 0.40 | -1.71 | 2.53 | 9.63 | 8.99 | 0.97 |

**Date (ET)**

| segment | n | total bias | pace | efficiency | ESPN total bias | margin bias | margin MAE | ESPN margin MAE | margin z-SD |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-01 | 2 | -12.30 | 4.57 | -16.86 | -13.50 | -1.40 | 10.05 | 8.50 | 1.13 |
| 2026-11-02 | 117 | 3.69 | 4.40 | -0.71 | -2.06 | 0.35 | 10.65 | 9.98 | 1.06 |
| 2026-11-03 | 19 | -3.81 | 0.82 | -4.63 | -5.08 | 2.35 | 9.89 | 9.13 | 1.08 |
| 2026-11-04 | 10 | 8.63 | 0.85 | 7.78 | 4.50 | 0.13 | 7.53 | 8.50 | 0.90 |
| 2026-11-05 | 43 | 1.41 | 0.04 | 1.37 | -2.45 | -0.56 | 8.98 | 7.92 | 0.97 |
| 2026-11-06 | 59 | 4.63 | 0.24 | 4.39 | 1.14 | 3.29 | 10.76 | 9.36 | 1.10 |
| 2026-11-07 | 48 | 5.21 | -0.44 | 5.65 | 1.73 | -1.80 | 7.48 | 7.15 | 0.83 |
| 2026-11-08 | 27 | 4.95 | 0.41 | 4.54 | 2.17 | -1.15 | 10.81 | 9.65 | 1.07 |
| 2026-11-09 | 34 | -2.51 | -2.76 | 0.25 | -4.71 | 1.10 | 8.70 | 8.32 | 0.88 |

Pace dispersion: realised possessions regressed on projected have slope **0.78** (90% [0.63, 0.92]); mean projected 70.6 vs realised 71.2 possessions. Total points on projected total: slope 0.93 [0.75, 1.11] (consistent with 1: a level error, not a dispersion error).

### Largest misses

November 6 (largest margin misses; ESPN's error on the same game in the last columns). Blowouts the market also missed by almost the same amount are variance, not model-specific failure:

| game | matchup (away @ home) | projected | final | margin err | total err | poss err | ESPN margin err | ESPN total err |
|---|---|---|---|---|---|---|---|---|
| 401919040 | Queens University Royals @ Oklahoma State Cowboys | 94.1-81.0 (poss 78.3) | 118-68 (poss 80.3) | 37.0 | 10.9 | 1.9 | 32.5 | 7.5 |
| 401909523 | Detroit Mercy Titans @ Marquette Golden Eagles | 90.5-64.5 (poss 72.7) | 93-32 (poss 67.3) | 35.0 | -30.1 | -5.4 | 28.5 | -29.5 |
| 401919048 | Southern Jaguars @ TCU Horned Frogs | 86.4-60.2 (poss 72.8) | 106-54 (poss 72.8) | 25.8 | 13.5 | 0.0 | 25.5 | 7.5 |
| 401926131 | Valparaiso Beacons @ Purdue Boilermakers | 80.0-60.1 (poss 66.6) | 80-83 (poss 77.4) | -22.9 | 22.9 | 10.8 | -22.5 | 18.5 |
| 401922219 | North Florida Ospreys @ UCLA Bruins | 92.9-64.5 (poss 73.5) | 114-63 (poss 80.3) | 22.7 | 19.6 | 6.8 | 19.5 | 20.5 |
| 401923260 | Florida Atlantic Owls @ Wright State Raiders | 79.9-76.0 (poss 74.5) | 97-71 (poss 70.1) | 22.1 | 12.1 | -4.4 | 21.5 | 11.5 |

Largest total misses overall:

| game | matchup (away @ home) | projected | final | margin err | total err | poss err | ESPN margin err | ESPN total err |
|---|---|---|---|---|---|---|---|---|
| 401919001 | UT Martin Skyhawks @ Tulane Green Wave | 70.8-63.8 (poss 66.5) | 100-98 (poss 85.3) | -5.0 | 63.4 | 18.8 | -4.5 | 50.5 |
| 401911453 | Saint Mary's Gaels @ Nevada Wolf Pack | 70.6-70.9 (poss 67.1) | 96-95 (poss 83.1) | 1.4 | 49.5 | 16.0 | -0.5 | 44.5 |
| 401926112 | Northern Iowa Panthers @ Furman Paladins | 67.0-67.0 (poss 64.3) | 98-83 (poss 75.0) | 15.0 | 47.0 | 10.7 | 10.5 | 31.5 |
| 401920952 | Southern Illinois Salukis @ Kansas City Roos | 70.4-76.1 (poss 74.1) | 100-93 (poss 74.8) | 12.7 | 46.6 | 0.8 | 5.5 | 49.5 |
| 401906791 | Tennessee Tech Golden Eagles @ Mississippi State Bulldogs | 85.7-64.8 (poss 71.3) | 106-88 (poss 77.8) | -2.9 | 43.6 | 6.6 | -0.5 | 37.5 |
| 401910997 | Western Michigan Broncos @ Old Dominion Monarchs | 80.4-71.4 (poss 71.3) | 61-49 (poss 60.7) | 3.0 | -41.8 | -10.6 | 13.5 | -45.5 |

### Diagnosis (strongest evidence-supported cause)

1. **Scoring level, not margin.** pure-0.5.0 under-predicts the total by **+2.94** points (pace +1.28 ± 0.55, efficiency +1.65 ± 0.78); the margin mean is unbiased (+0.49). The same error is in every PURE version (+2.9 to +3.5) and the ESPN total is not biased (-1.05), so it is a model scoring-level error that the market has priced in.
2. **Where it sits.** The pace shortfall is concentrated in each team's first game and in projected-slow games; the efficiency shortfall in second games, mid-pace and close games (tables above). It is not confined to one day. Early-season reversion to last season's scoring level (a prior that is too low for this year's early-season pace and efficiency) is the single explanation consistent with all segments; the per-team prior weighting that would test it directly is in the archived ratings but not exposed per game, so it is **not** adjusted here (next wave).
3. **Weak or not supported:** pace dispersion (projected possessions are somewhat too spread: slope 0.78 with an interval excluding 1, but the total-points slope includes 1 and a fix needs per-team pace posteriors that the archive does not expose — blocked); staleness, roster continuity (the overlay does not move totals), opponent quality (total bias is similar in all terciles), and a larger margin-SD problem (overall margin z-SD ≈ 1.0 on the games used for evaluation; the earlier 1.15 came from the first-week sample).
4. **November 6** margin misses are blowouts by heavy favourites (Queens @ Oklahoma State, Detroit Mercy @ Marquette, Southern @ TCU) where the ESPN margin was missed by nearly the same amount, plus pace outliers (Valparaiso @ Purdue +10.8 possessions). They are tail events of an already-wide distribution (std. errors ≈ 2–3), not a separate defect.

## 2. The challenger (`wf-level-0.5.0-v1`)

Applied to the frozen pure-0.5.0 projection of each game: add `λ × projected_possessions` to the total (margin untouched) and rescale `total_sd` / `margin_sd` by shrunk RMS standardised residuals, margin scale by |margin| bin — all estimated from games whose final was first visible in the schedule archive at or before the projection's `as_of`. Hyperparameters were fixed a priori (`{'k_level': 30.0, 'k_sd': 40.0, 'level': True, 'margin_bins': [6.0, 14.0], 'min_games': 30, 'sd': True}`). No market data is an input. λ rose from 0.042 to 0.048 points per possession (≈ +3 points on a 70-possession game) as games accrued. Code: `cbb_edge/model/level_adapt.py`; registration: `models/challengers/wf-level-0.5.0-v1.json`.

Blocked / not attempted (recorded, nothing faked): per-team pace shrinkage and early-season prior weighting (per-team posteriors are not in the archived records), team-total and half distributions (frozen model has none), any market-derived input (forbidden). Margin mean untouched (no significant bias).

## 3. Identical-game evaluation

**Eligible games: 240** on 7 dates (first 2026-11-03T23:00Z): every forecaster defined, ≥ 30 finished games at `as_of`, ESPN line observed. By date: {'2026-11-03': 19, '2026-11-04': 10, '2026-11-05': 43, '2026-11-06': 59, '2026-11-07': 48, '2026-11-08': 27, '2026-11-09': 34}. Every number below is **EXPLORATORY HISTORICAL**: the hypothesis was formed on this window (see WAVE12.md §1), although each challenger forecast uses only information available before its own `as_of`.

| forecaster | margin MAE | margin RMSE | margin bias | total MAE | total RMSE | total bias | Brier (normal p) | log loss (normal p) | log loss (published p) | 90% margin cover | 90% total cover |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pure-0.2.0 (incumbent) | 9.72 | 12.47 | 1.43 | 13.60 | 16.84 | 2.02 | 0.1306 | 0.4020 | 0.4052 | 0.90 | 0.90 |
| pure-0.3.0 | 9.27 | 11.88 | 0.89 | 13.59 | 16.79 | 1.79 | 0.1250 | 0.3819 | 0.3849 | 0.91 | 0.92 |
| pure-0.4.0 | 9.29 | 11.89 | 0.67 | 13.68 | 16.85 | 2.29 | 0.1249 | 0.3817 | 0.3851 | 0.91 | 0.91 |
| pure-0.5.0 (base) | 9.29 | 11.85 | 0.57 | 13.79 | 16.93 | 2.69 | 0.1245 | 0.3805 | 0.3839 | 0.91 | 0.91 |
| pure-0.5.0+roster | 9.24 | 11.61 | -0.99 | 13.80 | 16.93 | 2.67 | 0.1220 | 0.3678 | 0.3750 | 0.92 | 0.91 |
| **wf-level-0.5.0-v1** | 9.29 | 11.85 | 0.57 | 13.66 | 16.77 | -0.07 | 0.1245 | 0.3827 | – | 0.94 | 0.91 |
| ESPN line (benchmark) | 8.49 | 10.82 | 0.02 | 13.06 | 16.12 | -0.45 | – | – | – | – | – |

`normal p` = Φ(margin / margin_sd) for every model, so the challenger is compared like for like; PURE's published probabilities (`published p`) use their own calibration. Nominal 90% interval coverage = 0.90.

**Attribution (ablations, same games):**

| variant | total MAE | total bias | margin MAE | log loss (normal p) | margin cover90 | total cover90 |
|---|---|---|---|---|---|---|
| pure-0.5.0 (base) | 13.79 | 2.69 | 9.29 | 0.3805 | 0.91 | 0.91 |
| wf-level-only | 13.66 | -0.07 | 9.29 | 0.3805 | 0.91 | 0.90 |
| wf-sd-only | 13.79 | 2.69 | 9.29 | 0.3827 | 0.94 | 0.93 |
| **wf-level-0.5.0-v1** | 13.66 | -0.07 | 9.29 | 0.3827 | 0.94 | 0.91 |
| wf-level-0.5.0r | 13.68 | 0.07 | 9.24 | 0.3686 | 0.95 | 0.90 |
| pure-0.5.0+roster | 13.80 | 2.67 | 9.24 | 0.3678 | 0.92 | 0.91 |

**Paired differences on identical games** (negative = first-named is better; 90% game-bootstrap interval, 4000 resamples):

| comparison | margin |e| | margin e² | total |e| | total e² | Brier | log loss |
|---|---|---|---|---|---|---|
| wf-level-0.5.0-v1 − pure-0.5.0 | +0.00 [+0.00, +0.00] | +0.0 [+0.0, +0.0] | -0.13 [-0.42, +0.15] | -5.4 [-15.1, +4.5] | +0.0001 [-0.0013, +0.0013] | +0.0022 [-0.0048, +0.0086] |
| wf-level-0.5.0-v1 − pure-0.2.0 | -0.42 [-0.63, -0.21] | -15.0 [-20.2, -10.0] | +0.06 [-0.21, +0.34] | -2.6 [-12.6, +7.3] | -0.0060 [-0.0097, -0.0025] | -0.0192 [-0.0314, -0.0076] |
| wf-level-0.5.0-v1 − pure-0.5.0+roster | +0.06 [-0.25, +0.37] | +5.8 [-2.1, +13.7] | -0.14 [-0.42, +0.14] | -5.7 [-15.4, +4.3] | +0.0026 [-0.0022, +0.0074] | +0.0150 [+0.0010, +0.0285] |
| wf-level-0.5.0-v1 − ESPN line | +0.80 [+0.45, +1.16] | +23.5 [+14.8, +32.7] | +0.60 [+0.20, +1.00] | +21.3 [+7.9, +36.0] | – | – |
| pure-0.5.0 − pure-0.2.0 | -0.42 [-0.63, -0.21] | -15.0 [-20.2, -10.0] | +0.19 [+0.00, +0.38] | +2.8 [-3.4, +9.0] | -0.0061 [-0.0095, -0.0028] | -0.0214 [-0.0301, -0.0130] |
| pure-0.5.0+roster − pure-0.5.0 | -0.06 [-0.37, +0.25] | -5.8 [-13.7, +2.1] | +0.00 [-0.01, +0.02] | +0.2 [-0.2, +0.7] | -0.0025 [-0.0072, +0.0021] | -0.0128 [-0.0253, -0.0005] |

### Accuracy by date and team game number

**Date (ET)** — total MAE / bias, then margin MAE

| Date (ET) | n | 0.2.0 total | 0.5.0 total | challenger total | ESPN total | 0.2.0 margin | 0.5.0 margin | ESPN margin |
|---|---|---|---|---|---|---|---|---|
| 2026-11-03 | 19 | 12.34 / -5.10 | 11.92 / -3.81 | 13.08 / -6.87 | 11.34 / -5.08 | 10.29 | 9.89 | 9.13 |
| 2026-11-04 | 10 | 15.67 / 7.26 | 16.96 / 8.63 | 15.60 / 6.35 | 15.30 / 4.50 | 7.96 | 7.53 | 8.50 |
| 2026-11-05 | 43 | 14.54 / 0.29 | 14.42 / 1.41 | 14.35 / -1.11 | 14.22 / -2.45 | 9.51 | 8.98 | 7.92 |
| 2026-11-06 | 59 | 12.71 / 3.93 | 13.01 / 4.63 | 12.49 / 2.27 | 12.35 / 1.14 | 11.40 | 10.76 | 9.36 |
| 2026-11-07 | 48 | 14.57 / 4.95 | 14.52 / 5.21 | 13.95 / 2.33 | 13.25 / 1.73 | 7.82 | 7.48 | 7.15 |
| 2026-11-08 | 27 | 14.22 / 4.25 | 14.47 / 4.95 | 14.41 / 1.96 | 13.02 / 2.17 | 11.03 | 10.81 | 9.65 |
| 2026-11-09 | 34 | 12.19 / -2.60 | 12.90 / -2.51 | 13.58 / -5.89 | 12.91 / -4.71 | 8.91 | 8.70 | 8.32 |

**Team game number** — total MAE / bias, then margin MAE

| Team game number | n | 0.2.0 total | 0.5.0 total | challenger total | ESPN total | 0.2.0 margin | 0.5.0 margin | ESPN margin |
|---|---|---|---|---|---|---|---|---|
| min_games_seen=0 | 88 | 13.89 / 3.20 | 13.97 / 3.92 | 13.86 / 1.22 | 13.30 / 0.36 | 9.34 | 8.89 | 8.00 |
| min_games_seen=1 | 132 | 13.43 / 2.08 | 13.69 / 2.74 | 13.37 / 0.01 | 12.70 / -0.32 | 10.31 | 9.85 | 9.03 |
| min_games_seen=2 | 20 | 13.47 / -3.60 | 13.71 / -3.00 | 14.72 / -6.24 | 14.45 / -4.90 | 7.51 | 7.41 | 7.10 |

### Winner-probability calibration (normal p, equal-width bins)

| forecaster | bin | n | mean predicted | observed home-win rate |
|---|---|---|---|---|
| pure-0.5.0 (base) | [0.0,0.2) | 1 | 0.177 | 0.000 |
| pure-0.5.0 (base) | [0.2,0.4) | 6 | 0.312 | 0.167 |
| pure-0.5.0 (base) | [0.4,0.6) | 39 | 0.518 | 0.538 |
| pure-0.5.0 (base) | [0.6,0.8) | 49 | 0.699 | 0.694 |
| pure-0.5.0 (base) | [0.8,1.0) | 145 | 0.938 | 0.924 |
| **wf-level-0.5.0-v1** | [0.0,0.2) | 1 | 0.195 | 0.000 |
| **wf-level-0.5.0-v1** | [0.2,0.4) | 6 | 0.316 | 0.167 |
| **wf-level-0.5.0-v1** | [0.4,0.6) | 36 | 0.511 | 0.528 |
| **wf-level-0.5.0-v1** | [0.6,0.8) | 57 | 0.697 | 0.684 |
| **wf-level-0.5.0-v1** | [0.8,1.0) | 140 | 0.922 | 0.936 |

### Sensitivity (reported, never used to choose the primary)

| setting | n | total MAE | total bias | total MAE − base | log loss − base |
|---|---|---|---|---|---|
| k_level=120 | 240 | 13.67 | 0.69 | -0.121 [-0.330, +0.083] | +0.0022 [-0.0048, +0.0086] |
| k_level=15 | 240 | 13.67 | -0.26 | -0.129 [-0.434, +0.167] | +0.0022 [-0.0048, +0.0086] |
| k_level=60 | 240 | 13.67 | 0.24 | -0.129 [-0.383, +0.117] | +0.0022 [-0.0048, +0.0086] |
| k_sd=20 | 240 | 13.66 | -0.07 | -0.132 [-0.419, +0.145] | +0.0028 [-0.0047, +0.0097] |
| k_sd=80 | 240 | 13.66 | -0.07 | -0.132 [-0.419, +0.145] | +0.0016 [-0.0047, +0.0073] |
| min_games=20 | 240 | 13.66 | -0.07 | -0.132 [-0.419, +0.145] | +0.0022 [-0.0048, +0.0086] |
| min_games=60 | 240 | 13.66 | -0.07 | -0.132 [-0.419, +0.145] | +0.0022 [-0.0048, +0.0086] |

### Decision rule (fixed in WAVE12.md §5)

| criterion | met |
|---|---|
| abs_total_bias_lower | yes |
| dates_ge_5 | yes |
| logloss_not_worse | **no** |
| margin_mae_not_worse | yes |
| margin_rmse_not_worse | yes |
| n_ge_150 | yes |
| total_mae_lower_ci_excludes_0 | **no** |

**INSUFFICIENT EVIDENCE.** The challenger removes the total bias (2.69 → -0.07) and nudges total MAE and RMSE down, but the paired total-MAE difference is -0.132 [-0.419, +0.145], whose interval includes 0. Margin accuracy is identical by construction. The margin-SD recalibration is not supported on this window (base margin z-SD ≈ 1.0; widening/narrowing it leaves log loss +0.0022 [-0.0048, +0.0086] versus base and over-covers: 90% interval coverage 0.93). A scoring-level bias of ~3 points is worth only ~0.15 points of MAE when the total's error SD is ~17, so a few hundred games cannot resolve the MAE gain even though the bias itself is clear. Against the ESPN line the model is still behind on margin and total accuracy (total |e| +0.60 [+0.20, +1.00]); the level fix does not close that gap.

**Caveats the numbers expose.** (1) The level error is not constant in team game number: pure-0.5.0 total bias is 3.92 (team game 1, n=88), 2.74 (game 2, n=132), -3.00 (game 3, n=20); a single pooled level over-corrects the late, small group (challenger bias -6.24 at game 3, and on 2026-11-09). A game-number-aware level is the natural next structure but game 3+ has too few games to fit it. (2) The roster overlay, not this challenger, is what improves margin accuracy and winner probabilities; the level rule is orthogonal to it. The secondary variant on the roster base (`wf-level-0.5.0r`) keeps the roster margin gains (margin MAE 9.24) while removing the total bias (0.07); it is reported, not selected, and the same rules apply to it.

## 4. Connection to market research (diagnostic only)

RESEARCH_ONLY: no bet, order or recommendation; hypothetical fills are diagnostics. The challenger's distribution feeds the existing contract-semantics probability mapping, so every FULL-game WINNER / MARGIN (spread and alternate spread ladders) / TOTAL (total and alternate total ladders) contract gets a fair value from the same normal score distribution. `main` = the strike with the mid nearest 50¢ in its ladder; `alt` = every other strike.

**Universe preserved.** Pre-tip contracts of the eligible games: 8003 — {'MODELLED': 7189, 'UNMODELLED:no_half_distribution_in_frozen_model': 730, 'UNMODELLED:no_overtime_model': 12, 'UNMODELLED:no_race_to_points_model': 4, 'UNMODELLED:no_team_score_distribution_in_frozen_model': 60, 'UNMODELLED:no_validated_payoff_parser': 8}. The newest panel partition (`kalshi_cbb_20261110T124917Z.panel.jsonl.gz`) holds **20774** contracts across all families (futures, props, halves, in-play, unmapped); all are in `by_key` of `wave12_market.json`; unmodelled markets are never dropped, only marked with the reason.

Brier on identical resolved contracts (lower is better; mid = last pre-tip two-sided mid):

| market type | contracts | games | mid | pure-0.2.0 | pure-0.5.0 | challenger | |p−mid| 0.5.0 | |p−mid| challenger |
|---|---|---|---|---|---|---|---|---|
| ALL | 7003 | 239 | 0.1490 | 0.1626 | 0.1600 | 0.1592 | 0.0623 | 0.0573 |
| MARGIN | 2926 | 239 | 0.1236 | 0.1433 | 0.1363 | 0.1366 | 0.0592 | 0.0593 |
| MARGIN:alt | 2514 | 239 | 0.1108 | 0.1283 | 0.1217 | 0.1223 | 0.0566 | 0.0571 |
| MARGIN:main | 412 | 239 | 0.2018 | 0.2348 | 0.2253 | 0.2236 | 0.0751 | 0.0729 |
| TOTAL | 3668 | 239 | 0.1714 | 0.1792 | 0.1804 | 0.1788 | 0.0658 | 0.0553 |
| TOTAL:alt | 3429 | 239 | 0.1660 | 0.1738 | 0.1748 | 0.1734 | 0.0644 | 0.0543 |
| TOTAL:main | 239 | 239 | 0.2496 | 0.2567 | 0.2604 | 0.2567 | 0.0857 | 0.0704 |
| WINNER | 409 | 207 | 0.1299 | 0.1531 | 0.1460 | 0.1460 | 0.0533 | 0.0608 |
| WINNER:alt | 202 | 202 | 0.1317 | 0.1550 | 0.1478 | 0.1478 | 0.0543 | 0.0621 |
| WINNER:main | 207 | 207 | 0.1281 | 0.1513 | 0.1442 | 0.1442 | 0.0523 | 0.0594 |

**Executable-ask economics (HYPOTHETICAL, SIMULATED, UNVALIDATED — not a recommendation).** Net EV per contract of the better executable side (YES at the ask or NO at 1 − bid) after the assumed Kalshi taker fee (`kalshi-quadratic-v1`, rate 0.07, assumed unless the series API carried fee fields); hypothetical P&L = the same sides held to settlement at the quoted price, 1 contract, depth ignored. Quote, fill, fee and mid are separate columns in `wave12_contracts.csv.gz`.

| market | distribution | contracts with positive modelled EV | mean modelled net EV | hypothetical realised net P&L / contract |
|---|---|---|---|---|
| MARGIN | pure-0.5.0 | 1788 | 0.0607 | -0.0682 |
| MARGIN | wf-level-0.5.0-v1 | 1771 | 0.0620 | -0.0677 |
| TOTAL | pure-0.5.0 | 2421 | 0.0644 | -0.0065 |
| TOTAL | wf-level-0.5.0-v1 | 2236 | 0.0544 | -0.0436 |
| WINNER | pure-0.5.0 | 313 | 0.0525 | -0.0678 |
| WINNER | wf-level-0.5.0-v1 | 333 | 0.0582 | -0.0705 |

What the better score distribution does: it moves total-ladder fair values up (mean P(over) 0.445 → 0.493) and reduces the average model-vs-mid gap (0.0658 → 0.0553), i.e. it agrees more with prices the market had already set. Spread and moneyline fair values are essentially unchanged (the level fix leaves the margin mean alone; the margin-SD rescale moves tail strikes slightly). The market mid still scores better than every PURE distribution on every market type; the hypothetical P&L rows are negative or tiny and are **not** evidence of an edge, and the challenger's total-ladder P&L is lower than the base's on this sample — shown, not optimised.

Ladder example (one game, every FULL-game contract): see `ladder_demo` in `wave12_market.json`.

## 5. Larger issues found (next wave, not in this PR)

* **Orientation of neutral-site games.** The schedule archive and the frozen projections disagree on home/away for event games; any scorer that does not guard this (this PR does; the scoreboard does) invents 35–66-point misses. A single canonical orientation key at projection time would remove the class of problem.
* **No team-level prior-weight exposure.** The archived record exposes ratings but not each team's prior-vs-current weight, so early-season prior weighting cannot be tested per team; export it in the projection record to test shrinkage directly.
* **Team-score and half distributions.** The frozen model has none, so team totals, halves and alternates beyond FULL-game WINNER/MARGIN/TOTAL remain unmodelled.
* **Power.** Total-MAE improvements of ~0.15 need several thousand games to resolve; judge scoring-level fixes on total bias and likelihood scores as well as MAE.

## Reproduce

```bash
# archives (read-only) -> local dirs
git archive origin/projections-archive | tar -x -C $WORK/proj
git archive origin/schedule-archive    | tar -x -C $WORK/sched
git archive origin/espn-lines-archive  | tar -x -C $WORK/espn
git archive origin/kalshi-panel-archive| tar -x -C $WORK/panel
curl -L -o $WORK/team_box_2027.parquet https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_mens_college_basketball_team_boxscores/team_box_2027.parquet
python scripts/research/run_wave1.py --projections $WORK/proj --schedule $WORK/sched --espn $WORK/espn \
    --team-box $WORK/team_box_2027.parquet --panel $WORK/panel --out research/wave12
python scripts/research/render_wave1_report.py research/wave12 research/reports/WAVE12_SCORING_LEVEL.md
```
Archives are append-only; re-running later includes newer games (and a different N). The committed outputs are the 2026-11-10 snapshot (data cut: ET dates ≤ 2026-11-09).

