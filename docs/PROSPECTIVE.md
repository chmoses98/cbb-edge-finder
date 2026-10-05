# Prospective 2026–27 projection archive

The gold-standard evaluation set: PURE_BASKETBALL projections written **before** tip-off
and never edited.

* Workflow `.github/workflows/prospective-projections.yml` — twice daily Nov–Apr
  (14:10 and 21:10 UTC, after SportsDataverse's 07:00 UTC refresh). Free inputs only.
* Each run re-downloads the in-progress season's bulk files into dated immutable bronze
  paths (`<dataset>/live/<stamp>/`), rebuilds silver/stints/shot profile, computes
  states with information available before `as_of`, applies the frozen model
  (`models/pure/<version>.json`, sha256 recorded in every record), and writes one record
  per (game, run) for games starting within 30 hours.
* Archive branch `projections-archive`: `projections/<season>/<date>/<game_id>/<as_of>.json`.
  The writer refuses to overwrite (`ArchiveOverwriteError`); the workflow skips existing
  paths; git history makes edits visible.
* Record = Sift schema (`sift-cbb-projection-1.x`) + `prospective` block (`as_of`,
  code version, model sha256), including projected scores, margin, total, possessions,
  win probability, margin/total SD, adjusted ratings, player/rotation context
  (`player_context`: player-layer team offense/defense, whether the rotation was known),
  and data freshness.
* Later evaluation joins actual results, Kalshi prices at multiple timestamps, and free
  ESPN lines — downstream, without touching the archived projections.
* The 2025–26 season was observed in PR #1 and is no longer an untouched test; 2026–27
  prospective games are the cleanest test from now on.

## Incumbent + shadow challenger (Wave 3)

* `models/pure/active.json` lists the **incumbent** (`pure-0.2.0`, production) and the
  **challengers** (`pure-0.3.0`, B15) run in shadow. Every run projects every active model
  from its own frozen artifact; `load_model()` with no version returns the incumbent,
  never "the newest file".
* Archive paths: the incumbent keeps the original layout
  (`projections/<season>/<date>/<game_id>/<as_of>.json`); every other version is written
  under `projections/<version>/...`. Records carry `prospective.role`
  (`incumbent` / `challenger`). Existing `pure-0.2.0` records are never touched, and
  `tests/test_wave3.py::test_pure_020_artifact_unchanged` pins the `pure-0.2.0` artifact
  hash.
* `pure-0.3.0` needs additional live inputs, rebuilt by `cbb_edge/app/wave3_live.py`
  with information before `as_of` only: base engine finals (conference anchor),
  walk-forward RAPM chain → roster graph → preseason roster state, rotation × season-start
  player ratings (roster strength), and box-score-updated player features from the frozen
  player-prior coefficients stored in the artifact.
* Live/research parity (2025-12-06, 127 games): `pure-0.3.0` corr 0.9993, mean |Δ| 0.30
  pts vs the research walk-forward; `pure-0.2.0` corr 0.9994, mean |Δ| 0.27
  (`research/wave3/live_parity.json`).

## Free pre-tip line snapshots (benchmark only)

`.github/workflows/espn-line-capture.yml` snapshots the ESPN public scoreboard line every
30 minutes in season (`cbb_edge/market/espn_capture.py`, schema
`espn-line-snapshot-v1`): provider, spread, total, moneylines, minutes to tip and horizon
(T-24h, T-6h, T-90m, T-30m, latest), appended to the `espn-lines-archive` branch. Used
only downstream to measure convergence to the market at fixed horizons; never a PURE
input (CI-enforced import ban + column guard).

## Wave 4 additions

* `active.json`: incumbent `pure-0.2.0`; challengers `pure-0.3.0`, `pure-0.4.0` (hashes
  of all three pinned in `tests/test_wave3.py`).
* `pure-0.4.0` live inputs (`cbb_edge/app/wave3_live.py`): dynamic conference hook
  (k = 400), absence-persistence rotation (frozen per-season P(plays) models and
  replacement weights in the artifact), player shooting skill
  (`shooting.live_features`; upcoming games use each team's state after its completed
  games). Live/research parity 2025-12-06: corr 0.9995, mean |Δ| 0.26 pts.
* P-AVAIL overlay: challengers' games with reported player statuses are re-projected
  and archived as `projections/<version>_avail/...` (PROSPECTIVE_ONLY; base records
  untouched). See `docs/AVAILABILITY.md`.
* Roster snapshots (`roster-archive`) and availability captures
  (`availability-archive`) start running after this PR merges.
* Benchmarks (`prospective-benchmark` workflow, Mondays in season → `benchmark-reports`):
  stage benchmark, future_market_alignment, Kalshi table, availability impact.
  MARKET_BENCHMARK only.
* Promotion: `cbb_edge/research/promotion.py` implements the rule fixed in
  `research/hypotheses/WAVE4.md`; evaluated once after the 2027 national championship.
