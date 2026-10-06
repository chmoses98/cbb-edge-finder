# WAVE 10 — Unknown tip times (no new hypothesis)

Written 2026-10-06, before any 2026–27 game. Wave 10 is operational reliability only. It
**does not change** any of the following:

- the models;
- the P-ROSTER-1 rules;
- roster confidence;
- the expected rotation;
- continuity;
- identity;
- what is scored or how.

It fixes how the frozen pipeline handles games whose tip time is not yet announced. It
records that handling here before any result exists.

## 1. Frozen (verified after merging PR #9, `6c60608`)

All of these are unchanged in Wave 10:

| artifact | hash |
|---|---|
| WAVE7.md (P-ROSTER-1 protocol) | `847361b0…` |
| `models/overlays/p-roster-1.json` | `0d1b22ff…` |
| `pure-0.2.0` | `fb109b54…` |
| `pure-0.3.0` | `d5fbc78e…` |
| `pure-0.4.0` | `4a5a3cb7…` |
| `pure-0.5.0` | `9d255ed3…` |
| WAVE8.md (scoring definitions) | `34f97ab7…` |
| WAVE9.md (gate, catch-up, amendment A1) | `e71718b6…` |
| `player_identity_2026.parquet` | `3bd7b8ab…` |
| `player_aliases.csv` | `70400e4d…` |

No file under the following paths differs from `main`:

- `models/`;
- `research/hypotheses/` (other than this new file);
- `cbb_edge/rosters/{pretip_gate,identity,overlay,rotation,truth,scorecard}.py`.

## 2. Evidence: how ESPN represents an unknown tip time

From pre-game scheduling metadata only.

**2026–27 SDV schedule (1,629 games listed on 2026-10-06):**

| listing | games | detail |
|---|---|---|
| `time_valid` false | 1,520 | All listed at exactly 00:00 ET. Every status detail reads "M/D - TBD". Every status is `STATUS_SCHEDULED`. |
| `time_valid` true | 109 | A real time. None at 00:00 ET. |

**Completed seasons 2023–24 to 2025–26 (18,866 games):**

- Every game ends with `time_valid` true.
- **None** is listed at 00:00 ET.
- So a TBD listing is replaced by a real time before (or at) the game.
- A genuinely announced midnight-ET tip did not occur in three seasons. If one occurs,
  it is still recognised, by `timeValid`, not by the hour.

**Live ESPN scoreboard** (`site.api.espn.com`, already used by availability capture):

- It carries the same fields: `competitions[0].timeValid` and `status.type.{state, name,
  shortDetail}`.
- `state` is pre / in / post.

**States** (`cbb_edge/ops/schedule_state.py`; "midnight" is never used as evidence):

| state | evidence |
|---|---|
| ANNOUNCED | `timeValid` true |
| TBD | `timeValid` false, detail contains "TBD" |
| PLACEHOLDER | `timeValid` false, no TBD detail |
| UNKNOWN | no `timeValid` |

## 3. Rules (fixed before any 2026–27 game)

**R1. Projection window.**

- The frozen rule is unchanged: project D-I games whose listed tip is in (now, now + 30 h].
- *Addition:* a game whose listed tip has passed is also projected, but only if this
  run's live scoreboard (fetched after the run's `as_of`) shows **all** of:
  - `state` "pre" with a pre-game status (scheduled / pregame / TBD);
  - an ET date between today and the horizon;
  - a time that is not announced, or announced and still ahead.

**R2. Game-start exclusion.**

- A game the live scoreboard shows in any other state is **never projected**, whatever
  its listing says. This covers in progress, halftime, final, delayed, postponed,
  cancelled, forfeit and unrecognised states.
- A passed-placeholder game with **no** live observation is not projected (fail closed)
  and is reported.

**R3. Catch-up.** Coverage gaps follow R1 and R2.

**R4. Evidence.**

- Every run archives its live observations with its records.
- Each record carries its listed start, why it was in the window, and the live state.
- The append-only `schedule-archive` branch keeps the tip-time history and the
  not-started evidence.

**R5. Scoring (the gate is not loosened).**

- An announced final tip is the actual tip, as in Wave 9.
- When the final listing **never** announced a time, the start is unknown. The gate then
  uses the provable lower bound on the start as the tip: the later of the 00:00 ET
  placeholder and the last live observation showing the game not started.
- If a required record (base or P-ROSTER-1) exists only after that bound, by `as_of` or
  by first commit, and before the first observation showing the game started, the game
  is **UNSCORABLE** (`tbd_start_unprovable`). This is checked against both the record's
  `as_of` and its first-commit time.
- It is never guessed and never reconstructed after the game.

## 4. FUTURE_HYPOTHESES (inactive; owner decisions, none applied)

- **Identity pool restricted to D-I teams.**
  - The frozen identity table holds every player with box-score minutes in a game
    against a D-I team (2010–2026). That includes 38,169 players who never played for a
    D-I team, for example NAIA and D-II opponents.
  - Those namesakes block unique exact matches. One of them is Utah Valley's Tanner
    Davis (T0333).
  - Restricting the pool would change 11 unresolved rows and 89 current matches. Some of
    those changes are probably wrong namesakes.
  - Any change needs its own preregistration.
- **Verified alias** (step 1 of the frozen identity order): Utah Valley "Tanner Davis"
  → P5314822. The official page lists his previous school as Utah Tech, which is
  P5314822's 2025–26 team (879 minutes). This is an owner decision.
