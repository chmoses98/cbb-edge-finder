# WAVE 14 PROPOSAL — prior-weight-proportional scoring-level correction (NOT registered, no results)

Status: proposal for owner review. It is not a protocol until it is committed as one before any data exists
for it. RESEARCH_ONLY; nothing promoted; the failed Wave 13 hierarchy is not retuned and no Wave 12/13 sample is reused.

## Question

Wave 12 found a ~3 point scoring-level shortfall in pure-0.5.0 that flipped sign across team game numbers
(+3.9 / +2.7 / −3.0, the last n = 20). Game number is only a crude proxy for the thing that plausibly drives
it: how much of each team's pace and efficiency rating is still the prior (last season's regressed rating) rather
than current-season evidence. The new `model_inputs` block exports exactly that per team (`pace_weighting.prior_weight`,
`efficiency_weighting.prior_weight`, effective samples, posterior SDs). Hypothesis: the total-level error per possession
rises with the game's mean prior weight, i.e. it is a *prior-too-low-for-this-season's-scoring* effect that fades as evidence
accumulates, not a game-number step.

## The one experiment

Challenger `pw-level` on the frozen pure-0.5.0 projection: add `beta * pbar * projected_possessions` to the total, where
`pbar` is the mean of the two teams' efficiency and pace prior weights from the record's own `model_inputs`, and
`beta` is ONE walk-forward parameter (shrunk toward 0 with a fixed pseudo-game weight, as in Wave 12, estimated only from
games whose final was visible at `as_of`). One parameter, continuous covariate, no groups, no SD rescale, margin untouched.
Comparators: pure-0.5.0, the roster overlay, Wave 12 level-only (the better level baseline).

## Why it is a new experiment, not a retune

It uses a covariate that did not exist in any archived record before the export; it cannot be evaluated on Nov 1–9 (those
records carry no `model_inputs`, and old records are never back-filled). It needs genuinely future games.

## Gate before registering

1. PR #46 and the orientation follow-up are reviewed and merged by the owner, and the export is live in the next daily run.
2. A one-day dry run on the production lake confirms `model_inputs` is populated for every active version.
3. Register hyperparameters and the decision rule in a protocol committed before the first eligible game is evaluated;
   require ≥150 games on ≥5 dates with `model_inputs`, total-MAE interval excluding 0 against pure-0.5.0 and no worse than
   Wave 12 level-only, margin and log loss not worse.

Out of scope (SIFT Alpha owns input cataloguing): any new data source. Uncertainty use of `pace_posterior_sd` is a separate,
later experiment.
