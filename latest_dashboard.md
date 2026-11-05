# P-ROSTER-1 prospective scoreboard — 20261105T155803Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 145**

Pre-tip gate: VALID 148 · INVALID 0 · UNSCORABLE 2 · PENDING 2 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **145** | 10.43 | 10.35 | -0.08 | 13.16 | 13.06 | -0.10 | 0.63 | -1.58 | 52% | -0.08 | 146.9 → 0.8 (278 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **3** | 5.71 | 7.63 | 1.92 | 7.10 | 11.29 | 4.19 | -2.04 | -5.30 | 33% | 1.92 | suppressed (N<20 or <10 days) |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **145** | 10.43 | 10.35 | -0.08 | 13.16 | 13.06 | -0.10 | 0.63 | -1.58 | 52% | -0.08 | suppressed (N<20 or <10 days) |
| games_2_3 | **3** | 5.71 | 7.63 | 1.92 | 7.10 | 11.29 | 4.19 | -2.04 | -5.30 | 33% | 1.92 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **140** | 10.59 | 10.44 | -0.15 | 13.30 | 13.17 | -0.13 | 0.86 | -1.36 | 54% | -0.15 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **3** | 5.71 | 7.63 | 1.92 | 7.10 | 11.29 | 4.19 | -2.04 | -5.30 | 33% | 1.92 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 356 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-6h | 356 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-72h | 356 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.12 | 0.01 |
| T-7d | 356 | 0.60 | 0.70 | 0.61 | 8.00 | 0.76 | 0.70 | 0.12 | 0.01 |
| latest | 356 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| BASE | 356 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **145** | 10.43 | 10.35 | -0.08 | 13.16 | 13.06 | -0.10 | 0.63 | -1.58 | 52% | -0.08 | suppressed (N<20 or <10 days) |
| team_game_2 | **9** | 7.69 | 8.33 | 0.64 | 10.99 | 12.01 | 1.01 | 0.89 | -0.87 | 56% | 0.64 | suppressed (N<20 or <10 days) |
| team_game_3 | 0 | | | | | | | | | | | |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **53** | 11.06 | 11.07 | 0.01 | 13.85 | 13.78 | -0.07 | 0.07 | -0.07 | 58% | 0.01 | suppressed (N<20 or <10 days) |
| 2-4 | **41** | 9.50 | 9.85 | 0.35 | 11.79 | 12.17 | 0.39 | -2.44 | -3.92 | 41% | 0.35 | suppressed (N<20 or <10 days) |
| 4-6 | **29** | 10.66 | 9.61 | -1.05 | 13.64 | 12.06 | -1.59 | 5.43 | 1.71 | 59% | -1.05 | suppressed (N<20 or <10 days) |
| >=6 | **22** | 10.35 | 10.52 | 0.16 | 13.23 | 14.13 | 0.91 | 1.34 | -5.20 | 45% | 0.16 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **145** | 10.43 | 10.35 | -0.08 | 13.16 | 13.06 | -0.10 | 0.63 | -1.58 | 52% | -0.08 | suppressed (N<20 or <10 days) |
| LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **62** | 9.87 | 9.94 | 0.07 | 12.46 | 12.43 | -0.03 | -1.15 | -2.53 | 55% | 0.07 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **65** | 10.58 | 10.34 | -0.24 | 13.09 | 12.97 | -0.12 | 1.57 | -0.70 | 51% | -0.24 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **64** | 10.46 | 10.45 | -0.01 | 13.11 | 12.93 | -0.18 | -0.80 | -3.07 | 50% | -0.01 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **64** | 10.75 | 10.68 | -0.07 | 13.72 | 13.73 | 0.01 | 1.30 | -1.95 | 48% | -0.07 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 356 | 9.50 | 147.1 | 0.70 |
| ROSTER@T-24h | 356 | 0.13 | 1.0 | 0.01 |
| ROSTER@T-6h | 356 | 0.13 | 1.0 | 0.01 |
| ROSTER@T-72h | 356 | 0.13 | 1.0 | 0.01 |
| ROSTER@T-7d | 356 | 0.13 | 0.9 | 0.01 |
| ROSTER@latest | 356 | 0.13 | 1.0 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.3 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 148
* truth_snapshot_before_as_of: 148
* base_and_roster_same_run: 148
* margin_base_consistent: 148
* roster_records_with_code_sha: 148
* truth_evidence_complete: 148
* base_committed_before_tip: 148
* base_commit_unknown: 0
* roster_committed_before_tip: 148
* roster_commit_unknown: 0
* truth_committed_before_tip: 148
* truth_commit_unknown: 0
