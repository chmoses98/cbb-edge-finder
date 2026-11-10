# WAVE 13 — canonical orientation, exported modelling inputs, hierarchical level challenger (protocol)

Written 2026-11-10 and committed BEFORE any Wave 13 challenger number was computed. RESEARCH_ONLY.
Wave 12 (`WAVE12.md`, `WAVE12_SCORING_LEVEL.md`, `research/wave12/`) is unchanged and its result
(INSUFFICIENT EVIDENCE) stands. Nothing is promoted; `models/pure/active.json`, frozen projections,
candidates, gates, workflows and schedules are untouched.

## 1. Evidence status

2026-11-01..09 is **exploratory development data**, not an untouched holdout: the Wave 12 diagnosis
(including the observation that total-level error differs by team game number) was formed on it.
A Wave 13 forecast for a game uses only information available at that projection's `as_of`, but the
*idea* was seen on these games. Therefore:

* on this window the best possible label is INSUFFICIENT EVIDENCE (never IMPROVED);
* the only prospective evidence is games with `tip >= PROSPECTIVE_FROM = 2026-11-10T21:00:00Z` (the
  registration time of this protocol), recomputable from the immutable archives;
* a game-number effect is not assumed to be causal or stable. Games with team game number >= 3 number
  about 20 in the exploratory window, so no free-standing group-3 adjustment is fitted.

## 2. Challenger `wf13-hier-level-0.5.0-v1` (the only modelling change)

`cbb_edge/model/level_hier.py`, applied to the frozen `pure-0.5.0` projection; no SD rescale (the
projected `margin_sd` / `total_sd` are untouched), margin mean untouched.

Per-possession total residual of a finished game: `r = (actual_total - projected_total) / projected_possessions`.
Groups from team game number known pregame: `G1` = min games seen 0, `G2` = 1, `G3` = 2 or more.
Hierarchical normal model with a pooled level and group deviations:

`r_j = lambda0 + delta_g(j) + e_j`, `e_j ~ N(0, sigma^2)`, `lambda0 ~ N(0, sigma^2 / n0)`,
`delta_g ~ N(0, sigma^2 / n_tau)`.

`sigma^2` = variance of `r` over the finished games in the history (floored at 0.20^2); `n0 = 30`
pseudo-games (identical to Wave 12 `k_level`) and `n_tau = 100` pseudo-games (strong shrinkage of
group deviations toward the pooled level: a group of 20 games gets about 17% of its raw deviation, a
group of 100 about 50%). The posterior mean of `lambda0 + delta_g` times projected possessions is added
to the total (split evenly between the teams). All hyperparameters are fixed now and never tuned.
History rule is identical to Wave 12: only games whose final was first visible in the schedule archive
at or before `as_of`; at least 30 finished games or no adaptation exists (explicit gap).

Preserved baselines (unchanged code and settings): `pure-0.2.0`, `pure-0.5.0`, `pure-0.5.0+roster`,
Wave 12 level-only (`la.Params(sd=False)`). Secondary (reported, not selected): the Wave 13 rule on the
roster base. Ablation reported: independent per-group corrections (no hierarchy) to show what the
shrinkage buys; it is not a candidate.

## 3. Blocked / not used

Per-team pace shrinkage and prior-weight modelling: the needed inputs are exported only for NEW
records (from the first run after this PR is deployed); archived records are never back-filled, so
they cannot enter this evaluation. Market prices as an input: forbidden. Half / team-total / player
distributions: not modelled (Phase 4 interface only).

## 4. Evaluation protocol

Identical eligible games for every row: all five frozen versions, a verified final mapped to the
projected teams by canonical orientation identity (`cbb_edge/data/ids/orientation.py`; UNVERIFIED
games are excluded and counted), tip before 2026-11-10T05:00Z for the exploratory window, challenger
defined (>= 30 finished games), an ESPN pre-tip line for the benchmark (oriented to the projection by
the same identity). Metrics: margin and total MAE / RMSE / bias, winner Brier and log loss (normal p
for every model), 90% interval coverage, by date and team game number, paired game bootstrap
(4000 resamples, seed 20261110, 90% intervals). ESPN and Kalshi are benchmarks only.

## 5. Decision rule (fixed now)

Primary comparisons on the exploratory window: Wave 13 vs `pure-0.5.0` and Wave 13 vs Wave 12 level-only.

* **IMPROVED** — requires genuinely prospective games: at least 150 games on at least 5 dates with
  `tip >= PROSPECTIVE_FROM`, where Wave 13 total MAE is lower than `pure-0.5.0` with the paired 90%
  interval excluding 0, |total bias| is lower, margin MAE/RMSE are not worse (upper bound <= +0.10),
  winner log loss is not worse (upper bound <= +0.005), AND Wave 13 total MAE is no worse than Wave 12
  level-only (upper bound <= +0.05).
* **NOT IMPROVED** — on the exploratory window Wave 13 total MAE is not lower than Wave 12 level-only
  (point difference >= 0), or is higher than `pure-0.5.0`, or margin MAE / winner log loss is worse
  with the paired interval excluding 0.
* **INSUFFICIENT EVIDENCE** — anything else, including every outcome where there are fewer than 150
  prospective games (today: none).

Promotion remains governed by `WAVE4.md`; profitability is never an objective.
