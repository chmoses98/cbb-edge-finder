# P-ROSTER-1 prospective scoreboard — 20261106T183322Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 162**

Pre-tip gate: VALID 191 · INVALID 0 · UNSCORABLE 2 · PENDING 3 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **162** | 10.08 | 10.08 | -0.00 | 12.75 | 12.70 | -0.05 | 0.24 | -1.84 | 51% | -0.00 | 146.4 → 0.8 (280 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **29** | 9.76 | 9.45 | -0.31 | 12.64 | 12.50 | -0.14 | 0.72 | -0.56 | 66% | -0.31 | suppressed (N<20 or <10 days) |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **162** | 10.08 | 10.08 | -0.00 | 12.75 | 12.70 | -0.05 | 0.24 | -1.84 | 51% | -0.00 | suppressed (N<20 or <10 days) |
| games_2_3 | **29** | 9.76 | 9.45 | -0.31 | 12.64 | 12.50 | -0.14 | 0.72 | -0.56 | 66% | -0.31 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **157** | 10.21 | 10.15 | -0.06 | 12.86 | 12.78 | -0.08 | 0.44 | -1.65 | 52% | -0.06 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **27** | 8.97 | 8.74 | -0.23 | 11.33 | 11.39 | 0.06 | -0.74 | -2.00 | 63% | -0.23 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **2** | 20.39 | 18.97 | -1.42 | 24.14 | 22.67 | -1.47 | 20.39 | 18.97 | 100% | -1.42 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 359 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-6h | 359 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-72h | 359 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 359 | 0.60 | 0.70 | 0.62 | 8.00 | 0.76 | 0.69 | 0.11 | 0.01 |
| latest | 359 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| BASE | 359 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **162** | 10.08 | 10.08 | -0.00 | 12.75 | 12.70 | -0.05 | 0.24 | -1.84 | 51% | -0.00 | suppressed (N<20 or <10 days) |
| team_game_2 | **51** | 8.86 | 8.97 | 0.10 | 11.52 | 11.57 | 0.05 | -0.39 | -1.52 | 57% | 0.10 | suppressed (N<20 or <10 days) |
| team_game_3 | 0 | | | | | | | | | | | |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **61** | 10.71 | 10.73 | 0.02 | 13.32 | 13.28 | -0.04 | -0.44 | -0.58 | 57% | 0.02 | suppressed (N<20 or <10 days) |
| 2-4 | **47** | 9.09 | 9.52 | 0.42 | 11.41 | 11.87 | 0.46 | -2.79 | -4.33 | 40% | 0.42 | suppressed (N<20 or <10 days) |
| 4-6 | **32** | 10.14 | 9.35 | -0.80 | 13.14 | 11.66 | -1.48 | 5.24 | 1.71 | 56% | -0.80 | suppressed (N<20 or <10 days) |
| >=6 | **22** | 10.35 | 10.52 | 0.16 | 13.23 | 14.13 | 0.91 | 1.34 | -5.20 | 45% | 0.16 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **162** | 10.08 | 10.08 | -0.00 | 12.75 | 12.70 | -0.05 | 0.24 | -1.84 | 51% | -0.00 | suppressed (N<20 or <10 days) |
| LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **68** | 9.56 | 9.75 | 0.19 | 12.14 | 12.15 | 0.01 | -1.53 | -2.82 | 53% | 0.19 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **69** | 10.35 | 10.23 | -0.12 | 12.78 | 12.77 | -0.01 | 0.72 | -1.47 | 49% | -0.12 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **68** | 9.95 | 9.90 | -0.05 | 12.52 | 12.33 | -0.19 | -0.90 | -3.17 | 50% | -0.05 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **69** | 10.95 | 10.98 | 0.03 | 13.89 | 13.98 | 0.10 | 1.41 | -1.71 | 48% | 0.03 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 359 | 9.49 | 146.7 | 0.70 |
| ROSTER@T-24h | 359 | 0.13 | 1.0 | 0.01 |
| ROSTER@T-6h | 359 | 0.13 | 1.0 | 0.01 |
| ROSTER@T-72h | 359 | 0.13 | 1.0 | 0.01 |
| ROSTER@T-7d | 359 | 0.13 | 0.9 | 0.01 |
| ROSTER@latest | 359 | 0.13 | 1.0 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.2 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 191
* truth_snapshot_before_as_of: 191
* base_and_roster_same_run: 191
* margin_base_consistent: 191
* roster_records_with_code_sha: 191
* truth_evidence_complete: 191
* base_committed_before_tip: 191
* base_commit_unknown: 0
* roster_committed_before_tip: 191
* roster_commit_unknown: 0
* truth_committed_before_tip: 191
* truth_commit_unknown: 0
