# H-B4-1: Roster continuity improves early-season projections

Registered 2026-10-04.

* Prior for team i in season s: ρ_i × (last-season rating), with
  ρ_i = ρ̄ · (c0 + c1·share_i) / (c0 + c1·mean share), ρ̄ = tuned carry-over (0.9).
  (c0, c1) = (0.548, 0.358) estimated on DEV seasons only
  (`research/baseline/roster_prior_dev.json`).
* share_i(D) = share of the team's previous-season minutes played by players who have
  **already appeared** for the team in season s before day D (leakage-safe: no future
  roster knowledge). Before a team's first game: league-average share.
* Accept if B4 improves validation margin RMSE over B3 overall AND in games where
  min(games played) < 6.
* Known limitation: transfers-in, freshmen and recruiting are not yet modeled.
