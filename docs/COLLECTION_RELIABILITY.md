# Prospective collection reliability (audit 2026-11-13)

RESEARCH_ONLY, $0. No new runner, credential, paid service, model change or trading action. Nothing
here reconstructs a missing pregame forecast. Every proposed change is fail-closed and inactive until an
owner merges it.

## 1. Audit: scheduled vs. completed runs, 72 h to 2026-11-13T19:23Z

Run listings were read from the GitHub Actions API; archives from `projections-archive` and
`schedule-archive` (git history = push time). The numbers are reproducible with
`python -m cbb_edge.ops.collection_health --projections <pa> --schedule-archive <sa> --runs name=<json> ... --now 2026-11-13T19:23:00Z`.

| workflow | cron ticks expected | `schedule` runs GitHub created | production runs | longest gap |
|---|---:|---:|---:|---:|
| prospective-projections | 78 | 15 (19%) | 15 | 9.1 h |
| prospective-scores | 75 | 14 (19%) | 14 | 8.9 h |
| espn-line-capture | 144 | 11 (8%) | 11 | 8.6 h |
| availability-capture | 144 | 11 (8%) | 11 | 8.8 h |
| ops-watch | 72 | 10 (14%) | 10 | 9.0 h |
| market-research | 72 | 11 (15%) | 32 | 8.7 h |
| kalshi-capture | 288 | 11 (4%, all coalesced) | 177 (164 dispatched captures) | **1.6 h** |

Every completed production run succeeded. Runs were not failing; GitHub was **not creating** cron runs.
`workflow_dispatch` was delivered every time. That is why the self-chained kalshi-capture is the only
collector whose cadence held.

## 2. What the missed runs cost

**Pregame snapshots: no loss in the window, but close calls.** All 128 projected games that tipped in the
window have a pure-0.5.0 and a pure-0.5.0+roster record whose `as_of` is before tip and whose archive push
was before tip. The median lead was 2.8 h and the minimum 14 min (game 401921005: as_of 16:46:20, pushed
16:49:16, tip 17:00). The 38 ESPN games without a record are outside the projection universe (no team
appears in any record), not misses. The 30 h projection horizon is what absorbed the 9 h cron gaps.

**Season to date: one game already lost to Waves 14-16, and 23 near misses.** For game 401916315, the
latest pre-tip record had as_of 22:57:54, the tip was 23:00 and the push was at 23:01:34. The evaluators
selected the latest `as_of < tip` record and excluded the game unless it was provably pushed before tip, so
the earlier, safely frozen record no longer counted. (That game predates the Wave 14 registration boundary, so
it was never eligible anyway.) 23 of 495 tipped games had their freshest safe record less than 30 min before
tip. Section 6 describes the amended selection rule.

**Final scores: delayed, not lost.** 165 of 166 finals reached `schedule-archive`: median 4.3 h after tip,
p90 9.0 h, max 11.4 h. An ESPN final remains retrievable. Late finals only delay walk-forward training
(each fit uses finals observed before the forecast's `as_of`, as registered), and they delay scoring.

## 3. The Kalshi recovery bug (queued run with no jobs)

At 16:52:22 on 2026-11-13, kalshi-capture's chain step got `HTTP 502` from the dispatch API. GitHub had
nevertheless created run **43467050714**, with **0 jobs**. The retry created 43467085061. The orphan stayed
`queued` for 2.5 h or more. It did not hold the concurrency slot (later captures ran), but the market-research
stale-capture recovery counted any queued production run as "already waiting" and would not dispatch while
the orphan was within its 20-run listing. The chain kept running, so no capture was actually lost. The flaw
stayed latent. The same recovery step also read a failed run listing as "0 active" (fail-open).

`cbb_edge.ops.dispatch_guard` sets a conservative **30-minute** limit. A production run that is
queued, pending, waiting or requested for 30 min or more is stale and no longer blocks. An in-progress run
blocks until the job timeout plus 30 min. An unreadable listing or `createdAt` fails closed (SKIP). A false
"stale" verdict costs at most one extra dispatch, which the serialized concurrency group coalesces.

## 4. Changes in this PR

| change | effect | active without approval? |
|---|---|---|
| `cbb_edge/ops/dispatch_guard.py` + tests | stale-run classification, capture recovery, heartbeat decision | no (library only) |
| `cbb_edge/ops/collection_health.py` + tests | cron delivery, stalled queues, lost / pushed-after-tip pre-tip records, lead, finals latency; missing input = UNKNOWN | no (CLI only) |
| `cadence.freeze_guard` + `refresh_and_project.py --freeze-guard-min/--existing-archive` | default 0 = byte-identical behaviour; an unreadable archive projects UNGUARDED and reports `_freeze_guard.status` (never aborts, never drops) | no (opt-in flag) |
| `wave14.VerifiedPush` / `load_verified` (WAVE14.md 5a) | evaluation selects the latest record VERIFIED as pushed before tip; later unverified or post-tip records are quarantined, and selection falls back to that earlier record | yes, on the next `run_wave14.py` regrade (research only; identical result on the current archive) |
| market-research.yml: recovery uses `dispatch_guard capture-recovery` | orphan no longer blocks; listing failure now SKIPs | **needs approval (merge)** |
| kalshi-capture.yml: projections failover heartbeat step | at most one catch-up tick per 55 min when no production projections run exists; single attempt, `continue-on-error`, never affects the capture or chain | **needs approval (merge)** |
| prospective-projections.yml: `catchup` dispatch input; always fetch archive; `--freeze-guard-min 60` | dispatched catch-up ticks decide like cron ticks; an already-covered game tipping within 60 min (= job timeout) gets no new record, so its earlier record stays authoritative | **needs approval (merge)** |
| ops-watch.yml: `actions: read` + diagnostics step | report only (`continue-on-error`), copied to `ops-reports` | **needs approval (merge)** |

Replaying the heartbeat against the real 72 h listings gives 52 extra catch-up ticks (about 17 a day,
free on this public repository). The longest gap between projections runs drops from 9.05 h to
1.86 h, bounded by the capture chain's own gaps. Each catch-up tick also runs "Observe game states",
so finals land within about 2 h of a game ending instead of up to 11 h after tip.

## 5. Not changed (needs a separate decision)

* `panel_recovery_decision` (kalshi-market-panel) treats any queued panel run as active. A test asserts
  this for a 120-min-old queued run. It has the same orphan exposure, but its 90-min cooldown and hourly
  `schedule` fallback bound the impact. Changing it alters a tested contract.
* The chain's dispatch retry loop (`for i in 1 2 3`) can still create a duplicate run after a 502. This is
  now harmless (the orphan is ignored after 30 min). Removing the retry would trade liveness for tidiness.
* Coupling: the heartbeat lives in the capture chain. If that chain's circuit opens (3 consecutive failures),
  projections fall back to cron-only, today's behaviour. market-research's stale-capture recovery (now unblocked) still restarts the chain.
* The freeze guard changes which records get written, never how they are graded. Grading changed
  separately (section 6).

## 6. Evaluation selection and the freeze guard: what is and is not guaranteed

**Selection (WAVE14.md amendment 5a).** A frozen record at or after `PROSPECTIVE_FROM` can be selected only
if a verified manifest lists it and that manifest's server-side `pushed_by` is strictly before tip. The
evaluator takes the latest such record. A later record that was pushed at or after tip, or has no provable
push time, or is listed in no manifest, is **quarantined**: it is reported in
`wave14_results.json -> verified_push_selection` and is never selected. Evidence fetched later cannot move a
push time before the tip. Records before the registration boundary are selected as before: they are never
eligible and only train the challengers. The rule reads only provenance, never outcomes. On the
2026-11-13 archive it gives the same 23 eligible games, the same `as_of` for each, and the same verdict as
the old rule. The 107 quarantined post-boundary records per version come from manifests newer than the
committed provenance evidence. A regrade with `--fetch-evidence` verifies them.

**Freeze guard limits.** `--freeze-guard-min 60` holds back a new record only for a game that already has an
archived pre-tip record and tips within 60 min of this run's `as_of`. For those games the push happens inside the
60-min job, so it lands before tip or not at all. It guarantees **nothing** for:
* a game with **no** existing forecast. It is always projected, because this run is its only chance, and it
  can still be pushed after tip. The evaluator then quarantines that record and the game has no eligible
  forecast. That is correct: a forecast that cannot be shown to precede the tip is not a forecast;
* a game whose existing record has an unverifiable push. "Covered" means an archived `as_of < tip`,
  not a verified push. Because the archive is fetched before `as_of` and before tip, that record really was on
  origin before tip, but the evaluator still requires the provenance evidence;
* a run whose archive fetch failed. The guard reports `UNGUARDED_ARCHIVE_UNREADABLE` and does not act.
Post-tip publication is therefore prevented by the evaluator's quarantine, not by the guard. The guard only
reduces how many records end up quarantined.
