# P-ROSTER-1 prospective scoreboard — 20261103T182102Z

Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative = P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip gate are counted.

## Sample size first: **game 1 N = 119**

Pre-tip gate: VALID 119 · INVALID 0 · UNSCORABLE 2 · PENDING 1 (INVALID / UNSCORABLE games are never scored and never reconstructed; see `integrity_gate.csv`).

Intervals need N ≥ 20 games on ≥ 10 distinct days; until then they are suppressed. **No table here decides anything during 2026–27.**

## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)

| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | Base bias | P-ROSTER-1 bias | % improved | paired mean \|e\| diff | departed-player false minutes (Base → P-ROSTER-1) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **119** | 10.64 | 10.52 | -0.12 | 13.19 | 13.25 | 0.06 | 0.32 | -1.84 | 52% | -0.12 | 146.3 → 0.6 (238 teams) |

## Game 2 and Game 3, separately (never pooled into the game-1 headline)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_2 | 0 | | | | | | | | | | | |
| game_3 | 0 | | | | | | | | | | | |

## PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; games 2–3 = 1–2

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 | **119** | 10.64 | 10.52 | -0.12 | 13.19 | 13.25 | 0.06 | 0.32 | -1.84 | 52% | -0.12 | suppressed (N<20 or <10 days) |
| games_2_3 | 0 | | | | | | | | | | | |

## PRIMARY by confidence of the side(s) that triggered the overlay

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| game_1 / CONFIRMED | **114** | 10.85 | 10.64 | -0.21 | 13.36 | 13.38 | 0.01 | 0.60 | -1.58 | 54% | -0.21 | suppressed (N<20 or <10 days) |
| game_1 / LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |

## Intermediate (each team's first game, by archived snapshot)

| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | recall | false-inclusion rate | omission |
|---|---|---|---|---|---|---|---|---|---|
| T-24h | 305 | 0.59 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-6h | 305 | 0.59 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-72h | 305 | 0.59 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| T-7d | 305 | 0.59 | 0.70 | 0.61 | 7.99 | 0.76 | 0.70 | 0.12 | 0.01 |
| latest | 305 | 0.59 | 0.70 | 0.62 | 8.01 | 0.76 | 0.70 | 0.11 | 0.01 |
| BASE | 305 | – | – | – | – | – | – | 1.00 | 0.69 |

## Diagnostic: team game number (not pooled)

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| team_game_1 | **119** | 10.64 | 10.52 | -0.12 | 13.19 | 13.25 | 0.06 | 0.32 | -1.84 | 52% | -0.12 | suppressed (N<20 or <10 days) |
| team_game_2 | 0 | | | | | | | | | | | |
| team_game_3 | 0 | | | | | | | | | | | |

## Diagnostic: game-1 |continuity adjustment| buckets

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <2 | **42** | 11.53 | 11.47 | -0.06 | 14.29 | 14.13 | -0.16 | -0.57 | -0.63 | 57% | -0.06 | suppressed (N<20 or <10 days) |
| 2-4 | **34** | 10.32 | 10.30 | -0.02 | 12.53 | 12.68 | 0.15 | -2.45 | -3.77 | 47% | -0.02 | suppressed (N<20 or <10 days) |
| 4-6 | **25** | 9.98 | 9.03 | -0.95 | 12.83 | 11.51 | -1.32 | 6.49 | 2.62 | 56% | -0.95 | suppressed (N<20 or <10 days) |
| >=6 | **18** | 10.10 | 10.76 | 0.65 | 12.19 | 14.37 | 2.18 | -0.91 | -7.21 | 44% | 0.65 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by roster confidence

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONFIRMED | **119** | 10.64 | 10.52 | -0.12 | 13.19 | 13.25 | 0.06 | 0.32 | -1.84 | 52% | -0.12 | suppressed (N<20 or <10 days) |
| LIKELY | **5** | 5.84 | 7.78 | 1.93 | 8.26 | 9.77 | 1.51 | -5.84 | -7.78 | 0% | 1.93 | suppressed (N<20 or <10 days) |

## Diagnostic: team game 1 by expected-newcomer quartile

| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | 90% CI (day bootstrap) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| q1 (0-5 newcomers) | **52** | 10.06 | 10.38 | 0.32 | 12.45 | 12.84 | 0.39 | -1.76 | -2.85 | 52% | 0.32 | suppressed (N<20 or <10 days) |
| q2 (5-7 newcomers) | **54** | 10.28 | 10.02 | -0.27 | 12.50 | 12.55 | 0.05 | 1.30 | -1.24 | 50% | -0.27 | suppressed (N<20 or <10 days) |
| q3 (7-9 newcomers) | **53** | 10.94 | 10.57 | -0.37 | 13.38 | 13.05 | -0.33 | -1.02 | -3.26 | 55% | -0.37 | suppressed (N<20 or <10 days) |
| q4 (9-16 newcomers) | **54** | 10.69 | 10.73 | 0.03 | 13.39 | 13.84 | 0.45 | 0.81 | -2.34 | 48% | 0.03 | suppressed (N<20 or <10 days) |

## Departed-player false inclusion (realized, locked definition)

| rotation @ snapshot | teams | false players | false minutes | omitted share |
|---|---|---|---|---|
| BASE@- | 305 | 9.49 | 146.3 | 0.69 |
| ROSTER@T-24h | 305 | 0.12 | 0.8 | 0.01 |
| ROSTER@T-6h | 305 | 0.13 | 0.8 | 0.01 |
| ROSTER@T-72h | 305 | 0.12 | 0.9 | 0.01 |
| ROSTER@T-7d | 305 | 0.13 | 0.8 | 0.01 |
| ROSTER@latest | 305 | 0.13 | 0.8 | 0.01 |

Pre-tip ESTIMATE (separate): BASE 146.3 false minutes / 9.5 players per team over 367 teams.

## Snapshot integrity

* games_scored: 119
* truth_snapshot_before_as_of: 119
* base_and_roster_same_run: 119
* margin_base_consistent: 119
* roster_records_with_code_sha: 119
* truth_evidence_complete: 119
* base_committed_before_tip: 119
* base_commit_unknown: 0
* roster_committed_before_tip: 119
* roster_commit_unknown: 0
* truth_committed_before_tip: 119
* truth_commit_unknown: 0
