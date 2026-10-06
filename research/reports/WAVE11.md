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

> **Superseded by §14.4** (pre-amendment run: SDV rows kept unchanged; no reconciliation scenarios).

**Setup.** `scripts/prospective/dry_run_w11.py`, synthetic outcomes, sandbox archive,
never evidence.

- The schedule universe is the real current one: the SDV file plus the archived ESPN rows
  of 2026-10-06.
- The production `project_all` runs at all **19 regular slots**, Oct 31 21:10 → Nov 9
  21:10 UTC: every active version, P-ROSTER-1, the Wave 10 live window and Wave 11
  provenance.
- Live game states follow a simulated clock. Each TBD game gets a seeded actual tip; 70 %
  are announced two days ahead, 30 % never.
- At **T2 = Nov 4 12:00 UTC**, SDV "publishes" every fallback game tipping later.
- Settlement runs through `score_proster.results_and_schedule` on the completed final
  schedule. Scoring runs `prospective_score.score` with the gate.

**Known D-I vs D-I games, Nov 1–9 (ET dates)**: 357, of which 107 were in SDV at the start
and 250 were ESPN-only.

| stage | SDV-native | ESPN fallback | total |
|---|---|---|---|
| known | 107 | 250 | 357 |
| in the completed schedule | 107 | 250 | 357 |
| base projection (pure-0.5.0) | 107 | 250 | 357 |
| P-ROSTER-1 projection | 107 | 250 | 357 |
| settled | 107 | 250 | 357 |
| pre-tip gate VALID | 107 | 250 | 357 |
| scored pair | 107 | 250 | 357 |

- **Gate:** 357 VALID, 0 INVALID, 0 UNSCORABLE. The scorer's game-1 headline N = 357
  (synthetic).
- **Every run succeeded.** No version failed. Records from fallback games:
  1 / 33 / 70 / 74 / 57 / 17 / 19 before T2, then 0, because SDV lists them all from T2.
- **TBD:**
  - 171 TBD games, 64 of them never announced.
  - The live window added 6–63 placeholder-passed games per run while they were
    positively "pre".
  - Started games were excluded: 1 … 449, cumulative.
  - **0 records were made at or after any game's actual tip.**
- **SDV catch-up (J):**
  - 8 games were projected first from the ESPN fallback, then from SDV after T2.
  - Each has **exactly one** scored row, and their schedule source is SDV now.
  - Their earlier records keep `ESPN_FALLBACK` provenance.
  - **0 archived files were modified or deleted** (`git log --diff-filter=MD`).
  - The fallback rows behind the records are archived (7 `schedule_rows` files).
- **Local state.** The working silver and bronze copies the dry run uses were restored
  byte-identical afterwards.

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

> **Superseded by §14.5** (pre-amendment run: UTC window, 356 games, SDV kept on disagreements).

**Inputs.** `python -m cbb_edge.ops.readiness --from 2026-11-01 --days 9`, run 2026-10-06
19:14 UTC on the real SDV file, the archived ESPN rows and roster snapshot
`20261006T121950Z`. The universe is SDV ∪ ESPN.

**Schedule completeness, season:**

| measure | games |
|---|---|
| SDV rows | 1,629 |
| ESPN-fallback rows | 4,158 |
| excluded fail-closed (all `teams_not_determined`: bracket placeholders, not games yet) | 55 |
| shared-game disagreements (SDV kept) | 46 |

**Window, Nov 1–9 UTC:**

| measure | games |
|---|---|
| D-I vs D-I games | **356** (473 including non-D-I opponents) |
| schedule source SDV | 107 |
| schedule source ESPN fallback | **249** |
| absent from both sources | **0** |
| announced tip | 94 |
| TBD | 262 (no PLACEHOLDER / UNKNOWN listings observed) |
| team mapping | every team resolves (no `TEAM_ID_UNRESOLVED`) |
| baseline projection possible | 356 |
| P-ROSTER-1 eligible | 356 |
| both rosters CONFIRMED | 287 |
| pre-tip capture | no snapshot yet (projections start Nov 1, 00:40 UTC catch-up / 14:10 slot) |
| **at risk** | **0** |

The dry run counts 357 because it windows on ET dates rather than UTC.

**Alerts: 0 CRITICAL, 46 WARNING**, all shared-game disagreements (SDV kept):

| kind | count |
|---|---|
| field | 30 |
| orientation | 12 |
| different opponent | 4 |

Two of them are in the window:

- 401909532 (Nov 7): ESPN has a tournament id; SDV has none.
- 401911532 (Nov 2): home/away swapped. If SDV flips it before settlement, rule G1 makes
  the game UNSCORABLE instead of mis-scored.

**Target met:** no game is absent merely because SDV has not published it, and there are
zero silent drops.

## 11. Rosters and T0333

- **Roster status.** Latest snapshot `20261006T121950Z`: CONFIRMED 330, CONFLICTED 17,
  STALE 14, UNKNOWN 4, LIKELY 1. No team's status changed in Wave 11. Alabama, LSU,
  Jacksonville and LIU are still STALE.
- **T0333 (Utah Valley).** Unchanged. Tanner Davis stays unresolved. The identity system,
  table and aliases are untouched. The data-quality finding is carried as FUTURE
  (WAVE11 §5).

## 12. Projection-archive heartbeat (N)

Pending (unchanged by A1): a single `prospective-projections` dispatch from main after this PR is merged (owner approval). It must be a no-window run that writes a manifest-only heartbeat.

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
- **Freeze.** After the last Wave 11 commit every hash in §1 is unchanged. `git diff 6165438..HEAD` is empty for `models/`, WAVE7–WAVE10 and `cbb_edge/rosters/{pretip_gate,identity,overlay,rotation,truth,scorecard}.py`.

## 14. Amendment A1 results (owner amendment, 2026-10-06, before merge)

Rules: `research/hypotheses/WAVE11.md` §5–§6. All numbers below supersede §8 and §10.

### 14.1 Policy implemented

- **Existence and identity stay SDV-first.** A game id SDV lists stays SDV-native
  (`schedule_source = SDV`). A game id SDV lacks uses the ESPN fallback (S2, S3).
- **Field-level reconciliation of shared games** (`schedule_completion.reconcile`). It is
  not a generic overwrite. Named groups take ESPN's latest valid observation of the same
  game id:

| group | fields |
|---|---|
| teams | `home_id`, `away_id`, `home_location`, `away_location`, `home_conference_id`, `away_conference_id` |
| tip | `date`, `start_date`, `time_valid`, `status_type_short_detail` |
| neutral_site | `neutral_site` |
| conference_competition | `conference_competition` |
| tournament_id | `tournament_id`, `season_type` |
| notes | `notes_headline` |
| venue | `venue_id`, `venue_full_name`, `venue_address_city`, `venue_address_state` |

- **Never reconciled:** `game_id`, `season`, status name/state/completed, scores, period.
- **Provenance per row:**
  - `schedule_source` (base source, `SDV`);
  - `reconciled_fields` (the groups ESPN supplied);
  - `reconciliation` (per field `{sdv, espn}`, plus `_teams` with its kind:
    `orientation_swap`, `different_teams` or `team_metadata`);
  - `source_observed_at` (the ESPN observation's timestamp).
- Every projection record carries these under `schedule.*`. The ESPN rows behind each
  record are archived in `schedule_rows/<stamp>.jsonl`.
- **Fail closed:**
  - ESPN observation not valid (required field missing, placeholder teams) → SDV row
    kept, reported `unresolved_sdv_kept`;
  - reconciled matchup colliding with another game (same teams, same ET date) → game
    excluded, `ambiguous_excluded`, alerted.
- Every disagreement stays in the completion report and in readiness with its
  resolution.

### 14.2 Historical invariance and rest days

- **Historical.** Silver 2006–2027, built with the amended code and no completion file,
  is byte-identical to main `6165438`:

| table | rows |
|---|---|
| games | 123,520 |
| team_games | 242,048 |
| player_games | 3,563,942 |

- The code path applies to season ≥ 2027 with a completion file only.
- **Rest days (approved consequence C1).**
  - `cbb_edge/features/context.py` has no diff against main.
  - Rest-day inputs change for 639 of 1,629 SDV-native games (45 in Nov 1–9).
  - Every change is attributed to a schedule event:
    - 452 to a newly included fallback game before them;
    - 187 to a reconciled tip (their own or the previous game's);
    - **0 unexplained.**
  - A schedule-input correction, not a methodology change.

### 14.3 ESPN/SDV reconciliation of current-season shared games

| measure | frozen snapshot (SDV `bddafb0c`, schedule-archive `ad1f26a`) | Actions overlap run 37528044729 (fresh fetch, 20:43 UTC) |
|---|---|---|
| shared games | 1,625 | 1,625 |
| exact | 1,371 | 1,301 |
| reconciled to ESPN | 254 | 324 |
| — tip | 204 | 272 |
| — notes | 37 | 48 |
| — venue | 41 | 43 |
| — teams (swap / different / metadata only) | 35 (12 / 4 / 19) | 35 (12 / 4 / 19) |
| — conference game | 18 | 18 |
| — tournament id | 8 | 8 |
| — neutral site | 4 | 5 |
| unresolved (SDV kept) | 0 | 0 |
| ambiguous (excluded) | 0 | 0 |

- All 47 material disagreements in the Actions run resolve `reconciled_to_espn`. One
  changes the game's ET date. They stay listed in `overlap.json` with SDV and ESPN
  values.
- The completed 2025–26 season (1,391 games) still differs only in display and venue
  names.

### 14.4 Full dry run with A1 scenarios (synthetic, never evidence)

`scripts/prospective/dry_run_w11.py`, 19 slots Oct 31 21:10 → Nov 9 21:10 UTC, exit 0.
Silver and bronze were restored byte-identical afterwards.

| stage | SDV-native | ESPN fallback | total |
|---|---|---|---|
| canonical known (ET) | 107 | 250 | **357** |
| in the completed schedule | 107 | 250 | 357 |
| base projection | 107 | 250 | 357 |
| P-ROSTER-1 projection | 107 | 250 | 357 |
| settled | 107 | 250 | 357 |
| gate VALID | 106 | 250 | 356 |
| scored pair | 106 | 250 | 356 |

The one UNSCORABLE game is the designed scenario. No version failed.

| scenario | game | records (matchup) | reconciled | gate |
|---|---|---|---|---|
| pure SDV, no disagreement | 401909694 | 3 × T0028 v T0027 | — | VALID |
| fresher ESPN tip | 401902275 | 3 × T0180 v T0149 | tip | VALID |
| home/away disagreement (real) | 401911532 | 3 × T0350 v T0307 (ESPN orientation) | teams, notes, venue | VALID |
| opponent change (SDV stale) | 401909738 | 3 × T0007 v T0014 | teams | VALID |
| neutral-site reconciliation | 401909750 | 3 | neutral_site | VALID |
| conference reconciliation | 401909751 | 3 | conference_competition | VALID |
| tournament reconciliation (real) | 401909532 | 3 | tournament_id, tip, notes | VALID |
| ESPN fallback game | 401913099 | 3, source `ESPN_FALLBACK` | — | VALID |
| fallback later appearing in SDV | 8 games | fallback records then SDV records | — | 8 VALID, one scored row each, 0 archive mutations, 19 `schedule_rows` files |
| TBD game | 401902277 | 3 | tip | VALID |
| matchup change before any projection | 401911305 | 3 × corrected matchup | teams | VALID |
| matchup change after a projection snapshot | 401911335 | T0164 v T0004 ×2, then T0164 v T0143 | teams | VALID (latest pre-tip record matches) |
| matchup change after the last pre-tip projection | 401911345 | 3 × T0352 v T0007; final T0352 v T0176 | — | **UNSCORABLE** `schedule_identity_changed` |
| duplicate workflow execution | slot 2026-11-02T14:10 | 0 written, 628 skipped | — | — |

- **TBD:** 235 TBD games, 64 never announced; **0 records made at or after an actual
  tip.**
- **Final reconciliation** (after the synthetic SDV catch-up): 5,694 shared, 469
  reconciled, 0 unresolved, 0 ambiguous.

### 14.5 Opening-window readiness on one frozen as-of snapshot

**Inputs:**

- `python -m cbb_edge.ops.readiness --sdv-file <SDV bddafb0c> --schedule-archive <ad1f26a> --now 2026-10-06T18:45:00Z --from-date 2026-11-01 --days 9`;
- roster snapshot `20261006T121950Z`;
- window 2026-11-01T04:00Z → 2026-11-10T05:00Z (ET dates).

Per-game detail: `research/reports/WAVE11_nov1_9_games.csv` (357 rows).

| measure | games |
|---|---|
| D-I vs D-I games (all opponents) | **357** (478) |
| set-equal to `canonical_universe` | yes |
| schedule source SDV / ESPN fallback | 107 / 250 |
| reconciled SDV games in the window | 35 (tip 27, notes 7, venue 7, teams 2, tournament 1) |
| absent from both sources | 0 |
| excluded fail-closed in the window | 0 (season: 55, all `teams_not_determined`) |
| announced / TBD | 122 / 235 |
| baseline projection possible | 357 |
| P-ROSTER-1 eligible | 357 |
| both rosters CONFIRMED | 288 |
| at risk | **0** |

**Alerts: 0 CRITICAL, 16 WARNING.**

- 12 are `SCHEDULE_ORIENTATION_RECONCILED` and 4 are `SCHEDULE_IDENTITY_RECONCILED`, all
  resolved to ESPN.
- The only one in the window is 401911532 (orientation, Nov 2).
- Against the targets:
  - zero silent drops;
  - zero unexplained differences;
  - zero matchup or orientation inputs knowingly stale: every disagreement is
    reconciled to ESPN's latest observation.

### 14.6 356 vs 357

- **Game:** 401920686, UConn–Wagner, listed 2026-11-10T00:00Z = Nov 9, 7:00 PM EST.
- **Why the counts differed:**
  - The pre-amendment readiness window was `[Nov 1 00:00Z, Nov 10 00:00Z)` (UTC), which
    excludes this game.
  - The dry run counted ET dates, which include it.
- **Fix:** both now use `ss.et_midnight` and `ss.et_window_end` (DST-aware) and the one
  `canonical_universe`.
- **Canonical Nov 1–9 universe: 357 D-I vs D-I games** (107 SDV + 250 ESPN-only).
- **Regression tests:**
  - `test_canonical_universe_uses_eastern_dates`;
  - `test_readiness_window_equals_the_canonical_et_universe` (SDV + fallback ==
    canonical).

### 14.7 Matchup/orientation integrity gate (G1, kept)

- The latest pre-tip record of a version is the scored one.
- If its teams or orientation differ from the final resolved schedule, the game is
  UNSCORABLE (`schedule_identity_changed`; PENDING until settled) and never paired.
- A1 makes this rare, because records follow ESPN's current matchup. The dry run shows
  both sides:
  - a correction before the last pre-tip record → VALID;
  - a correction after it → UNSCORABLE.

### 14.8 Freeze audit (after A1)

- Every §1 hash is unchanged.
- `git diff 6165438..HEAD` is empty for:
  - `models/`;
  - WAVE7–WAVE10;
  - `cbb_edge/rosters/{pretip_gate,identity,overlay,rotation,truth,scorecard}.py`;
  - `cbb_edge/features/`, `cbb_edge/model/`, `cbb_edge/players/`.
- `cbb_edge/rosters/prospective_score.py` adds only the G1 gate check
  (`identity_changed`). The metrics are unchanged.
- WAVE11.md is amended (A1, recorded in its §6) before merge and before any 2026–27
  outcome.
