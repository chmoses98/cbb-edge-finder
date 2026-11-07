# P-ROSTER-1 prospective scoreboard — 20261107T164807Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 182**

Pre-tip gate: VALID 250 · INVALID 0 · UNSCORABLE 2 · PENDING 3 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **182** | 10.07 | 10.11 | 0.05 | 12.79 | 12.72 | -0.07 | 0.51 | -1.62 | 50% | 0.05 | 146.2 → 0.7 (283 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **68** | 10.57 | 10.29 | -0.28 | 13.24 | 12.84 | -0.40 | 2.38 | 0.69 | 60% | -0.28 | suppressed (N<20 or <10 days) |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **182** | 10.07 | 10.11 | 0.05 | 12.79 | 12.72 | -0.07 | 0.51 | -1.62 | 50% | 0.05 | suppressed (N<20 or <10 days) |
| games_2_3 | **68** | 10.57 | 10.29 | -0.28 | 13.24 | 12.84 | -0.40 | 2.38 | 0.69 | 60% | -0.28 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **176** | 10.19 | 10.18 | -0.01 | 12.91 | 12.81 | -0.10 | 0.64 | -1.51 | 51% | -0.01 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **66** | 10.27 | 10.02 | -0.25 | 12.77 | 12.43 | -0.34 | 1.83 | 0.13 | 59% | -0.25 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **2** | 20.39 | 18.97 | -1.42 | 24.14 | 22.67 | -1.47 | 20.39 | 18.97 | 100% | -1.42 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 362 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.70 | 0.10 | 0.01 |
| T-6h | 362 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.70 | 0.10 | 0.01 |
| T-72h | 362 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 362 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| latest | 362 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.70 | 0.10 | 0.01 |
| BASE | 362 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **182** | 10.07 | 10.11 | 0.05 | 12.79 | 12.72 | -0.07 | 0.51 | -1.62 | 50% | 0.05 | suppressed (N<20 or <10 days) |
| team_game_2 | **106** | 10.12 | 10.09 | -0.03 | 12.83 | 12.53 | -0.29 | 1.78 | 0.09 | 56% | -0.03 | suppressed (N<20 or <10 days) |
| team_game_3 | **3** | 20.99 | 18.25 | -2.74 | 23.98 | 21.84 | -2.14 | 20.99 | 18.25 | 100% | -2.74 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **72** | 10.47 | 10.47 | -0.01 | 13.09 | 13.01 | -0.08 | -0.28 | -0.45 | 56% | -0.01 | suppressed (N<20 or <10 days) |
| 2-4 | **49** | 9.06 | 9.48 | 0.43 | 11.31 | 11.76 | 0.45 | -2.57 | -4.16 | 41% | 0.43 | suppressed (N<20 or <10 days) |
| 4-6 | **37** | 10.60 | 9.75 | -0.86 | 13.93 | 12.27 | -1.66 | 6.04 | 2.31 | 57% | -0.86 | suppressed (N<20 or <10 days) |
| >=6 | **24** | 10.07 | 10.88 | 0.81 | 12.89 | 14.32 | 1.42 | 0.66 | -6.01 | 42% | 0.81 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **181** | 10.07 | 10.11 | 0.05 | 12.80 | 12.73 | -0.07 | 0.46 | -1.68 | 50% | 0.05 | suppressed (N<20 or <10 days) |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **72** | 9.94 | 10.07 | 0.13 | 12.76 | 12.61 | -0.15 | -0.68 | -2.14 | 54% | 0.13 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **74** | 10.46 | 10.26 | -0.20 | 12.80 | 12.71 | -0.10 | 1.22 | -0.94 | 49% | -0.20 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **74** | 10.07 | 9.99 | -0.09 | 12.75 | 12.47 | -0.28 | -0.45 | -2.71 | 50% | -0.09 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **74** | 10.23 | 10.57 | 0.34 | 13.12 | 13.48 | 0.35 | 0.54 | -2.67 | 45% | 0.34 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 362 | 9.49 | 146.4 | 0.70 |
| ROSTER@T-24h | 362 | 0.12 | 0.8 | 0.01 |
| ROSTER@T-6h | 362 | 0.12 | 0.7 | 0.01 |
| ROSTER@T-72h | 362 | 0.12 | 0.8 | 0.01 |
| ROSTER@T-7d | 362 | 0.13 | 0.8 | 0.01 |
| ROSTER@latest | 362 | 0.12 | 0.7 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.2 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 250
* truth_snapshot_before_as_of: 250
* base_and_roster_same_run: 250
* margin_base_consistent: 250
* roster_records_with_code_sha: 250
* truth_evidence_complete: 250
* base_committed_before_tip: 250
* base_commit_unknown: 0
* roster_committed_before_tip: 250
* roster_commit_unknown: 0
* truth_committed_before_tip: 250
* truth_commit_unknown: 0
