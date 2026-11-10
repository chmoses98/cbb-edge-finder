# WAVE 12 (Model Wave 1) — scoring-level challenger `wf-level-0.5.0-v1` (protocol)

Written 2026-11-10 and committed BEFORE the challenger's evaluation numbers were produced.
RESEARCH_ONLY. No frozen projection, existing candidate rule, promotion gate, workflow, schedule or
active trading behaviour is changed. `models/pure/active.json` is untouched: nothing is promoted.

## 1. What was already seen (disclosure)

Before this protocol, the Phase 1 diagnosis (`research/reports/WAVE12_SCORING_LEVEL.md` §1) looked at
frozen pure-0.5.0 errors on all 363 scored games through 2026-11-09 ET, and the earlier
`MODEL_DIAGNOSIS_20261104.md` looked at the first 121. The hypothesis "the frozen total is too low
and the margin SD is too narrow in lopsided games" was formed on that window. **Therefore every
number computed on 2026-11-01..09 games is EXPLORATORY HISTORICAL evidence, not prospective.** The
only prospective evidence is games tipping after the challenger's registration commit; it is
re-computable at any time from the immutable archives (the challenger is a deterministic function of
frozen base records and finals known before each `as_of`).

## 2. The challenger (the only change)

`cbb_edge/model/level_adapt.py`, applied to the frozen `pure-0.5.0` projection of each game:

1. total level: `total += lambda * projected_possessions`, split evenly across both teams (margin mean
   unchanged); `lambda` = possession-weighted mean total residual of games finished at `as_of`,
   shrunk toward 0 with weight `k_level` games;
2. uncertainty: `total_sd` and `margin_sd` multiplied by shrunk RMS standardised residuals of those
   games; margin scale by |projected margin| bin (<6, 6–14, >=14).

Walk-forward rule: a game's adaptation state uses only games whose final score was first observed in
the schedule archive at or before the projection's `as_of`. With fewer than `min_games` such games no
adaptation exists (explicit gap; the game is not in the eligible set).

## 3. Hyperparameters (fixed a priori, never tuned on evaluation games)

`k_level = 30`, `k_sd = 40` games, `min_games = 30`, margin bin edges 6 and 14. Sensitivity
(`k_level` 15/60/120, `k_sd` 20/80, `min_games` 20/60) is REPORTED, never used to choose the primary.
Ablations (level only; sd only) are reported for attribution.

Blocked / not used (recorded, no workaround): market prices as an input (forbidden — PURE/market
separation); in-game or post-tip data; per-team pace shrinkage (needs the team-level pace posterior
that is not in the archived records; only the pooled pace slope is observable); half and team-total
distributions (the frozen model has no marginal team-score or period distribution).

## 4. Evaluation protocol

Identical eligible games for all rows: every version has a frozen pregame projection (`as_of < tip`),
a verified final, tip before 2026-11-10T05:00Z (ET date <= 2026-11-09), challenger defined
(`>= min_games` finished games at `as_of`), and an ESPN pre-tip line for the market benchmark.
Compared: pure-0.2.0 (incumbent), pure-0.3.0, pure-0.4.0, pure-0.5.0, pure-0.5.0+roster, the
challenger, and the ESPN market (point forecasts only). Metrics: margin and total MAE/RMSE, bias,
winner Brier / log loss, 90% interval coverage, calibration bins, by date and by team game number.
Paired game-level bootstrap, 4000 resamples, seed 20261110, 90% intervals.

## 5. Decision rule (fixed now)

Primary comparison: challenger vs pure-0.5.0 on identical eligible games.

* **IMPROVED** — ALL of: total MAE lower with the paired 90% interval excluding 0; |total bias|
  lower; margin MAE and RMSE not worse (paired upper bound <= +0.10 points); winner log loss not
  worse (paired upper bound <= +0.005); at least 150 eligible games on at least 5 distinct dates.
* **NOT IMPROVED** — total MAE point difference >= 0 (no gain), OR margin MAE/RMSE or winner log
  loss worse with the paired interval excluding 0.
* **INSUFFICIENT EVIDENCE** — anything else (e.g. better point estimates with intervals that include
  0, or too few games / dates).

Even if IMPROVED, the label is exploratory-historical: nothing is promoted, the incumbent stays
`pure-0.2.0`, and promotion remains governed by `research/hypotheses/WAVE4.md`.
Market benchmarks are context only and never a selection criterion; profitability is never an
objective (Phase 4 reports are diagnostics, not recommendations).
