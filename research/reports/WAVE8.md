# WAVE 8 — Prospective roster validation + coverage closure (report)

Status on 2026-10-06. **No 2026–27 game has been played** (the first scheduled game in
the ESPN schedule is 2026-11-02). This report contains **no P-ROSTER-1 result**, and none
is invented. Everything below is pre-results work.

Preregistration: `research/hypotheses/WAVE8.md`. It adds descriptive diagnostics only.
The locked protocol remains `research/hypotheses/WAVE7.md` §7.

The report has five parts, kept separate:

1. pre-results work;
2. prospective observations;
3. frozen P-ROSTER-1 results;
4. exploratory diagnostics;
5. future hypotheses.

---

## 1. Pre-results work

### 1.1 Merge and freeze audit

**PR #7 and main CI**

* PR #7 merged as `9b0fbaedd1f5847b6f77f50f6ee16fc1d4fceb30`. Its tree is identical to
  the reviewed head `572c306`.
* Main CI on the merge commit: run 37406633287, success.

**Frozen files: sha256 recomputed, unchanged**

| file | sha256 |
|---|---|
| `models/overlays/p-roster-1.json` | `0d1b22ff…` |
| P-ROSTER-1 internal spec checksum | `c1464d5d…` (recomputes) |
| `research/hypotheses/WAVE7.md` | `847361b0…` |
| `pure-0.2.0` | `fb109b54…` |
| `pure-0.3.0` | `d5fbc78e…` |
| `pure-0.4.0` | `4a5a3cb7…` |
| `pure-0.5.0` | `9d255ed3…` |

**Wave 8 diff against main**

* No change to `models/pure/**`, `models/overlays/**` or `research/hypotheses/WAVE7.md`.
* No change to `research/reports/WAVE1–7`.
* No change to `cbb_edge/rosters/{overlay,rotation,truth,identity}.py`, `cbb_edge/app/**`
  or `cbb_edge/data/silver/**`.

**Archives**

* **roster-archive:** append-only. Wave 7 commits only added dated files. The single
  rewritten path is the designed pointer copy `ncaa_directory/latest_registry.json`.
* **projections-archive:** does not exist yet, because there are no 2026–27 games in
  the window.

**Market independence**

* `tests/test_official_rosters.py::test_roster_layer_never_imports_market_code` passes.
  It also covers the new `cbb_edge/rosters/prospective_score.py`, which builds no
  market column.
* The market column for the preregistered market gap is built in
  `scripts/prospective/score_proster.py`, downstream only.

### 1.2 Prospective scorer (ready before the first game)

**Pieces**

* `cbb_edge/rosters/prospective_score.py`: the scorer.
* `scripts/prospective/score_proster.py`: the command-line entry point.
* `.github/workflows/prospective-scores.yml`: runs daily Nov–Apr. It writes dated
  directories plus `latest_dashboard.md` to the new append-only `prospective-scores`
  branch.
* With no settled game it writes an empty scoreboard. That path was tested locally with
  the live SDV schedule: 0 completed games, 0 records, "Settled paired games: 0".

**What it computes**

* **Record selection.** Each version's latest record with `as_of` strictly before tip
  (WAVE7 §7).
* **Pairs.** Base `pure-0.5.0` and `pure-0.5.0+roster` on the same game. The incumbent
  `pure-0.2.0` is a reference column.
* **Per-game errors.** Signed, absolute and squared errors and log loss. The paired
  |e| and e² differences are kept per game in `paired_games.csv`, so any interval can be
  recomputed.
* **Primary tables.** Game 1 and games 2–3, plus the same slices by the confidence of
  the overlay-triggering side. Each table shows MAE, RMSE, bias, % improved, mean paired
  change, and the market gap when lines exist.
* **Intervals.** A day-clustered bootstrap 90% CI, shown only when N ≥ 20. **N is the
  first column of every table.**
* **Intermediate metrics (WAVE7 §7)** at T−7d / T−72h / T−24h / T−6h / latest: top-5,
  top-8, starters, minutes MAE, precision/recall, false-inclusion rate and current-player
  omission.
* **Diagnostics D1–D8** (WAVE8.md §3):
  * team game number 1 / 2 / 3, not pooled;
  * strata by confidence, continuity-adjustment bucket, newcomer quartile, returning
    share, transfer and first-D-I counts, freshness, disagreement, site, opponent quality,
    D-I opponent and snapshot age;
  * the frozen (a)/(b) component split;
  * estimated vs realized false inclusion;
  * rotation validation;
  * integrity.

**Integrity (L).** Every scored game carries:

* the projection file paths and sha256 hashes;
* the code SHA;
* the truth snapshot stamp, the sha256 of its truth and official evidence files, and the
  roster-archive commit;
* the checks `as_of` < tip, truth < `as_of` and rotation-in-record = snapshot rotation;
* first-commit times of the projection and truth files from the full history of the
  append-only branches. That is push time, independent of what the record states.

Because the archives are append-only, a post-tip page refresh can only add a later
snapshot. It can never alter the one a record points to.

**Provenance and determinism**

* **Provenance (new).** From this PR on, `refresh_and_project.py` adds
  `prospective.code_sha` (`GITHUB_SHA`) and `roster.truth_archive_commit` to new records
  after validation. Projections are untouched.
* **Determinism.** Two runs over the same inputs produce byte-identical outputs (tested).

### 1.3 Team universe

`models/rosters/d1_membership.csv` (sha256 `fc6ee89e…`) has 7,721 rows and is built by
`cbb_edge/rosters/membership.py`.

**Sources**

* **2006–2026:** the frozen pipeline's own `d1_membership` classification, read from
  silver. 334–365 teams per season (2021: 339, the COVID season). Every team's season
  count matches `teams.csv` `n_d1_seasons` (tested).
* **2026–27:** the NCAA directory, 365 members.

**Saint Francis (PA), T0293**

* Rows for 2006–2026 are kept. There is no 2026–27 row. Nothing was renamed or deleted.
* ESPN team 2598: `isActive: false`, group 51 (not a conference).
* The roster dashboard now lists it under "Not D-I this season" and no longer counts it
  as a STALE team.

**West Florida**

* The NCAA directory lists it as a 2026–27 member: org 11740, ASUN.
* **It now has an ESPN id: 2697**, "West Florida Argonauts", `isActive: true`, group 46
  (ASUN). Evidence:
  * the ESPN team endpoint (probe run 37408616872, sha256 `0b0cfb36…`);
  * the ESPN-derived SDV 2027 schedule, which lists 14 ASUN games for 2697 (asset
    sha256 `bddafb0c…`).
* It has **no canonical team id**. The frozen pipeline therefore treats its games as
  non-D-I, and the 2026–27 projections do not cover them. Assigning one is an owner
  decision (T-1).

**Reproducibility.** Historical seasons are reproducible from silver (`python -m
cbb_edge.rosters.membership --write`). The projection pipeline's own classification is
unchanged.

### 1.4 Roster coverage closure (no outcome-dependent fixes)

The probe was run from Actions (run 37408616872). Evidence is in
`roster-source-samples:20261006T032543Z/gaps`.

| team | Wave 7 failure | finding | action |
|---|---|---|---|
| Missouri (T0065) | home 404 | `www.mutigers.com` answers **404** (nginx behind Imperva). The registered host `mutigers.com` answers 200 and its roster parses **15 players, labelled 2026–27** | rule C4: after a `www.` 404, try the same registered host bare. Covered from the next capture |
| Arizona State (T0006) | routes 404 | `sundevils.com` is a Drupal hub. Its navigation data links the men's roster on `thesundevils.com` (JSON-escaped URL) | rule C1 (linked official host, deterministic) plus escaped-link reading. With the evidence applied, discovery parsed **13 players, labelled 2026–27**. Evidence committed to the registry |
| Alabama (T0155) | parser? | not a parser problem. The page's own server state is roster 748 "2026-27 Men's Basketball Roster": **0 players, 4 coaches, 12 support**. Akron and Abilene Christian, on the same platform, ship 15 players in the same structure | none. Correctly NOT_PUBLISHED; re-checked daily |
| LSU (T0050) | 4 players | the page data (`roster-773-players-list`) holds exactly 4 published players | none. Incomplete publication; stays below the 8-player minimum |
| Jacksonville (T0137), LIU (T0334) | 0 players | the 2026–27 roster pages list coaches only; the player container is empty | none. Not published |
| Little Rock (T0171) | robots | robots.txt (200) disallows our user agent | respected |
| CCSU (T0184), Tennessee Tech (T0305) | robots | robots.txt answers 405 | fail-closed; respected |
| Colgate (T0190), Omaha (T0349) | connection | robots.txt connection reset / closed | fail-closed; respected |

**Expected effect after merge** (not yet live: no branch code was run against the
production archive):

* Missouri and ASU each get an official roster.
* Each should become CONFIRMED if identity coverage ≥ 0.8, which the next live run will
  show.
* Projected CONFIRMED + LIKELY: 329 + 2 → up to 331 + 2 of 364 member teams with ids.

**Stale and other unresolved teams (snapshot 20261005T223610Z)**

* **STALE (14 members) and UNKNOWN (4):**

  | group | teams | reason |
  |---|---|---|
  | STALE, no fresh majority | T0050, T0065, T0137, T0155, T0171, T0184, T0188, T0209, T0225, T0260, T0305, T0334, T0349, T0369 | roster page not found or stale, plus ESPN not fresh |
  | UNKNOWN | T0096, T0138, T0306, T0319 | official identity coverage 0.79 / 0.69 / 0.67 / 0.31 < 0.8 |

* **Stale pages named by the owner.** No page is forced to CURRENT; they are re-checked
  daily.

  | team | page status | team confidence |
  |---|---|---|
  | Arkansas-Pine Bluff (T0170) | labelled 2025–26 | CONFLICTED |
  | Chicago State (T0188) | labelled 2025–26 | STALE |
  | CSU Fullerton (T0209) | labelled 2025–26 | STALE |
  | CSU Northridge (T0260) | labelled 2025–26 | STALE |
  | Prairie View A&M (T0268) | labelled 2025–26 | LIKELY (ESPN fresh) |
  | East Texas A&M (T0369) | labelled 2025–26 | STALE |
  | Lehigh (T0225) | no label, no new-player evidence (page UNKNOWN) | STALE |

* **UNKNOWN (owner list).** Western Illinois (T0319, 9 of 13 names unresolved), UTSA
  (T0306, 5 of 15), Old Dominion (T0138, 5 of 16) and Penn State (T0096, 3 of 14).
  * All four have CURRENT 2026–27 pages.
  * The cause: the pages list **no class year or previous school** for the unmatched
    names. A name with no exact D-I match therefore cannot be classified as
    `no_d1_history` under the frozen A4 rule, and stays unresolved.
  * Accent folding is already applied (Zečević → zecevic). That name is a freshman
    sharing a 2020 D-I player's name, hence unresolved.
  * The rule is left as frozen.
* **CONFLICTED (17).** Each has 1–2 players in a cross-source conflict. They are listed
  per player in `truth/<stamp>_conflicts.jsonl`. None is resolved silently.

**Identity impact (measured, never used to link).**
`scripts/prospective/pretip_diagnostics.py` reports:

* 144 names without an id across 102 teams: 138 unresolved, 6 conflicting.
* Only 12 have a same-name 2025–26 D-I player who is on no roster in the snapshot.
* Upper bound on expected-rotation minutes at stake: **39.5 of 72,800 (0.05%)**.
* One team exceeds 10 minutes: T0333, one name, up to 25 minutes per game.
* 73 names have no same-name D-I history at all.

The fail-closed rule therefore costs little rotation coverage, and no fuzzy matching
is adopted.

---

## 2. Prospective observations

None yet. No 2026–27 game has been played, and the projections archive starts with
the first in-window run (cron from 2026-11-01).

## 3. Frozen P-ROSTER-1 results

None yet. The first scoreboard appears on `prospective-scores` the morning after the
first settled game. The headline N, for game 1 and for games 2–3, will be read there
before any metric.

## 4. Exploratory diagnostics (pre-tip, no outcomes; snapshot 20261005T223610Z)

**Estimated BASE false inclusion** (pre-tip, separate from the realized metric):

* 148.0 of 200 game-1 minutes and 9.5 players per team (364 member teams) are on
  players the snapshot does not place on the team.
* By confidence: CONFIRMED 147.4, CONFLICTED 153.6, STALE 160.2, UNKNOWN 157.4,
  LIKELY 90.8.

**Continuity correction tail** (327 CONFIRMED teams, frozen formula, uncapped):

| \|adj\| | teams |
|---|---|
| < 2 | 183 |
| 2–4 | 99 |
| 4–6 | 37 |
| ≥ 6 | 8 |

* Summary: mean −0.65, median −0.43, p95 5.32, max 8.39.
* The largest corrections come from teams with near-zero returning share and 10–13
  first-D-I players expected to play (e.g. T0143: −8.39).
* This is a measurement, not a cap.

**Expected newcomers** (transfers + first-D-I with ≥ 4 expected minutes, per team):
quartiles 5 / 7 / 9, p90 12, mean 7.1.

**Risk carried from Wave 7, to be watched rather than fixed.** The first-D-I expected
count has a long tail, and its term drives most of the ≥ 6 bucket.

## 5. Future hypotheses (not tested; any of them needs its own preregistration)

* **P-ROSTER-2.** Any revision of the continuity terms, the newcomer term or the
  rotation. It must be trained without the 2026–27 games in the P-ROSTER-1 evaluation
  window (WAVE8.md §1).
* **Identity.** A deterministic attribute-based link (previous school + height + class +
  hometown) for same-name candidates. With 39.5 rotation minutes at stake, it has low
  priority.
* **West Florida.** A canonical id, plus a decision on whether its games enter the
  frozen pipeline (owner decision T-1).

---

## Cost (this wave)

| source | requests | paid |
|---|---|---|
| official athletics sites (probe) | 29 page requests + ≤ 17 robots.txt | $0 |
| ESPN public | 3 | $0 |
| NCAA directory | 0 (no refresh due) | $0 |
| SportsDataverse (GitHub release assets) | schedule, from the local dry run | $0 |
| Odds API / CBBD | **0 / 0** | **$0** |

**Total paid usage: $0.** All requests went through the chokepoint with robots.txt and
per-host spacing.
