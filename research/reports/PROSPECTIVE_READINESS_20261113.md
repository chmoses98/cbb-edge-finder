# Prospective-collection readiness audit (2026-11-13, ~17:50Z)

RESEARCH_ONLY. Read-only audit of main @ 115cb17 (PR #48 merged 16:35Z), draft PRs #49 (Wave 15) and #50
(Wave 16), and GitHub Actions run history. No code, schedule, runner, trigger, model or archive was changed.

## 1. Post-merge catch-up observation: NOT YET VERIFIED

* No scheduled `prospective-projections` run has fired since the merge. The last scheduled run is 43405211540
  (09:55Z, pre-merge code 06ce7c4); the schedule archive was last written at 10:00:29Z.
* Scheduler evidence (existing Actions records only): between 09:55Z and 17:50Z GitHub created 10 scheduled
  runs across all 15 workflows, against several hundred cron ticks. None at all fired between 13:27Z and 17:07Z.
  `prospective-projections` scheduled fires over the last 48 h were 21:21, 22:59, 04:08, 13:12, 21:03, 21:27,
  02:05 and 09:55, with gaps of up to about 9 h. This is GitHub dropping schedule ticks repo-wide. The
  workflow's triggers are not at fault, and nothing in the repository can fix it without a schedule or
  runner change.
* Static check: `.github/workflows/prospective-projections.yml` gates the observe step on
  `!cancelled() && event != pull_request` only, and `tests/test_workflows_parse.py` pins this. The step needs
  only `pip install` and the public scoreboard. A tick with `due=false` therefore skips projecting and still
  archives finals. This remains **unverified in production** until a real tick runs it.
* Gap tolerance: observe reads ET dates from yesterday to now+30 h (`back_days=1`). A date's finals are lost to
  the archive only if no tick of this workflow fires for roughly 24–48 h. The worst gap so far is about 9 h.

## 2. Wave 14

* Regraded locally from projections-archive 2664b10 and schedule-archive 7d00b8e. The result matches CI regrade
  run 43465158358: **23 eligible games**, all on ET 2026-11-12. The other post-boundary games are 57
  `no_verified_final_yet`, and 472 are `record_before_registration`.
* **Uncollected finals: 0.** All 57 pending games tip between 2026-11-13T20:00Z and 2026-11-14T16:00Z. None had
  tipped at audit time.
* Their eligibility also needs manifest 20261113T100153Z, which is unverified in the committed evidence. The
  CI regrade verifies it by fetching job records live, and it read 16 new job records in run 43465158358.

## 3. Waves 15 and 16 (draft PRs #49 / #50)

| check | result |
|---|---|
| frozen spec == code | `research/wave1{5,6}/spec.json` asserted by `tests/test_wave1{5,6}.py`; 31 / 30 tests (wave + shared + workflow) pass locally |
| shared module | `cbb_edge/research/challenger_eval.py` byte-identical on both branches |
| model pin | `MODEL_SHA` c4600f62… = `sha256` in `models/pure/pure-0.5.0.json` (unchanged since Wave 5) = `model_sha256` of all 80 post-Nov-12 `pure-0.5.0` and `pure-0.5.0_roster` records |
| prospective eligibility | today 0 eligible (552 `record_before_registration_or_missing`), as designed; window opens 2026-11-15T00:00Z |
| eligible path end-to-end | dry run with the boundary moved to the Wave 14 boundary (not committed): both waves grade the same 23 games as Wave 14 using real provenance |
| reproducibility | outputs are a deterministic function of the archives, the registered code and seed 20261113; only the status label reads the clock |
| CI | CI check runs on the PR heads succeeded; the shared regrade job ran `prospective_wave15.py` and `prospective_wave16.py` against verified provenance |
| registration anchors | heads acfcdf7 (#49, opened 16:40:53Z) and 4097be1 (#50, opened 16:41:02Z); GitHub-side PR and check-run timestamps predate the boundary |

Collection does not depend on CI or on the PRs being merged. Every input is written by production workflows on
main (projections-archive, schedule-archive, roster-archive). The regrade only reads.

## 4. Is deterministic reconstruction enough? Yes, with two conditions

Each challenger forecast is f(frozen base record, registered code, finals first observed at or before the
record's `as_of`).

* The base records are provenance-verified fail-closed against GitHub's own job records (`pushed_by < tip`).
* The function and its parameters are fixed before any eligible outcome exists.
* A separately frozen challenger stream would add no information the function does not already determine.

Conditions for the 2026-12-22 analysis:

1. **Code identity.** Run the analysis on code byte-identical to the registration heads. The procedure is
   `git diff acfcdf7 -- cbb_edge/research/{challenger_eval,wave15}.py scripts/research/prospective_wave15.py research/wave15/spec.json`
   (and the same for 4097be1 / wave16), and it must be empty. Any later push to these branches is visible in the
   PR timeline.
2. **Training-cutoff timestamps.** `available_at` of finals comes from schedule-archive file stamps, which are
   not separately provenance-checked. A wrong stamp could only change which games train `s`, `c` or the offset,
   never the frozen base forecast. Residual risk is low and is reported as a limitation.

No archive is needed. If the owner nevertheless wants an independently frozen challenger stream, the smallest
safe design is:

* A step in the CI regrade job, `push`-to-main only, that writes `waves_out/*_results.json` as new stamp-named
  files to an orphan `challenger-archive` branch, append-only, using the same push-retry pattern as
  schedule-archive.
* **Approval needed:** `contents: write` on the regrade job (currently `read`) and a new branch. No schedule,
  runner or credential change is needed. It would only run when main is pushed, so it is not a timely freeze
  either, which is one more reason the reconstruction route is preferred.

## 5. kalshi-capture: about 26 runs in 10 h

Window: runs 644–671, 07:22Z–17:26Z (10.06 h), 28 runs in total.

| class | runs | work done |
|---|---|---|
| self-chain `workflow_dispatch`, completed success | 24 | one snapshot each |
| self-chain in progress (671) | 1 | — |
| zombie dispatch 669 (queued since 16:52:22Z, **0 jobs**) | 1 | none |
| `schedule` ticks (647, 668), cancelled by the concurrency slot | 2 | none, a few seconds each |

* The run count is the self-chain working as designed (`CHAIN_WAIT_SECONDS=720`). The mean interval is about
  23 min against the 15-min target, so captures are not over-frequent.
* Truly unnecessary executions: **3 of 28** (2 cancelled schedule ticks and 1 zombie), and none consumed meaningful
  runner time.
* The real cost is idle runner time. In each successful job (job 132008494322, for example), the capture plus
  archive push takes about 3.5 min, while the chain step sleeps 12.4 min. That is about 77% of the job, or roughly
  300 of about 385 runner-minutes in the window. It keeps one concurrent runner slot busy around the clock. The
  repository is public, so this costs no money, but it competes with other jobs: run 667 waited 19 min in the
  queue while PR #48's CI was running.
* Latent defect, unfixed because it is capture behaviour: market-research's "Recover stale capture" treats any
  queued kalshi-capture as active, so a zombie such as 669 suppresses recovery for as long as it exists. The
  chain itself still dispatches (`supersede_pending_capture`), so there is no impact while the chain is alive.

Proposed minimal improvements, **not implemented** (they need authorization):

* (a) In the market-research recovery, ignore queued runs older than 30 min that have no jobs.
* (b) Optionally, have the chain sleep only until `previous capture start + 15 min` instead of a fixed 720 s.
  This keeps the cadence and trims idle time when the queue was slow.
* (c) Cancelling zombie run 669 is a one-off manual action and is harmless.

## 6. Can all three waves collect without manual intervention?

**Yes for collection**, provided GitHub keeps firing `prospective-projections` at least about once a day (the worst
gap so far is about 9 h).

* Wave 14 accrues automatically.
* Waves 15 and 16 start accruing at 2026-11-15T00:00Z with no action.
* The one manual step is the registered analysis itself: a regrade on each wave branch at or after
  2026-12-22T12:00Z, using push or `workflow_dispatch` with the code-identity check above.
* Remaining blocker: real production confirmation of item 1, which needs the first post-merge `due=false` tick.
