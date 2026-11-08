# P-ROSTER-1 prospective scoreboard — 20261108T140338Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 202**

Pre-tip gate: VALID 298 · INVALID 0 · UNSCORABLE 2 · PENDING 3 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **202** | 9.79 | 9.74 | -0.05 | 12.50 | 12.35 | -0.15 | 0.55 | -1.39 | 51% | -0.05 | 146.2 → 0.6 (283 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **96** | 9.70 | 9.58 | -0.12 | 12.50 | 12.26 | -0.24 | 0.59 | -0.90 | 55% | -0.12 | suppressed (N<20 or <10 days) |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **202** | 9.79 | 9.74 | -0.05 | 12.50 | 12.35 | -0.15 | 0.55 | -1.39 | 51% | -0.05 | suppressed (N<20 or <10 days) |
| games_2_3 | **96** | 9.70 | 9.58 | -0.12 | 12.50 | 12.26 | -0.24 | 0.59 | -0.90 | 55% | -0.12 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **196** | 9.89 | 9.79 | -0.10 | 12.60 | 12.42 | -0.18 | 0.67 | -1.28 | 53% | -0.10 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **91** | 9.65 | 9.55 | -0.10 | 12.30 | 12.10 | -0.20 | 0.22 | -1.34 | 54% | -0.10 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **5** | 10.61 | 10.22 | -0.39 | 15.78 | 14.89 | -0.89 | 7.28 | 7.03 | 80% | -0.39 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 362 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-6h | 362 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-72h | 362 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 362 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| latest | 362 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.70 | 0.11 | 0.01 |
| BASE | 362 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **202** | 9.79 | 9.74 | -0.05 | 12.50 | 12.35 | -0.15 | 0.55 | -1.39 | 51% | -0.05 | suppressed (N<20 or <10 days) |
| team_game_2 | **148** | 9.18 | 9.23 | 0.05 | 12.00 | 11.80 | -0.19 | 0.81 | -0.58 | 53% | 0.05 | suppressed (N<20 or <10 days) |
| team_game_3 | **13** | 12.02 | 11.47 | -0.54 | 15.72 | 14.78 | -0.94 | 0.74 | -1.30 | 54% | -0.54 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **82** | 10.15 | 10.09 | -0.06 | 12.73 | 12.64 | -0.09 | -0.25 | -0.33 | 59% | -0.06 | suppressed (N<20 or <10 days) |
| 2-4 | **55** | 8.59 | 9.04 | 0.44 | 10.93 | 11.32 | 0.39 | -2.63 | -3.93 | 40% | 0.44 | suppressed (N<20 or <10 days) |
| 4-6 | **39** | 10.53 | 9.62 | -0.90 | 13.84 | 12.10 | -1.74 | 6.14 | 2.57 | 56% | -0.90 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **201** | 9.79 | 9.74 | -0.05 | 12.51 | 12.36 | -0.15 | 0.51 | -1.44 | 51% | -0.05 | suppressed (N<20 or <10 days) |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **78** | 9.61 | 9.67 | 0.06 | 12.40 | 12.20 | -0.20 | -0.63 | -2.05 | 55% | 0.06 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **81** | 10.46 | 10.13 | -0.33 | 12.77 | 12.53 | -0.24 | 1.03 | -0.98 | 53% | -0.33 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **79** | 9.98 | 9.96 | -0.02 | 12.64 | 12.41 | -0.23 | -0.03 | -2.02 | 49% | -0.02 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **78** | 9.93 | 9.96 | 0.03 | 12.84 | 13.01 | 0.17 | 0.46 | -2.70 | 46% | 0.03 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 362 | 9.49 | 146.4 | 0.70 |
| ROSTER@T-24h | 362 | 0.12 | 0.7 | 0.01 |
| ROSTER@T-6h | 362 | 0.13 | 0.7 | 0.01 |
| ROSTER@T-72h | 362 | 0.12 | 0.8 | 0.01 |
| ROSTER@T-7d | 362 | 0.12 | 0.7 | 0.01 |
| ROSTER@latest | 362 | 0.13 | 0.7 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.2 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 298
* truth_snapshot_before_as_of: 298
* base_and_roster_same_run: 298
* margin_base_consistent: 298
* roster_records_with_code_sha: 298
* truth_evidence_complete: 298
* base_committed_before_tip: 298
* base_commit_unknown: 0
* roster_committed_before_tip: 298
* roster_commit_unknown: 0
* truth_committed_before_tip: 298
* truth_commit_unknown: 0
