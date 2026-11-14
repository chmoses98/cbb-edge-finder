# Waves 15 and 16, amendment 1: verified pre-tip push selection (Wave 14 amendment 5a)

RESEARCH_ONLY. Registered 2026-11-14, before the family's eligibility boundary (`PROSPECTIVE_FROM` =
2026-11-15T00:00Z), when no record in the window exists. The rule reads freeze provenance only, never
outcomes. No parameter, model, metric, window, floor, guard, bootstrap, family or decision rule changes.

The original protocols stay frozen and byte-identical: `research/hypotheses/WAVE15.md`,
`research/hypotheses/WAVE16.md`, `research/wave15/spec.json`, `research/wave16/spec.json`. Their sha256 at
registration are pinned in `research/waves15_16/amendment_1.json`, and a test fails if any of them changes.
This file is the only place the amendment is stated. Where it conflicts with the originals, this file governs.

## What changes

Only **which frozen record is selected per (version, game)**. This is the same as WAVE14.md section 5a.
Both waves call one function, `cbb_edge.research.challenger_eval.load_verified`, built on
`cbb_edge.research.wave14.VerifiedPush`.

* A record with `as_of >= PROSPECTIVE_FROM` is selectable only if a verified manifest lists it and that
  manifest's server-side `pushed_by` is strictly before tip. The manifest comes from
  `cbb_edge.research.freeze_provenance`, which uses GitHub Actions job records.
* A record pushed at or after tip, one with an unverifiable push time, and one listed in no manifest are
  **quarantined**. They are reported under `record_selection.quarantined` and are never selected.
  Evidence fetched later cannot move a push time to before tip.
* The game **falls back** to the latest earlier admitted record. That record must still pass every
  original eligibility rule. In particular, a fallback to a record with `as_of < PROSPECTIVE_FROM` is
  ineligible (`record_before_registration_or_missing`) and is never graded.
* Records with `as_of < PROSPECTIVE_FROM` are selected exactly as registered (latest `as_of < tip`). They only train.
  The exploratory historical analysis is therefore unchanged.

## Why

Under the original rule, the latest `as_of < tip` record is selected first and then checked for
`pushed_by < tip`. A late-pushed latest record therefore excluded the whole game, even when an earlier record
had been verifiably frozen before tip. This lost eligible games but never admitted a bad forecast. The
amendment keeps every safety check and only recovers those games.

## Safety properties (tested)

* **Same base population in both waves.** Both waves select `pure-0.5.0` with the same function and
  the same provenance, so the selected record per game is identical. Each results file reports
  `record_selection.base_selection_digest`, and the two digests must be equal. Wave 16 additionally needs a
  verified `pure-0.5.0_roster` record, so its eligible games are a subset of Wave 15's.
* **No post-tip or unverifiable forecast is admitted.** Selection admits only verified pre-tip pushes, and
  the original eligibility check (`pushed_by < tip` for every compared version's selected record, computed
  independently by `challenger_eval.pushed_by`) still runs as defence in depth.
* **Outcome-blind.** The rule's inputs are archive manifests and GitHub job records only.
