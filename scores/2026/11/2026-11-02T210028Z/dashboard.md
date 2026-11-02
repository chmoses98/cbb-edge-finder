# P-ROSTER-1 prospective scoreboard — 20261102T210011Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 3**

Pre-tip gate: VALID 3 · INVALID 0 · UNSCORABLE 0 · PENDING 6 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

**INSUFFICIENT SAMPLE (N = 3 < 20): descriptive only, no interval, no conclusion.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **3** | 6.73 | 5.21 | -1.51 | 8.29 | 7.05 | -1.24 | -0.91 | -2.72 | 33% | -1.51 | 163.9 → 0.0 (6 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | 0 | | | | | | | | | | | |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **3** | 6.73 | 5.21 | -1.51 | 8.29 | 7.05 | -1.24 | -0.91 | -2.72 | 33% | -1.51 | suppressed (N<20 or <10 days) |
| games_2_3 | 0 | | | | | | | | | | | |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **3** | 6.73 | 5.21 | -1.51 | 8.29 | 7.05 | -1.24 | -0.91 | -2.72 | 33% | -1.51 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 6 | 0.47 | 0.56 | 0.50 | 10.47 | 0.58 | 0.62 | 0.00 | 0.01 |
| T-6h | 6 | 0.47 | 0.56 | 0.50 | 10.47 | 0.58 | 0.62 | 0.00 | 0.01 |
| T-72h | 6 | 0.47 | 0.56 | 0.50 | 10.47 | 0.58 | 0.62 | 0.00 | 0.01 |
| T-7d | 6 | 0.47 | 0.58 | 0.53 | 10.24 | 0.59 | 0.62 | 0.00 | 0.01 |
| latest | 6 | 0.47 | 0.56 | 0.50 | 10.47 | 0.58 | 0.62 | 0.00 | 0.01 |
| BASE | 6 | – | – | – | – | – | – | 1.00 | 0.79 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **3** | 6.73 | 5.21 | -1.51 | 8.29 | 7.05 | -1.24 | -0.91 | -2.72 | 33% | -1.51 | suppressed (N<20 or <10 days) |
| team_game_2 | 0 | | | | | | | | | | | |
| team_game_3 | 0 | | | | | | | | | | | |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **2** | 5.77 | 6.70 | 0.93 | 8.10 | 8.48 | 0.38 | -5.68 | -5.21 | 0% | 0.93 | suppressed (N<20 or <10 days) |
| 2-4 | 0 | | | | | | | | | | | |
| 4-6 | **1** | 8.65 | 2.25 | -6.40 | 8.65 | 2.25 | -6.40 | 8.65 | 2.25 | 100% | -6.40 | suppressed (N<20 or <10 days) |
| >=6 | 0 | | | | | | | | | | | |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **3** | 6.73 | 5.21 | -1.51 | 8.29 | 7.05 | -1.24 | -0.91 | -2.72 | 33% | -1.51 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (6-6 newcomers) | **2** | 10.05 | 7.08 | -2.97 | 10.15 | 8.57 | -1.58 | -1.40 | -4.83 | 50% | -2.97 | suppressed (N<20 or <10 days) |
| q2 (7-7 newcomers) | **1** | 0.09 | 1.49 | 1.41 | 0.09 | 1.49 | 1.41 | 0.09 | 1.49 | 0% | 1.41 | suppressed (N<20 or <10 days) |
| q3 (7-8 newcomers) | **2** | 10.05 | 7.08 | -2.97 | 10.15 | 8.57 | -1.58 | -1.40 | -4.83 | 50% | -2.97 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 6 | 11.00 | 163.9 | 0.79 |
| ROSTER@T-24h | 6 | 0.00 | 0.0 | 0.01 |
| ROSTER@T-6h | 6 | 0.00 | 0.0 | 0.01 |
| ROSTER@T-72h | 6 | 0.00 | 0.0 | 0.01 |
| ROSTER@T-7d | 6 | 0.00 | 0.0 | 0.01 |
| ROSTER@latest | 6 | 0.00 | 0.0 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.3 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 3
* truth_snapshot_before_as_of: 3
* base_and_roster_same_run: 3
* margin_base_consistent: 3
* roster_records_with_code_sha: 3
* truth_evidence_complete: 3
* base_committed_before_tip: 3
* base_commit_unknown: 0
* roster_committed_before_tip: 3
* roster_commit_unknown: 0
* truth_committed_before_tip: 3
* truth_commit_unknown: 0
