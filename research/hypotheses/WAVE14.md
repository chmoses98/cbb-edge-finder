# WAVE 14 — prior-weight-proportional scoring-level challenger `pw-level-0.5.0-v1` (REGISTRATION)

RESEARCH_ONLY. Registered 2026-11-11 before any outcome of an eligible game exists. No frozen projection, existing
model, candidate, promotion gate, schedule or workflow is changed; `models/pure/active.json` is untouched. Nothing is
promoted. Immutable machine-readable spec: `research/wave14/spec.json` (a test asserts code == spec).

## 1. Hypothesis and disclosure

Wave 12 found pure-0.5.0's total ~3 points low early in the season, with a sign flip by team game number. Wave 13's
game-number hierarchy was NOT IMPROVED. Hypothesis H14: the per-possession total error is proportional to how much of
the teams' pace/efficiency ratings is still the prior (last season's regressed rating), as exported in `model_inputs`.

Disclosure: the Wave 12/13 outcomes (Nov 1-9) were seen; they carry no `model_inputs` and are NOT used for any choice
here. Before registration I audited only the structure of `model_inputs` (bounds, identities, timestamps), not the
relationship between prior weight and outcomes. All parameters below were fixed from the proposal, not from data.

## 2. Challenger (the only change)

`adjusted_total = base_total + beta * pbar * projected_possessions`, shift split evenly between the teams
(`home_score += shift/2`, `away_score += shift/2`); margin, margin SD, total SD and win probability are unchanged, so
margin accuracy and probability calibration are identical to pure-0.5.0 BY CONSTRUCTION (still reported and tested).

* `pbar` = mean of the four prior weights (home/away x pace/efficiency) in the record's own `model_inputs`.
* `beta`: ridge slope through the origin of `actual_total - projected_total` on `x = pbar * possessions`,
  `beta = sum(x*e) / (sum(x^2) + k_beta * x_ref^2)`, `k_beta = 30` pseudo-games, `x_ref = 40` (constant). Fit only on
  pure-0.5.0 games with valid inputs whose final was first observed at or before the target projection's `as_of`
  (strict walk-forward). `min_games = 30` such games, else no adjustment (explicit gap, game not eligible).
* ONE parameter (`beta`), fixed shrinkage. No game-number groups, no SD rescale, no market input, no tuning on Wave 12/13.

## 3. Fail closed

No adjustment (game ineligible, excluded from fitting) if: `model_inputs` absent; version != `cbb-model-inputs-1`; basis !=
`ridge_diagonal_approx`; any of the four prior weights missing, non-finite or outside [0,1]; prior+current != 1;
`prior_strength/effective_sample != prior_weight`; `info_cutoff_utc` after `as_of` (point-in-time); exported expected
possessions != projection possessions. Historical records without `model_inputs` stay missing; nothing is back-filled.

## 4. Known limitations of the input (documented, not fixed)

* The exported weight is a ridge-DIAGONAL approximation: it ignores opponent coupling and recency decay; the exact prior
  value and posterior covariance are not exposed (`missing` in every record).
* Pace prior weight is exactly `3/(3+games_seen)` - a pure function of game number. Only the efficiency weight
  (`225/(225+possessions_seen)`) varies independently, so H14 is only partly distinct from the failed Wave 13 game-number
  idea. Early-season `pbar` lives in roughly [0.55, 1.0] (games_seen 0-4 so far): beta is identified from a narrow range.
* The expected sign of beta is positive (more prior -> larger shortfall); beta is not constrained, so a negative estimate is allowed.

## 5. Prospective boundary and evaluation protocol

Eligibility boundary `PROSPECTIVE_FROM = 2026-11-11T22:00:00Z` (set before the registration push; the push time of the
registration commit on `origin` is the audit stamp). Eligible game: the latest frozen pure-0.5.0 record (`as_of` < tip) has
`as_of >= PROSPECTIVE_FROM`; valid inputs; orientation-verified final; frozen records for pure-0.2.0, pure-0.5.0 and
pure-0.5.0_roster; challenger and Wave 12 level-only (`k_level=30`, level only, `min_games=30`) both defined. Games with
earlier records are NEVER eligible (they may train beta because their finals precede later predictions). Identical games
for all rows. Forecasters: pure-0.2.0, pure-0.5.0, roster overlay, Wave 12 level-only, challenger. Metrics: total and margin
MAE/bias, winner log loss and Brier. Matched-game differences with a 90% percentile bootstrap that resamples ET game
DATES (clusters), 4000 reps, seed 20261111.

### 5a. Amendment 2026-11-13: verified-push selection (outcome-blind, before the sample floor)

The selected record per (version, game) is the latest one with `as_of` < tip **and** a server-side push time,
taken from a verified manifest (`research/wave14/freeze_provenance.json`), that is strictly before tip. A
record pushed at or after tip, with an unverifiable push time, or listed in no manifest is quarantined and never
selected. Selection falls back to the latest earlier verified record, which must still satisfy every rule above,
including `as_of >= PROSPECTIVE_FROM`. Records before `PROSPECTIVE_FROM` are selected as before (latest `as_of` < tip):
they are never eligible and only train. The rule reads provenance only, never outcomes. On the archive at amendment
time it changes no eligible game, `as_of` or verdict (`docs/COLLECTION_RELIABILITY.md` section 6). Previously a
late-pushed latest record excluded the whole game even when an earlier record had been safely frozen.

## 6. Decision rule (fixed now)

Floor: >= 150 eligible games on >= 5 distinct dates. Below it the only status is **COLLECTING / INSUFFICIENT EVIDENCE**.
At or above the floor, versus pure-0.5.0 unless noted:

* **IMPROVED** - ALL: total-MAE difference interval upper bound < 0; total-MAE upper bound vs Wave 12 level-only <= +0.10;
  margin-MAE upper bound <= +0.10; log-loss upper bound <= +0.005.
* **NOT IMPROVED** - total-MAE point difference >= 0, or its interval lower bound > 0, or interval lower bound vs Wave 12
  level-only > +0.10.
* **INSUFFICIENT EVIDENCE** - anything else.

Even IMPROVED is exploratory-prospective: nothing is promoted; promotion stays governed by `research/hypotheses/WAVE4.md`.
Market data is never an input; profitability is never an objective.

## 7. Tooling

`python scripts/research/run_wave14.py --projections <arch> --schedule <sched>` regenerates
`research/wave14/wave14_results.json` and `research/reports/WAVE14_PRIOR_WEIGHT.md` deterministically from the immutable archives.
