# P-ROSTER-1 prospective scoreboard — 20261104T190034Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 138**

Pre-tip gate: VALID 138 · INVALID 0 · UNSCORABLE 2 · PENDING 2 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **138** | 10.54 | 10.43 | -0.11 | 13.22 | 13.12 | -0.10 | 0.60 | -1.67 | 51% | -0.11 | 147.1 → 0.9 (272 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | 0 | | | | | | | | | | | |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **138** | 10.54 | 10.43 | -0.11 | 13.22 | 13.12 | -0.10 | 0.60 | -1.67 | 51% | -0.11 | suppressed (N<20 or <10 days) |
| games_2_3 | 0 | | | | | | | | | | | |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **133** | 10.71 | 10.53 | -0.19 | 13.38 | 13.23 | -0.14 | 0.85 | -1.44 | 53% | -0.19 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 348 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-6h | 348 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-72h | 348 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.69 | 0.12 | 0.01 |
| T-7d | 348 | 0.60 | 0.70 | 0.61 | 8.02 | 0.76 | 0.69 | 0.12 | 0.01 |
| latest | 348 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| BASE | 348 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **138** | 10.54 | 10.43 | -0.11 | 13.22 | 13.12 | -0.10 | 0.60 | -1.67 | 51% | -0.11 | suppressed (N<20 or <10 days) |
| team_game_2 | **2** | 4.48 | 2.96 | -1.52 | 4.54 | 2.99 | -1.54 | 0.71 | -0.42 | 100% | -1.52 | suppressed (N<20 or <10 days) |
| team_game_3 | 0 | | | | | | | | | | | |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **47** | 11.24 | 11.22 | -0.01 | 13.98 | 13.90 | -0.08 | -0.08 | -0.15 | 57% | -0.01 | suppressed (N<20 or <10 days) |
| 2-4 | **40** | 9.73 | 10.04 | 0.31 | 11.94 | 12.32 | 0.38 | -2.50 | -3.96 | 42% | 0.31 | suppressed (N<20 or <10 days) |
| 4-6 | **29** | 10.66 | 9.61 | -1.05 | 13.64 | 12.06 | -1.59 | 5.43 | 1.71 | 59% | -1.05 | suppressed (N<20 or <10 days) |
| >=6 | **22** | 10.35 | 10.52 | 0.16 | 13.23 | 14.13 | 0.91 | 1.34 | -5.20 | 45% | 0.16 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **138** | 10.54 | 10.43 | -0.11 | 13.22 | 13.12 | -0.10 | 0.60 | -1.67 | 51% | -0.11 | suppressed (N<20 or <10 days) |
| LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **60** | 10.12 | 10.11 | -0.01 | 12.65 | 12.59 | -0.06 | -1.11 | -2.45 | 57% | -0.01 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **62** | 10.78 | 10.65 | -0.13 | 13.33 | 13.25 | -0.07 | 1.52 | -0.78 | 48% | -0.13 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **61** | 10.32 | 10.31 | -0.01 | 12.90 | 12.72 | -0.19 | -1.10 | -3.47 | 49% | -0.01 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **62** | 10.99 | 10.95 | -0.04 | 13.94 | 14.00 | 0.06 | 1.30 | -2.05 | 47% | -0.04 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 348 | 9.53 | 147.3 | 0.70 |
| ROSTER@T-24h | 348 | 0.14 | 1.0 | 0.01 |
| ROSTER@T-6h | 348 | 0.14 | 1.0 | 0.01 |
| ROSTER@T-72h | 348 | 0.14 | 1.0 | 0.01 |
| ROSTER@T-7d | 348 | 0.14 | 0.9 | 0.01 |
| ROSTER@latest | 348 | 0.14 | 1.0 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.3 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 138
* truth_snapshot_before_as_of: 138
* base_and_roster_same_run: 138
* margin_base_consistent: 138
* roster_records_with_code_sha: 138
* truth_evidence_complete: 138
* base_committed_before_tip: 138
* base_commit_unknown: 0
* roster_committed_before_tip: 138
* roster_commit_unknown: 0
* truth_committed_before_tip: 138
* truth_commit_unknown: 0
