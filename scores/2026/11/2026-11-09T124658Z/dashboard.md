# P-ROSTER-1 prospective scoreboard — 20261109T124619Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 206**

Pre-tip gate: VALID 325 · INVALID 0 · UNSCORABLE 4 · PENDING 3 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **206** | 9.87 | 9.82 | -0.04 | 12.53 | 12.38 | -0.14 | 0.72 | -1.19 | 51% | -0.04 | 146.2 → 0.6 (283 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **113** | 9.93 | 9.72 | -0.21 | 12.63 | 12.34 | -0.29 | 0.15 | -1.28 | 57% | -0.21 | suppressed (N<20 or <10 days) |
| game_3 | **6** | 7.70 | 7.54 | -0.16 | 8.82 | 8.87 | 0.05 | -4.86 | -5.39 | 67% | -0.16 | suppressed (N<20 or <10 days) |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **206** | 9.87 | 9.82 | -0.04 | 12.53 | 12.38 | -0.14 | 0.72 | -1.19 | 51% | -0.04 | suppressed (N<20 or <10 days) |
| games_2_3 | **119** | 9.82 | 9.61 | -0.21 | 12.46 | 12.19 | -0.27 | -0.10 | -1.49 | 57% | -0.21 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **200** | 9.97 | 9.88 | -0.09 | 12.63 | 12.46 | -0.17 | 0.84 | -1.08 | 52% | -0.09 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **111** | 9.68 | 9.49 | -0.20 | 12.20 | 11.97 | -0.23 | -0.13 | -1.63 | 56% | -0.20 | suppressed (N<20 or <10 days) |
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
| team_game_1 | **206** | 9.87 | 9.82 | -0.04 | 12.53 | 12.38 | -0.14 | 0.72 | -1.19 | 51% | -0.04 | suppressed (N<20 or <10 days) |
| team_game_2 | **165** | 9.39 | 9.36 | -0.03 | 12.14 | 11.91 | -0.23 | 0.49 | -0.87 | 54% | -0.03 | suppressed (N<20 or <10 days) |
| team_game_3 | **33** | 11.09 | 10.25 | -0.84 | 13.61 | 12.74 | -0.87 | -1.10 | -2.40 | 67% | -0.84 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **85** | 10.23 | 10.22 | -0.01 | 12.73 | 12.68 | -0.05 | 0.00 | -0.08 | 56% | -0.01 | suppressed (N<20 or <10 days) |
| 2-4 | **56** | 8.74 | 9.14 | 0.40 | 11.06 | 11.39 | 0.33 | -2.28 | -3.59 | 41% | 0.40 | suppressed (N<20 or <10 days) |
| 4-6 | **39** | 10.53 | 9.62 | -0.90 | 13.84 | 12.10 | -1.74 | 6.14 | 2.57 | 56% | -0.90 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **205** | 9.87 | 9.82 | -0.04 | 12.54 | 12.40 | -0.14 | 0.68 | -1.24 | 51% | -0.04 | suppressed (N<20 or <10 days) |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **79** | 9.67 | 9.84 | 0.16 | 12.44 | 12.29 | -0.15 | -0.65 | -2.00 | 54% | 0.16 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **82** | 10.59 | 10.19 | -0.40 | 12.85 | 12.59 | -0.27 | 1.41 | -0.67 | 52% | -0.40 | suppressed (N<20 or <10 days) |
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

* games_scored: 325
* truth_snapshot_before_as_of: 325
* base_and_roster_same_run: 325
* margin_base_consistent: 325
* roster_records_with_code_sha: 325
* truth_evidence_complete: 325
* base_committed_before_tip: 325
* base_commit_unknown: 0
* roster_committed_before_tip: 325
* roster_commit_unknown: 0
* truth_committed_before_tip: 325
* truth_commit_unknown: 0
