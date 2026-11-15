# P-ROSTER-1 prospective scoreboard — 20261115T181903Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 214**

Pre-tip gate: VALID 602 · INVALID 1 · UNSCORABLE 0 · PENDING 17 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **214** | 9.88 | 9.81 | -0.07 | 12.51 | 12.33 | -0.18 | 0.83 | -1.05 | 51% | -0.07 | 146.2 → 0.6 (287 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **201** | 9.71 | 9.62 | -0.08 | 12.11 | 11.99 | -0.12 | -0.15 | -1.25 | 52% | -0.08 | [-0.32, 0.20] |
| game_3 | **144** | 9.39 | 9.39 | -0.00 | 12.03 | 12.15 | 0.12 | -0.70 | -1.45 | 53% | -0.00 | suppressed (N<20 or <10 days) |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **214** | 9.88 | 9.81 | -0.07 | 12.51 | 12.33 | -0.18 | 0.83 | -1.05 | 51% | -0.07 | [-0.33, 0.26] |
| games_2_3 | **345** | 9.57 | 9.52 | -0.05 | 12.08 | 12.06 | -0.02 | -0.38 | -1.33 | 52% | -0.05 | [-0.23, 0.17] |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **208** | 9.98 | 9.86 | -0.11 | 12.60 | 12.40 | -0.20 | 0.94 | -0.93 | 52% | -0.11 | [-0.35, 0.27] |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **332** | 9.58 | 9.55 | -0.03 | 12.04 | 12.05 | 0.01 | -0.41 | -1.40 | 52% | -0.03 | [-0.22, 0.20] |
| games_2_3 / LIKELY | **13** | 9.40 | 8.95 | -0.46 | 13.08 | 12.34 | -0.75 | 0.54 | 0.45 | 77% | -0.46 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 364 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-6h | 364 | 0.60 | 0.70 | 0.62 | 8.04 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-72h | 364 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 364 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.69 | 0.11 | 0.01 |
| latest | 364 | 0.60 | 0.70 | 0.62 | 8.04 | 0.76 | 0.69 | 0.11 | 0.01 |
| BASE | 364 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **214** | 9.88 | 9.81 | -0.07 | 12.51 | 12.33 | -0.18 | 0.83 | -1.05 | 51% | -0.07 | [-0.33, 0.26] |
| team_game_2 | **253** | 9.40 | 9.41 | 0.01 | 11.89 | 11.77 | -0.12 | 0.13 | -0.99 | 51% | 0.01 | [-0.20, 0.23] |
| team_game_3 | **235** | 9.67 | 9.52 | -0.15 | 12.17 | 12.07 | -0.10 | -0.54 | -1.32 | 54% | -0.15 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **90** | 10.18 | 10.17 | -0.01 | 12.69 | 12.61 | -0.07 | -0.07 | -0.16 | 56% | -0.01 | [-0.12, 0.28] |
| 2-4 | **58** | 8.81 | 9.21 | 0.39 | 11.10 | 11.39 | 0.29 | -1.83 | -3.09 | 41% | 0.39 | suppressed (N<20 or <10 days) |
| 4-6 | **40** | 10.58 | 9.56 | -1.02 | 13.82 | 12.00 | -1.82 | 6.31 | 2.68 | 57% | -1.02 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **213** | 9.88 | 9.81 | -0.06 | 12.52 | 12.34 | -0.18 | 0.79 | -1.10 | 51% | -0.06 | [-0.33, 0.27] |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **81** | 9.67 | 9.85 | 0.18 | 12.40 | 12.25 | -0.15 | -0.73 | -1.99 | 54% | 0.18 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **85** | 10.64 | 10.23 | -0.42 | 12.92 | 12.61 | -0.31 | 1.79 | -0.26 | 53% | -0.42 | [-1.40, -0.03] |
| q3 (7-9 newcomers) | **83** | 9.93 | 9.85 | -0.08 | 12.56 | 12.29 | -0.28 | 0.23 | -1.74 | 49% | -0.08 | [-0.63, 0.78] |
| q4 (9-16 newcomers) | **82** | 10.14 | 10.16 | 0.02 | 12.93 | 13.08 | 0.15 | 0.52 | -2.46 | 46% | 0.02 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 364 | 9.47 | 146.3 | 0.70 |
| ROSTER@T-24h | 364 | 0.12 | 0.7 | 0.01 |
| ROSTER@T-6h | 364 | 0.13 | 0.7 | 0.01 |
| ROSTER@T-72h | 364 | 0.12 | 0.8 | 0.01 |
| ROSTER@T-7d | 364 | 0.12 | 0.7 | 0.01 |
| ROSTER@latest | 364 | 0.13 | 0.7 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.2 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 602
* truth_snapshot_before_as_of: 602
* base_and_roster_same_run: 602
* margin_base_consistent: 602
* roster_records_with_code_sha: 602
* truth_evidence_complete: 602
* base_committed_before_tip: 602
* base_commit_unknown: 0
* roster_committed_before_tip: 602
* roster_commit_unknown: 0
* truth_committed_before_tip: 602
* truth_commit_unknown: 0
