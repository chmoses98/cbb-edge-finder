# P-ROSTER-1 prospective scoreboard — 20261111T165234Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 211**

Pre-tip gate: VALID 418 · INVALID 1 · UNSCORABLE 0 · PENDING 5 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **211** | 9.90 | 9.86 | -0.04 | 12.54 | 12.38 | -0.16 | 0.83 | -1.05 | 51% | -0.04 | 146.2 → 0.6 (287 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | **157** | 9.55 | 9.34 | -0.21 | 11.97 | 11.79 | -0.18 | 0.34 | -0.98 | 55% | -0.21 | suppressed (N<20 or <10 days) |
| game_3 | **50** | 9.56 | 9.47 | -0.09 | 12.74 | 12.96 | 0.22 | -0.40 | -1.76 | 54% | -0.09 | suppressed (N<20 or <10 days) |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **211** | 9.90 | 9.86 | -0.04 | 12.54 | 12.38 | -0.16 | 0.83 | -1.05 | 51% | -0.04 | [-0.31, 0.29] |
| games_2_3 | **207** | 9.55 | 9.37 | -0.18 | 12.16 | 12.08 | -0.08 | 0.16 | -1.17 | 55% | -0.18 | suppressed (N<20 or <10 days) |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **205** | 10.00 | 9.91 | -0.09 | 12.64 | 12.45 | -0.19 | 0.95 | -0.93 | 52% | -0.09 | [-0.33, 0.30] |
| game_1 / LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |
| games_2_3 / CONFIRMED | **198** | 9.50 | 9.32 | -0.18 | 12.03 | 11.98 | -0.04 | 0.15 | -1.25 | 55% | -0.18 | suppressed (N<20 or <10 days) |
| games_2_3 / LIKELY | **9** | 10.58 | 10.39 | -0.19 | 14.80 | 14.09 | -0.72 | 0.44 | 0.75 | 67% | -0.19 | suppressed (N<20 or <10 days) |

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
| team_game_1 | **211** | 9.90 | 9.86 | -0.04 | 12.54 | 12.38 | -0.16 | 0.83 | -1.05 | 51% | -0.04 | [-0.31, 0.29] |
| team_game_2 | **209** | 9.21 | 9.15 | -0.06 | 11.74 | 11.58 | -0.16 | 0.56 | -0.73 | 54% | -0.06 | suppressed (N<20 or <10 days) |
| team_game_3 | **113** | 9.93 | 9.55 | -0.38 | 12.51 | 12.29 | -0.22 | 0.28 | -0.97 | 57% | -0.38 | suppressed (N<20 or <10 days) |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **88** | 10.28 | 10.26 | -0.02 | 12.77 | 12.70 | -0.08 | 0.05 | -0.04 | 57% | -0.02 | suppressed (N<20 or <10 days) |
| 2-4 | **58** | 8.81 | 9.21 | 0.39 | 11.10 | 11.39 | 0.29 | -1.83 | -3.09 | 41% | 0.39 | suppressed (N<20 or <10 days) |
| 4-6 | **39** | 10.53 | 9.62 | -0.90 | 13.84 | 12.10 | -1.74 | 6.14 | 2.57 | 56% | -0.90 | suppressed (N<20 or <10 days) |
| >=6 | **26** | 10.12 | 10.30 | 0.18 | 12.74 | 13.79 | 1.05 | 1.43 | -5.29 | 46% | 0.18 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **210** | 9.90 | 9.86 | -0.04 | 12.55 | 12.40 | -0.16 | 0.79 | -1.10 | 51% | -0.04 | [-0.30, 0.30] |
| LIKELY | **6** | 6.52 | 8.05 | 1.53 | 8.55 | 9.71 | 1.16 | -3.22 | -4.91 | 17% | 1.53 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **81** | 9.67 | 9.85 | 0.18 | 12.40 | 12.25 | -0.15 | -0.73 | -1.99 | 54% | 0.18 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **84** | 10.77 | 10.33 | -0.43 | 13.00 | 12.69 | -0.31 | 1.80 | -0.27 | 54% | -0.43 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **82** | 9.90 | 9.89 | -0.01 | 12.56 | 12.34 | -0.22 | 0.07 | -1.85 | 49% | -0.01 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **81** | 10.13 | 10.15 | 0.02 | 12.95 | 13.09 | 0.15 | 0.67 | -2.35 | 47% | 0.02 | suppressed (N<20 or <10 days) |

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

* games_scored: 418
* truth_snapshot_before_as_of: 418
* base_and_roster_same_run: 418
* margin_base_consistent: 418
* roster_records_with_code_sha: 418
* truth_evidence_complete: 418
* base_committed_before_tip: 418
* base_commit_unknown: 0
* roster_committed_before_tip: 418
* roster_commit_unknown: 0
* truth_committed_before_tip: 418
* truth_commit_unknown: 0
