# Wave 2 preregistration (2026-10-05, before any wave-2 validation result was computed)

Objective: reduce the independent PURE_BASKETBALL forecast error (margin RMSE first;
then total RMSE, log loss, calibration). Betting ROI is not a criterion for anything here.

Common protocol for every arm:
* stacked ridge (alpha 10, standardized features), expanding window: season s is
  predicted by a model trained on 2012..s-1 only (identical window for all arms,
  including the B3 reference, so differences are attributable to features);
* validation 2015–2024; historical 2025–2026 (already observed in PR #1 — evidence only);
* promotion: validation margin RMSE < B3 AND better in ≥ 7/10 seasons AND log loss not
  worse. A promoted block must still not worsen the historical seasons materially;
* market data: none. `market_gap` is computed afterwards, downstream.

| ID | Hypothesis | Block |
|---|---|---|
| H-B6-1 | Player impact (prior-anchored ridge RAPM from free NCAA stints, ESPN-id identity across seasons/transfers) on the expected rotation (EW minutes, missed games = 0) adds information beyond team-level ratings, especially early season and when rotations change. | `blocks.player_block` |
| H-B6-2 | RAPM hyperparameters (prior strength λ, carry-over, new-player prior) tuned on DEV 2012–2014 only. | `scripts/research/tune_rapm_dev.py` |
| H-B7-1 | Opponent-adjusted shot profile (rim rate, rim FG%, mid rate, mid FG%, assisted share) and rim-offense × rim-defense interaction add information beyond eFG%/3PA rate. | `blocks.shot_block` |
| H-B8-1 | Rest days, season phase and a hierarchically shrunk team-specific home-court effect (prior 3 seasons, k = 40 pseudo-games) improve projections. | `blocks.context_block` |
| H-B9-1 | Combining all blocks beats each block alone (complexity must earn its place). | B9 |
| H-PACE-1 | A ridge possession model (additive tempo + interaction + slow-side + rest/phase) has lower possession MAE than the calibrated additive model. | `model/pace.py` |
| H-UNC-1 | Heteroscedastic margin σ (sample size, total, pace, 3PA, mismatch, neutral, roster known) improves win-probability log loss and interval calibration vs bucketed SD and the logistic link. | `model/uncertainty.py` |

Deferred (no free data or not yet built): coaching continuity (no free coach history in
our sources), travel distance / altitude (no free venue geocoding), transfer-specific
priors beyond RAPM carry-over (RAPM already follows ESPN athlete ids across schools).
