# WAVE 16 — roster-overlay centring challenger B `rcenter-0.5.0r-v1` (REGISTRATION)

RESEARCH_ONLY. Registered 2026-11-13, before any record in the eligibility window exists. The window opens on 2026-11-15T00:00Z.
No frozen projection, production model, default, candidate, promotion gate, schedule, runner or permission is changed, and nothing is promoted.
The immutable spec is `research/wave16/spec.json`; a test asserts code == spec.
Wave 16 is separate from Waves 14 and 15. It has its own code, spec, outputs and verdict, and it shares only the family-wise error
correction and the evaluation window with Wave 15.

## 1. Hypothesis (from `research/reports/PROJECTION_DIAGNOSTICS_20261113.md`, exploratory 468 games)

The roster overlay `pure-0.5.0_roster` has the best margin MAE and log loss of the five versions, but its margins sit about one
point too far toward the home team: margin bias −1.04 [−1.64, −0.34].
**H16-B:** removing that mean offset, while keeping the overlay's game-to-game adjustments, lowers winner log loss versus the
overlay without giving up its margin accuracy.

## 2. Challenger

* **Centring term.** `c = Σ(y − roster_margin) / (n + k)` is a walk-forward mean residual of the overlay, shrunk toward 0 with
  `k = 30` pseudo-games and `min_games = 30`. It is fit only on games whose orientation-verified final was first observed at or
  before the target record's `as_of`.
* **Forecast.** `margin' = roster_margin + c`; the total and `margin_sd` are unchanged.
* **Probability.** The probability moves along the frozen production link: `p' = σ(logit(p_roster) + 0.161365·c)`.

**Considered and not registered: an outcome-free centring.** Subtracting the mean (roster − base) delta over earlier records uses no outcomes, so it is attractive.
It is reported descriptively only. On the exploratory data the delta is mostly a margin *stretch*: slope 0.10 on the base
margin, intercept +0.08. Removing its mean therefore over-corrects, moving the bias to +1.11.

## 3. Fail closed / eligibility (identical games for every forecaster)

A game is eligible only if all of the following hold:
* The latest pre-tip `pure-0.5.0` and `pure-0.5.0_roster` records both have `as_of ≥ 2026-11-15T00:00Z`.
* The tip is on an ET date ≤ 2026-12-20.
* Both records carry the registered model sha `c4600f62…`.
* The game has an orientation-verified archived final.
* Both records' manifests have verified freeze provenance from GitHub Actions job records, with `pushed_by < tip`.
* There are at least 30 finished training games.

One row per game.

## 4. Evaluation and decision rule (fixed now)

* **Window.** The fixed window is analysed once, at or after 2026-12-22T12:00Z, and is COLLECTING before then.
* **Floor.** ≥ 300 games on ≥ 10 ET dates; otherwise INSUFFICIENT EVIDENCE.
* **Bootstrap.** Clustered by ET date, 10 000 replicates, seed 20261113.
* **Multiplicity.** This is one test of the three-test family shared with Wave 15. It is tested one-sided at α = 0.05/3
  (Bonferroni), so the primary bound is the 98.33% quantile. Guards use the 95% one-sided bound.
* **IMPROVED (versus `pure-0.5.0_roster`):** all of:
  * the log-loss upper bound is < 0;
  * the margin-MAE upper bound is ≤ +0.05, which protects the overlay's accuracy advantage;
  * the Brier upper bound is ≤ +0.002.
* **NOT IMPROVED:** the log-loss point difference is ≥ 0, or its lower bound is > 0, or a guard's lower bound exceeds its tolerance.
  Anything else is INSUFFICIENT EVIDENCE.
* **Always reported:** directional margin bias with intervals, and every metric versus both `pure-0.5.0_roster` and
  `pure-0.5.0`. Calibration is reported by win-probability quintile and |margin| band.

Even IMPROVED is research evidence only. Promotion remains governed by `research/hypotheses/WAVE4.md`.

## 5. Disclosure of exploratory development (historical; NOT evidence)

* **Setup.** `k` and `min_games` follow Wave 12/14/15 conventions. The walk-forward run used only records frozen before the Wave 14 boundary:
  347 games on 10 dates, in `research/wave16/wave16_exploratory_historical.json`. None of these games is ever eligible.
* **Versus the overlay** (point estimates, 90% date-clustered intervals):
  * log loss −0.0035 [−0.0074, −0.0002];
  * margin MAE −0.016 [−0.083, +0.044];
  * Brier −0.0008 [−0.0021, +0.0005];
  * bias −0.79 → +0.37.
* **Versus base:** log loss −0.0114 [−0.0209, −0.0027].

These numbers chose the registered variant over the outcome-free one, so they are not evidence for H16-B. The expected effect is
small, and a confirmatory IMPROVED needs the full window.

## 6. Known limitations

Same as Wave 15 §6:
* challenger predictions are deterministic recomputations from frozen records and this commit's code, not a separately frozen stream;
* finals come from one provider and are re-checked later from the same provider;
* the window overlaps Wave 14's games, but the hypotheses differ and neither result enters the other's decision.

## 7. Tooling

`python scripts/research/prospective_wave16.py --projections <arch> --schedule <sched> --provenance research/wave14/freeze_provenance.json --out research/wave16 --report research/reports/WAVE16_ROSTER_CENTERING.md --exploratory`

The CI regrade job runs it alongside Wave 14, reusing that run's archives and verified provenance.
