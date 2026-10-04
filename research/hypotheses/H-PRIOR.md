# H-PRIOR-1: Prior strength and decay

Registered 2026-10-04. DEV seasons only (2008–2014 evaluated; 2006–2007 warm-up).

* Grid: prior strength scale ∈ {0.35, 0.5, 1, 2} × base λ (eff 450 possessions, tempo 6
  games, …), carry-over ρ ∈ {0.5, 0.65, 0.8, 0.9, 1.0}, recency τ ∈ {none, 45, 90} days.
* Selection: lowest DEV margin RMSE of B2 (eff + tempo only).
* Result: scale 0.5 (eff prior = 225 possessions ≈ 3.3 games), ρ = 0.9, τ = 90 days
  (RMSE 10.905 vs 10.910 without recency). Optimum is interior in every dimension.
  Interpretation: a team's prior is worth ~3 games of data; after ~10 games the
  current season dominates (data weight n/(n+λ) ≈ 0.75).
