# Possession challenger `poss-ch-v1` vs production `pure-0.2.0` (RESEARCH_ONLY)

**Verdict: FAILED.** On the holdout, neither the standalone possession model nor the
dev-frozen blend beats the frozen production model on margin, winner or totals.
Nothing is promoted; no production code, workflow, schedule or model file changed.

Code: `cbb_edge/research/possession_challenger.py`, script
`scripts/research/run_possession_challenger.py`, tests `tests/test_possession_challenger.py`,
frozen parameters `frozen_params.json`, results `results.json` (this directory).

## Benchmark (production) — how it was reproduced

* 2025-26 (season 2026): `pure-0.2.0` walk-forward from its committed boundary-2025 checkpoint,
  via the live `feature_frame` code (as-of after season end; the engine and RAPM still use only
  rows with `available_at` before each game day). Margin MAE 9.040, matching Wave 2 levels.
* Dev 2023-24 and 2024-25: same code with `reconstruction="warmup"`. Check: warmup vs checkpoint
  on 2026 agree to median |Δmargin| 0.003 pts (corr 0.9999998).
* 2026-27 to date (season 2027): the real archived pre-tip incumbent records
  (`projections-archive`, latest record with `as_of` < tip), neutral-site orientation fixed to
  schedule order. A replay agrees with them to a median |Δmargin| of 0.25.
* Caveat: `pure-0.2.0` lists `trained_seasons [2012, 2026]`, so its stacked layer saw 2025-26
  (and the dev seasons). That favours production on those seasons; only 2026-27 is fully
  out of sample for production.

## Challenger

Day-by-day ridge (only rows with `available_at` < first tip of the day): per-100 offensive and
defensive efficiency with a home term and a shrunk team-specific home term, plus tempo. Weights are
possessions × recency (τ=120 d). The preseason prior is 0.95 × last season's centred rating. Points
= possessions × efficiency (multiplicative). A per-season linear stretch and probit SD by games seen
are fitted on the 6 previous seasons. Tuning used only 2015-24. The blend (production + w × (challenger
− production)) was fitted on 2023-25 dev and frozen: **w_margin = 0.00**, w_total = 0.093, plus a
probit win link. The holdout was scored once, after freezing.

## Development (not evidence)

| check | result |
|---|---|
| standalone, 2015-24 (53,778 games) margin MAE | 8.906 vs published B3 8.853 / B9 8.833 |
| standalone − production, 2023-25 (11,490) margin MAE | +0.171 [+0.139, +0.202] |
| residual correlation challenger vs production | 0.988 (no diversity to blend) |
| production residuals by month/site/games-seen/size | all biases < ~1.5 pts; largest error at games-seen 0-2 (MAE ~10) |

## Holdout (2025-26 full + 2026-27 to 2026-11-16; n = 6,390 identical games)

Differences are challenger − production (negative = challenger better). Bootstrap 95% CIs from
2,000 resamples of games (each game is one cluster).

| metric | production | standalone | Δ standalone [95% CI] | blend | Δ blend [95% CI] |
|---|---|---|---|---|---|
| margin MAE | 9.143 | 9.340 | +0.197 [+0.153, +0.243] | 9.143 | 0.000 (w=0) |
| total MAE | 13.609 | 13.802 | +0.193 [+0.125, +0.266] | 13.608 | −0.001 [−0.008, +0.006] |
| team-total MAE | 8.232 | 8.383 | +0.150 [+0.120, +0.182] | 8.234 | +0.001 [−0.002, +0.004] |
| Brier | 0.1728 | 0.1763 | +0.0035 [+0.0024, +0.0047] | 0.1727 | −0.0001 [−0.0002, 0.0000] |
| log loss | 0.5108 | 0.5202 | +0.0095 [+0.0066, +0.0123] | 0.5103 | −0.0005 [−0.0010, +0.0002] |
| calibration slope | 0.968 | 1.013 | — | 0.956 | — |

Slices (Δ standalone margin MAE): 2025-26 n=5,752 +0.187 [+0.142, +0.232]; 2026-27 n=638
+0.294 [+0.081, +0.486] (standalone total MAE +0.856 [+0.500, +1.183]). Production's 2026-27
win-probability calibration slope is **0.82** (it is overconfident early in the season); the blend's is 0.77.

## Why it failed

All four leading hypotheses are already inside `pure-0.2.0` (arm B9). It has an opponent-adjusted
ridge for efficiency and tempo with recency weights and a previous-season prior. It has Four
Factors and shot-profile matchup terms, a shrunk team-specific home court with neutral handling,
and walk-forward RAPM player strength. A team-box-only re-implementation therefore carries the same
signal (residual correlation 0.988) with less information. Cheap tests of each idea on dev
found no slice with a systematic production error large enough to recover (largest bias < 1.5 pts
outside games-seen 0-2). Most of the remaining error is game-level noise. On 2018-23 the free
closing line was only 0.17 margin MAE better than B3 (BASELINE.md).

## Next best lever

The early season, roughly games-seen 0-3. Errors are largest there (MAE ~10), and production's
2026-27 win-probability slope is 0.82. A leakage-safe preseason roster prior needs archived
preseason rosters plus transfers. History exists only from 2026 (`models/rosters`), so it has to be
collected going forward or reconstructed from player boxes with an explicit as-of. Also refit the
production stack out of sample (its training includes 2026).

## Reproduce

Restore the vault archives `CBB/espn_team_box_schedules` and `espn_player_box_pbp_early_seasons`.
Link them into `$CBB_DATA_DIR/bronze/sportsdataverse_releases/{schedules,team_box,player_box}`.
Download free sportsdataverse `ncaa_mbb_possessions` / `ncaa_mbb_lineups` for 2017-26. Then run
`cbb_edge.data.silver.build.build(2006..2027, update_registry=False)`,
`python -m cbb_edge.players.stints --seasons 2017-2026` and `shot_profile.build(2017..2026)`.
Export `OMP_NUM_THREADS=1` and run the script steps in its docstring (`prod`, `raw`, `freeze`,
`holdout`).
