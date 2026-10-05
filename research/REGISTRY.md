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
| B6 | B3 + player impact (walk-forward RAPM, NCAA stints 2011–2026) on expected rotation | **accepted** (wave 2) |
| B7 | B3 + opponent-adjusted shot profile (rim/mid/assisted) + rim matchup | **accepted** (wave 2) |
| B8 | B3 + rest, season phase, shrunk team-specific home court | **accepted** (wave 2) |
| B9 | B3 + B6 + B7 + B8 — **PURE production arm `pure-0.2.0`** | **accepted** (wave 2) |
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

## Wave 2 outcomes (see research/reports/WAVE2.md; preregistration research/hypotheses/WAVE2.md)

| Hypothesis | Result | Status |
|---|---|---|
| H-B6-1 player impact | val RMSE −0.006 vs B3 (7/10 seasons), larger in 2024–26 (−0.03 to −0.04) | accepted (weak) |
| H-B6-2 RAPM tuning (DEV) | λ = 800 poss (interior optimum), carry 0.95, new-player prior (−0.8, +0.4) | done |
| H-B7-1 shot profile | val RMSE −0.006 (9/10) | accepted (weak) |
| H-B8-1 context | val RMSE −0.010 (9/10) | accepted |
| H-B9-1 combined | val RMSE −0.025 (10/10); historical −0.060 | accepted → production |
| H-PACE-1 ridge possession model | possession MAE 3.749 vs 3.752 (calibrated additive) | rejected (no meaningful gain) |
| H-UNC-1 heteroscedastic σ | log loss 0.5303 vs 0.5303 (bucket SD); PIT deviation slightly worse | rejected (no gain) |
| H-B4 roster continuity (PR #1) | superseded by B6 (player identity carries over) | rejected |
| H-B5 matchup interactions (PR #1) | no gain | rejected |
