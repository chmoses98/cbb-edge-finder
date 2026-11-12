# P-ROSTER-1 prospective scoreboard — 20261112T132916Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 213**

Pre-tip gate: VALID 466 · INVALID 1 · UNSCORABLE 0 · PENDING 4 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **213** | 9.86 | 9.82 | -0.04 | 12.51 | 12.35 | -0.16 | 0.77 | -1.08 | 51% | -0.04 | 146.2 → 0.6 (287 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **177** | 9.35 | 9.18 | -0.16 | 11.71 | 11.51 | -0.20 | 0.63 | -0.62 | 56% | -0.16 | suppressed (N<20 or <10 days) |
| game_3 | **76** | 10.43 | 10.11 | -0.32 | 13.79 | 13.68 | -0.11 | -0.60 | -1.58 | 58% | -0.32 | suppressed (N<20 or <10 days) |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **213** | 9.86 | 9.82 | -0.04 | 12.51 | 12.35 | -0.16 | 0.77 | -1.08 | 51% | -0.04 | [-0.27, 0.30] |
| games_2_3 | **253** | 9.67 | 9.46 | -0.21 | 12.37 | 12.20 | -0.17 | 0.26 | -0.91 | 57% | -0.21 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **207** | 9.96 | 9.88 | -0.09 | 12.60 | 12.42 | -0.18 | 0.89 | -0.97 | 52% | -0.09 | [-0.30, 0.31] |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **243** | 9.66 | 9.45 | -0.21 | 12.30 | 12.15 | -0.14 | 0.23 | -0.99 | 56% | -0.21 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **10** | 10.03 | 9.71 | -0.32 | 14.14 | 13.41 | -0.73 | 0.91 | 1.04 | 70% | -0.32 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 363 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-6h | 363 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-72h | 363 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 363 | 0.60 | 0.70 | 0.62 | 8.01 | 0.76 | 0.69 | 0.11 | 0.01 |
| latest | 363 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| BASE | 363 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **213** | 9.86 | 9.82 | -0.04 | 12.51 | 12.35 | -0.16 | 0.77 | -1.08 | 51% | -0.04 | [-0.27, 0.30] |
| team_game_2 | **229** | 9.09 | 9.04 | -0.04 | 11.55 | 11.38 | -0.18 | 0.76 | -0.47 | 54% | -0.04 | suppressed (N<20 or <10 days) |
| team_game_3 | **154** | 10.02 | 9.63 | -0.39 | 12.81 | 12.49 | -0.32 | 0.37 | -0.66 | 58% | -0.39 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **90** | 10.18 | 10.17 | -0.01 | 12.69 | 12.61 | -0.07 | -0.07 | -0.16 | 56% | -0.01 | [-0.12, 0.28] |
| 2-4 | **58** | 8.81 | 9.21 | 0.39 | 11.10 | 11.39 | 0.29 | -1.83 | -3.09 | 41% | 0.39 | suppressed (N<20 or <10 days) |
| 4-6 | **39** | 10.53 | 9.62 | -0.90 | 13.84 | 12.10 | -1.74 | 6.14 | 2.57 | 56% | -0.90 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **212** | 9.86 | 9.83 | -0.04 | 12.52 | 12.36 | -0.15 | 0.73 | -1.13 | 50% | -0.04 | [-0.27, 0.31] |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **81** | 9.67 | 9.85 | 0.18 | 12.40 | 12.25 | -0.15 | -0.73 | -1.99 | 54% | 0.18 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **85** | 10.64 | 10.23 | -0.42 | 12.92 | 12.61 | -0.31 | 1.79 | -0.26 | 53% | -0.42 | [-1.40, -0.03] |
| q3 (7-9 newcomers) | **82** | 9.90 | 9.89 | -0.01 | 12.56 | 12.34 | -0.22 | 0.07 | -1.85 | 49% | -0.01 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **82** | 10.14 | 10.16 | 0.02 | 12.93 | 13.08 | 0.15 | 0.52 | -2.46 | 46% | 0.02 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 363 | 9.47 | 146.2 | 0.70 |
| ROSTER@T-24h | 363 | 0.12 | 0.7 | 0.01 |
| ROSTER@T-6h | 363 | 0.13 | 0.7 | 0.01 |
| ROSTER@T-72h | 363 | 0.12 | 0.8 | 0.01 |
| ROSTER@T-7d | 363 | 0.12 | 0.7 | 0.01 |
| ROSTER@latest | 363 | 0.13 | 0.7 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.2 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 466
* truth_snapshot_before_as_of: 466
* base_and_roster_same_run: 466
* margin_base_consistent: 466
* roster_records_with_code_sha: 466
* truth_evidence_complete: 466
* base_committed_before_tip: 466
* base_commit_unknown: 0
* roster_committed_before_tip: 466
* roster_commit_unknown: 0
* truth_committed_before_tip: 466
* truth_commit_unknown: 0
