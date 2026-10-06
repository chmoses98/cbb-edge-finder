# WAVE 10 — Unknown tip times and final opening-day readiness (report)

Written 2026-10-06, before any 2026–27 game. This wave is operational only:

- no model, P-ROSTER-1, roster-confidence, rotation, continuity, identity or scoring
  definition changed;
- the rules it adds are recorded in `research/hypotheses/WAVE10.md` before any result.

## 1. PR #9 merge, main CI, freeze

**PR #9** was merged as `6c606084f1efe74a436a6b239070a6da7015a7b6`. Its tree is
identical to the reviewed head `a7a6685`.

**Workflows on main:**

| workflow | run | result |
|---|---|---|
| CI | 37415344194 | success |
| prospective-scores (dispatched) | 37415348860 | success |
| ops-watch (dispatched) | 37415352569 | success |
| roster-capture (dispatched) | 37415350742 | success |

The roster-capture run wrote truth snapshot `20261006T045352Z` (366 teams). Its only
change from the previous snapshot is **West Florida (T0374): CONFIRMED** (27 listed,
15 confirmed, school and ESPN groups fresh).

**Freeze audit** (after the Wave 10 commits; `git diff 6c60608..HEAD` is empty for
`models/`, the earlier `research/hypotheses/` files and the frozen roster modules):

| artifact | hash |
|---|---|
| WAVE7.md | `847361b0…` |
| WAVE8.md | `34f97ab7…` |
| WAVE9.md | `e71718b6…` |
| `p-roster-1.json` | `0d1b22ff…` |
| pure-0.2.0 | `fb109b54…` |
| pure-0.3.0 | `d5fbc78e…` |
| pure-0.4.0 | `4a5a3cb7…` |
| pure-0.5.0 | `9d255ed3…` |
| `player_identity_2026.parquet` | `3bd7b8ab…` |
| `player_aliases.csv` | `70400e4d…` |

Unchanged code:

- `pretip_gate.py`, `identity.py`, `overlay.py`, `rotation.py`, `truth.py` and
  `scorecard.py` are byte-identical to main.
- The projection code path for a game is unchanged. Only the set of games passed to it
  can grow, by TBD games with live not-started evidence (§3). It can also shrink, by
  games the live scoreboard shows started.

## 2. How ESPN represents unknown tip times (evidence)

Only pre-game scheduling metadata is used.

- **2026–27 SDV schedule, 1,629 games:**
  - `time_valid=false` covers exactly 1,520 games. All are listed at 00:00 ET, all have
    the detail "M/D - TBD", and all are `STATUS_SCHEDULED`.
  - `time_valid=true` covers 109 games, each with a real time. None is at midnight.
- **Completed 2023–24 to 2025–26, 18,866 games:** all `time_valid=true`, **0** listed at
  00:00 ET. A TBD placeholder is always replaced by a real time.
- **Live ESPN scoreboard, first observation `20261006T050839Z` for Nov 1–12:**
  - 629 games: 374 TBD, 255 announced, all `state=pre`, all `STATUS_SCHEDULED`.
  - Every TBD has `timeValid=false` and the detail "TBD".
  - The parser (`parse_scoreboard`) was validated on this real payload.
- **Later time updates.** The scoreboard is fresher than SDV. Of the 114 Nov 2–9 games
  both sources list, 27 that SDV still shows as TBD already have an announced time on
  the scoreboard. SDV shows no announced time that the scoreboard lacks.

So, evidence for each state:

| state | evidence |
|---|---|
| ANNOUNCED | `timeValid=true` |
| TBD | `timeValid=false` with a TBD detail; observed in both sources |
| PLACEHOLDER | `timeValid=false` without a TBD detail; never observed, kept only as a fail-closed bucket |
| UNKNOWN | field missing; never observed, kept only as a fail-closed bucket |

"Midnight" is never used as evidence. A genuinely announced midnight-ET tip has
`timeValid=true` and is ANNOUNCED.

## 3. TBD-safe pre-tip capture (`cbb_edge/ops/schedule_state.py`, `refresh_and_project.py`)

**The window.**

- The frozen rule is unchanged: listed tip in (as_of, as_of + 30 h].
- The narrowest extension: the projection run fetches the live scoreboard **after**
  fixing `as_of`.
- `live_window` then returns three sets:
  - **extra:** listed tip has passed, live `state=pre` with a pre-game status, ET date
    within the horizon, and a time that is not announced or is announced and still
    ahead.
  - **exclude:** any game the scoreboard shows in progress, halftime, final, delayed,
    postponed, cancelled, forfeit or in an unrecognised state. Excluded whatever its
    listing says, including a game still listed under its placeholder.
  - **unprotected:** listed tip has passed and there is no live observation (the fetch
    failed or the game is not listed). Not projected; counted in the run output.
- `window_override` applies the extra and exclude sets to every model's
  `project_window` call in that run. Outside the context the frozen selection is
  untouched (tested).

**Provenance.**

- Each record carries `schedule`: listed start, window reason (`listed` or
  `tbd_extra`), and the live observation.
- The run's observations go to `schedule_obs/<stamp>.jsonl` next to its records, in the
  same append-only commit.

**Never after tip.**

- A started game is excluded, and the exclusion is decided from evidence fetched after
  `as_of`.
- A delayed Actions run therefore cannot project a game that has begun.
- Earlier snapshots are never touched.

## 4. Tip-time history (`schedule-archive`, append-only)

**What is written.**

- ops-watch observes every hour: the scoreboard for today through +8 days, plus the SDV
  listing.
- Each projection run also observes its own window.
- Files: `obs/YYYY/MM/DD/<stamp>_<source>.jsonl`. An existing path is never written
  again.

**Bounded growth.** The archive keeps:

- every game's first observation;
- every change of start, time state or game state;
- unchanged, the scoreboard rows the gate needs: games with no announced time, not
  finished, whose date has arrived.

Each run's complete observation set is still used for that run's decisions. Measured:

- the full SDV listing is about 0.5 MB, and an hourly copy would add about 12 MB/day;
- the thinned archive adds only changes.

**`history()` per game:**

- first observed date and time and time state;
- whether it was ever TBD or a placeholder;
- every change with the time it was observed;
- the final announced tip and when it was first seen;
- the last "pre" observation and the first "started" observation.

The branch was created by run 37417021514 (commit `71e32e1`): 629 scoreboard and 1,629
SDV observations.

## 5. Game-start gate and scoring (`prospective_score.tbd_bounds` / `tbd_ambiguous`)

The independent, fail-closed signal is the live scoreboard game state. It is a free,
allowed source that availability capture already uses, through the HTTP chokepoint at
1 req/s. Only `state=pre` with a scheduled, pregame or TBD status counts as not started.

**Scoring:**

| final listing | rule | result |
|---|---|---|
| announced tip | the actual tip, as in Wave 9 | — |
| never announced | tip = the later of the placeholder and the last live `pre` observation (a provable lower bound on the start) | — |
| never announced, a required record exists (by `as_of` **or first commit**) only after that bound and before the first `started` observation | — | **UNSCORABLE** (`tbd_start_unprovable`; PENDING until settled) |

The gate's ten Wave 9 checks run unchanged on top. There is no post-game
reconstruction.

**Found during testing and fixed before commit.** A record whose `as_of` preceded the
bound but whose first commit came after it was reported INVALID (a commit-after-tip
integrity failure). Its start is unprovable, not corrupt, so it is now UNSCORABLE. It is
never VALID.

## 6. TBD failure simulations (`tests/test_tbd_tips.py`, 17 tests)

The system fails closed in every case.

| scenario | outcome |
|---|---|
| regular run missed, several hourly ticks missed | catch-up owes the TBD game while the scoreboard shows it pre; a finished game is never owed |
| live fetch failed entirely | nothing beyond the frozen rule; the passed-placeholder games are reported unprotected |
| tip announced late (7:30 PM, record made on game day under the placeholder) | VALID |
| tip moved earlier, still after the record | VALID |
| tip moved earlier, before the record | UNSCORABLE |
| tip moved later / postponed and replayed on another date | VALID; the latest record before the new tip is scored |
| game begins while still listed under the placeholder | excluded from projection; a record whose push may follow the start is UNSCORABLE |
| never-announced tip, no live evidence after the record | UNSCORABLE `tbd_start_unprovable` |
| never-announced tip, live `pre` after the push | VALID |
| record made before the placeholder date | VALID (a game cannot start before its date) |
| postponed, cancelled | never projected, never owed |
| duplicate / late snapshots | a post-start record never counts; the pre-tip record is scored |
| Actions delayed several hours | the delayed run cannot project a started game; the earlier record stands |
| archive overwrite | refused (`FileExistsError`) |
| SDV fetch failure inside observe | scoreboard observations still archived (`sdv_error` reported) |

The first Actions run surfaced the last case. The step read a sidecar the canonical SDV
copy does not carry, and `continue-on-error` hid the failure. It was fixed in
`6a608e4`.

## 7. Opening-week readiness (Nov 2–9) — and the one real operational problem

**Inputs.**

- `python -m cbb_edge.ops.readiness --days 9`, window **Nov 1–9**. Opening day is
  **Nov 1**: Villanova vs Notre Dame tips Nov 1 14:30 UTC.
- Roster snapshot `20261006T045352Z`.
- Schedule archive `71e32e1`, holding the first live scoreboard observation.
- The ops-watch run on the branch (37417449673, report `2026-10-06T051439Z`) shows the
  same picture for Nov 2–8.

**Results:**

| measure | games |
|---|---|
| games total (D-I vs D-I / all) | **356** / 473 |
| announced tip | 94 |
| TBD (no placeholder or unknown states observed) | 262 |
| valid pre-game snapshot available now | 0 (expected: projections start Nov 1) |
| baseline projection possible | 356 |
| P-ROSTER-1 eligible (a side with input substitution) | 356 |
| both sides CONFIRMED | 287 |
| **at risk of becoming unscorable** | **249** |
| operational reason for all 249 | on the live ESPN scoreboard but **missing from the SDV schedule** that drives projection |

Teams with a game in the window: 362.

| roster confidence | teams |
|---|---|
| CONFIRMED | 327 |
| CONFLICTED | 17 |
| STALE | 13 |
| UNKNOWN | 4 |
| LIKELY | 1 |

Of these, 352 have a valid expected rotation. P-ROSTER-1 input substitution covers 345
teams and continuity correction 326.

**The problem.**

- The SDV 2026–27 schedule release lists 1,629 games. It has been unchanged since at
  least 2026-10-04 22:01 UTC and was still the same at the 05:08 and 05:13 UTC fetches
  today.
- Every game it is missing has an ESPN id above SDV's maximum: 481 of 481 in Nov 1–12.
  SDV's last schedule build predates ESPN's creation of those games. It is lagging, not
  wrong.
- Wave 9 counted 103 games and 0 unscorable for opening week. That was built from SDV,
  so it could not see the gap.
- Before Wave 10, nothing would have reported such a game. The projection window,
  readiness and the scorer's expected-game list all read SDV. A game SDV never lists
  would be neither projected, alerted nor reported unscorable.

**What Wave 10 does (detection only; no projection-input change).**

- Readiness adds every live-scoreboard D-I game that SDV lacks to the games table
  (`in_schedule_source=false`, with a reason) and alerts:
  - `GAME_MISSING_FROM_SCHEDULE_SOURCE` (WARNING) while every missing game is more than
    30 h away. Today: 339 games, Nov 1–12.
  - `..._IMMINENT` (**CRITICAL**: ops-watch turns red) per game within 30 h of tip or
    started.
- The hourly ops-watch therefore shows whether SDV catches up, and fails loudly the day
  before any game would be lost.
- The readiness window now starts at the earliest tip in either source, which is Nov 1
  rather than Nov 2.

**Not done (owner decision R1).**

- Projecting games SDV does not list needs their rows in the projection input. The
  scoreboard carries everything those rows use: teams, start, neutral site, conference
  game. Those fields are now archived.
- Using the scoreboard as a second schedule source changes the frozen pipeline's source
  of record, so it is the owner's call.
- If SDV has not caught up when the alert turns CRITICAL, those games will be
  UNSCORABLE: visibly, not silently.

## 8. Rosters (normal automated refresh; no fuzzy matching, no bypass)

**Latest snapshot `20261006T045352Z`:**

| status | teams |
|---|---|
| CONFIRMED | 330 (+ West Florida) |
| CONFLICTED | 17 |
| STALE | 14 |
| UNKNOWN | 4 |
| LIKELY | 1 |

**Tracked schools: unchanged.**

- Alabama, LSU, Jacksonville and LIU: still STALE (`no_fresh_majority`). Their official
  pages still publish no full player list.
- STALE (14): Alabama, LSU, Jacksonville, LIU, Little Rock, Central Connecticut, Chicago
  State, Cal State Fullerton, Lehigh, Cal State Northridge, Saint Francis, Tennessee
  Tech, Omaha, East Texas A&M.
- UNKNOWN (4): Penn State, Old Dominion, UTSA, Western Illinois. Their official pages
  have no class labels or previous schools (WAVE9 FUTURE_HYPOTHESES).
- CONFLICTED (17): the same teams as in Wave 9.
- Between `20261006T042552Z` and `20261006T045352Z`, no team changed status other than
  the West Florida addition.

## 9. T0333 = Utah Valley

**The unresolved row.** Official name "Tanner Davis", class So., previous school
**Utah Tech**. Utah Valley is CONFIRMED with identity coverage 0.9375. At most about
25 expected-rotation minutes are at stake.

**Why it is unresolved.** The frozen identity pool (last 5 seasons) holds two players
with that exact name:

| id | team | evidence |
|---|---|---|
| P5314822 | Utah Tech (T0361) | 2025–26: 34 games, 879 minutes |
| P4706060 | **Northwest University (NAIA)** | one game, 27 minutes at Seattle U on 2021-12-22 (SDV player box 2022) |

The name is not unique, so `exact_history` correctly refuses to match.

**Is it a deterministic data defect?**

- Yes, in the table, not the algorithm. `scripts/data/build_player_identity.py` keeps
  every box-score row with minutes from games against D-I teams, including the
  non-D-I opponent's players.
- 38,169 of the 70,972 identity rows never played for a D-I team. The module documents
  the pool as "D-I players".

**What a D-I-only pool would change** (latest snapshot, counterfactual only):

- 11 of 138 unresolved rows would gain a unique candidate. Tanner Davis → P5314822 is
  one of them.
- Some of the 11 look like wrong namesakes. Examples: a sophomore from "Pebblebrook
  High School", and a redshirt sophomore from Barton Community College.
- 89 current matches point to never-D-I ids, 64 of them via `exact_history`. For
  example, the West Florida players resolve to their own ESPN ids from D-II games
  against D-I teams.

**Not changed.**

- The table is frozen in `models/rosters/manifest.json`.
- Changing it alters P-ROSTER-1 inputs league-wide, in both directions. That is not an
  obvious correction.
- Both remedies are listed as owner decisions (WAVE10 hypotheses §4):
  - a D-I-only pool (preregistered);
  - or a single hand-verified alias, step 1 of the frozen order. The previous school
    "Utah Tech" equals P5314822's team.

## 10. Market independence and cost

**Market independence.** No market data is read by any Wave 10 code. The new source is
the ESPN scoreboard's game state and schedule fields only (no odds fields are parsed).

**Cost.**

- Every request goes through `cbb_edge/data/http.py`, as `espn_public` at 1 req/s:
  - hourly ops-watch: about 9 scoreboard requests;
  - each projection run: about 3.
- Odds API: 0 requests.
- CBBD: 0 requests.
- Paid spend: $0.
- The cost-audit step passes in every run.

## 11. Contingencies documented, not implemented

**External pinger.** GitHub may delay or drop scheduled runs. The defences already in
place are:

- hourly catch-up ticks;
- ops-watch alerts (`WORKFLOW_STALE`);
- live evidence that prevents late projections.

If those prove insufficient, the contingency is an outside scheduler calling
`workflow_dispatch`, for example a cron service using a fine-grained token limited to
`actions:write` on this repository. That needs a new secret and an outside dependency.
**Not added; owner approval required.**

## 12. Files changed

- `cbb_edge/ops/schedule_state.py` (new)
- `cbb_edge/app/prospective.py` (`select_window` / `window_override`)
- `scripts/prospective/refresh_and_project.py`
- `cbb_edge/ops/cadence.py`
- `cbb_edge/ops/readiness.py`
- `cbb_edge/rosters/prospective_score.py`
- `scripts/prospective/score_proster.py`
- `.github/workflows/{prospective-projections,prospective-scores,ops-watch}.yml`
- `tests/test_tbd_tips.py` (new)
- `tests/test_ops_readiness.py`
- `research/hypotheses/WAVE10.md` (new)
- `research/reports/WAVE10.md` (new)
- `research/REGISTRY.md`
- `docs/PROSPECTIVE.md`
