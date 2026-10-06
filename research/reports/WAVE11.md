# WAVE 11 — Schedule completeness rescue (report)

Written 2026-10-06, before any 2026–27 game. Rules: `research/hypotheses/WAVE11.md`.
This is not a model-development wave. No model, P-ROSTER-1, continuity, rotation,
identity, roster-confidence, scoring-definition or market logic changed.

## 1. PR #10 merge, main CI, freeze

**PR #10** was merged as `6165438e651acad03a98f2a356f1a298db78aef9` after all five checks
passed on `1573ec5`. The merge tree is identical to the reviewed head.

**Main, after the merge:**

| workflow | run | result |
|---|---|---|
| CI | 37511420962 | success |
| prospective-scores (dispatch) | 37511458733 | success |
| ops-watch (dispatch) | 37511463015 | success |
| ops-watch (first scheduled run under Wave 10 code) | 37511652414 | success |
| roster-capture (dispatch) | 37511467020 | success |

prospective-projections is scheduled from November only. Its main-branch heartbeat is
§12.

**Frozen hashes** (re-checked at the end of the wave, §13):

| artifact | hash |
|---|---|
| WAVE7 | `847361b0` |
| WAVE8 | `34f97ab7` |
| WAVE9 | `e71718b6` |
| WAVE10 | `4ec4b3b1` |
| `p-roster-1.json` | `0d1b22ff` |
| pure-0.2.0 | `fb109b54` |
| pure-0.3.0 | `d5fbc78e` |
| pure-0.4.0 | `4a5a3cb7` |
| pure-0.5.0 | `9d255ed3` |
| identity table | `3bd7b8ab` |
| aliases | `70400e4d` |

## 2. ESPN-vs-SDV overlap validation (B)

**Method** (`scripts/prospective/schedule_overlap.py`, ops-watch run 37512838613, report
`ops-reports/reports/2026/10/2026-10-06T184547Z/overlap.json`):

- It compares every SDV schedule field the pipeline reads, raw.
- It also compares the **silver games row** each source produces through the same
  transform (`silver.build.schedule_rows_to_silver`), which is the projection input.

**Completed 2025–26 season**

- 37 dates, 1,391 games: regular season, conference tournaments, NCAA tournament week,
  neutral sites, final scores.
- All 1,391 games are in both sources. No game is ESPN-only or SDV-only.
- **22 of 25 silver fields are identical on every game**: season, season type, tip time,
  ET date, neutral site, conference game, tournament id, both ESPN team ids, both
  conference ids, both scores, status, completion, periods and overtime count,
  `available_at`, notes, venue id/city/state.
- The other 3 fields are display names only, and no projection reads them:
  - venue name: 14 games (renamings, e.g. "Fant-Ewing Coliseum" → "b1Bank Fant Coliseum");
  - home name: 4 games;
  - away name: 8 games (e.g. "New Orleans" → "LSU New Orleans").
- This covers the settlement path: final scores, status and completion agree on all
  1,391 games.

**Current season**

- 161 dates. ESPN lists 5,857 games, SDV 1,629.
- 1,625 games are shared, 4,232 are ESPN-only, and 4 are SDV-only (listed by SDV, no
  longer by ESPN).
- On shared games, every difference is SDV staleness. SDV's build predates ESPN's
  updates:

| difference | games | detail |
|---|---|---|
| tip time | 253 | SDV still "TBD", ESPN announced |
| conference game | 18 | e.g. Louisiana Tech's new Sun Belt games: conference games on ESPN, not on SDV |
| tournament id | 8 | event games tagged since |
| neutral site | 5 | |
| teams: orientation swap | 12 | 11 neutral-site event games |
| teams: different opponent | 4 | e.g. 401911454: SDV South Carolina Beaufort vs Nevada, ESPN UC Santa Barbara vs Nevada |
| notes, venues, conference ids | — | |

**Per policy S1**, SDV's rows are kept for shared games, and each material difference
raises a diagnostic and alert (§9). No projection is tuned on any of this.

**Conclusion.** ESPN reproduces every schedule field the pipeline consumes, for
scheduled and for completed games. An ESPN-only row is therefore exactly the row SDV
will publish for that game.

## 3. Schedule-source policy implementation (A, C)

`cbb_edge/ops/schedule_completion.py`:

- `espn_rows` turns ESPN payloads into SDV-schema rows.
- `complete` applies SDV first, ESPN only when absent, and fails closed. Its reasons:
  `missing_required_field`, `teams_not_determined`, `ambiguous_reconciliation`,
  `duplicate_scheduled_game`. It also classifies disagreements.
- `completed_schedule` writes the run's fallback rows and its report.
- `source_map` gives each game's provenance.

Where the completed schedule is used:

- `silver.build.load_schedule` appends the run's fallback rows for the current season,
  SDV first again, then applies the unchanged transform.
- `cadence` (decide), `refresh_and_project` (projection), `readiness` and
  `score_proster` (results and schedule) all read the completed schedule.

The projection engine is untouched. A fallback game reaches `project_window` as an
ordinary silver row. Its projection math is the code path an SDV row takes, on
identical inputs (§2).

## 4. Historical safety (D)

**Silver.** Silver 2006–2027 was rebuilt from the same bronze with main's code (`6165438`)
and with the Wave 11 code, with no fallback file. All three tables are
**byte-identical** (`DataFrame.equals`):

| table | rows |
|---|---|
| games | 123,520 |
| team_games | 242,048 |
| player_games | 3,563,942 |

Every frozen historical projection therefore reads unchanged inputs.

**The fallback is prospective only.** It applies to seasons ≥ 2026–27 and only through a
prospective run's completion file. No historical game can switch source.

**Recorded consequence C1.**

- Inside 2026–27, rest-day context is computed from the whole schedule.
- With the fallback, 441 of the 1,629 SDV-native games (38 of the 114 in Nov 1–9) get
  the rest days a caught-up SDV would give. Example: a team that played two days
  earlier in an ESPN-only game is no longer capped at 7.
- Their own rows are unchanged. There are no 2026–27 records yet, so no archived
  projection differs.

## 5. Game identity and deduplication (E, J)

- **Key.** Reconciliation keys on the ESPN game id, which is SDV's game id: identical in
  every season, with 0 duplicates in 2024–2027.
- **SDV catch-up.** When SDV lists a fallback game, `complete` uses the SDV row from the
  next read. It is the same id, so no new game exists.
- **Same matchup under a different id.** If SDV or another ESPN-only id lists the same
  two teams on the same ET date, the game is excluded and alerted. It is never
  duplicated.
- **Archive.** Records already archived are never touched. Each keeps its own
  `schedule.source`.
- **Scorer.** The scorer selects one record per (version, game id), the latest before
  tip, and pairs one observation per game.
- **Tests:** `test_sdv_catch_up_reconciles_to_the_same_game` (T1 fallback → T2 SDV,
  same id, one game) and the dry-run catch-up in §8.

## 6. TBD compatibility (F)

- Fallback rows carry `time_valid` and the status detail, so ANNOUNCED / TBD /
  PLACEHOLDER / UNKNOWN are derived the same way for them.
- The Wave 10 live window, game-start exclusion and TBD scoring bound run on the
  completed schedule. A fallback game has no special path.
- A fallback TBD game is never treated as safer than an SDV one.
- In the dry run (§8), no record was made at or after any game's actual tip.

## 7. Pre-tip integrity (G)

The Wave 9 and Wave 10 gate checks are unchanged. Every fallback record needs the same
pre-tip evidence.

**Provenance on each record:**

| field | content |
|---|---|
| `schedule.source` | `SDV` / `ESPN_FALLBACK` |
| `schedule.source_observed_at` | when the ESPN row was observed |
| `schedule.listed_start` | the listed tip |
| `schedule.window` | `listed` / `tbd_extra` |
| `schedule.live` | game-state evidence |

The record's sha256 is in the run manifest. The exact ESPN rows behind the run's
fallback records are archived with them (`schedule_rows/<stamp>.jsonl`).

**What the scorer reports per game:**

- `schedule_source_at_projection`;
- `schedule_source_now`;
- `sdv_added_later`;
- `settled_from_espn_fallback`.

**New fail-closed rule G1 (tightening only).** A game whose final schedule lists
different teams, or swapped home/away, from a record made for it is UNSCORABLE
(`schedule_identity_changed`). Today this applies to 4 changed matchups and 12 swaps;
SDV may switch to ESPN's version when it rebuilds.

## 8. Full opening-window dry run (I, J)

<<DRY>>

## 9. Alert coverage (K)

| condition | alert |
|---|---|
| known ESPN D-I game absent from both sources | `GAME_MISSING_FROM_SCHEDULE_SOURCE` (WARNING), `_IMMINENT` (CRITICAL, ≤ 30 h) |
| unmapped ESPN team | `TEAM_ID_UNRESOLVED` (now over the completed schedule) |
| ambiguous reconciliation | `SCHEDULE_RECONCILIATION_AMBIGUOUS` |
| ESPN/SDV disagreement on identity | `SCHEDULE_IDENTITY_DISAGREEMENT` (CRITICAL ≤ 30 h), `SCHEDULE_ORIENTATION_DISAGREEMENT` |
| other material disagreement | `SCHEDULE_SOURCE_DISAGREEMENT` |
| duplicate scheduled game | `SCHEDULE_DUPLICATE_GAME` |
| incomplete fallback row | `SCHEDULE_FALLBACK_ROW_INCOMPLETE` |
| fallback game disappearing | `FALLBACK_GAME_DISAPPEARED` |
| projection missing despite a valid row | `EXPECTED_PROJECTION_MISSING`, `TIPPED_WITHOUT_PRE_TIP_PROJECTION`, `OPENING_GAME_MISSED` (all over the completed schedule) |
| fallback game near tip without a record | `FALLBACK_GAME_NO_SNAPSHOT_NEAR_TIP` (CRITICAL, ≤ 6 h) |

The ops-watch report has a **Schedule completeness** section, independent of roster
readiness. Each game in the games table carries `schedule_source` (`SDV`,
`ESPN_FALLBACK` or `ABSENT_FROM_BOTH`).

## 10. November 1–9 readiness (H)

<<READY>>

## 11. Rosters and T0333

- **Roster status.** Latest snapshot `20261006T121950Z`: CONFIRMED 330, CONFLICTED 17,
  STALE 14, UNKNOWN 4, LIKELY 1. No team's status changed in Wave 11. Alabama, LSU,
  Jacksonville and LIU are still STALE.
- **T0333 (Utah Valley).** Unchanged. Tanner Davis stays unresolved. The identity system,
  table and aliases are untouched. The data-quality finding is carried as FUTURE
  (WAVE11 §5).

## 12. Projection-archive heartbeat (N)

<<HEARTBEAT>>

## 13. Market independence, cost, freeze

- **Market independence.**
  - No market data is read.
  - `espn_rows` parses only schedule, status and score fields from the scoreboard. The
    odds block is never read.
  - Market data stays confined to `score_proster.market`, unchanged.
- **Cost.**
  - All requests go through the `cbb_edge/data/http.py` chokepoint (`espn_public`,
    1 req/s).
  - Hourly ops-watch: about 9 requests.
  - Daily full-season sweep: about 190.
  - Each projection run: 11 (rows) + 3 (live).
  - Odds API 0, CBBD 0, $0.
- **Freeze.** <<FREEZE>>
