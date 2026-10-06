# WAVE 9 — Preseason operational hardening (no new hypothesis)

Written 2026-10-06, before any 2026–27 game. Wave 9 **does not change the model, the
P-ROSTER-1 rules or the preregistered scoring**. It makes the frozen experiment run by
itself, reproducibly, and fail loudly instead of losing or manufacturing an observation.

## 1. Frozen (verified after merging PR #8, `824c9db`)

These hashes are unchanged in Wave 9:

| artifact | hash |
|---|---|
| WAVE7.md (P-ROSTER-1 protocol) | `847361b0…` |
| `p-roster-1.json` | `0d1b22ff…` (spec checksum `c1464d5d…`) |
| `pure-0.2.0` | `fb109b54…` |
| `pure-0.3.0` | `d5fbc78e…` |
| `pure-0.4.0` | `4a5a3cb7…` |
| `pure-0.5.0` | `9d255ed3…` |
| WAVE8.md | `34f97ab7…` |

The following are not changed:

- the continuity coefficients;
- a continuity cap (still none);
- the confidence thresholds;
- the expected rotation;
- positional bounds and starter rules (still rejected);
- the identity rules (exact only);
- the record selection (latest record before tip, per version).

## 2. Team universe (infrastructure, not a model version)

**West Florida.**

- New canonical id **T0374**, appended. No existing id is renumbered.
- It maps ESPN 2697 **only from 2026–27** (`cbb_edge/data/ids/team_entry.csv`). In
  2006–2022 it was a D-II opponent and keeps no id there.

**Saint Francis (PA), T0293.**

- It is unchanged, with history 2006–2026.
- It is not a 2026–27 member.

**D-I membership.**

- A season with an authoritative NCAA list (2026–27) uses that list as its D-I set.
- Every earlier season keeps the frozen games-count rule.
- Silver rebuilt with the old and the new code is **identical for 2006–2026** (all
  three tables). In 2026–27 only West Florida's 14 listed games change.

**Frozen checkpoints.**

- A boundary checkpoint loads with a registry grown only by teams that entered D-I after
  its boundary.
- Such a team starts from the engine's own rule for a team absent from the previous
  season (`walkforward.priors_from_previous`).
- Pre-season projections for every other game are byte-identical. In-season, existing
  teams' states differ only within solver tolerance: at most 5.1e-7 rating points over
  the full 2025–26 replay.

## 3. Pre-tip evidence gate (scoring integrity; no change to what is scored)

Only **VALID** games enter any metric.

| status | meaning |
|---|---|
| VALID | every check in `cbb_edge/rosters/pretip_gate.py` passes |
| INVALID | a pre-tip record exists but a check fails |
| UNSCORABLE | no pre-tip record for a required version; never reconstructed |
| PENDING | not settled |

Every game is judged against the schedule's **actual** tip.

## 4. Catch-up cadence (no change to what is scored)

Hourly catch-up ticks run a workflow only when one of these holds:

- a regular slot passed without a run;
- for projections, a D-I game tipping in the next 30 hours has no record for a
  required version.

Catch-up never projects a game that has tipped. When only a coverage gap is owed, it
writes only the missing (version, game) records. The scored record is still each
version's latest record before tip.

## 5. Amendment A1 (presentation only; made before any 2026–27 game)

WAVE8.md D2 shows the day-clustered bootstrap interval when N ≥ 20. A cluster bootstrap
over very few days is degenerate: the Wave 9 dry run had 54 games on 2 days.

The interval is now shown only when **N ≥ 20 AND the games span ≥ 10 distinct days**.
Otherwise it is suppressed and labelled. No metric, slice or decision changes.

## 6. FUTURE_HYPOTHESES (inactive; none implemented, none to be tuned on 2026–27 results)

- **Identity:**
  - Deterministic attribute matching (previous school + height + class + hometown)
    for same-name candidates.
  - Current exposure is ≤ 39.5 of 72,800 expected-rotation minutes, of which one team
    (T0333) carries ≤ 25 minutes.
  - It is proposed only if that exposure becomes operationally material. It needs its
    own preregistration.
- **Pages without class labels:**
  - Some official pages list no class year or previous school, which leaves unmatched
    names unresolved instead of `no_d1_history`.
  - Affected teams: Western Illinois, UTSA, Old Dominion, Penn State.
  - Any rule change needs its own preregistration.
- **P-ROSTER-2:**
  - Any revision of the continuity terms, the newcomer term, a cap, or the rotation.
  - It must be trained without the 2026–27 games in the P-ROSTER-1 evaluation window
    (WAVE8.md §1).
- **Projection timing for games with an ESPN "time TBD" placeholder (00:00 ET):**
  - The frozen projection step only projects games whose *listed* tip is in the future.
  - For such a game, the last chance is the evening before.
  - Changing that is a pipeline change: owner decision, not Wave 9.
