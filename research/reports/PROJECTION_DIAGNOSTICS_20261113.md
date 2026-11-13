# Projection weaknesses across the five frozen model versions (2026-11-13)

RESEARCH_ONLY, **EXPLORATORY_HISTORICAL**. Nothing is promoted and no model, default, weight or frozen record is changed.

Reproduce with:

```
python scripts/research/run_projection_diagnostics.py --projections <projections-archive> --schedule <schedule-archive> --espn <espn-lines-archive>
```

This writes `research/diagnostics/projection_diagnostics.json`, from which every number below is taken. Code is in `cbb_edge/research/projection_diagnostics.py`. Archives used: projections `b18484d`, schedule `86d2e0e`, espn-lines `9d9c934`.

## Scope and separation from Wave 14
- The sample is **468 games on 12 ET dates (Nov 1–12)**. Every game has a frozen pre-tip record for all five versions and an orientation-verified final; finals orientation is 471 SAME and 5 SWAPPED, with none excluded.
- Every statistic is computed on the identical game set. The ESPN pre-tip line is present for all 468 games and is used **only as a benchmark**, never as an input.
- Records frozen at or after the Wave 14 boundary (2026-11-11T22:00Z) are **excluded**: 8 games with finals. The frozen Wave 14 evaluation (`WAVE14_PRIOR_WEIGHT.md`) is the only place prospective evidence is judged. Nothing here bears on its verdict.
- Intervals are 90% bootstraps that resample whole ET dates. Two dates are tiny (Nov 1: 2 games, Nov 12: 1 game) and Nov 2 holds 119 games, so the intervals are rough.

## Version table (identical 468 games; bias = actual − projected)

| version | total bias | total MAE | margin bias | margin MAE | log loss | Brier | total z-SD | margin z-SD | margin slope* |
|---|---|---|---|---|---|---|---|---|---|
| pure-0.2.0 | +3.25 | 13.86 | +1.14 | 10.13 | 0.4036 | 0.1314 | 1.01 | 1.05 | 1.11 |
| pure-0.3.0 | +2.72 | 13.66 | +0.76 | 9.76 | 0.3897 | 0.1276 | 1.00 | 1.02 | 1.09 |
| pure-0.4.0 | +2.87 | 13.70 | +0.58 | 9.75 | 0.3886 | 0.1270 | 1.00 | 1.02 | 1.09 |
| pure-0.5.0 | +2.96 | 13.73 | +0.44 | 9.77 | 0.3918 | 0.1277 | 1.00 | 1.03 | 1.08 |
| pure-0.5.0_roster | +2.88 | 13.73 | −1.04 | 9.64 | 0.3858 | 0.1258 | 1.01 | 1.01 | 0.97 |
| ESPN line (benchmark) | −0.60 | 13.08 | – | 8.96 | – | – | – | – | – |

\*The margin slope is the OLS slope of the actual margin on the projected margin. A slope of 1 is ideal; a slope above 1 means projected margins are too compressed toward zero.

## What the evidence says

| question | finding (pure-0.5.0 unless stated) | verdict |
|---|---|---|
| Total-score bias | +2.96 [+1.38, +4.04]; market −0.60 | **Real, persistent level error.** It is present in all five versions. |
| Pace | Bias by projected-possessions tercile (low/mid/high): +3.46 / +3.03 / +2.38. Total slope 0.97 [0.80, 1.13] | No pace-specific failure. A level shift dominates, slightly larger in slow games. |
| Early-season priors | Bias by the lower games-seen count of the two teams: 0 → +3.78 (n=213), 1 → +3.06 (177), 2 → +0.48 (78). Market: −0.97 / +0.19 / −1.40 | **The level error lives in the prior.** It fades once teams have two games of data. This is the thread Waves 12–14 test. |
| Market disagreement on totals | Slope of (actual − model) on (market − model): 0.93 [0.77, 1.23] | The market's total disagreement with the model is borne out almost one-for-one. |
| Opponent adjustment / margin dispersion | Margin slope 1.08 [1.05, 1.13]. Where \|projected margin\| ≥ 16 (n=212), the favourite beats the projection by +1.81 and the margin z-SD is 1.13. Where it is < 8 (n=157), the z-SD is 0.82. Market margin-disagreement slope 1.21 [1.03, 1.52] | **Mismatches are under-projected and their uncertainty is under-stated, while close games are over-dispersed.** The SD does not scale with \|margin\|. |
| Roster uncertainty | Roster minus base, margin MAE: −0.12 [−0.20, −0.03] overall, −0.09 [−0.25, +0.10] where the overlay moves the margin ≥ 2. Log loss 0.3858 vs 0.3918. Roster margin bias **−1.04 [−1.64, −0.34]**; slope 0.97 [0.93, 1.04] | The overlay helps and removes the compression, but **adds a home-direction offset of about one point.** |
| Calibration | Total z-SD 1.00 and 80% coverage 0.79. Win-probability reliability by quintile (forecast → observed): 0.46→0.50, 0.74→0.65, 0.90→0.86, 0.97→0.94, 0.99→1.00 (about 94 games per bin) | Totals are well calibrated. Mid-range home favourites look about 5–9 points overconfident, but that is within about 2 SE per bin, so it is noted, not claimed. |

## The three strongest evidence-supported improvement hypotheses
These are registration candidates. Each one needs its own preregistered protocol and prospective evaluation before any claim.

1. **H-A: early-season scoring-level prior (totals).** The league-level points-per-possession prior is too low for 2026-27. Total bias is +3.8 / +3.1 / +0.5 at 0 / 1 / 2+ games seen, and the market is near zero. Every version shares it, and 93% of the market's total disagreement is borne out.
   - Wave 12 (walk-forward level) and Wave 14 (prior-weight scaling) already target this, and Wave 13 (game-number hierarchy) was NOT IMPROVED. The untested variant is a better-centred prior *mean* rather than a post-hoc level shift: preseason league PPP set from the prior season's late-season level plus a known year-over-year drift.
   - **Wave 14 is collecting; do not start a competing totals challenger on the same games until it resolves.**
2. **H-B: heteroscedastic margin uncertainty and mismatch compression (margins and calibration).** Projected margins are about 8% too compressed (slope 1.08, interval excludes 1 under date clustering).
   - The shortfall concentrates in mismatches: +1.8 points toward the favourite and z-SD 1.13 where \|margin\| ≥ 16, against z-SD 0.82 in close games.
   - The market's extra margin information is fully borne out (slope 1.21).
   - Candidate: `margin_sd = a + b·|margin|` plus a margin stretch, both fit walk-forward on base `pure-0.5.0`. This mostly affects log loss and Brier. It is distinct from Wave 14, which leaves margins untouched, so it can run in parallel without touching Wave 14's comparison population.
3. **H-C: centring the roster overlay.** `pure-0.5.0_roster` has the best margin MAE and log loss and fixes the compression (slope 0.97), but shifts margins about 1.0 point toward the home team (bias −1.04 [−1.64, −0.34]).
   - Candidate: a walk-forward mean-zero constraint on the overlay's adjustment, or one shared home-court term for base and overlay.
   - Expected gain is small in MAE (≈ the bias² share) but direct in log loss.

## Limitations
- The sample is 12 dates of early-season play, with 45% of games projected at \|margin\| ≥ 16 (many power-versus-low-major mismatches). Effects may shrink as conference play starts.
- The ESPN line is one book's free line. It is a benchmark, not an independent ground truth.
- There is no box-score possession data here, so the pace and efficiency split relies on Wave 12's exact decomposition (pace +1.28, efficiency +1.66 of the total bias on Nov 1–9).
- Nothing here uses Wave 14's 8 prospective games, and nothing should be read as evidence for or against H14.
