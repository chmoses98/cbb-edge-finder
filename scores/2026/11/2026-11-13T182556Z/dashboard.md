# P-ROSTER-1 prospective scoreboard — 20261113T182532Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 214**

Pre-tip gate: VALID 490 · INVALID 1 · UNSCORABLE 0 · PENDING 4 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **214** | 9.88 | 9.81 | -0.07 | 12.51 | 12.33 | -0.18 | 0.83 | -1.05 | 51% | -0.07 | 146.2 → 0.6 (287 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **184** | 9.28 | 9.17 | -0.10 | 11.68 | 11.49 | -0.18 | 0.51 | -0.63 | 54% | -0.10 | suppressed (N<20 or <10 days) |
| game_3 | **89** | 10.23 | 10.10 | -0.13 | 13.36 | 13.42 | 0.06 | -0.73 | -1.63 | 56% | -0.13 | suppressed (N<20 or <10 days) |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **214** | 9.88 | 9.81 | -0.07 | 12.51 | 12.33 | -0.18 | 0.83 | -1.05 | 51% | -0.07 | [-0.33, 0.26] |
| games_2_3 | **273** | 9.59 | 9.48 | -0.11 | 12.25 | 12.15 | -0.10 | 0.10 | -0.96 | 55% | -0.11 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **208** | 9.98 | 9.86 | -0.11 | 12.60 | 12.40 | -0.20 | 0.94 | -0.93 | 52% | -0.11 | [-0.35, 0.27] |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **261** | 9.59 | 9.49 | -0.10 | 12.20 | 12.13 | -0.07 | 0.12 | -0.99 | 54% | -0.10 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **12** | 9.43 | 9.08 | -0.35 | 13.36 | 12.67 | -0.70 | -0.17 | -0.12 | 75% | -0.35 | suppressed (N<20 or <10 days) |

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
| team_game_2 | **236** | 9.04 | 9.04 | -0.00 | 11.53 | 11.37 | -0.16 | 0.66 | -0.49 | 53% | -0.00 | [-0.21, 0.23] |
| team_game_3 | **173** | 9.90 | 9.67 | -0.22 | 12.60 | 12.41 | -0.19 | 0.11 | -0.78 | 55% | -0.22 | suppressed (N<20 or <10 days) |

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

* games_scored: 490
* truth_snapshot_before_as_of: 490
* base_and_roster_same_run: 490
* margin_base_consistent: 490
* roster_records_with_code_sha: 490
* truth_evidence_complete: 490
* base_committed_before_tip: 490
* base_commit_unknown: 0
* roster_committed_before_tip: 490
* roster_commit_unknown: 0
* truth_committed_before_tip: 490
* truth_commit_unknown: 0
