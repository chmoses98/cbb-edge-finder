# P-ROSTER-1 prospective scoreboard — 20261121T165918Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 215**

Pre-tip gate: VALID 855 · INVALID 1 · UNSCORABLE 0 · PENDING 15 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **215** | 9.84 | 9.79 | -0.05 | 12.49 | 12.31 | -0.17 | 0.82 | -1.02 | 51% | -0.05 | 146.2 → 0.6 (287 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **207** | 9.81 | 9.73 | -0.08 | 12.27 | 12.19 | -0.08 | -0.32 | -1.44 | 52% | -0.08 | [-0.33, 0.20] |
| game_3 | **188** | 9.80 | 9.83 | 0.03 | 12.30 | 12.44 | 0.13 | -0.11 | -0.74 | 52% | 0.03 | [-0.22, 0.29] |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **215** | 9.84 | 9.79 | -0.05 | 12.49 | 12.31 | -0.17 | 0.82 | -1.02 | 51% | -0.05 | [-0.31, 0.30] |
| games_2_3 | **395** | 9.81 | 9.78 | -0.03 | 12.28 | 12.31 | 0.02 | -0.22 | -1.11 | 52% | -0.03 | [-0.20, 0.18] |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **209** | 9.94 | 9.84 | -0.10 | 12.58 | 12.38 | -0.20 | 0.94 | -0.90 | 52% | -0.10 | [-0.34, 0.31] |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **380** | 9.77 | 9.75 | -0.02 | 12.18 | 12.21 | 0.03 | -0.19 | -1.10 | 51% | -0.02 | [-0.20, 0.19] |
| games_2_3 / LIKELY | **15** | 10.68 | 10.50 | -0.18 | 14.59 | 14.49 | -0.10 | -1.00 | -1.31 | 73% | -0.18 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 364 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-6h | 364 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| T-72h | 364 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 364 | 0.60 | 0.70 | 0.62 | 8.02 | 0.76 | 0.69 | 0.11 | 0.01 |
| latest | 364 | 0.60 | 0.70 | 0.62 | 8.03 | 0.76 | 0.69 | 0.11 | 0.01 |
| BASE | 364 | – | – | – | – | – | – | 1.00 | 0.70 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **215** | 9.84 | 9.79 | -0.05 | 12.49 | 12.31 | -0.17 | 0.82 | -1.02 | 51% | -0.05 | [-0.31, 0.30] |
| team_game_2 | **259** | 9.49 | 9.49 | 0.01 | 12.02 | 11.94 | -0.08 | -0.01 | -1.14 | 51% | 0.01 | [-0.19, 0.23] |
| team_game_3 | **280** | 9.95 | 9.85 | -0.10 | 12.39 | 12.34 | -0.04 | -0.25 | -0.95 | 53% | -0.10 | [-0.31, 0.15] |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **90** | 10.19 | 10.18 | -0.01 | 12.70 | 12.63 | -0.07 | -0.06 | -0.15 | 56% | -0.01 | [-0.12, 0.28] |
| 2-4 | **58** | 8.81 | 9.21 | 0.39 | 11.10 | 11.39 | 0.29 | -1.83 | -3.09 | 41% | 0.39 | suppressed (N<20 or <10 days) |
| 4-6 | **41** | 10.35 | 9.44 | -0.91 | 13.65 | 11.87 | -1.78 | 6.13 | 2.72 | 56% | -0.91 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **214** | 9.84 | 9.79 | -0.05 | 12.50 | 12.33 | -0.17 | 0.78 | -1.06 | 50% | -0.05 | [-0.31, 0.31] |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **82** | 9.69 | 9.76 | 0.07 | 12.38 | 12.18 | -0.20 | -0.59 | -1.94 | 55% | 0.07 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **85** | 10.59 | 10.26 | -0.33 | 12.90 | 12.64 | -0.26 | 1.60 | -0.33 | 53% | -0.33 | [-1.04, -0.04] |
| q3 (7-9 newcomers) | **83** | 10.08 | 10.00 | -0.07 | 12.70 | 12.42 | -0.28 | 0.50 | -1.48 | 49% | -0.07 | [-0.60, 0.86] |
| q4 (9-16 newcomers) | **82** | 9.96 | 10.03 | 0.07 | 12.80 | 12.97 | 0.17 | 0.31 | -2.60 | 45% | 0.07 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 364 | 9.47 | 146.3 | 0.70 |
| ROSTER@T-24h | 364 | 0.13 | 0.7 | 0.01 |
| ROSTER@T-6h | 364 | 0.13 | 0.7 | 0.01 |
| ROSTER@T-72h | 364 | 0.13 | 0.8 | 0.01 |
| ROSTER@T-7d | 364 | 0.13 | 0.7 | 0.01 |
| ROSTER@latest | 364 | 0.13 | 0.7 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.2 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 855
* truth_snapshot_before_as_of: 855
* base_and_roster_same_run: 855
* margin_base_consistent: 855
* roster_records_with_code_sha: 855
* truth_evidence_complete: 855
* base_committed_before_tip: 855
* base_commit_unknown: 0
* roster_committed_before_tip: 855
* roster_commit_unknown: 0
* truth_committed_before_tip: 855
* truth_commit_unknown: 0
