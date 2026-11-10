# P-ROSTER-1 prospective scoreboard — 20261110T130431Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 207**

Pre-tip gate: VALID 358 · INVALID 1 · UNSCORABLE 4 · PENDING 4 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **207** | 9.90 | 9.84 | -0.06 | 12.55 | 12.39 | -0.16 | 0.80 | -1.12 | 51% | -0.06 | 146.2 → 0.6 (283 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **132** | 9.85 | 9.73 | -0.12 | 12.39 | 12.26 | -0.13 | 0.08 | -1.46 | 55% | -0.12 | suppressed (N<20 or <10 days) |
| game_3 | **19** | 7.07 | 6.95 | -0.13 | 8.53 | 8.57 | 0.04 | 0.66 | -0.84 | 58% | -0.13 | suppressed (N<20 or <10 days) |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **207** | 9.90 | 9.84 | -0.06 | 12.55 | 12.39 | -0.16 | 0.80 | -1.12 | 51% | -0.06 | suppressed (N<20 or <10 days) |
| games_2_3 | **151** | 9.50 | 9.38 | -0.12 | 11.98 | 11.86 | -0.12 | 0.15 | -1.38 | 55% | -0.12 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **201** | 10.00 | 9.89 | -0.10 | 12.65 | 12.46 | -0.19 | 0.92 | -1.01 | 52% | -0.10 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **143** | 9.38 | 9.27 | -0.10 | 11.73 | 11.66 | -0.07 | 0.14 | -1.49 | 54% | -0.10 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **8** | 11.73 | 11.31 | -0.42 | 15.69 | 14.90 | -0.79 | 0.33 | 0.47 | 75% | -0.42 | suppressed (N<20 or <10 days) |

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
| team_game_1 | **207** | 9.90 | 9.84 | -0.06 | 12.55 | 12.39 | -0.16 | 0.80 | -1.12 | 51% | -0.06 | suppressed (N<20 or <10 days) |
| team_game_2 | **184** | 9.39 | 9.40 | 0.02 | 12.02 | 11.89 | -0.12 | 0.40 | -1.04 | 53% | 0.02 | suppressed (N<20 or <10 days) |
| team_game_3 | **61** | 9.99 | 9.49 | -0.50 | 12.17 | 11.66 | -0.51 | 0.44 | -1.17 | 59% | -0.50 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **85** | 10.23 | 10.22 | -0.01 | 12.73 | 12.68 | -0.05 | 0.00 | -0.08 | 56% | -0.01 | suppressed (N<20 or <10 days) |
| 2-4 | **57** | 8.87 | 9.22 | 0.35 | 11.17 | 11.43 | 0.26 | -1.96 | -3.29 | 42% | 0.35 | suppressed (N<20 or <10 days) |
| 4-6 | **39** | 10.53 | 9.62 | -0.90 | 13.84 | 12.10 | -1.74 | 6.14 | 2.57 | 56% | -0.90 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **206** | 9.90 | 9.84 | -0.05 | 12.56 | 12.40 | -0.16 | 0.75 | -1.17 | 51% | -0.05 | suppressed (N<20 or <10 days) |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **79** | 9.67 | 9.84 | 0.16 | 12.44 | 12.29 | -0.15 | -0.65 | -2.00 | 54% | 0.16 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **83** | 10.66 | 10.23 | -0.43 | 12.90 | 12.60 | -0.30 | 1.59 | -0.50 | 53% | -0.43 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **80** | 9.88 | 9.86 | -0.02 | 12.52 | 12.31 | -0.22 | -0.15 | -2.08 | 49% | -0.02 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **80** | 10.09 | 10.12 | 0.04 | 12.94 | 13.11 | 0.17 | 0.85 | -2.22 | 46% | 0.04 | suppressed (N<20 or <10 days) |

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

* games_scored: 358
* truth_snapshot_before_as_of: 358
* base_and_roster_same_run: 358
* margin_base_consistent: 358
* roster_records_with_code_sha: 358
* truth_evidence_complete: 358
* base_committed_before_tip: 358
* base_commit_unknown: 0
* roster_committed_before_tip: 358
* roster_commit_unknown: 0
* truth_committed_before_tip: 358
* truth_commit_unknown: 0
