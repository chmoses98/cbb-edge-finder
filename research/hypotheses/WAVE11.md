# WAVE 11 — Schedule completeness rescue (no new hypothesis)

Written 2026-10-06, before any 2026–27 game. Wave 11 exists for one reason: the projection
pipeline read only the SportsDataverse (SDV) schedule, and SDV's 2026–27 file lags ESPN.
On 2026-10-06, 249 of the 356 Nov 1–9 D-I vs D-I games were absent from it
(research/reports/WAVE10.md §7).

It changes **no**:

- model;
- P-ROSTER-1 rule;
- continuity, rotation, identity or roster-confidence rule;
- scoring definition;
- market logic.

## 1. Frozen (verified after merging PR #10, `6165438`)

| artifact | hash |
|---|---|
| WAVE7.md | `847361b0…` |
| WAVE8.md | `34f97ab7…` |
| WAVE9.md | `e71718b6…` |
| WAVE10.md | `4ec4b3b1…` |
| `p-roster-1.json` | `0d1b22ff…` |
| pure-0.2.0 | `fb109b54…` |
| pure-0.3.0 | `d5fbc78e…` |
| pure-0.4.0 | `4a5a3cb7…` |
| pure-0.5.0 | `9d255ed3…` |
| `player_identity_2026.parquet` | `3bd7b8ab…` |
| `player_aliases.csv` | `70400e4d…` |

## 2. Schedule source policy (S1–S6)

**S1. SDV first for existence and identity; ESPN for current mutable metadata
(amended A1, see §6).**

- A game SDV lists stays an SDV-native game: its game id, season and SDV identity are
  kept, as are its game state and results (status, completion, scores, period).
- *Original rule (superseded by A1 before merge):* the SDV row was kept unchanged and a
  diagnostic raised when ESPN disagreed.
- *A1 rule:* the game's mutable schedule-only fields are field-level reconciled to
  ESPN's latest valid observation of the same game id (§6).

**S2. ESPN fallback only when absent.**

- An ESPN scoreboard row enters the schedule only when its ESPN game id is absent from
  SDV.
- It is written in SDV's own schema. SDV's schedule is a flattening of the same ESPN
  scoreboard payload: same game ids, same fields.

**S3. Fail closed.** An ESPN-only row is excluded and reported in any of these cases:

| case | reason |
|---|---|
| a required field is missing | `missing_required_field` |
| a bracket placeholder (team ids ≤ 0, ESPN's "TBD" teams) | `teams_not_determined` |
| SDV lists the same two teams on the same ET date under another id | `ambiguous_reconciliation` |
| another ESPN-only id does the same | `duplicate_scheduled_game` |

**S4. Provenance.**

- Every row carries `schedule_source`: `SDV` or `ESPN_FALLBACK`. A field-reconciled SDV
  row also carries `reconciled_fields` and `reconciliation` (per field: SDV value, ESPN
  value) and the ESPN `source_observed_at` (A1).
- A fallback row also carries the ESPN `observed_at` it came from.
- Every projection record carries `schedule.source`, `schedule.source_observed_at`,
  `schedule.reconciled_fields` and `schedule.reconciliation`. The exact ESPN rows behind
  a run's fallback and reconciled records are archived next to them
  (`schedule_rows/<stamp>.jsonl`).
- ESPN rows are archived append-only on `schedule-archive` (`rows/…`). The archive keeps
  every change, and once a day the whole remaining season.

**S5. Prospective only.**

- The fallback applies to seasons ≥ 2026–27 and only inside a prospective run.
- Historical schedules are never touched.
- Silver built by the Wave 11 code is byte-identical to main's for 2006–2027 when no
  fallback file exists (verified, all three tables).

**S6. Reconciliation.**

- When SDV later lists a fallback game, it is the same ESPN game id, so the same game.
- From then on the SDV row is used.
- Records already archived keep their provenance and are never rewritten.
- The scorer pairs one observation per game id.

## 3. Consequences recorded before any result

**C1. Rest-day context of SDV-native games (approved by the owner before merge).**

- Rest days (all versions) are computed from the whole season schedule by the frozen
  formula (`cbb_edge/features/context.py`, unchanged from main).
- With the fallback and the A1 reconciliation, the schedule the formula reads is the
  most complete known real one.
- Measured on the frozen snapshot: rest-day inputs change for 639 of the 1,629
  SDV-native games, 45 of them in Nov 1–9. Every change is attributed to a schedule
  event:
  - 452 to a newly included ESPN-fallback game before them;
  - 187 to a reconciled tip time (their own or the previous game's);
  - 0 unexplained.
- **A schedule-input correction is not a model-methodology change.** The rest-day
  formula, its cap and every feature definition are frozen.

**C2. Settlement.**

- A fallback game settles from ESPN's final row: status, completion and scores in SDV's
  schema.
- On the completed 2025–26 season (1,391 games), ESPN and SDV agree on every field the
  pipeline reads.
- Player box scores still come from SDV only. Rotation metrics for a fallback game wait
  for SDV.

**C3. Ratings.** In-season engine updates read SDV team box scores. A played fallback game
contributes to ratings once SDV publishes its box score, as before Wave 11.

## 4. Gate rule added (fail closed; tightening only)

**G1. Schedule identity changed (kept by the owner; refined in A1).**

- The record judged is the **scored** pre-tip record of a version: the latest before
  tip.
- If that record is for different teams than the game's final resolved schedule, or for
  the same teams with home and away swapped, it predicts another matchup or a margin of
  the opposite sign.
- The game is then **UNSCORABLE** (`schedule_identity_changed`; PENDING until settled)
  and is never paired with the result.
- A matchup corrected before a later pre-tip projection costs nothing: the corrected
  record is the scored one.
- This is a research-integrity safeguard. A1 makes it rare; it stays fail-closed.

The Wave 9 and Wave 10 gate checks are unchanged.

## 5. Canonical opening-week universe (A1)

- A window of dates ("Nov 1–9") means **US Eastern calendar dates**, DST-aware. Nov 1
  starts at 00:00 EDT and the window ends Nov 10 00:00 EST.
- The known D-I vs D-I universe of the window is `schedule_completion.canonical_universe`:
  every game id SDV or ESPN lists, with ESPN's latest valid teams and tip, else SDV's.
- Readiness and the dry run both count this universe.
- The pre-amendment readiness window was UTC. It dropped 401920686 (UConn–Wagner,
  2026-11-10T00:00Z = Nov 9 7 PM ET) and so reported 356 games where the dry run had
  357.

## 6. Amendment A1 (owner, 2026-10-06, before merge and before any 2026–27 outcome)

Overlap validation showed two things:

- ESPN reproduces every pipeline field on 1,391 completed games;
- SDV's current-season copy is stale on shared games.

So, for the **current season only**:

**A1a. Existence and identity.**

- A game SDV lists stays SDV-native (same game id).
- A game SDV does not list uses the ESPN fallback (S2, S3).

**A1b. Field-level reconciliation of shared games** (`schedule_completion.reconcile`).

- For a shared game whose ESPN latest observation is valid, these groups take ESPN's
  current value:

| group | fields |
|---|---|
| teams | home/away ids with their names and conference ids |
| tip | time with its `time_valid` and status detail (the TBD state) |
| other | neutral site, conference game, tournament id, season type, notes, venue |

- All are schedule-only fields validated identical in semantics on the completed season.
- Never reconciled: game id, season, game state and results (status, completion,
  scores, period). Those stay SDV's; the live game-state gate reads ESPN state directly
  (Wave 10).
- This is not a generic ESPN overwrite.

**A1c. Fail closed.**

- An ESPN observation that is not valid (missing a required field, or placeholder
  teams) leaves the SDV row as is (`unresolved`, reported).
- A reconciled matchup that collides with another game (same two teams, same ET date)
  is excluded (`ambiguous`, alerted).

**A1d. Audit.** Every disagreement stays visible in the report and in readiness, with its
resolution: `reconciled_to_espn`, `unresolved_sdv_kept` or `ambiguous_excluded`.
Matchup and orientation reconciliations alert (`SCHEDULE_IDENTITY_RECONCILED`,
`SCHEDULE_ORIENTATION_RECONCILED`).

**A1e. Historical.** No historical schedule is touched. The code path applies to seasons
≥ 2026–27 inside a prospective run only. Silver 2006–2027 without a completion file is
byte-identical to main (re-verified after A1).

**A1f.** C1 (rest days), G1 (refined) and §5 (canonical ET universe) as above.

## 7. FUTURE (inactive)

- **Identity data quality (from Wave 10, unchanged):**
  - T0333 Utah Valley "Tanner Davis" stays unresolved.
  - The frozen identity pool holds 38,169 players without D-I participation.
  - This is to be investigated separately. No alias is added, the pool is not
    restricted, and the table is not altered.
- **External pinger:** not added. Hourly catch-up stays the design.
