# Wave 6: pregame roster truth and the first-game problem

Preregistration: `research/hypotheses/WAVE6.md` (commit 65069de, before any Wave 6 arm
was evaluated). Reference: B25 = `pure-0.5.0`. Cost: Odds API 0, CBBD 0, $0. No market
quantity enters any PURE feature, roster decision, minutes estimate or adjustment.

## A. Verdict

**Did we materially improve pregame / first-game knowledge? We learned exactly where it
is, but historically we cannot use it yet.**

* **The ±2-point first-game bias is roster truth, not team estimation.**
  * Validation first games, team side, B25 error by realized departed minute share:
    +2.03 → −1.81 points across quintiles (corr −0.10).
  * The same quantity from P(return), which is known preseason: corr 0.001.
  * The departed players' VALUE does not matter (corr −0.03). The model simply does
    not know who is still on the team.
  * The bias decays slowly: slope −6.9 at game 1, −6.1 at game 2, −5.3 at games 3–4,
    −1.4 at games 12–21.
* **If the roster were known, the gain would be large.** ORACLE upper bounds use
  eventual participation, so they are NOT backtests:
  * input substitution (a): first-game RMSE −0.191;
  * continuity correction (b): first-game RMSE −0.192, games 2–5 −0.050, overall
    −0.0215, 2025–26 −0.014.
* **The free preseason roster data is not good enough yet.** ESPN's "2026-27" rosters
  are mostly last season's in content:
  * 82% of last season's minutes still listed, against a 42% historical norm;
  * 183 of 296 list ≥ 2 eligibility-exhausted players;
  * stats.ncaa.org rosters are behind a bot challenge;
  * school sites are fresh but have to be allowlisted one by one.
* **Historical arms.**
  * B26 (development), B27 (preseason-known continuity): not useful.
  * B28 (continuity revealed by games already played): −0.0257 overall and −0.089 in
    games 2–5, all 5 blocks, P = 1.00. But it is worse in 2024–25 and 2025–26 games
    2–5 (+0.014, +0.044).
  * B29 = B25 + B28 is REJECTED by the preregistered first-game gate (−0.010 vs −0.03
    required). **Nothing new is frozen.**
* **P-ROSTER-1** (a prospective overlay on pure-0.5.0, frozen spec, archived alongside
  the untouched base) is deployed.
  * It applies its continuity correction only to CONFIRMED rosters, because the ESPN
    evidence was shown to be stale.
  * Its value will be measured on 2026–27 games.

## B. Model state

| version | role | change |
|---|---|---|
| pure-0.2.0 | incumbent | none |
| pure-0.3.0, 0.4.0, 0.5.0 | shadow | none (artifacts and checkpoints hash-pinned) |
| pure-0.5.0+roster (P-ROSTER-1) | PROSPECTIVE_ONLY overlay | new, spec sha in `models/overlays/p-roster-1.json` |
| pure-0.4.0+avail (P-AVAIL) | PROSPECTIVE_ONLY overlay | none |

No promotion before the Wave 4 post-championship rule.

## C. Roster source audit

Full detail is in `docs/ROSTER_SOURCE_AUDIT.md`.

| source | coverage | status |
|---|---|---|
| ESPN site | 365 teams | stale for 69 by label, and in content for most others |
| ESPN core | 365 lists | identical to 2025-26 for stale teams |
| SportsDataverse | 354 teams, Last-Modified 2026-09-15, overwritten in place | ESPN copy |
| stats.ncaa.org | team list 365 | rosters blocked (Akamai challenge), not used |
| SIDEARM school pages | 3 allowlisted teams | fresh, official |

## D. Roster truth

`cbb_edge/rosters/truth.py`, with rules fixed before measuring any effect:

* four freshness tests:
  * season label;
  * copy of last season's core list;
  * eligibility-exhausted players listed;
  * older copy of a stale feed;
* independence groups, with same-feed supersession;
* player statuses CONFIRMED / LIKELY / CONFLICTED / STALE / UNKNOWN;
* exact-id or exact-name-same-team identity only;
* experience observed from box scores;
* append-only snapshots with first_seen / last_confirmed;
* a daily source-quality report.

**Amendment A1** (`research/hypotheses/WAVE6.md`). It was found by reading the first
live snapshot, before any 2026–27 game was played. It tightens the rules:

* the newest fresh capture of a feed defines that feed's team listing;
* a fresh official roster defines membership. ESPN-only players it omits are STALE
  and logged;
* an unmatched official name is classified `unknown`, not `first_d1`;
* a team whose official listing matches fewer than 80% of names to ESPN ids gets
  confidence `UNKNOWN`, and P-ROSTER-1 does not apply.

The first snapshot also exposed a code bug, fixed in the same PR. Classification was
merged on player id alone, so a player listed on two teams (one stale) got one team's
label on both: 78 trusted records showed a transfer as `returning`. It is now merged
per (player, team).

Tests: `tests/test_rosters.py`.

## E. Current 2026–27 rosters (local reconstruction, 2026-10-05)

From ESPN site + SDV: 183 teams LIKELY and 182 STALE. Player status: 3,157 LIKELY,
2,821 STALE.

**Live multi-source snapshot `20261005T171153Z`** (roster-capture, with amendment A1).
Sources: ESPN site, ESPN core, SDV and 3 school pages.

| source | teams current / listed |
|---|---|
| ESPN site | 201 / 365 |
| ESPN core | 201 / 365 |
| SDV copy | 129 / 318 |
| school sites | 3 / 3 |

Stale reasons:

* ESPN: 95 list eligibility-exhausted players; 69 still carry the 2025-26 label (ESPN
  core: copy of last season);
* SDV: 108 copies of last season.

| | count |
|---|---|
| teams CONFIRMED | 2 |
| teams LIKELY | 178 |
| teams STALE | 184 |
| teams UNKNOWN (official roster 5 of 16 names identified) | 1 |
| players CONFIRMED | 34 |
| players LIKELY | 2,850 |
| players STALE | 3,094 |
| players UNKNOWN | 12 |

The conflict log holds 13 entries:

* 12 unmatched official names. One is an ESPN name with a dropped diacritic, kept
  unmatched rather than fuzzy-matched;
* 1 ESPN-only player absent from the official roster.

No player is listed on two teams by fresh sources. That snapshot's classification
counts predate the per-(player, team) fix; later snapshots carry the fix.

## F. Player classification

* Classification comes from observed participation before the season:
  * returning: same team last season;
  * returning_after_gap;
  * transfer: last D-I team differs;
  * first_d1: no D-I minutes.
* Class strings are never used for this. 1,139 listed players carry a FR label despite
  D-I history (`class_label_conflict`).
* On the stale October data, classification accuracy cannot be scored yet. It is
  scored once rosters can be compared with game-1 participation (section N).

## G. Expected rotation

* **Model:** HistGradientBoosting (preregistered settings), retrained at run time from
  `models/rosters/rotation_train.parquet`.
  * Conditional on roster membership: P(minutes | on roster).
  * Features: previous minutes, starts, usage, rating, experience, position, transfer,
    origin strength, same-position depth.
* **Validation 2015–2024** (2025–26 in parentheses):

  | metric | model | naive (last season's minutes) |
  |---|---|---|
  | top-5 identification | 82.2% (79.2%) | 80.6% |
  | top-8 identification | 88.0% | 87.8% |
  | game-1 starters | 78.3% (74.3%) | 76.6% |
  | rotation recall (≥ 10 min) | 0.98 | 0.88 |
  | rotation precision | 0.83 | 0.88 |
  | minutes MAE | **7.4 min** (8.0) | 10.6 |

* **Prospective:** archived P-ROSTER states at T−7d / T−72h / T−24h / T−6h / latest,
  scored after each team's first game (`rotation_scorecard.csv`, weekly).

## H. Player development (DEV pairs, next season ≤ 2014; ×0.5 shrink applied in B26)

Raw mean next-season residual, next weak-RAPM − 0.95 × current, offence / defence
(negative defence = fewer points allowed):

| experience | low minutes | high minutes |
|---|---|---|
| 1 D-I season | +1.52 / −0.63 | +0.66 / −0.25 |
| 2 seasons | +0.85 / −0.20 | +0.82 / −0.20 |
| 3 seasons | +0.50 / +0.14 | +0.51 / +0.19 |
| 4+ seasons (pooled, n = 73) | −0.79 / −0.08 | −0.79 / −0.08 |

* Survivor selection inflates these values, hence the halving.
* As a model input, B26 is −0.0007 (P 0.83): not useful. Player development does not
  explain the experienced-roster residual; P(return)-weighted youth and experience
  have |corr| ≤ 0.02 with the game-1 error.

## I. Continuity-dependent carryover

* **B27** (preseason continuity via P(return)) is −0.0016 with blocks F4/F5 worse:
  not useful. Expected continuity carries no signal.
* **B28** (continuity revealed by players who have appeared) works strongly in
  validation. By games seen:

  | games seen | Δ RMSE |
  |---|---|
  | game 1 | −0.010 |
  | 2–3 | −0.078 |
  | 4–5 | −0.100 |
  | 6–10 | −0.035 |
  | 11–20 | −0.014 |
  | 21+ | −0.005 |

* B28 does not hold in 2024–25 or 2025–26: games 2–5 are +0.014 / +0.044, overall
  −0.004 / +0.007.
* **Answer:** previous-team strength does deserve less weight after major turnover.
  But only REVEALED turnover can be used historically, and its recent-season reversal
  must be understood before any freeze.

## J. Roster-derived team prior

P-ROSTER-1 (a) is the roster-derived prior, built from offence and defence separately:

* each listed player's frozen season-start priors (pure-0.5.0 provider; transfers
  carry their history);
* weighted by the expected rotation;
* used in place of last season's full roster, before game 1 only.

Both the substituted and the base `p_off` / `p_def` values are recorded.

## K. First-game bias: where it comes from

The decomposition was run on B25 errors:

* **Not the departed players' value:**
  * phantom value (corr −0.03);
  * development (|corr| ≤ 0.02);
  * expected continuity (corr 0.001).
* **The realized share of last season's minutes that is gone** (corr −0.10, ±2 points
  across quintiles), for ANY departing player.
* **Mechanism.**
  * At game 1 the player block uses last season's full roster (`rapm._prev_shares`).
  * The team prior uses P(return), which correlates only 0.40 with actual departures.
  * The stack's coefficients were learned on that noisy expectation, so it
    under-reacts to true turnover.
  * The bias then persists through the conference-schedule start, because the ratings
    update slowly (games 2–10).
* **Fix.** This is missing information, not a wrong coefficient. It needs preseason
  roster truth (P-ROSTER-1) or, historically, revealed participation (B28).

## L. Historical results (Δ vs B25, validation 2015–2024)

| arm | Δ | F1 | F2 | F3 | F4 | F5 | seasons < 0 | P(better) | game 1 | games 2–5 | Nov–Dec | Jan–Mar | log loss | total | 2024–26 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B26 | −0.0007 | −0.0025 | −0.0002 | +0.0010 | −0.0031 | +0.0007 | — | 0.83 | +0.002 | −0.007 | −0.003 | +0.001 | −0.0000 | +0.002 | +0.001 | not useful |
| B27 | −0.0016 | −0.011 | −0.009 | −0.007 | +0.016 | +0.005 | — | 0.76 | +0.021 | −0.013 | −0.002 | −0.001 | +0.0001 | +0.001 | +0.002 | not useful |
| B28 | **−0.0257** | −0.041 | −0.021 | −0.037 | −0.011 | −0.018 | 10 | 1.00 | −0.010 | **−0.089** | −0.051 | −0.010 | −0.0013 | +0.003 | +0.001 | useful |
| **B29** (= B25 + B28) | −0.0257 | same | | | | | 10 | 1.00 | **−0.010** | −0.089 | −0.051 | −0.010 | −0.0013 | +0.003 | +0.001 | **REJECT** (gate 5: first game ≤ −0.03) |
| ORACLE (b) | −0.0215 | −0.042 | −0.007 | −0.019 | −0.023 | −0.027 | — | 1.00 | **−0.192** | −0.050 | −0.054 | −0.001 | −0.0009 | 0.000 | −0.014 | not eligible |
| ORACLE (a) | −0.0098 | −0.012 | −0.015 | +0.001 | −0.011 | −0.013 | — | 1.00 | **−0.191** | −0.001 | −0.024 | −0.001 | −0.0003 | −0.002 | −0.024 | not eligible |

ORACLE (b) is evaluated on 2016–2024, because its expanding window needs one training
season.

## M. P-ROSTER-1 (`cbb_edge/rosters/overlay.py`, spec `models/overlays/p-roster-1.json`)

* **(a)** game-1 player block from the expected rotation over CONFIRMED / LIKELY roster
  players; the frozen artifact is re-applied unchanged.
* **(b)** a continuity correction, fitted on the ORACLE definition:

  ```
  6.75 × Δcontinuity + 0.99 × transfer_prev_share − 0.35 × first_d1
  ```

  * each term × 1 / (1 + gs / 3), home minus away, games seen ≤ 10;
  * the intercept (−0.04) is not applied;
  * only for CONFIRMED rosters.
* **Every record carries:**
  * the truth snapshot;
  * per-side confidence;
  * expected returning share and truth continuity;
  * projected returning / transfer / unseen minutes;
  * the top-8 expected rotation;
  * adjustments (a) and (b) and their total;
  * margin_base / total_base.

  Records are archived as `pure-0.5.0+roster`; base records are untouched.
* **Opening-day simulation** (2026-11-02, today's local truth):
  * 183 teams LIKELY, so (a) applies: SD 0.27 points.
  * 0 teams CONFIRMED, so (b) is not applied.
  * Without the CONFIRMED rule, (b) would have moved game-1 margins by up to ±6 points
    on stale ESPN content. The rule exists precisely for that.

## N. Game-1 rotation scorecard

No games yet. `prospective-benchmark` now writes `rotation_scorecard.csv` (top-5 /
top-8, minutes MAE, starters, precision / recall per snapshot) once teams play.

## O. Games 2–3 update

* Historically, B28 is the rapid game-1 → game-2 update: revealed participation is
  worth −0.078 in games 2–3 in validation.
* It reverses in 2024–26 and is not frozen.
* No faster-EWMA variant was tried: B28 already isolates the participation signal.

## P. Market gap (benchmark only)

Unchanged for the frozen models: pure-0.5.0 +0.097 overall, +0.501 in game 1
(`research/wave5/market.json`).

* B28 would remove roughly 0.010 of the game-1 RMSE gap.
* The ORACLE bounds (−0.19) are about 40% of the game-1 gap. True preseason roster
  knowledge is the largest single lever left.
* The P-ROSTER-1 market gap is measured prospectively (`proster_metrics.json`).

## Q. Prospective archives

| archive | status |
|---|---|
| `roster-archive` | ESPN snapshots, plus daily truth / P-ROSTER state / quality reports from this PR. Live since `20261005T164553Z` (pre-A1, kept as is: append-only) and `20261005T171153Z` |
| `availability-archive` | capturing |
| `espn-lines-archive` | capturing |
| `kalshi-archive` | capturing |
| `projections-archive` | starts with the first games; base, `+avail` and `+roster` records, append-only |

All four PURE versions project successfully on main (post-merge dispatch). Parity and
checkpoint tests pass.

## R. Market independence

* No market column is read anywhere in `cbb_edge/rosters`.
* Every frozen artifact's features pass the guard (`test_frozen_artifact_features_are_pure`).
* The P-ROSTER-1 spec is market-free (`test_overlay_spec_hash_pinned_and_market_free`).

## S. Cost audit

`cost_policy audit` is OK: Odds API 0, CBBD 0, $0. New sources are registered as
FREE_RATE_LIMITED with ≥ 5 s spacing:

* `ncaa_stats`;
* `school_athletics` (explicit host allowlist).

## T. Rejected / negative results

* B26 player development priors;
* B27 continuity from P(return);
* B29 (first-game gate);
* the stats.ncaa.org rosters (bot challenge);
* ESPN rosters as preseason truth in early October (content-stale);
* single-feed continuity corrections. The (b) inputs on ESPN-only data average 0.82
  continuity, which would bias every game-1 margin. Blocked by the CONFIRMED rule.

## U. PR

The PR and its CI status are listed in the handoff message.

## Next

* **Raise CONFIRMED coverage.** Verified official domains, one at a time; ESPN's
  refresh as November nears, tracked by the quality report.
* **Explain B28's 2024–26 reversal** (portal-era revealed-continuity semantics) before
  any freeze.
* **Score P-ROSTER-1 on 2026–27 games** with its preregistered prospective questions.
