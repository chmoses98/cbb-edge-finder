# Residual-driven hypotheses (registered 2026-10-05 from VALIDATION 2015–2024 residuals of B9)

Generated from `research/wave2/metrics.json → residual_slices_validation`. Not fitted on
any evaluation data. To be tested on the 2026-27 prospective archive (and, for model
changes, with a fresh walk-forward run where the change is preregistered first).

| ID | Observation (validation) | Hypothesis | Proposed test |
|---|---|---|---|
| H-RES-1 | First game of season: margin RMSE 13.02 vs 10.90 after 11+ games; 1–3 games: total bias +1.27 | Preseason priors and early totals are the largest remaining error source; market_gap is +0.34 in November vs +0.05–0.10 in Feb–Mar | preseason roster-based team prior (players on the ESPN preseason roster × carried RAPM, freshmen generic prior); early-season total shrinkage toward league mean |
| H-RES-2 | Strength quintiles: margin bias +0.38 (weakest) / −0.45 (strongest) | Mild shrinkage of extreme teams that differs by side (home strong teams under-projected) | bias by strength × site on prospective data; if persistent, add a strength × site term |
| H-RES-3 | |proj margin| ≥ 25: RMSE 13.18, bias −1.30, total bias −1.28 | Blowout dynamics (garbage time / bench minutes) are not linear in rating gap | prospective check; then a preregistered non-linear (spline) margin layer |
| H-RES-4 | Fastest-pace quintile: total RMSE 18.09 vs 16.20 slowest, bias +0.39 | Total variance and level scale with pace beyond the linear model | heteroscedastic total σ by pace (calibration only), pace×efficiency interaction for totals |
| H-RES-5 | Neutral sites: margin RMSE 11.35 vs 11.21, total bias +0.44 | Neutral/tournament games are slightly harder and score lower than projected | neutral-specific total offset tested prospectively (Nov events + postseason) |
| H-RES-6 | Postseason total bias +0.51 | Postseason pace/defense differs | phase-specific total term (already partly in B8 context) |
