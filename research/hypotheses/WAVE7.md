# Wave 7 preregistration (2026-10-05, before the first full official-roster capture and before any 2026–27 game)

**Objective.** Get a trustworthy current roster for essentially every D-I men's
basketball team before opening day. Remove players who are no longer on the team from
the model's game-1 inputs, and put in the players who actually are, using
authoritative free basketball information only.

**Unchanged.**

* The incumbent is `pure-0.2.0`. `pure-0.3.0`, `0.4.0` and `0.5.0` are shadows.
  P-ROSTER-1 is a PROSPECTIVE_ONLY overlay on `pure-0.5.0`.
* No historical model is frozen this wave. Official 2026–27 rosters are never used to
  build historical arms.
* The Wave 4 prospective promotion rule alone decides promotion.
* PURE_BASKETBALL: market data never touches roster membership, roster confidence,
  expected rotation, player role, continuity or team prior.
* Cost: Odds API 0, CBBD 0, $0. Every request goes through
  `cbb_edge/data/http.py` → `cost_policy.authorize`.

Everything below is fixed now. Only rules that tighten may be added before
opening day. Nothing may be added after.

## 1. Universe and official domains (`cbb_edge/rosters/ncaa_directory.py`)

* **Source.** `web3.ncaa.org/directory/api/directory/memberList?type=12&division=I&sportCode=MBB`.
  * The directory web app calls this public JSON endpoint itself. It was found in the
    app's script bundle (`roster-source-samples`, 20261005T204013Z).
  * robots.txt does not disallow `/directory/`.
  * 2026-10-05: 365 members, `academicYear` 2027, each with an `athleticWebUrl`.
* **Team mapping.** Exact normalized name match, or a hand-verified alias keyed by
  NCAA org id (`models/rosters/ncaa_team_aliases.csv`). Nothing else.
* **Registry.** `models/rosters/ncaa_athletics_domains.json` is generated and
  checksum-pinned.
  * It is the only source of `cost_policy.SCHOOL_HOSTS`. A missing or modified
    registry fails closed.
  * A host shared by two members is an EXCEPTION.
  * A redirect target is added only from an observed redirect of the NCAA link,
    recorded with its evidence.
* **Cadence.** Refresh weekly September–November and monthly otherwise. Never per
  projection run.

## 2. Official roster pages (`discovery.py`, `parsers/`, `official.py`)

* **Politeness.**
  * At least 5 s between requests to any one host. The chokepoint's spacing is per
    host for this source.
  * robots.txt is consulted first. A robots.txt that cannot be fetched means
    disallow; a 404 means allow.
  * At most 6 page requests per site per run. A known roster URL costs one request.
  * Every redirect hop is authorized before it is requested.
* **Discovery order.**
  1. Links on the home page.
  2. The platform route.
  3. Conventional paths.
  4. One level of links from the men's basketball page.

  No search engine is used.
* **A page is a roster** when a parser finds at least 8 players.
* **Parsers.** SIDEARM (nextgen cards, classic list) first, then a header-driven
  table parser (PrestoSports and custom sites). They read only visible fields and
  never infer.
* **Page freshness** (`official.page_freshness`):
  * **STALE**: the season label is older than 2026-27, or more than 2 listed players
    already played 4 D-I seasons.
  * **CURRENT**: the season label is 2026-27, and the page is not STALE.
  * **PROBABLY_CURRENT**: no season label, but at least 1 listed player played
    2025-26 for a different D-I team (an incoming transfer). Not STALE.
  * **UNKNOWN**: otherwise.

  CURRENT and PROBABLY_CURRENT pages are fresh official evidence. STALE and UNKNOWN
  pages are not.

## 3. Identity (`identity.py`)

* **Exact match only. The order is fixed:**
  1. verified alias;
  2. same team's ESPN rows;
  3. unique in the D-I box-score history of the last 5 seasons;
  4. unique among all ESPN rows.
* **Rejected as `conflicting_identity`:**
  * a true freshman (FR, not redshirt) matched to an id that has D-I minutes;
  * two official rows of one team resolving to the same id.
* **Amendment A2.** A listed (redshirt) freshman with no exact name in D-I history or
  any ESPN listing is `no_d1_history`. He gets a synthetic id (`N:<team>:<name>`),
  counts as resolved and is classified `first_d1`. Any other unmatched name is
  `unresolved`.
* The team identity-coverage threshold stays at **0.80** (A1). It now counts
  `no_d1_history` as resolved.

## 4. Membership and confidence (unchanged thresholds)

* **Membership.** A fresh official roster defines membership. An ESPN-only player it
  omits becomes STALE and is logged (A1). Historical identities are never deleted.
* **Team CONFIRMED** requires all of:
  * at least 2 fresh independent groups, or a fresh official page;
  * official identity coverage of at least 0.80;
  * no player conflicted across teams.
* **Team LIKELY**: one fresh group covering at least 80% of listed players.
* **Team CONFLICTED / STALE / UNKNOWN**: as in Wave 6 and A1.
* **Source independence.** SportsDataverse is in the ESPN group. Corroboration counts
  only across groups.

## 5. Expected rotation (Amendment A3)

* **Shares** are water-filled to exactly 200 minutes, with no player above 40. The
  2015–2026 ranking is identical to Wave 6: top-5 0.816, top-8 0.880.
* **Positional bounds and a ≤ 3 per position starter rule were tested and rejected.**
  * Top-5 fell 0.816 → 0.802.
  * MAE rose 8.04 → 8.54.
  * Starter accuracy fell 0.777 → 0.769.
* **Per player:**
  * expected minutes;
  * P(rotation), from a calibration table on seasons ≤ 2014;
  * expected starter (top 5 by minutes);
  * usage role.
* **Membership rule.** For a CONFIRMED team, only CONFIRMED players (the official
  roster) enter. For other trusted teams, CONFIRMED or LIKELY players enter (the
  Wave 6 rule).
* **Sanity checks before games.**
  * 200 ± 1 minutes;
  * at most 40 for any player;
  * no duplicates;
  * no departed players;
  * 5 starters;
  * at least 5 players.

## 6. P-ROSTER-1 authority (unchanged)

* **(a) Input substitution** applies at games-seen 0 for CONFIRMED, LIKELY and
  CONFLICTED teams.
* **(b) Continuity correction** applies to CONFIRMED teams only. It uses the pinned
  coefficients (`models/overlays/p-roster-1.json`, unchanged). There is no cap and no
  rescaling.
* **Continuity audit before opening day.**
  * The distribution of (b) across CONFIRMED teams is reported: mean, median, p90,
    p95, max, and counts with |adj| above 2, 3 and 4.
  * Each |adj| > 3 must be explained by measured turnover: truth continuity vs the
    expected returning share, incoming transfer share, first-D-I players. If one is
    not explained, the roster truth is re-verified. It is never capped.

## 7. Prospective scoring (locked; reported weekly, never re-specified)

**Comparison.** `pure-0.5.0` vs `pure-0.5.0+roster`, on games where both have a
pregame record. Each version's latest record before tip is used.

**Slices.**

| slice | definition |
|---|---|
| game 1 | min(home, away games seen) = 0 |
| games 2–3 | min games seen in 1–2 |

The same slices are also reported by the overlay roster confidence of the side(s)
that triggered the overlay.

**Primary metrics** (game 1, then games 2–3):

* margin RMSE;
* margin MAE;
* log loss;
* market gap (benchmark only), defined as RMSE(model) − RMSE(closing-line implied
  margin) on games with a captured line.

**Intermediate metrics** (each team's first game, T−7d / T−72h / T−24h / T−6h /
latest archived state):

* top-5 recall;
* top-8 recall;
* starter accuracy;
* expected-minutes MAE;
* rotation precision and recall (≥ 10 minutes);
* departed-player false-inclusion rate;
* current-player omission rate.

**Departed-player false inclusion (the Wave 6 mechanism).** For a team's first game:

* A player allocated minutes by a rotation is **false** if he is not listed (played
  or DNP) in any of the team's first five games' box scores.
* Per team and rotation, report:
  * false players (count);
  * false minutes (40 × share);
  * false usage (Σ share × last-season usage share);
  * false value (Σ share × last-season player net rating).
* **BASE rotation.** Last season's full minute shares of the team, which is what
  `pure-0.5.0` uses at game 1.
* **ROSTER rotation.** The archived P-ROSTER-1 expected rotation.
* **Target.** ROSTER drives false minutes toward 0.

**Current-player omission.** The share of the team's first-game minutes played by
players absent from the rotation.

**Rule.** No metric here promotes anything or changes P-ROSTER-1's authority during
2026–27. The rules are not edited after opening week.

## 8. Coverage targets (operational, reported honestly)

| measure | target |
|---|---|
| official domains | ≥ 99% of D-I MBB teams |
| roster pages found | ≥ 95% |
| pages CURRENT / PROBABLY_CURRENT | as high as honestly possible |
| identity match for rotation candidates | ≥ 90% |
| teams CONFIRMED or LIKELY | ≥ 90% |

Unresolved teams are listed with a reason, never hidden.

## Amendment A4 (2026-10-05 ~21:50Z, after the first full live capture `20261005T212117Z`; before any 2026–27 game and before any P-ROSTER-1 outcome)

The first full capture found 349 official pages; 325 were fresh. Confidence stayed
low, with 72 teams CONFIRMED, 178 CONFLICTED and 76 UNKNOWN. Two defects caused this.
Fixing them changes no threshold: identity coverage stays at 0.80, and CONFIRMED,
LIKELY and CONFLICTED keep their definitions.

1. **Order of the membership rule.** Section 4 says a fresh official roster defines
   membership. The code applied that rule only after it had looked for cross-team
   conflicts.
   * The live snapshot had 481 transfers. Each appeared on his new team's official
     roster and on his old team's stale ESPN listing.
   * For 430 of them, the old team's own fresh official roster omits him.
   * Those ESPN listings are now set aside before conflicts are computed. The player
     is STALE (`absent_from_official`) on the old team and logged.
   * The 51 old teams with no fresh official page keep their conflicts. They stay
     CONFLICTED, as section 4 requires.
2. **Identity for players with no D-I history.**
   * Most of the 636 unresolved official names were JUCO, D-II, NAIA and international
     newcomers, or walk-ons. Examples: Ranger College, Fort Hays State, Dodge City CC,
     Daemen.
   * They have no D-I box-score trace by construction. Each still has to pass the same
     exact searches.
   * The rule changes below are tightened and documented. There is still no fuzzy
     matching:
     * **Name keys.** A quoted nickname or a parenthetical is dropped (`Samuel "Tobi"
       Ariyibi`). Periods and apostrophes are removed, so "D.J." = "DJ" and "D'Arcy" =
       "DArcy". History keys come from every name the box scores printed.
     * **First year.** "FY", "1st" and "First Year" count as freshman labels.
     * **No D-I history.** `no_d1_history` now also covers a player with no exact name
       in D-I history or any ESPN listing whose page lists a previous school that is
       not a D-I program, judged by exact normalized names of every program ever D-I
       in the lake (`identity.previous_school_is_d1`).
     * **Still unresolved.** An upperclassman with no previous school listed, or with
       a D-I previous school, stays `unresolved`.
     * **Namesakes.** A true freshman whose name matches a D-I player with minutes is a
       namesake (`no_d1_history`) when his previous school is not a D-I program.
       Otherwise he stays `conflicting_identity`.

**Effect, re-resolving the live official rows offline:**

| measure | before | after |
|---|---|---|
| unresolved names | 636 | 146 |
| conflicting identities | 45 | 9 |
| teams at ≥ 0.80 identity coverage | 270 of 349 | 344 of 349 |
