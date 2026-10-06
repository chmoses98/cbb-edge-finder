# WAVE 9 — Preseason operational hardening (report)

Status 2026-10-06. **No 2026–27 game has been played.** This report has no model change
and no P-ROSTER-1 result. Every number below is operational. The dry-run scoreboards
are SYNTHETIC by construction and are not evidence. Preregistration and amendment:
`research/hypotheses/WAVE9.md`.

## 1. Merge, CI, freeze

**PR #8**

- Merged as `824c9db88fa81b296a76e55ff2a920be91b65e29`. Its tree is identical to the
  reviewed head `ec0db17`.
- Main CI run 37410474100: success.
- `prospective-scores` dispatched from main (run 37410486598): success. It created the
  `prospective-scores` branch, first scoreboard `scores/2026/10/2026-10-06T034602Z`,
  with "Settled paired games: 0".

**Frozen hashes, re-verified after the merge and unchanged by Wave 9**

| artifact | hash |
|---|---|
| WAVE7.md | `847361b0…` |
| `p-roster-1.json` | `0d1b22ff…` |
| P-ROSTER-1 spec checksum | `c1464d5d…` |
| `pure-0.2.0` | `fb109b54…` |
| `pure-0.3.0` | `d5fbc78e…` |
| `pure-0.4.0` | `4a5a3cb7…` |
| `pure-0.5.0` | `9d255ed3…` |
| WAVE8.md | `34f97ab7…` |
| checkpoint manifests | unchanged; the existing pinned-hash test passes |

**What Wave 9 changes in projection behaviour.** No model file, overlay spec, rule,
coefficient or scoring definition changes. Two infrastructure facts do change:

1. West Florida's 2026–27 games are now projected.
2. The 2026–27 D-I set is the NCAA directory list.

## 2. West Florida and the historical universe

**What changed**

- **T0374** was appended to `cbb_edge/data/ids/teams.csv`: ESPN 2697, "West Florida
  Argonauts", ASUN, first and last D-I season 2027.
- ESPN aliases were added. No id was renumbered. The ESPN team endpoint confirms 2697 as
  active in group 46 (ASUN).
- **Season gate.** `team_entry.csv` maps 2697 to T0374 only from 2026–27. West Florida
  appears as a D-II opponent in historical games (2006: 1, 2007: 2, 2008: 1, 2011: 1,
  2022: 1), and those rows keep no id.
- **Saint Francis (PA), T0293:**
  - untouched, with D-I seasons 2006–2026;
  - not a 2026–27 member;
  - out of the 2026–27 roster-capture universe;
  - listed apart in dashboards.
- **Authoritative membership.** For 2026–27 the D-I set is the NCAA directory's 365
  members. Every earlier season keeps the frozen games-count rule.
- **Universe and registry.** These were regenerated offline from the archived directory
  snapshot `20261005T221703Z`, with no new fetch. West Florida resolves by exact name
  and becomes VERIFIED (goargos.com). Its row is the only content change.
- **Membership table.** 2006–2026 rows are byte-identical to before; the 2026–27 West
  Florida row now carries T0374.
- **Registry refresh.** On the first production capture after merge, the directory
  refresh runs because the committed registry verifies a team the archived one does not.

**Reproducibility proof**

**Silver rebuild, old code vs new code, same bronze inputs:**

| table | rows 2006–2026 | identical |
|---|---|---|
| games | 121,891 | yes, hash `50d4857b…` both |
| team_games | 242,048 | yes, hash `7cf85c9a…` both |
| player_games | 3,563,942 | yes, hash `b4e6ff93…` both |

In 2026–27 exactly West Florida's 14 listed games change: team id NaN → T0374 and D-I
flag False → True.

**Projections, old vs new code**, all four frozen versions, at as_of 2026-11-02 14:10
and 2027-01-15 14:10:

- every common game is byte-identical (12/12 and 56/56);
- the only new projection is West Florida vs Jacksonville.

**Frozen checkpoints.**

- A checkpoint loads with a registry grown only by teams that entered D-I after its
  boundary. Such a team starts from the engine's own new-team rule.
- A full 2025–26 replay from the 2025 checkpoint, with and without the extra registry
  entry, changes existing teams' states by **at most 5.1e-7** points. That is solver
  tolerance, not behaviour.

## 3. End-to-end dry run (production code, simulated clock, sandbox archive)

`scripts/prospective/dry_run.py` runs `refresh_and_project.project_all` against:

- the real 2026–27 schedule;
- the real roster truth (`20261005T223610Z`);
- the frozen models and checkpoints.

It writes to a sandbox git repository that plays the append-only archive branch, then
settles games with SYNTHETIC results (seeded noise) and runs the production scorer and
gate. Two projection runs (Nov 1 21:10 and Nov 2 14:10 UTC) wrote 312 files.

| scenario | result |
|---|---|
| one game / 54 simultaneous games (Nov 1 21:10 → Nov 3 12:40 window) | 54 of 54 D-I games projected by all five versions, settled, VALID, scored; N shown first |
| neutral site | 6 neutral-site games VALID |
| confidence classes | VALID: CONFIRMED 50, CONFLICTED 4 in this window; all five classes covered by `tests/test_pretip_gate.py` |
| duplicate workflow execution | 0 files written, 61 skipped (identical); scoreboard byte-identical |
| scorer idempotence | two runs on the same inputs → byte-identical outputs |
| box score missing, then arriving, then corrected | headline metrics unchanged; realized false inclusion appears once the box exists |
| postponed / cancelled / tipped without a result | PENDING / excluded / PENDING (→ alert after 36 h) |
| no usable roster overlay (run without roster archive) | 54 UNSCORABLE (`no_pre_tip_record`) — never reconstructed |
| retry after failure, next regular slot only | 42 UNSCORABLE, 12 VALID |
| retry after failure, **hourly catch-up** | **54 VALID**; catch-up decision `full` (250 owed pairs), one hour later `skip` |
| partial push (base only), catch-up `missing_only` | 50 owed pairs → 50 records written (+ manifest), VALID |
| archived file edited after push | INVALID: `roster_archived_file_mutated; roster_hash_mismatch_vs_manifest` |
| only run comes after tip (missed cron) | games already tipped: UNSCORABLE |
| West Florida (Jan 16 vs Jacksonville) | all five versions projected; VALID; roster confidence UNKNOWN (no truth row before the first post-merge capture) |
| non-D-I opponent | not projected, not expected, not counted (none in this window; 5 in the opening week) |

Notes on two rows:

- **Retry, next slot only.** 42 of the 54 games carry ESPN's 05:00 UTC "time TBD"
  placeholder, so their listed tip passed before the next slot.
- **Partial push.** The 4 UNSCORABLE games tip after the 30-hour horizon of that
  scenario's single run.

**A bug the dry run found.** Every game first came out INVALID with
`hash_mismatch_vs_manifest`. The incumbent's legacy archive path (no version folder) is
a suffix of every other version's path for the same game and run, and manifest lookup
was by suffix. The fix uses exact paths, and a regression test was added.

## 4. Pre-tip evidence gate

`cbb_edge/rosters/pretip_gate.py`. Only **VALID** games enter any metric.

**Checks, all fail-closed:**

1. both records' `as_of` < actual tip;
2. truth snapshot < `as_of` and < tip;
3. truth and official evidence files exist, with sha256 equal to the hashes the
   projection stored before tip;
4. code SHA and roster-archive commit recorded;
5. record sha256 equals its run-manifest entry;
6. first-commit time of the records, truth records and official rows < tip;
7. no archived file modified or deleted after it was added;
8. no differing duplicate (version, game, as_of);
9. rotation in the record equals the snapshot's;
10. margin = margin_base + (a) + (b).

`tests/test_pretip_gate.py` covers each check:

- a full chain → VALID;
- a post-tip snapshot;
- missing code SHA;
- P-ROSTER-1 record only after tip → UNSCORABLE;
- replaced snapshot plus edited record;
- pushed after tip;
- a differing duplicate;
- all five confidence classes;
- a tip moved earlier → UNSCORABLE;
- unsettled and out-of-scope games;
- missing git history → INVALID;
- the legacy-layout regression;
- a component-sum mismatch.

**New provenance on records.**

- Each projection run writes `manifests/<stamp>.json`, which is also its heartbeat.
- P-ROSTER-1 records store `truth_files_sha256`.
- Projections are unchanged.

## 5. Workflow reliability and catch-up

**Observed in this repository.** The offseason Kalshi schedule (`23 */6`) should have
fired 5 times between repo creation and now. It ran **2 times**, at 14:49 and 00:06:
3 ticks dropped and the other 2 about 2.5 and 5.7 hours late. A schedule is not a
guarantee.

| workflow | trigger / frequency | last successful run | one tick missed | catch-up | duplicate runs | manual | ephemeral state |
|---|---|---|---|---|---|---|---|
| prospective-projections | 14:10 + 21:10 UTC Nov–Apr | PR run 37409554565 (Oct 6, no games in window); first scheduled tick Nov 1 14:10 | **now: hourly :40 tick runs the owed slot in full; any D-I game in the next 30 h without a record for a version gets just that record** | yes, never post-tip | harmless (existing files skipped, concurrency group) | yes | none (archive branches; data rebuilt each run) |
| roster-capture | 11:17 daily Sep–Nov; Mondays 12:17 Dec–Apr | dispatch on main, run 37413150136 (Oct 6) | hourly :47 tick re-runs the owed day | yes | harmless (append-only; state files are designed rewrites) | yes | none (`roster-archive` state/) |
| prospective-scores | 12:40 daily Nov–Apr | dispatch on main, run 37410486598 (Oct 6) | hourly :50 tick; the scorer recomputes everything from the archives, so a late run loses nothing | yes | harmless (dated directories; identical inputs → identical outputs) | yes | none |
| ops-watch (new) | hourly :25 Oct–Apr | first run on this PR | next hourly tick | — | harmless | yes | none |
| prospective-benchmark | Mondays (downstream, market) | not required for P-ROSTER-1 scoring | — | — | harmless | yes | none |
| espn-line-capture / kalshi-capture / availability-capture | every 30 min in season | not required for P-ROSTER-1 scoring (market gap only) | a gap removes market-gap rows only | — | harmless | yes | none |

**What can still lose an observation.** Every tick failing from a game's first
appearance in the 30-hour window until its listed tip. That is about 30 hourly ticks
plus 2–3 regular slots in a row. For a game with ESPN's "time TBD" placeholder, the
window closes at 00:00 ET of game day.

If that happens, `ops-watch` raises `OPENING_GAME_MISSED` or
`TIPPED_WITHOUT_PRE_TIP_PROJECTION` and turns red. The observation is UNSCORABLE and is
never reconstructed.

**Note on GitHub schedule suspension.** GitHub can disable schedules in a public repo
after 60 days without activity. The archive branches receive bot commits every day in
season.

## 6. November 2 readiness (live run on the current schedule and roster snapshot)

`python -m cbb_edge.ops.readiness` previews opening week before the opener. Run
2026-10-06 against snapshot `20261005T223610Z`, window Nov 2–9:

| question | answer |
|---|---|
| 1. teams with a game in the window | 142 (103 games, 98 D-I vs D-I) |
| 2. roster confidence | CONFIRMED 124, STALE 9, CONFLICTED 6, UNKNOWN 3 |
| 3. valid expected rotation | 137 |
| 4. identities sufficient (CONFIRMED / LIKELY) | 124 |
| 5. baseline projection possible | 142 |
| 6. P-ROSTER-1 input substitution / continuity correction | 130 / 124 |
| 7. currently unscorable | 0 |
| 8. why | — |
| tip time still TBD in ESPN (00:00 ET placeholder) | 87 of 103 games |

Alerts: 0 CRITICAL, 1 WARNING (`UNRESOLVED_IDENTITY_MATERIAL` T0333: up to 25.2
minutes).

The ESPN schedule is still partial, so the team count will grow as schedules are
published. The hourly `ops-watch` run keeps this report current on `ops-reports`.

## 7. Roster refresh and identity

**First production capture on merged code.** `roster-capture` was dispatched on main
`824c9db` (run 37413150136, success), producing snapshot `20261006T042552Z`. It also ran
the NCAA directory refresh, because the committed registry carried ASU's linked-host
evidence.

| measure | 2026-10-05 (Wave 8 final) | 2026-10-06 (first merged capture) |
|---|---|---|
| official roster pages found | 353 / 364 | **355 / 364** |
| CONFIRMED | 327 | **329** |
| LIKELY | 2 | 1 |
| CONFLICTED | 17 | 17 |
| STALE (members) | 14 | 13 |
| UNKNOWN | 4 | 4 |
| CONFIRMED + LIKELY over 365 members | 90.1% | **90.4%** |

**Movement.** Only two teams changed:

- **Missouri (T0065):** STALE → CONFIRMED. The `mutigers.com` page is CURRENT with 15
  players and identity coverage 1.0.
- **Arizona State (T0006):** LIKELY → CONFIRMED. The `thesundevils.com` page is CURRENT
  with 13 players and identity coverage 1.0.

Every other team stayed put (CONFIRMED 327, CONFLICTED 17, STALE 13, UNKNOWN 4,
LIKELY 1). Both Wave 8 fixes are verified in production.

**Still unresolved, documented, not forced:**

| team(s) | status | reason |
|---|---|---|
| Alabama (T0155) | STALE | its 2026–27 official roster still has 0 players (shell). No roster is fabricated |
| LSU (T0050) | STALE | 4 published players |
| Jacksonville (T0137), LIU (T0334) | STALE | coaches only |
| Little Rock (T0171) | not reached | robots.txt disallow, respected |
| CCSU (T0184), Tennessee Tech (T0305) | not reached | robots.txt 405, fail-closed |
| Colgate (T0190), Omaha (T0349) | not reached | connection reset, fail-closed |
| Arkansas-Pine Bluff, Chicago State, CSU Fullerton, CSU Northridge, Prairie View, East Texas A&M | stale page | pages labelled 2025–26 |
| Lehigh | stale page | unlabelled, no new-player evidence |
| Western Illinois, UTSA, Old Dominion, Penn State | UNKNOWN | identity coverage below 0.8 (no class or previous school on the page) |
| CONFLICTED teams (17) | CONFLICTED | per-player conflicts in `truth/<stamp>_conflicts.jsonl` |

- **West Florida** enters the roster universe with this PR: its domain becomes VERIFIED
  and the first capture after merge refreshes the registry.
- **Saint Francis** is out of the 2026–27 universe.

**Identity exposure (unchanged, exact-only kept).**

- 144 unresolved names across 102 teams.
- Upper bound on expected-rotation minutes at stake: 39.5 of 72,800 (0.05%).
- One team over 10 minutes: T0333, 25.2 minutes. `ops-watch` raises it as a WARNING
  (`UNRESOLVED_IDENTITY_MATERIAL`).
- No identity hypothesis is proposed: the exposure is not material.

## 8. Market independence and cost

**Market independence**

- The import-boundary test covers every file under `cbb_edge/rosters` (gate and scorer
  included).
- `cbb_edge/ops` imports no market code.
- The market column is still built only in `scripts/prospective/score_proster.py`.

**Cost**

| item | usage |
|---|---|
| ESPN | 0 new requests this wave |
| official athletics | one production roster capture: 377 page requests + robots.txt, per-host spacing (§7) |
| NCAA directory | 0 new fetches; regenerated offline from the archived snapshot |
| SportsDataverse release assets | schedule, local runs only |
| Odds API | 0 |
| CBBD | 0 |
| **paid** | **$0** |
| GitHub Actions | free for a public repository |

## 9. Rejected or deferred (not done on purpose)

- No coefficient, cap, threshold, rotation, position or starter change.
- No identity heuristic.
- No forced-current page.
- No hindsight counterfactual.
- No reconstruction of missed projections.
- No change to the frozen rule that projection covers listed tip > now. That decides
  TBD-tip timing; it is an owner decision.
- The FUTURE_HYPOTHESES in `research/hypotheses/WAVE9.md` stay inactive.
