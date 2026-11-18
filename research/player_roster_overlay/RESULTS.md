# Player-aggregate roster overlay `pro-ch-v1` on production `pure-0.2.0` (RESEARCH_ONLY)

**Verdict: small real gain on winner probability early in the season. Margin gains come almost
entirely from the oracle-roster first game. Not "substantial", and not promoted.** No production
code, workflow, schedule or model file was changed.

Code: `cbb_edge/research/player_roster_overlay.py` and `scripts/research/run_player_roster_overlay.py`
(it reuses `run_possession_challenger.py` for production reproduction and scoring). Tests:
`tests/test_player_roster_overlay.py`. Also `frozen_params.json` and `results.json` (this directory).
The pattern follows NBA Phase 14 (`nba_edge/research/player_game.py`).

## Data coverage

The vault CBB player-box archive (`espn_player_box_pbp_early_seasons`) covers every season
2003-2027: 126k-208k player rows and 4.7k-6.3k games per season, with DNP rows listed.
Coverage is adequate. Profiles use 2012 onward; rosters and aggregates were built for 2021-2027.
**No historical pregame roster source exists** (`models/rosters` begins with 2026-27).

## Model

* **Player profile.** Per-minute pts, FGA, FTA, 3PA, ORB, DRB, AST, STL, BLK, TOV and PF. Built
  from all of the player's strictly earlier games, including prior seasons and prior schools (the
  ESPN athlete id follows transfers). Decayed with a 40-game half-life and shrunk with 150 minutes
  of prior toward the previous season's replacement level (players with < 200 career minutes).
  **Pedigree** is the net points per game of last season's main team, minute-weighted.
* **Roster, team-game k >= 1 (pregame-safe).** Every player listed in the team's earlier box scores
  this season. Projected minutes are the decayed mean (4-game half-life) since his first appearance;
  DNP and absent games count as 0.
* **k = 0: ORACLE-ROSTER variant.** Uses the players listed in that game's box, with only their
  earlier history and last season's minutes per game. This is not pregame-safe and is reported
  separately.
* **Team aggregate.** Minute-share × profile per 40 minutes, plus prior share, new-player share
  and pedigree.
* **Overlay.** For each bucket (game-number 0-3, 4-10, 11+, using the smaller of the two teams'
  numbers), a ridge on production's residual using home−away differences for margin and sums for
  total. Production's forecast is the offset. Win probability uses production's own logistic link.
* **Selection.** Fitted on 2021-22 to 2023-24 and validated on 2024-25 (λ = 0.3; dev Brier −0.0009,
  margin MAE −0.028). Refitted on 2021-22 to 2024-25 and frozen. The production residuals in these
  fits come from the warmup reconstruction, which matches the checkpoint to 0.003 pts.

## Holdout: the same 6,390 games as `possession_challenger` (scored once)

Δ = overlay − production; 95% CIs from 2,000 bootstrap resamples of games.

| slice | n | margin MAE (prod → overlay), Δ [CI] | total MAE Δ [CI] | Brier (prod → overlay), Δ [CI] | log loss Δ [CI] |
|---|---|---|---|---|---|
| all | 6,390 | 9.143 → 9.118, −0.024 [−0.052, +0.003] | −0.006 [−0.036, +0.027] | 0.1728 → 0.1720, −0.0007 [−0.0012, −0.0002] | −0.0021 [−0.0035, −0.0008] |
| k 0-3 | 1,287 | 9.960 → 9.839, −0.121 [−0.231, −0.009] | +0.078 [−0.042, +0.202] | 0.1304 → 0.1273, −0.0031 [−0.0050, −0.0014] | −0.0089 [−0.0138, −0.0041] |
| · k 0, oracle roster | 298 | 10.914 → 10.449, −0.465 [−0.729, −0.204] | +0.198 [−0.078, +0.467] | −0.0025 [−0.0065, +0.0014] | −0.0089 [−0.0193, +0.0016] |
| · k 1-3, pregame-safe | 989 | 9.673 → 9.655, −0.017 [−0.133, +0.103] | +0.043 [−0.092, +0.174] | 0.1412 → 0.1379, −0.0033 [−0.0054, −0.0011] | −0.0089 [−0.0143, −0.0030] |
| k 4-10 | 1,213 | −0.026 [−0.083, +0.030] | −0.060 [−0.128, +0.007] | −0.0005 [−0.0018, +0.0008] | −0.0014 [−0.0046, +0.0019] |
| k 11+ | 3,890 | +0.008 [−0.009, +0.026] | −0.017 [−0.042, +0.009] | 0.0000 [−0.0004, +0.0004] | −0.0001 [−0.0012, +0.0009] |
| 2025-26 | 5,752 | −0.012 [−0.036, +0.013] | −0.018 [−0.050, +0.012] | −0.0005 [−0.0010, −0.0000] | −0.0014 [−0.0026, −0.0002] |
| 2026-27 to date | 638 | 10.070 → 9.936, −0.135 [−0.309, +0.038] | +0.101 [−0.056, +0.251] | 0.1425 → 0.1396, −0.0029 [−0.0059, −0.0000] | −0.0089 [−0.0165, −0.0015] |

Team-total MAE overall: 8.232 → 8.218, −0.015 [−0.029, +0.001].

Calibration slope gets worse everywhere: overall 0.968 → 0.934, k 0-3 0.940 → 0.895, 2026-27
0.819 → 0.785. The overlay sharpens probabilities without recalibrating them. A refit of the link
would be the first fix.

## Reading

* The early-season pregame-safe gain is in the winner probability: Brier −2.3% and log loss −2.1%
  on k 1-3, with CIs excluding 0. Margin MAE on k 1-3 is flat.
* The large first-game margin gain (−0.47, −4%) needs the true opening-night roster. It is an
  upper bound on what a preseason roster feed would be worth, not an achievable result today.
* Totals: no gain early. A small, insignificant gain appears at k 4-10.
* Caveat: production's stack was trained on seasons through 2025-26, which favours production on
  every slice except 2026-27.

## Next lever

Capture a pregame roster (preseason official rosters plus the transfer portal) for 2026-27 onward,
so the k = 0 variant becomes pregame-safe. Recalibrate the win link on the overlaid margin.
