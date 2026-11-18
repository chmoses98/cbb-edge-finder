# SIFT Phase 15 - CBB game and half models (research only)

Research code only. Nothing in `cbb_edge/`, `models/`, workflows, gates or prospective archives was changed, and
nothing was promoted. The production incumbent is still `pure-0.2.0` (`models/pure/active.json`).
Code: `research/phase15/cbb_p15_{data,model,eval,kalshi,run}.py`. Tests: `tests/test_phase15_cbb.py`.
Frozen parameters, the truncation test and the Kalshi match report are in `research/phase15/cbb_p15_results.json`.

## What was built
* **Full-game model `p15-eff-full`.** Opponent-adjusted offensive and defensive efficiency plus tempo, refitted for each
  date with ridge regression on earlier games of the season only. Recency weight is tau = 90 days and the prior weight
  is 8 game-rows; both were picked on DEV seasons 2010-19 from a pre-stated 3x2 grid. Non-D-I opponents share one
  pooled team.
* **Preseason prior.** The previous season's final rating is regressed toward the mean by roster continuity and adjusted
  for incoming-transfer quality (O: (0.52 + 0.37c)x + 0.78 tr*in). The regression was fitted on 2008-22 team-seasons
  (n = 5,214) and frozen.
  * Continuity is computed as of the forecast date. It is the share of last season's minutes from players already
    seen for the team. Players not yet seen count with P(return | seasons played) x 0.5^games.
  * A transfer is a player id seen for the team whose previous-season minutes were for another team.
* **Other inputs:**
  * Shrunk team home-court residual from the previous 5 seasons. Neutral sites get no home-court term.
  * Rest difference and back-to-back.
  * A linear calibration layer and a variance regression on games played and forecast size, with the margin-total
    correlation, all fitted on 2010-25.
  * The output is p15eval's discretised bivariate-normal score PMF. Winner, spread, total and team total are all read
    from that one PMF.
* **Baseline `p15-eff-base`.** The same engine with a prior regressed by a constant factor, global home court only, no
  rest terms and constant SDs.
* **Half models (`p15-1h-fitted`, `p15-2h-fitted`).** These are fitted to half outcomes, not split from the full game.
  * Data: 1H and 2H+OT scores from ESPN linescores, 2023-27, in `cbb_halftime_scores.parquet`. 25,917 games, each
    checked so that the periods sum to the final.
  * Features: the full-game mean and SD, plus each team's 1H share of points scored and allowed. The shares use earlier
    dates only and are shrunk with k = 10 games.
  * The model was fitted on 2023-25 (17,205 games) and frozen.
  * Baseline: a proportional split of the full-game forecast (means x s, SDs x sqrt(s), s = 0.470).
* **Holdout:** 2025-26 (ESPN season 2026), D-I vs D-I games, n = 5,752, scored once. 2026-27 to 2026-11-16 is reported
  separately (n = 638).
* **Truncation test.** On 4 dates (306 games), every input was rebuilt from data dated before the game, with the
  game-day scores overwritten. All six forecast streams were identical to the full run (max |diff| = 0.0). Unit tests
  cover the same check on synthetic data.
* **Kalshi strikes.** Settled markets were matched to ESPN games by ticker date and team code. 93% of events matched:
  5,166 of 5,532 spread, 5,143 of 5,509 total, 1,020 of 1,111 1H spread. Outcomes agree with ESPN finals on 100% of
  spread rows and 99.9% of total rows. The settlement `result` field is used as the outcome.
* **Two strike sets were scored:**
  * **Kalshi:** the actual settled strikes (both sides).
  * **Window:** a common half-point ladder around the mean of the two forecasts, for all games.

## Full game, 2025-26 holdout (model vs p15-eff-base; logloss delta [95% game-cluster CI])
| family | strikes | games | logloss | delta vs base | slope (base) |
|---|---|---|---|---|---|
| spread | Kalshi | 4,520 | 0.5247 | -0.0042 [-0.0062, -0.0020] | 0.89 |
| spread | window | 5,752 | 0.4713 | -0.0016 [-0.0029, -0.0002] | 0.95 |
| total | Kalshi | 4,536 | 0.6108 | -0.0021 [-0.0030, -0.0012] | 0.95 |
| total | window | 5,752 | 0.5618 | -0.0017 [-0.0024, -0.0010] | 1.03 |
| team total | window | 5,752 | 0.5260 | -0.0018 [-0.0024, -0.0011] | 1.00 |
| winner | Kalshi | 4,651 | 0.5281 | -0.0007 [-0.0028, +0.0014] | 0.98 |

* **Margin and total errors.** Margin MAE is 9.305 against 9.335 for the baseline (-0.030 [-0.063, +0.001]). Margin
  CRPS improves by -0.034 [-0.054, -0.015]. Total MAE is 13.78 against 13.83 (-0.042 [-0.063, -0.022]). Margin z-SD
  is 1.05 and total z-SD is 0.98.
* **Early slice (either team under 10 games, 1,708 games).** Margin bias is +1.07 and MAE is 10.07, against 8.98 from
  January on. Most of the gain is here: Kalshi spread logloss -0.016 [-0.023, -0.009], total -0.0034
  [-0.0053, -0.0016]. The Kalshi-spread calibration slope is 0.85 early. 2025-26 Kalshi winner rows have slope 1.18
  early, which means under-confident.
* **Compared with existing research on the same 5,752 games.** The repo's B2 has margin MAE 9.219 and B3 has 9.129
  (`research/baseline/metrics.json`), so this model sits at or below B2 level.
* **Against production (2026-27, 638 games, archived pre-tip `pure-0.2.0`).** Production is better on margins. Our
  margin MAE is 10.43 against 10.07 (+0.36 [+0.09, +0.62]), and CRPS is +0.22 [+0.06, +0.39]. Spread logloss on the
  window ladder is +0.0093 [+0.0001, +0.0187]. On Kalshi strikes it is +0.0097 [-0.0023, +0.0216]. Totals are a tie:
  CRPS +0.09 [-0.12, +0.29].
* **Verdict.** Full-game rows are capped at USABLE. This model should not replace production for full-game markets.

## Halves (fitted model vs proportional split)
| family | season / strikes | games | logloss | delta vs split | slope (split) |
|---|---|---|---|---|---|
| 1H spread | 2025-26 window | 5,752 | 0.5312 | -0.0046 [-0.0058, -0.0032] | 0.97 (0.84) |
| 1H spread | 2025-26 Kalshi (Feb-Apr) | 960 | 0.4445 | -0.0098 [-0.0157, -0.0041] | 0.92 (0.78) |
| 1H spread | 2026-27 window | 638 | 0.4877 | -0.0088 [-0.0127, -0.0049] | 1.01 |
| 1H total | 2025-26 window | 5,752 | 0.5593 | -0.0029 [-0.0039, -0.0019] | 0.99 (1.19) |
| 1H total | 2025-26 Kalshi | 980 | 0.5381 | -0.0038 [-0.0064, -0.0011] | 1.00 (1.20) |
| 1H total | 2026-27 window | 638 | 0.5600 | -0.0033 [-0.0059, -0.0004] | 1.02 |
| 1H winner (3-way) | 2025-26 Kalshi | 1,058 | 0.4757 | 0.0000 [-0.0019, +0.0019] | 0.96 |
| 2H spread | 2025-26 window | 5,752 | 0.5362 | -0.0036 [-0.0051, -0.0021] | 0.98 |
| 2H total | 2025-26 window | 5,752 | 0.5917 | -0.0003 [-0.0009, +0.0004] | 1.03 |

* **Where the 1H gain comes from.** It is mostly better-sized distributions, not better means. The proportional
  split's sqrt-share SD is too narrow for the 1H margin (z-SD 1.23) and too wide for the 1H total (z-SD 0.86). The
  fitted model is at 1.02 for both.
* **1H mean.** The 1H margin gain is concentrated early. The 1H margin MAE delta is -0.018 [-0.045, +0.010] overall but
  -0.10 [-0.16, -0.04] early. The fitted 1H margin carries 0.57 of the full-game margin, against a 0.47 points share.
* **1H CRPS** improves by -0.066 [-0.085, -0.046].
* **These are calibration gains, not sharpening.** Calibration slopes move toward 1 and logloss falls with them.
* **2H** is capped at USABLE because only 16 Kalshi 2H events exist.

## Verdicts (matrix `sift-alpha/research/phase15/matrix/CBB.json`, 44 rows)
* RELIABLE: 1H spread and 1H total.
* USABLE:
  * Full-game winner, spread, total and team total. They are calibrated, but production is stronger.
  * 1H winner (no gain).
  * 2H spread, total and winner.
* None ABSTAIN. The Kalshi team-total (16 events) and 2H (16 events) samples are reported but too small to judge.

## Missing pregame inputs (details in `readiness/CBB.json`)
* **Roster truth before game 1** (portal arrivals and departures, freshmen, exhausted eligibility). The best free source
  is the repo's daily official-roster capture (`roster-archive`, since 2026-10). It has no history before 2026-27, so it
  cannot be backtested. This model only learns continuity and transfers after a team's first game, which is why the
  early slice is weakest.
* **Injuries and availability.** ESPN summary and roster captures (`availability-archive`) exist only from 2026-11, and
  ESPN college injury coverage is sparse.

## Limits
* There is no historical per-game replay of production for 2025-26. The production comparison is 2026-27 only
  (n = 638, about 2 weeks, early season).
* The 1H model's training seasons depend on linescores, which start in 2023.
* KXNCAAMBOT and KXNCAAMBWINMARGIN were not modelled.
* 2026-27 slopes are measured on early-season games only.
* **Next step:** fit the 1H layer on the production full-game inputs once enough archived records exist.
