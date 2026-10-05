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
