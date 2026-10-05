# Research Registry

Every experiment is registered here **before** its validation result is viewed.
Status values: `registered` → `run` → `accepted` / `rejected`. A rejected idea stays
listed. Results live in `research/baseline/metrics.json` and `research/reports/`.

## Season roles (fixed 2026-10-04, before any validation result)

| Role | Seasons | Use |
|---|---|---|
| Seed | 2006 | builds priors only; never evaluated |
| DEV | 2007–2014 | hyperparameter tuning (`scripts/research/tune_dev.py`, `roster_prior_dev.py`) |
| VALIDATION | 2015–2024 | arm comparison, walk-forward, expanding-window fitted layers |
| HOLDOUT | 2025–2026 | opened once per frozen configuration; any later change must be re-registered |

2021 (COVID season) is kept but flagged; results are reported with and without it in
future reports.

## Primary metrics (decided in advance)

1. Margin RMSE and MAE (lower is better); 2. total RMSE/MAE; 3. win-probability log
loss and Brier; 4. calibration (ECE). ROI is a secondary diagnostic only, never a
selection criterion. An arm is "better" only if it improves validation margin RMSE
AND does not worsen log loss, on the common sample of games every arm projects.

## Arms

| ID | Description | Status |
|---|---|---|
| B0 | home court + league total (prior seasons) | run |
| B1 | raw rolling efficiency + tempo, same shrinkage engine, opponent adjustment off | run |
| B2 | opponent-adjusted efficiency + tempo, analytic projection | run |
| B3 | B2 + opponent-adjusted Four Factors / shot profile via expanding-window ridge | run |
| B4 | B3 with roster-continuity priors (returning-minutes share, leakage-safe) | run |
| B5 | B4 + preregistered matchup interactions (H-B5) | run |
| B6 | B5 + player/lineup layer (NCAA lineups/stints, 2011–2026) | registered (not built) |
| ELO | points-based Elo dynamic benchmark | run |
| MARKET | free historical closing line (ESPN pickcenter) | run |
| ENSEMBLE | B3 + market prior, expanding-window ridge | run |
| ESPN | ESPN published pregame win probability (benchmark only) | run |

## Hypotheses

* H-B1-1 Opponent adjustment improves projections: B2 margin RMSE < B1. — `research/hypotheses/H-B1.md`
* H-B3-1 Adjusted Four Factors add information beyond adjusted efficiency. — `H-B3.md`
* H-B4-1 Returning-minutes continuity improves early-season projections. — `H-B4.md`
* H-B5-1..6 Matchup interactions. — `H-B5.md`
* H-PRIOR-1 Prior decay rate (prior strength λ, carry-over ρ) — tuned on DEV only. — `H-PRIOR.md`
* H-MKT-1 Model anticipates open→close movement (exploratory on 2026; prospective test registered) — `H-MKT.md`
