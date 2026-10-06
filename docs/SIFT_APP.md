# CBB app publication for Sift (`edge_finder.app.v1`)

`cbb_edge/app/sift_app` translates what the frozen prospective system already archived into the generic
app contract every Edge Finder sport publishes (authored in `chmoses98/kalshi-bet-router`, vendored at
`contract/edge_finder_contract`, contract 1.2.0). Sift reads the publication; it never reads a CBB archive.

```
projections-archive  roster-archive  prospective-scores  schedule-archive  kalshi-archive  SDV schedule
            \               |               |                 |                /              /
             +--------------+---- cbb_edge/app/sift_app (adapter, read-only) --+-------------+
                                              |
                       app-data branch: app/latest (edge_finder.app.v1 + explorer/)
                                              |
                     router registry (CBB) -> Sift generic data layer -> Sift CBB screens
```

`sift-cbb-projection-1.0` (`cbb_edge/app/sift.py`) is unchanged: it stays the upstream model-output schema.
The publisher is an adapter from it.

## Where and when

* Branch `app-data`, root `app/latest`
  (`https://raw.githubusercontent.com/chmoses98/cbb-edge-finder/app-data/app/latest`). It is replaced
  wholesale on every publish (one orphan commit): a view, not evidence. The evidence stays on the
  append-only archive branches; `main` stays code-only.
* `.github/workflows/app-publish.yml` runs after `prospective-projections`, `roster-capture`,
  `prospective-scores`, `ops-watch` and `kalshi-capture` complete, plus a 3-hourly catch-up. Nothing listens
  to pushes on `app-data`, so there is no loop. A failed publish leaves the last good tree and rewrites only
  `health.json` (DEGRADED).

## Projection selection (never hindsight)

`selection.py`, tested in `tests/test_sift_app.py` (`test_integrity_*`):

* a record is eligible only with prospective provenance and `as_of` strictly before the CURRENT listed tip
  (announced time). For an unannounced (TBD) tip: before the 00:00 ET placeholder, or proven by the record's
  own live ESPN "pre" observation made after `as_of` (Wave 10). Anything else is `pretip_unproven`;
* per version, the newest eligible record wins; two different records at one `as_of` show nothing;
* a record for another matchup than the current schedule is flagged (`schedule_identity_changed`);
* a settled game's verdict (VALID / INVALID / UNSCORABLE) is read from the prospective scoreboard's
  `integrity_gate.csv`, never recomputed;
* the P-ROSTER-1 rotation shown is the one stored in the archived pre-tip record. An upcoming game without one
  shows the current roster truth, labelled as such; a started game never shows a later snapshot.

Game states: `PROJECTED`, `PENDING_WINDOW` (not yet in the 30 h capture window), `AWAITING_CAPTURE`,
`UNAVAILABLE` (started without a pre-tip record).

## What is published

| CBB source | `edge_finder.app.v1` document / field | Today (2026-10-06) | Limitation |
|---|---|---|---|
| Wave 11 completed schedule, D-I vs D-I | `events.json`, `board.json` (event ids `evt_` from `cbb_game_id` = `G<espn id>`; `source_ids.espn_event_id`) | 5,341 games; board = opening week (296) | games vs non-D-I opponents are outside the experiment and not published |
| D-I universe (`models/rosters/d1_membership.csv`) | participants (`prt_` from `T####`), `explorer/teams/*` | 365 teams | — |
| health | `health.json` + `extensions.cbb` (contract 1.2.0) | RESEARCH_ONLY; WAITING_FOR_WINDOW | market component NOT_APPLICABLE by design |
| capability manifest | `explorer/capabilities.json` + `health.extensions.cbb.capabilities` | computed from what is published | — |
| projections (5 frozen versions) | `explorer/events/*` `projections`, `distributions`, `extensions.cbb.models` | none yet (N = 0, no game in window) | research evidence; incumbent first; no ranking of models |
| opponent-adjusted ratings + Four Factors | `matchup` rows, `metrics.json`, `rankings/*` (`met_cbb.adj_*`) | publish with the first archived projections | newest archived pregame rating per team |
| roster truth, continuity, expected rotation | team profile + event `extensions.cbb.roster`; roster rankings | 4 roster rankings, 347 teams | rotation = expected pregame rotation, not a lineup |
| prospective scoreboard | `health.extensions.cbb.prospective` | N = 0 | no inference below N = 20 / 10 days (locked) |
| Kalshi capture | `markets.json`, event `markets` | 0 (no game contract maps; futures/season wins are not games) | read-only quotes, never priced by a model |
| recommendations, wagers, model prices, settlements | empty collections | 0 | research system |

## Freeze

The package imports no projection, rating, roster-overlay or scoring module (AST-tested), writes into no
archive checkout (hash-tested), and changes nothing under `models/`, `cbb_edge/{model,ratings,features,
players,rosters,backtest,research}` or the frozen Wave 7–11 protocols.

```bash
python -m cbb_edge.app.sift_app --season 2027 --projections arch/projections-archive \
  --rosters arch/roster-archive --scores arch/prospective-scores --schedule-archive arch/schedule-archive \
  --kalshi arch/kalshi-archive --out site/app/latest
python -m tests.sift_app_fixture --variant season --out /tmp/cbb-fixture   # synthetic TEST fixture
```
