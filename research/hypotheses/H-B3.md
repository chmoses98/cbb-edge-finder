# H-B3-1: Adjusted Four Factors add information beyond adjusted efficiency

Registered 2026-10-04.

* Features: opponent-adjusted eFG%, TO%, ORB%, FTR, 2P%, 3P%, 3PA rate (offense and
  defense), each fitted with the same prior-anchored ridge as efficiency, combined with
  the analytic B2 projection in an expanding-window ridge (alpha 10, trained only on
  prior validation seasons; first fitted season needs ≥ 3 prior seasons).
* Accept if validation margin RMSE(B3) < RMSE(B2) and log loss does not worsen.
* Risk: Four Factors are near-deterministic components of efficiency; gains, if any,
  come from different shrinkage per factor (e.g. 3P% is noisier than TO%).
