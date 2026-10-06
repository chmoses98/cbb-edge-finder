# Wave 7: official roster truth for the D-I universe

**Preregistration.** `research/hypotheses/WAVE7.md`, written before the first full
official-roster capture. Amendments A2–A4 come from reading roster data only. Each is
dated, made before any 2026–27 game, and made before any P-ROSTER-1 outcome existed.

**Model state.** Unchanged. **Cost.** Odds API 0, CBBD 0, $0.

**Reference snapshot.** `roster-archive`, truth snapshot **`20261005T215634Z`**:
roster-capture run 37378501591 at 977ed5d, a full live run that was green end to end.

**Final snapshot: `20261005T223610Z`.** Roster-capture run 37382759839 at 7a9828c,
green, after the Wofford redirect-host fix.

| measure | value |
|---|---|
| roster pages | **353 (96.7%)** |
| pages CURRENT / PROBABLY_CURRENT | 338 / 8 |
| teams CONFIRMED | **327 (89.6%)** |
| teams LIKELY | 2 |
| CONFIRMED + LIKELY | **329 (90.1%)**: the ≥ 90% target is met |
| teams CONFLICTED | 17 |
| teams STALE | 15 |
| teams UNKNOWN | 4 |
| identity match | 97.3% |

**Earlier verification snapshot: `20261005T221704Z`.** Roster-capture run 37380677974
at 8988f01, green, run after the redirect-registry fix. Compared with the reference
snapshot:

| measure | reference 215634Z | verification 221704Z |
|---|---|---|
| roster pages found | 349 | **352 (96.4%)** — Binghamton, New Orleans and Texas State now resolve |
| pages CURRENT / PROBABLY_CURRENT | 342 | 345 (337 / 8) |
| teams CONFIRMED | 320 | **323 (88.5%)** |
| teams LIKELY | 3 | 2 |
| teams CONFLICTED | 20 | 20 |
| teams STALE | 18 | 16 |
| teams UNKNOWN | 4 | 4 |
| CONFIRMED + LIKELY | | **325 (89.0%)** |
| continuity audit, mean | −0.67 | −0.65 |
| continuity audit, \|adj\| p95 | 5.30 | 5.27 |
| continuity audit, \|adj\| > 3 / > 4 | 80 / 44 | 81 / 44 |
| rotations passing sanity | 352 | 354 of 355 |

The detailed tables below use the reference snapshot. They differ from the
verification snapshot only by these few teams.

## A. Verdict

**Did we remove roster truth as the operational game-1 bottleneck? For about 9 teams
in 10, yes.** Unresolved teams are listed in section T.

* **Before (Wave 6, 2026-10-05 17:30).**
  * 2 teams were CONFIRMED. Membership came from ESPN feeds that were mostly last
    season's rosters.
* **Now (this wave).**

  | measure | count |
  |---|---|
  | official athletics domains, from the NCAA Membership Directory | 364 of 365 |
  | official roster pages found and parsed | 349 |
  | pages CURRENT or PROBABLY_CURRENT | 342 |
  | teams CONFIRMED | 320 (87.7%) |
  | teams LIKELY | 3 |
  | official names identified | 97.2% |
  | rotation players (≥ 10 expected minutes) with an ESPN identity | 98.6% |

* **The Wave 6 mechanism, measured before tip.** For CONFIRMED teams, `pure-0.5.0`'s
  game-1 player block gives **147 of 200 minutes on average (74%) to 9.5 players per
  team who are no longer on the roster**. The P-ROSTER-1 rotation gives them **0**.
  The definitive version of this metric is scored against box scores after each
  team's first game (section L).
* **CONFIRMED + LIKELY: 88.5% in the reference snapshot, 90.1% in the final one.**
  * The redirect and redirected-host fixes moved it.
  * The rest are listed in section T with reasons.
* **No historical freeze and no new version.** The P-ROSTER-1 spec and the authority
  of (b) are unchanged.

## B. NCAA directory

* **How the endpoint was found.**
  * The public directory web app (https://web3.ncaa.org/directory/) loads its member
    list from an unauthenticated JSON endpoint:
    `api/directory/memberList?type=12&division=I&sportCode=MBB`.
  * It was found by reading the app's own script bundle, captured on
    `roster-source-samples` (20261005T204013Z). No browser automation was used.
  * robots.txt disallows `/stats/`, `/football/` and similar paths, but not
    `/directory/`.
* **Cost.** One cached request per refresh, through the chokepoint (`ncaa_directory`,
  2 s spacing). Refresh weekly September–November and monthly otherwise.
* **What it returns.** 365 members with `academicYear` 2027 and `divisionRoman` I.
  Each row has conference, reclassification fields and `athleticWebUrl`, the official
  "Athletics Link".
* **The registry** (`models/rosters/ncaa_athletics_domains.json`) is generated from
  `athleticWebUrl` and checksum-pinned.
  * It is now the only source of `cost_policy.SCHOOL_HOSTS`; the three-domain hand
    list is gone. A modified registry fails closed.
  * A host shared by two schools is an exception.
  * Observed redirects of an NCAA link are added with evidence. Four hosts so far:
    `binghamtonbearcats.com`, `privateersports.com`, `txst.com`,
    `woffordterriers.com`.

## C. Team universe

`models/rosters/ncaa_reconciliation.json` and `ncaa_d1_mbb_universe.csv`.

| | count |
|---|---|
| NCAA D-I MBB members, 2026-27 | 365 |
| model current teams | 365 |
| exact normalized name | 257 |
| verified alias (`ncaa_team_aliases.csv`, keyed by NCAA org id, with domain as evidence) | 107 |
| in the model, not in the NCAA list | 1: **Saint Francis (PA)**, left D-I after 2025-26 |
| in the NCAA list, not in the model | 1: **University of West Florida** (org 11740, ASUN, `goargos.com`), new to D-I; no canonical team or ESPN id in the lake yet |

* **Reclassifying or recent programs, handled explicitly:**
  * mapped: Le Moyne, Mercyhurst, West Georgia, **New Haven**;
  * NCAA reclass fields set: Merrimack, North Alabama;
  * unmapped: West Florida.
* **Conference labels** differ for 60 mapped schools because of realignment and
  abbreviations. They are informational only.

## D. Athletics domains

* **Coverage.** 364 of 365 VERIFIED (99.7%).
  * The one exception is West Florida (`VERIFIED_UNMAPPED`). Its domain is known, but
    there is no team to attach it to.
  * There are no shared-host exceptions.
* **Redirects.** Four NCAA links redirect to a newer host:
  * Binghamton → binghamtonbearcats.com;
  * New Orleans → privateersports.com;
  * Texas State → txst.com;
  * Wofford → woffordterriers.com.

  The chokepoint correctly refused the unregistered hop, recorded the target and
  never requested it. The hosts are now in the committed registry with evidence.
  * In the reference snapshot these four still failed: the run used an archived
    registry that predated the evidence.
  * The directory refresh is now due whenever committed evidence is missing from the
    archived registry (8988f01). The next capture verifies it (section V).

## E. Roster page discovery

* **Politeness.**
  * At least 5 s per host; the chokepoint's spacing is now per host for this source.
  * robots.txt is checked first.
  * At most 6 pages per site.
  * Every redirect hop is authorized before it is requested.
  * No search engine.
* **Cost per run.**
  * First discovery: 812 page requests for 364 sites.
  * Daily runs: known URLs, **386 requests for 364 sites**.
* **Found:** 349 of 364 (95.6%).

  | platform | pages |
  |---|---|
  | SIDEARM | 320 |
  | WMT | 26 |
  | Presto / table | 3 |

* **First discovery, by method:**
  * home-page link: 188;
  * platform route: 136;
  * sport-page link: 2.
* **Parsers** (`cbb_edge/rosters/parsers/`): all built from live evidence on
  `roster-source-samples`.
  * SIDEARM: nextgen person cards, the classic list, and embedded `"players":[…]`
    JSON for client-rendered pages.
  * WMT: card and list containers, plus the page's own Nuxt `__NUXT_DATA__` payload
    or its external `_payload.json`.
  * A header-driven table parser for Presto and custom sites.
* **Season label.** Read only from the title, h1/h2 headings, the selected season
  option, WMT body metadata or the URL. Body text, news links and archive menus are
  never used: they produced false 2015 and 2023 labels in the first probe.

## F. Official rosters

| page status | count |
|---|---|
| CURRENT (2026-27 label) | 335 |
| PROBABLY_CURRENT (no label, incoming transfer listed) | 7 |
| STALE (2025-26 label: Arkansas-Pine Bluff, Chicago State, Cal State Fullerton, Cal State Northridge, Prairie View A&M, East Texas A&M) | 6 |
| UNKNOWN (Lehigh: no label, no new-player evidence) | 1 |
| not found | 15 (section T) |

* **5,296 official player rows.** Raw pages are archived gzipped whenever the parsed
  roster changes, under `official/pages/`. Parsed rows, page freshness and the
  discovery report are written per snapshot.
* **A4 fix (exhausted-players test).** 17 pages labelled 2026-27 were first marked
  STALE because each listed at least 3 four-season players. Each also listed 4–9
  incoming D-I transfers, which a 2025-26 page cannot list.

## G. Roster confidence

| | CONFIRMED | LIKELY | CONFLICTED | STALE | UNKNOWN |
|---|---|---|---|---|---|
| Wave 6, 17:30 | 2 | 178 | 0 | 184 | 1 |
| first full capture 21:21 (before A4) | 72 | 3 | 178 | 36 | 76 |
| **reference 21:56** | **320** | **3** | **20** | **18** | **4** |

Thresholds are unchanged. A4 fixed two things:

1. **Rule order.** Official membership is now applied before cross-team conflicts.
   430 of 481 "conflicts" were transfers whose old team's fresh official roster omits
   them.
2. **Identity for newcomers.** Players with no D-I history are now identified (see H).

## H. Player identities

* **Official rows, by identity:**

  | identity | rows |
  |---|---|
  | exact same-team ESPN row | 2,440 |
  | exact unique in D-I history (5 seasons) | 1,242 |
  | exact unique ESPN id elsewhere | 103 |
  | `no_d1_history` (freshman, or non-D-I previous school) | 1,364 |
  | **unresolved** | **138** |
  | conflicting identity | 9 |

* **Match rate: 97.2%.**
  * Rotation candidates with at least 10 expected minutes: 98.6% have an ESPN
    identity. The rest are first-D-I players with a synthetic `N:` id.
  * Team identity coverage: median 1.00, mean 0.972.
* **Unresolved names** are logged as `unmatched_official_name` and excluded from the
  rotation. Examples:
  * an upperclassman with no previous school listed;
  * a common name shared by two recent D-I players;
  * a D-I transfer whose name differs from the box score (e.g. DJ Wagner before the
    initials fix).

  Nothing is fuzzy-matched. Verified aliases (`models/rosters/player_aliases.csv`)
  can be added one by one.

## I. Returner / transfer / new

From observed D-I box-score history, for CONFIRMED and LIKELY records:

| class | players |
|---|---|
| returning | 1,531 |
| returning after a gap | 62 |
| transfer | 1,550 |
| first-D-I | 2,023 |

* Class labels are never used for this. 1,133 listed class labels contradict observed
  history and are flagged.

## J. Roster change events

`events/2026/<stamp>_events.jsonl`, append-only.

* **First full capture vs Wave 6:**
  * 2,410 players added;
  * 1,293 removed;
  * 26 team changes;
  * 336 confidence changes.
* **Reference vs first capture**, mostly A4 effects:
  * 1,217 added;
  * 522 identities resolved;
  * 252 confidence changes;
  * 52 removed;
  * 19 source-freshness changes;
  * 1 team change.

## K. Expected rotations

* **Allocation.** 353 teams have a rotation. Shares are water-filled to exactly 200
  minutes with no player above 40.
* **Rejected alternatives.**
  * Positional bounds and a ≤ 3 per position starter rule were tested and rejected:
    top-5 fell 0.816 → 0.802, MAE rose 8.04 → 8.54, and starter accuracy fell
    0.777 → 0.769.
  * Water-filling itself leaves the Wave 6 ranking identical: top-5 0.816, top-8 0.880.
* **Sanity checks: 352 of 353 pass.**
  * 200 ± 1 minutes (mean 199.9).
  * Max 40; median team max 29.9.
  * No duplicates.
  * **0 departed players listed.**
  * 5 starters.
  * Median 15 players, 8 with at least 10 minutes.
* The one failure is Western Illinois: 4 identified players, identity coverage 0.31.
  The overlay does not use it (A4.4).
* **Per player:** expected minutes, P(rotation) from a calibration table on seasons
  ≤ 2014, expected starter, and usage role.

## L. Departed-player false inclusion

**Pre-tip estimate.** The reference is the current roster truth. Over 320 CONFIRMED
teams:

| rotation | false players / team | false minutes / team |
|---|---|---|
| BASE (`pure-0.5.0`, last season's shares) | 9.5 | 147.3 of 200 (median 150) |
| ROSTER (P-ROSTER-1) | **0** | **0.0** |

* Also for BASE: false usage share 0.45 and false value −1.64 per team.
* **The scored version** (preregistered, `scorecard.false_inclusion`): weekly in
  `prospective-benchmark` as `false_inclusion.csv`, BASE vs ROSTER at T−7d … latest.
  A player counts as false when he appears in none of the team's first five box
  scores.

## M. P-ROSTER-1

* **(a) input substitution.**
  * Applies to 343 teams: CONFIRMED 320, LIKELY 3, CONFLICTED 20.
  * Each must pass the rotation sanity checks.
  * For CONFIRMED teams, only official-roster players enter.
* **(b) continuity correction.** Applies to the 320 CONFIRMED teams, with the pinned
  coefficients.
* **STALE / UNKNOWN teams** (22): base `pure-0.5.0` is authoritative.
* No projection records exist yet (no 2026–27 games). The overlay code path and its
  tests are unchanged apart from the sanity gate and the CONFIRMED-only membership.

## N. Continuity correction (audit, `<stamp>_continuity_audit.json`)

The per-team side term at games-seen 0. The game adjustment is the home − away
difference.

| | value |
|---|---|
| CONFIRMED teams | 320 |
| mean | −0.67 |
| median | −0.43 |
| \|adj\| p90 | 4.50 |
| \|adj\| p95 | 5.30 |
| \|adj\| max | 8.39 |
| \|adj\| > 2 | 141 |
| \|adj\| > 3 | 80 |
| \|adj\| > 4 | 44 |

* **Mechanism.**
  * Truth continuity averages **0.263**, against an expected returning share of 0.472
    from the preseason P(return) model.
  * Realized continuity in 2025-26 (ORACLE) was **0.267**. Measured roster truth now
    reproduces the 2025-26 portal-era turnover that P(return) misses, which is
    exactly the Wave 6 finding.
  * Mean terms: dcont −1.41, incoming-transfer prior share +1.71, first-D-I expected
    to play −0.97.
* **The largest corrections are verified major rebuilds.** Each has an official
  CURRENT page and, mostly, ESPN corroboration:

  | team | adj | truth continuity | expected | first-D-I expected |
  |---|---|---|---|---|
  | Idaho State | −8.4 | 0.04 | 0.60 | 13 |
  | Louisiana Tech | −7.2 | 0.10 | 0.54 | 12 |
  | South Alabama | −7.1 | 0.12 | 0.55 | 12 |
  | Mississippi Valley State | −7.0 | 0.00 | 0.57 | 10 |

  * At the top end: Cincinnati +4.7 (7.7 incoming transfer prior shares) and Grand
    Canyon +5.6.
  * Idaho State was checked player by player. Its official roster drops 13 of last
    season's ESPN-listed players. ESPN's own core list for 2027 agrees. It lists 3
    returners, 1 transfer and 12 first-D-I players.
* **Not capped, per the preregistration.** One risk is recorded:
  * The prospective "first-D-I expected to play" count (expected share ≥ 0.10) has
    mean 2.7, with 25% of teams at 0 and a long tail.
  * The ORACLE count the coefficient was fit on (actual appearances) has mean 4.4 in
    2025-26 and 6.6% of teams at ≥ 8.
  * The game-1 scoring in section P will show whether the tail over-corrects. It is
    not re-specified now.

## O. ESPN freshness

ESPN is updating slowly.

| feed | teams passing the staleness tests (21:56) | earlier (17:30) |
|---|---|---|
| ESPN site / core | 209 of 365 | 201 |
| SportsDataverse copy | 129 of 318 | unchanged |

* 58 site rosters still carry the 2025-26 label.
* 98 list eligibility-exhausted players.
* Fresh ESPN still counts as independent corroboration. ESPN core and site are one
  group, and SDV is in the same group, so nothing is double-counted. In the reference
  snapshot most CONFIRMED teams have both the ESPN and school groups fresh.

## P. Prospective preregistration (locked)

`research/hypotheses/WAVE7.md` section 7:

* **Comparison.** `pure-0.5.0` vs `pure-0.5.0+roster`, on game 1 and games 2–3.
* **Primary metrics:**
  * margin RMSE;
  * MAE;
  * log loss;
  * market gap (benchmark only).
* **Intermediate metrics:**
  * top-5 / top-8 recall;
  * starters;
  * minutes MAE;
  * rotation precision and recall;
  * departed-player false inclusion: count, minutes, usage, value;
  * current-player omission.
* **Snapshots.** T−7d / T−72h / T−24h / T−6h / latest.
* **Rule.** Nothing is promoted or re-weighted from these during 2026–27, and the
  rules are not edited after opening week.

## Q. Archives

| archive | status |
|---|---|
| `roster-archive` | three Wave 7 live snapshots on 2026-10-05: 212117Z (first full capture), 215634Z (reference), and the redirect-fix verification run. Includes ESPN snapshots, truth, official pages / rows / discovery, events, NCAA directory snapshots, quality reports and the dashboard (`reports/latest_dashboard.md`) |
| `projections-archive` | starts with the first games |
| availability / ESPN lines / Kalshi | capturing, unchanged |

## R. Market independence

* No module in `cbb_edge/rosters/` imports market code. This is enforced by
  `test_roster_layer_never_imports_market_code`.
* The P-ROSTER-1 spec says `market_inputs: NONE`.
* Roster membership, confidence, rotation, role and continuity come only from the NCAA
  directory, official athletics pages, ESPN roster feeds and box-score history.
* Market data appears only in the downstream benchmark's market gap.

## S. Cost audit

* Odds API 0, CBBD 0, paid $0.
* Every request went through `cbb_edge/data/http.py` → `cost_policy.authorize`:
  * NCAA directory: 1 request per refresh;
  * school sites: 812 requests on first discovery, then about 386 per daily run;
  * robots.txt: one per host per run.
* The cost audit passes in every workflow.

## T. Unresolved teams (reference snapshot)

**Roster page not found or unreachable (15 in the reference; 12 in the verification
snapshot):**

* **Redirects, fixed by this PR.** Binghamton, New Orleans, Texas State, Wofford.
  * The NCAA link redirects to a newer host. That host is now registered with
    evidence.
  * The first three resolve in the verification snapshot.
  * Wofford's redirect is followed, but discovery still built its routes on the old
    host. Fixed in the last commit: routes now use the redirected host.
* **robots.txt unavailable or disallowing.** They are respected and never bypassed:
  * Little Rock: robots.txt disallows us.
  * Central Connecticut and Tennessee Tech: robots.txt returns HTTP 405, a
    bot-protection response.
  * Colgate and Omaha: the connection is reset on robots.txt.
* **Missouri.** `mutigers.com` returns 404 to every request.
* **Roster not published yet.** These pages list staff only, or fewer than 8 players:
  Jacksonville, Long Island University, LSU (4 players listed).
* **Alabama.** Nuxt data comes from an external `_payload.json`. It was fetched (robots
  allows it), but its structure yields 0 roster entries for the current WMT payload
  reader. Next step: a parser for that layout, from a saved sample.
* **Arizona State.** No men's basketball roster at the platform routes.

**Official page STALE (6):** Arkansas-Pine Bluff, Chicago State, Cal State Fullerton,
Cal State Northridge, Prairie View A&M, East Texas A&M. The pages are still labelled
2025-26.

**Official page UNKNOWN (1):** Lehigh. No label and no new-player evidence.

**Identity coverage < 0.80, UNKNOWN (4):**

| team | coverage | why |
|---|---|---|
| Western Illinois | 0.31 | near-complete rebuild; most previous schools not listed |
| UTSA | 0.67 | |
| Old Dominion | 0.69 | |
| Penn State | 0.79 | |

**CONFLICTED (20):** a player is on this team's official roster while a fresh ESPN
listing still places him elsewhere, and that other team has no fresh official page.
They are kept and logged (38 players), never resolved silently. The teams:

* USC, Jacksonville State, Bradley, Indiana, Pittsburgh;
* DePaul, Arkansas-Pine Bluff, Bethune-Cookman, UCF, Charleston Southern;
* Colgate, Florida Atlantic, Loyola Marymount, Oregon, Robert Morris;
* Youngstown State, USC Upstate, Cal State Bakersfield, SIU Edwardsville, Southern
  Indiana.

Arkansas-Pine Bluff and Colgate are CONFLICTED even though their own pages are STALE
or unreachable: their ESPN listing is fresh, and another team's official roster lists
one of their players.

**STALE (18):** LSU, Missouri, Jacksonville, Texas State, Alabama, Little Rock,
Central Connecticut, Chicago State, Cal State Fullerton, Lehigh, New Orleans, Cal State
Northridge, Saint Francis, Tennessee Tech, Wofford, LIU, Omaha, East Texas A&M. These
teams have no usable official page and stale ESPN evidence; the base model is
authoritative.

**Other:**

* **Saint Francis (PA):** not D-I in 2026-27 (STALE).
* **West Florida:** new D-I member with no canonical team. Games involving it are
  treated as against a non-D-I opponent until a verified ESPN id is added.

## U. Rejected / failed sources and approaches

* **stats.ncaa.org rosters.** Akamai bot challenge (Wave 6). Not bypassed; no effort
  spent.
* **Search engines** for roster discovery: not used.
* **Body-text season labels** (archive menus, news links, image paths) gave false 2015
  and 2023 labels. Replaced with title, headings, selector and URL.
* **The SIDEARM HTML-only parser** missed client-rendered pages (Bradley, Akron
  family). Embedded JSON now covers them.
* **The WMT HTML card parser** alone missed list layouts and client-rendered sites
  (Clemson, New Mexico, Washington State). The Nuxt payload now covers them.
* **Positional rotation bounds** and the **≤ 3 per position starter rule**: rejected,
  see section K.
* **The first live truth run (before A4)** produced 178 CONFLICTED and 76 UNKNOWN
  teams from rule ordering and identity coverage. It is kept in the archive
  (append-only).

## V. PR

* **PR.** https://github.com/chmoses98/cbb-edge-finder/pull/7, branch
  `claude/determined-carson-hu0sdb`.
* **Live runs on this branch.**
  * The reference snapshot was produced by roster-capture run 37378501591 at 977ed5d,
    green.
  * A redirect-fix verification run was dispatched after 8988f01.
* **CI.** test, benchmark and probe were green on the latest head checked. Final
  status is in the PR.

## Next

* Daily captures (Sep–Nov) will raise coverage as LSU, Jacksonville and LIU publish
  rosters and ESPN refreshes.
* Add verified player aliases for the 138 unresolved names that matter for rotations.
* Add West Florida as a canonical team once a verified ESPN id appears in a schedule.
* Score P-ROSTER-1 from opening night under the locked rules.
