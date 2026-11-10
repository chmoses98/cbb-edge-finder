# Orientation integration — before/after on the complete archive (2026-11-10)

RESEARCH_ONLY. Follow-up to PR #46 (Wave 12/13 results unchanged, no predictive challenger promoted). **Not merged; the production scoring change awaits owner review.** OLD = production code at `b3203a31` loaded unmodified from git; NEW = this branch. Identical inputs, archives read-only (projections-archive `b8f32dd3ce`, roster-archive `f22b0febd2`, clock `2026-11-10T12:00:00Z`).

## What changed

`cbb_edge/data/ids/orientation.py::classify` is the single decision (canonical team ids): `SAME`, `SWAPPED` (same two teams reversed, accepted only when the neutral-site flag is true on every source that carries one), `UNVERIFIED` (anything else; fail closed).
* **Scoreboard** (`prospective_score.score`): a verified reversal is no longer `UNSCORABLE: schedule_identity_changed`; its result margin is mapped onto the projected teams (totals are orientation-free). A schedule row whose teams do not resolve is now `UNVERIFIED` (the earlier rule silently scored it). `remap_swapped=False` keeps the earlier reversal handling.
* **Kalshi panel** (`kalshi/history._projections` via `selection.select`): a verified reversal is reframed into the schedule's frame, which is the frame `parse_contract` / `settle` use for `subject_side`, so model probabilities point the right way. Contract parsing, `subject_team_id` and settlement code are untouched. The Sift app still treats every change as changed (unchanged behaviour).
* Archived projections and schedule rows are never rewritten; reframing is a copy made at read time.

## A. Scoreboard, old vs new

Records read 5675; completed games 523. Verified neutral-site reversals: `[401909694, 401918053, 401919029, 401921704]` (the four Wave 12 games). Unverified identities in the archive: `{}`.

| check | result |
|---|---|
| paired_games, all other games (every column) | **identical** (359 rows × 112 columns) |
| integrity gate, all other games | **identical** (363 rows × 3 columns) |
| team-game view, all other games | **identical** (718 rows × 38 columns) |
| gate counts | old {'INVALID': 1, 'PENDING': 4, 'UNSCORABLE': 4, 'VALID': 358} → new {'INVALID': 1, 'PENDING': 4, 'VALID': 362} |
| rows that differ | exactly `[401909694, 401918053, 401919029, 401921704]` |

The four reversed games (projected-home frame; base pure-0.5.0):

| game | old gate | new gate | schedule-home margin | result mapped to projected home | projected margin | error (old pairing would have used the wrong sign) |
|---|---|---|---|---|---|---|
| 401909694 | UNSCORABLE (schedule_identity_changed) | VALID | -43 | +43 | +23.4 | +19.6 |
| 401918053 | UNSCORABLE (schedule_identity_changed) | VALID | +18 | -18 | -17.1 | -0.9 |
| 401919029 | UNSCORABLE (schedule_identity_changed) | VALID | +7 | -7 | -1.0 | -6.0 |
| 401921704 | UNSCORABLE (schedule_identity_changed) | VALID | +6 | -6 | +7.6 | -13.6 |

### Fail closed (schedule inputs perturbed in memory for real games; old and new code)

| case | old | new |
|---|---|---|
| different_away_team | UNSCORABLE | UNSCORABLE — reason schedule_identity_changed |
| projected_game_reversed_at_non_neutral_site | UNSCORABLE | UNSCORABLE — reason schedule_identity_changed |
| reversed_game_marked_non_neutral | UNSCORABLE | UNSCORABLE — reason schedule_identity_changed |
| reversed_game_neutral_unknown | UNSCORABLE | UNSCORABLE — reason schedule_identity_changed |
| unresolved_schedule_team_id | VALID | UNSCORABLE — reason schedule_identity_changed |

The one behavioural difference outside the reversals: an unresolved schedule team id was previously scored as if it were the projected matchup (fail-open); it is now UNSCORABLE. No archived game is in that state, so no historical result moves because of it.

## B. Kalshi path, old vs new

* Frozen-projection selection compared per game at one minute before the tip: **427** games; old and new differ in **4** — the four reversals (old: no usable version, all five skipped as identity-changed; new: all five reframed). Every other game is identical.
* Settlement of every settled panel contract against the schedule-archive final: **1,335,172 agree, 0 disagree** (136,826 not checkable: halves, overtime, race, ties). On the reversed games: 17,902 agree, 0 disagree. Settlement code is unchanged; this confirms contract directions are untouched.

* The schedule archive flipped these games' orientation late on Nov 8. Panel rows captured BEFORE the flip (**4,021** rows) were built in the projection's own frame, already carry correct probabilities, and are untouched by NEW. Rows captured AFTER the flip are where OLD skipped every version (0 probabilities). For those, NEW reframes the projection into the schedule frame: **1,990** version×contract probabilities, outcomes from the settled score, Brier **0.1843** reframed versus 0.2849 if the projection were applied without reframing (backwards). Frames are never mixed: the reframing uses the schedule as of each row's own capture.

## C. `model_inputs` real-data dry run (before integration)

Production projection code on a locally rebuilt free-input lake, `pure-0.2.0` at as-of `2026-11-05T23:06:44.762463+00:00` (98 records). Pass: **True**.
* games / possessions seen vs an independent recomputation from raw silver rows: **0 mismatches**;
* pace / efficiency noise vs an independent loop recomputation: max |diff| 2.8e-14;
* exported efficiency and tempo vs the same run's `ratings` block: max |diff| 0.0e+00; vs the archived record of the same as-of (incumbent): 0.0 (the checkpoint-based challengers differ by up to 2.0 across environments because their roster/availability inputs are not reproducible locally — that is input data, not the export);
* **future-row perturbation**: 568 team-game rows with `available_at ≥ as_of` scaled (possessions ×1.6, ppp ×0.5): `model_inputs` changed in 0 of 98 records and the projection changed in 0. Nothing after `as_of` leaks in.
Problems found: none requiring a fix. Caveats recorded: the prior weight is the stated ridge-diagonal approximation (ignores recency decay and opponent coupling, ≈5% at this date); `days_since_last_game` uses the schedule as known when the projection runs.

## Reproduce

```bash
# archive checkouts (read-only) and a lake built like scripts/prospective/refresh_and_project.py
CBB_DATA_DIR=$LAKE python scripts/research/orientation_before_after.py --projections $A/projections-archive --rosters $A/roster-archive \
  --schedule $A/schedule-archive --espn $A/espn-lines-archive --panel $A/kalshi-panel-archive --now 2026-11-10T12:00:00Z \
  --baseline-ref b3203a31 --out research/orientation
CBB_DATA_DIR=$LAKE python scripts/prospective/model_inputs_dry_run.py --as-of 2026-11-05T23:06:44.762463Z --version pure-0.2.0 \
  --out research/wave13/model_inputs_dry_run.json
python scripts/research/render_orientation_report.py research/orientation research/wave13/model_inputs_dry_run.json research/reports/ORIENTATION_SCORING.md
```

