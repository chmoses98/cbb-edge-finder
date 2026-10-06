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

## Live / research parity: season-boundary checkpoints (Wave 5)

Live projections used to rebuild every long history (team engine from 2006, RAPM chains
from 2011, career shooting) from a shorter warm-up on the runner. That rebuild was only
approximately equal to the research replay (mean |Δ margin| 0.005–0.011 on the same
games and the same as-of, worst features `p_*` from the RAPM chain warm-up and
`margin_an`/`total_an` from the hooked engine).

Now `models/pure/checkpoints/<version>/boundary_<B>/` stores the exact end-of-season state
of the RESEARCH replay at the end of season B (engine fits, RAPM chain ratings, base-engine
finals, the preseason roster table for B+1, career shooting totals and last-five shooting
state). `prospective.feature_frame(..., reconstruction="auto")` replays ONLY season B+1
from that state with the same code. Each record carries
`prospective.reconstruction = {mode, boundary, sha256}`.

* Parity (`scripts/research/parity_diagnostics.py`, same games, same as-of = the day's
  first tip − 1 s, same artifact): 2025-12-06 and 2026-02-14, every model input and the
  projected margin/total agree to ≤ 4e-9 (pure-0.2.0) and ≤ 1e-13 (pure-0.3.0 /
  pure-0.4.0; bit-identical on 2026-02-14). Reports: `research/wave5/parity_*.json`.
* What remains between a live projection of a PAST game and the research OOS prediction
  is coefficients only: the frozen artifact was fitted on 2012–2026, the OOS stack for
  season s on 2012..s−1 (`research/wave5/parity_coefficients.json`: 0.12 / 0.16 mean
  |Δ| for 0.3.0 / 0.4.0 on 2025–26, mostly a −0.10 / −0.15 intercept shift). For the
  2026–27 target season the artifact IS the research expanding-window fit for s = 2027,
  so prospective projections and the research protocol are the same model.
* Checkpoints are immutable and hash-pinned (`tests/test_parity.py`); the boundary-2026
  checkpoints serve 2026–27. Boundary 2027 (for 2027–28) is written after the season
  with `scripts/research/build_checkpoints.py engine|chain|write 2027`, which re-runs the
  research replays and refuses to write unless they reproduce the cached research
  outputs.
* `reconstruction="warmup"` keeps the old path for diagnostics only.

## pure-0.5.0 (Wave 5 shadow challenger)

* B25 = pure-0.4.0 + B23 (absence-driven player signal) + B24 (player-level possession
  model: PBP shot zones, shrunk finishing / selection / possession-component priors,
  EWMA expected team profiles, opponent-adjusted defensive allowed excess, five
  interactions). See `research/reports/WAVE5.md`.
* `requires_checkpoint`: it runs only from its season-boundary checkpoint, which also
  stores the possession-model state (career counts, end-of-season posteriors, final
  EWMA weights, P(return), league zone means).
* The daily runner downloads the current season's free ESPN play-by-play release asset
  (`sdv.download_live("pbp", ...)`) and builds `silver/pbp_player_shots.parquet` for
  that season only. Without it the shot-zone histories of the current season are
  missing, so the record would still be produced but less informed.
* It is a SHADOW challenger. `pure-0.2.0` stays incumbent until the Wave 4 prospective
  promotion rule is evaluated after the 2026–27 season.

## P-ROSTER-1: roster-truth overlay (Wave 6, PROSPECTIVE_ONLY)

* `roster-capture` (daily Sep–Nov) builds the multi-source roster truth
  (`cbb_edge/rosters/truth.py`, rules in `docs/ROSTER_SOURCE_AUDIT.md`) and archives it
  in `roster-archive`, together with each team's P-ROSTER state (expected rotation,
  continuity inputs). These are the archived T−7d / T−72h / T−24h / T−6h game-1 states.
* `prospective-projections` writes `pure-0.5.0+roster` records next to the untouched
  `pure-0.5.0` records (`cbb_edge/rosters/overlay.py`, spec
  `models/overlays/p-roster-1.json`, hash-pinned):
  * (a) the game-1 player block from the expected rotation over roster-truth players;
  * (b) a continuity correction, applied only to CONFIRMED rosters.
* `prospective-benchmark` (weekly) adds:
  * `model_monitor.json`: every version and overlay, by games-seen slice, with market
    gap as a benchmark only;
  * `proster_metrics.json`: the preregistered P-ROSTER-1 questions;
  * `rotation_scorecard.csv`: game-1 rotation accuracy per snapshot;
  * `false_inclusion.csv`: departed-player false inclusion, BASE (last season's shares)
    vs the archived P-ROSTER rotation (`research/hypotheses/WAVE7.md` 7).
* Wave 7 inputs:
  * the roster truth now includes official athletics rosters for the whole D-I
    universe (NCAA Membership Directory → generated, pinned domain registry →
    discovery and parsers);
  * for a CONFIRMED team only official-roster players enter the rotation;
  * shares are water-filled to exactly 200 minutes, at most 40 per player;
  * each snapshot archives a continuity-correction audit and rotation sanity checks.
  * The authority of (a) and (b) is unchanged.
* Not a frozen version and never the incumbent. Game-1 results never alter archived
  game-1 records.

## P-ROSTER-1 prospective scoreboard (Wave 8)

* `prospective-scores` workflow (daily Nov–Apr, 12:40 UTC) →
  `scripts/prospective/score_proster.py` → append-only `prospective-scores` branch
  (`scores/YYYY/MM/<stamp>/`, `latest_dashboard.md`, `LATEST`).
* It reads the full history of `projections-archive` and `roster-archive`, plus the free
  SDV schedule and player box. The market column (benchmark only) comes from
  `espn-lines-archive` and is built outside `cbb_edge.rosters`.
* Outputs:
  * `paired_games.csv`: one row per game, base / roster / incumbent errors, paired
    differences, (a)/(b) split, evidence hashes, commit times;
  * `team_games.csv`: team game numbers and strata;
  * `continuity_tail.csv`;
  * `false_inclusion_{estimated,realized}.csv`;
  * `rotation_{scorecard,validation}.csv`;
  * `summary.json`;
  * `dashboard.md`.
* Protocol: `research/hypotheses/WAVE7.md` §7 (locked); diagnostics:
  `research/hypotheses/WAVE8.md` §3. N is shown first everywhere, and no table decides
  anything.
* New projection records carry `prospective.code_sha` and
  `roster.truth_archive_commit` (provenance only).
* Season-aware D-I membership: `cbb_edge/rosters/membership.py`,
  `models/rosters/d1_membership.csv`.
* Pre-tip diagnostics for any truth snapshot:
  `python scripts/prospective/pretip_diagnostics.py --rosters <roster-archive>`.

## Operations (Wave 9): no owner intervention needed on opening day

| workflow | slots | catch-up | writes |
|---|---|---|---|
| prospective-projections | 14:10, 21:10 UTC (Nov–Apr) | hourly :40; runs if a slot was missed, or a D-I game in the next 30 h lacks a record (then writes only the missing records) | `projections-archive` + one run manifest per run (heartbeat) |
| roster-capture | 11:17 UTC daily (Sep–Nov); Mondays 12:17 (Dec–Apr) | hourly :47 if the slot passed with no truth snapshot | `roster-archive` |
| prospective-scores | 12:40 UTC (Nov–Apr) | hourly :50 if the slot passed with no scoreboard | `prospective-scores` |
| ops-watch | hourly :25 (Oct–Apr) | — | `ops-reports`; the run turns **red** on any CRITICAL alert |

Every decision is made from the append-only archive branches (`cbb_edge/ops/cadence.py`):
- there is no runner state and no artifact dependency;
- duplicate ticks re-decide from the same facts;
- an existing record is never overwritten.

A catch-up run never projects a game that has tipped. When a game has no pre-tip record,
it is reported as UNSCORABLE, or as OPENING_GAME_MISSED for a team's first game. It is
never reconstructed.

The pre-tip gate (`cbb_edge/rosters/pretip_gate.py`) decides which games are credited.
Only VALID games are scored; INVALID, UNSCORABLE and PENDING games are listed in
`integrity_gate.csv`.

Readiness for any window:

```
python -m cbb_edge.ops.readiness --rosters <roster-archive> \
    [--projections <projections-archive>] [--scores <prospective-scores>] \
    [--from 2026-11-02T00:00:00Z] [--days 7] --out ops_out
```

Before the opener, the readiness report previews opening week. ESPN lists a game with no
set tip time at 00:00 ET of its date ("TBD"). The frozen projection step only projects
games whose listed tip is in the future, so a TBD game's last projection chance is the
evening before.

To rehearse the whole production chain in a sandbox:

```
python scripts/prospective/dry_run.py --rosters <roster-archive> --sandbox DIR
```

This uses the production code, a simulated clock and synthetic settlement. It is never
research evidence.
