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

**S1. SDV first.**

- A game SDV lists keeps its SDV row, unchanged.
- ESPN never overwrites an SDV row.
- When the two sources disagree on a material field of a shared game, the SDV row is
  used and a diagnostic is raised. Material fields:
  - season and season type;
  - teams and their orientation;
  - neutral site;
  - conference game;
  - tournament id;
  - status.

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

- Every row carries `schedule_source`: `SDV` or `ESPN_FALLBACK`.
- A fallback row also carries the ESPN `observed_at` it came from.
- Every projection record carries `schedule.source` and `schedule.source_observed_at`.
  The exact ESPN rows behind a run's fallback records are archived next to them
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

**C1. Rest-day context of SDV-native games.**

- Rest days (all versions) are computed from the whole season schedule.
- With the fallback, a team's games that SDV lacks now count, for 441 of the 1,629
  SDV-native games (38 of the 114 in Nov 1–9).
- Their own rows are unchanged. Their rest-day inputs are what a caught-up SDV would
  give, instead of the 7-day cap for a game SDV did not list.
- This is input completeness, not a model change.

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

**G1. Schedule identity changed.**

- Applies when a game's final schedule lists different teams from a base or P-ROSTER-1
  record made for it, or the same teams with home and away swapped.
- That record predicts another matchup, or a margin of the opposite sign.
- The game is **UNSCORABLE** (`schedule_identity_changed`; PENDING until settled) and is
  never paired with the result.
- Observed today on shared games: 4 matchups changed and 12 orientations swapped
  between SDV's build and ESPN's current listing.

The Wave 9 and Wave 10 gate checks are unchanged.

## 5. FUTURE (inactive)

- **Identity data quality (from Wave 10, unchanged):**
  - T0333 Utah Valley "Tanner Davis" stays unresolved.
  - The frozen identity pool holds 38,169 players without D-I participation.
  - This is to be investigated separately. No alias is added, the pool is not
    restricted, and the table is not altered.
- **Shared-game staleness:**
  - On shared games ESPN is fresher than SDV. Examples: Louisiana Tech's new Sun Belt
    games are flagged conference games on ESPN, not on SDV.
  - Preferring ESPN for shared games would change SDV-native inputs, so it is not done.
    It is an owner decision.
- **External pinger:** not added. Hourly catch-up stays the design.
