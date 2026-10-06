# WAVE 8 — Prospective roster validation + coverage closure (preregistered)

Written 2026-10-06, before any 2026–27 game has been played (first scheduled game in
the ESPN schedule: 2026-11-02). Nothing in this file was chosen after seeing a 2026–27
outcome. This file **adds no decision rule** and edits nothing in
`research/hypotheses/WAVE7.md`.

## 1. What is frozen (verified at the start of the wave)

| artifact | sha256 |
|---|---|
| `research/hypotheses/WAVE7.md` (P-ROSTER-1 prospective protocol) | `847361b00ad34b696b8d02f7df8cc72aac3333d550c7dc5665860db4a2d0eca9` |
| `models/overlays/p-roster-1.json` (file) | `0d1b22ffc1e90bcf4cfa4c86153f75f5e9f1834d76ebc692e818a85f909b978c` |
| P-ROSTER-1 spec checksum (inside the file, recomputed) | `c1464d5dbb6e27f49b20431f84ba3f5d82071cad7d94df92fdacf4e6968ba1c1` |
| `models/pure/pure-0.2.0.json` | `fb109b5402a3c128b10e815c328e74fda1bb764850e1483042f4acb0e304b8c2` |
| `models/pure/pure-0.3.0.json` | `d5fbc78eda59d5448189d76837e5dda0f1d2073c02c94772cce3c39fffe1781a` |
| `models/pure/pure-0.4.0.json` | `4a5a3cb75a84498265fdc1e7a0df9ea6ade0526b1c18f163b7312cec4562beb4` |
| `models/pure/pure-0.5.0.json` | `9d255ed3710e4895acf925f40857f26cf3deb921d060a06a6514631050472e50` |

Merge of PR #7: `9b0fbaedd1f5847b6f77f50f6ee16fc1d4fceb30`. Main CI on it: run
37406633287, success.

**Unchanged in this wave, and unchangeable on the basis of 2026–27 results:**

* P-ROSTER-1 membership rules;
* the confidence thresholds;
* the expected-rotation algorithm;
* the continuity formula, its coefficients, and the absence of any continuity cap;
* the game-1 and games-2–3 scoring rules;
* the false-inclusion metric;
* the preregistered snapshot selection;
* the benchmark definitions.

The code paths are `cbb_edge/rosters/overlay.py`, `rotation.py`, `truth.py` and
`identity.py`, plus the frozen projection pipeline (`cbb_edge/app`,
`cbb_edge/data/silver`). They are not modified by Wave 8. The Wave 8 diff touches
none of the hashed files above.

If something looks wrong after games begin, it is recorded as evidence in the report,
never tuned away. A **P-ROSTER-2** may only be a separate future hypothesis with its own
preregistration. It must be trained without any 2026–27 game that is part of the
P-ROSTER-1 evaluation (its training data must end before 2026-11-02, or it must be
scored only on a later, disjoint window). P-ROSTER-1's record is never re-scored with
P-ROSTER-2 rules.

## 2. Primary analysis

WAVE7.md §7, verbatim, governs:

* `pure-0.5.0` vs `pure-0.5.0+roster`, each version's latest record before tip;
* slices: game 1 (min games seen = 0) and games 2–3 (min games seen 1–2);
* the same slices by the confidence of the overlay-triggering side(s);
* margin RMSE, MAE, log loss and market gap;
* the intermediate rotation metrics at T−7d / T−72h / T−24h / T−6h / latest;
* departed-player false inclusion and current-player omission.

The implementation is `cbb_edge/rosters/prospective_score.py`. It runs daily from the
`prospective-scores` workflow, writes to the append-only `prospective-scores` branch,
and has been in place since before the first game. `pure-0.2.0` (incumbent) is
carried as a reference column only.

Error convention: error = actual home margin − projected home margin. Paired
difference d = |e_roster| − |e_base|, so negative means P-ROSTER-1 was closer.

## 3. Wave 8 diagnostics (descriptive; declared now; none promotes or changes anything)

**D1. Team game number.** Every (game, side) is a team game numbered by that team's
games seen + 1. Tables are reported separately for team games 1, 2 and 3. They are
never pooled with each other or with the primary slices. A game appears under every
team-game number one of its sides has.

**D2. Sample size first.** Every table shows N before any metric. The paired 90%
interval is a day-clustered bootstrap: days in America/New_York, 2,000 resamples,
seed 20261106. It is reported only when N ≥ 20; below that the table says "n < 20".
Wave 8 states no conclusion from any table. The report says only what N is and
whether the interval excludes 0.

**D3. Strata** (game-1 rows; side attributes from the archived roster record and its
truth snapshot):

* roster confidence: CONFIRMED / LIKELY / CONFLICTED / STALE / UNKNOWN (plus `NONE` when
  the side has no roster record);
* |continuity adjustment of the game| (`adjustment_b_continuity`): `<2`, `2–4`, `4–6`,
  `≥6`, with lower bounds inclusive;
* expected newcomers: the count of `transfer` + `first_d1` players with share ≥ 0.10 in
  the archived expected rotation, in rank-based quartiles;
* returning-minutes share (`proj_min_returning` / 200), transfer count, first-D-I
  count;
* fresh source groups, ESPN and official freshness flags, and the counts of conflicted
  and dropped players (roster disagreement);
* site (home / away / neutral);
* opponent quality: the opponent's archived base net rating, adj_off − adj_def;
* D-I opponent: the opponent is a 2026–27 member in `models/rosters/d1_membership.csv`;
* snapshot age: hours from the record's `as_of` to tip.

**D4. Component split (no new ablation).** P-ROSTER-1 records its own components:

* `margin_base`;
* (a) `adjustment_a_input_substitution`;
* (b) `adjustment_b_continuity`.

The "(a)-only" margin is `margin_base + (a)`, a quantity the frozen spec itself
computes. The signed effect of (b) is |e_full| − |e_(a)-only|. No other counterfactual
is computed.

**D5. False inclusion, estimated vs realized.** These are reported separately:

* **Estimated (pre-tip):** BASE minutes on players whom the latest truth snapshot
  before the team's first tip does not place on the team (CONFIRMED / LIKELY).
* **Realized:** the locked WAVE7.md §7 definition, against the first five box scores.

Their agreement is reported as a correlation and a mean difference over teams.

**D6. Rotation validation** (evaluation only; the rotation algorithm is not changed).
Per team, against first-five-game participation (mean minutes per game):

* minute-weighted overlap, Σ min(actual, predicted) / Σ actual;
* the share of actual minutes on players in the predicted rotation;
* predicted minutes on players who did not play (DNP or not listed);
* top-5 and top-8 identification;
* game-1 starters.

The rejected positional bounds and the rejected starter rule stay rejected.

**D7. Continuity safety table.** For each game-1 game, report:

* (a), (b) and the base error;
* the (a)-only error and the full error;
* the signed effect of (b);
* each side's returning share and expected returning share;
* incoming-transfer prior share and first-D-I count.

There is no cap and no hindsight ablation.

**D8. Integrity.** Every scored game links to the following:

* the projection file paths and sha256 hashes;
* the code SHA (records written from 2026-10-06 on);
* the truth snapshot stamp;
* the sha256 of its truth files (records, teams, proster_state, freshness, conflicts)
  and official files (rows, pages, discovery);
* the roster-archive commit.

The checks are:

* `as_of` < tip;
* truth stamp < `as_of`;
* the record's top-8 rotation equals the snapshot's;
* the first-commit time of each projection and truth file is < tip, from the full
  history of the append-only branches.

A failed check is reported. The game stays in the table, flagged.

## 4. Coverage rules added in Wave 8 (outcome-independent)

**C1. Linked official host.** Discovery may find a men's basketball roster link on a
team's NCAA Athletics Link **home page** that points to another host. That host is
added to the team's registry row (`linked_hosts`, with evidence: from, to,
observed_at, page sha256) iff both hold:

* the linked host's second-level label contains the registered host's second-level
  label (at least 5 characters);
* the host is not any other member's registered host.

Until the registry carries it, the host is never requested (chokepoint). Links are
also read from JSON-escaped URLs in the page.

**C2. Season-aware D-I membership.** `models/rosters/d1_membership.csv` has one row per
(season, team):

* 2006–2026 come from the frozen pipeline's own `d1_membership` classification;
* 2026–27 comes from the NCAA directory.

No entity is renamed, merged or deleted. Saint Francis (PA) keeps its 21 seasons and
has no 2026–27 row. West Florida is a 2026–27 member, ESPN id 2697, with no canonical
id (owner decision). Coverage reports count only members.

**C3. No search engines, no bot bypass.** A robots.txt that disallows us, cannot be
fetched (405, connection reset), or a bot wall, is recorded and respected.

**C4. Bare host after a `www.` 404.** If the Athletics Link's `www.` home page answers
404, the same registered host without `www.` is tried once (e.g. `www.mutigers.com`
404 behind Imperva/nginx, `mutigers.com` 200). It is the same registered host, and
robots.txt is consulted for it.

## 5. Identity (unchanged rules)

Matching stays exact-only, in the Wave 7 order. Fuzzy or attribute-based linking is
not adopted in Wave 8. The impact of unresolved names on expected rotation minutes is
measured and reported (an upper bound from same-name D-I candidates not otherwise on
a roster). It is never used to link.
