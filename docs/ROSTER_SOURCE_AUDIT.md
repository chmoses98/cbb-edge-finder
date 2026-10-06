# Roster source audit (Wave 6, 2026-10-05)

**Question.** Who is actually on each D-I roster before game 1, and which free sources
can say so, with timestamps?

**Evidence.**
* `scripts/data/probe_rosters.py`, run from GitHub Actions (the development sandbox
  blocks ESPN, NCAA and school sites);
* raw samples on the `roster-source-samples` branch;
* the 2026-10-05 roster-archive snapshot;
* `scripts/data/roster_archive_audit.py`.

**Cost.** Every request goes through the network chokepoint (`cbb_edge/data/http.py`)
and is cached. No paid source, CBBD or Odds API is ever called.

## Sources

| source (group) | teams / players | ids | name / pos / class / height / jersey | previous school | season label | timestamp | updated in place? | verdict |
|---|---|---|---|---|---|---|---|---|
| ESPN site roster `site.api.espn.com/.../teams/{id}/roster` (espn) | 365 / 5,341 | ESPN athlete id (= box id `"P"+id`) | yes / yes / `experience` (FR..SR) / yes / yes | no | `season.year` | none (no Last-Modified); our capture time | yes | primary, but **stale**: 69 teams still label 2025-26; 183 of 296 "2026-27" rosters list ≥ 2 players with 4+ D-I seasons; median 86% of listed players played 2025-26 |
| ESPN core season athletes `sports.core.../seasons/{s}/teams/{id}/athletes` (espn) | 365 (refs only) | ESPN athlete id | via a second call per athlete | no | in the URL (`seasons/2027`) | none | yes | for the 6 probed stale teams the 2027 list is IDENTICAL to the 2026 list, a copy. Used as a freshness test (`copy_of_previous_season`) |
| SportsDataverse `rosters_2027` release asset (espn) | 354 / 5,461 | ESPN athlete id | yes / yes / `experience_display_value` / yes / yes | no | `season` (its fetch parameter, not ESPN's label) | `Last-Modified: Tue, 15 Sep 2026 08:22:10 GMT` | **overwritten in place** (snapshotted with a dated live copy) | a re-packaged ESPN pull, NOT independent; older than our ESPN pull |
| stats.ncaa.org team list `team/inst_team_list?academic_year=2027` (ncaa) | 365 teams | NCAA team ids | — | — | academic year | none | — | reachable |
| stats.ncaa.org team roster `teams/{id}/roster` (ncaa) | — | NCAA player ids | — | — | — | — | — | **not usable**: an Akamai bot challenge (JavaScript interstitial). We do not try to defeat bot protection |
| NCAA Membership Directory `web3.ncaa.org/directory/api/directory/memberList?type=12&division=I&sportCode=MBB` (Wave 7) | 365 D-I MBB members (2026-27) | NCAA org id | — | — | `academicYear` 2027 | our capture time | yes | **the authority for the universe and official athletics domains** (`athleticWebUrl`); public JSON the directory app itself calls; robots.txt allows `/directory/`; 1 request per weekly refresh |
| official school athletics sites, all platforms (school) | every VERIFIED team in `models/rosters/ncaa_athletics_domains.json` (364 hosts, generated from the NCAA Athletics Link) | none (names; profile URLs) | as visibly listed (SIDEARM cards / lists, header-driven tables) | only when the page shows it | page heading / URL season | `Last-Modified` usually dynamic | yes | **membership authority when CURRENT / PROBABLY_CURRENT** (Wave 7); ≥ 5 s per host, robots.txt, ≤ 6 pages per site, known URL = 1 request |

* **Terms and rate limits.** ESPN endpoints are unofficial and free: 1 request/s,
  cached, once per day Sep–Nov. SportsDataverse is a public GitHub release asset.
  stats.ncaa.org and school sites: ≥ 5 s between requests, cached, and only the pages
  listed here.
* **Recruiting services** are not used: no free, timestamp-safe source was found.
* **Search engines** are not used to find roster pages (Wave 7): discovery starts from
  the NCAA Athletics Link and follows only that site's own links and routes.
* **Head coaches:** no free, timestamped historical coach source exists in the lake.
  Not audited further this wave; reported as unavailable.

## The decisive finding

In early October, ESPN's "2026-27" rosters are mostly last season's rosters in content.
For the 183 ESPN-family rosters that pass every staleness test:

| | ESPN listing | actual rosters 2022–26 (players in the first five games) |
|---|---|---|
| share of last season's minutes on the roster | **0.82** | 0.42 |
| incoming transfers' previous minute share | 0.46 | 1.13 |
| first-D-I players expected to play | 0.19 | 3.8 |

In actual 2025-26 rosters, ≥ 3 players with four prior D-I seasons occur on 1.1% of
teams. In ESPN's "2026-27" listings, ≥ 2 occur on 62% of teams. A class label of FR on
a player with D-I history (941 players) is another symptom.

**Consequence.** No ESPN-derived continuity is used to adjust a projection unless an
independent fresh source confirms the roster (P-ROSTER-1 component (b) requires
CONFIRMED; `cbb_edge/rosters/overlay.py`).

## Resolution rules

The rules are fixed before any model effect was measured. They live in
`cbb_edge/rosters/truth.py`, and `research/hypotheses/WAVE6.md` states them too.

1. **Freshness**, per source × team:
   * `season_label_<y>`: the source's season label is older than the target season;
   * `copy_of_previous_season`: the ESPN-family set equals last season's ESPN core
     list;
   * `lists_eligibility_exhausted_players`: an ESPN-family listing with more than 2
     players who already played 4 D-I seasons;
   * `older_copy_of_stale_feed`: an older capture of a feed whose latest capture is
     stale.
2. **Independence groups:** ESPN (site, core, SDV), NCAA, school. Within a group, a
   player's latest capture supersedes older captures. A same-feed lag is never a
   conflict. At team level, the group's latest fresh capture for a team defines its
   listing (amendment A1).
3. **Player status:**
   * CONFIRMED: ≥ 2 fresh groups, or an official group;
   * LIKELY: one fresh group;
   * CONFLICTED: fresh sources disagree on the team. Every team is kept and logged;
     nothing is resolved silently;
   * STALE: stale evidence only;
   * UNKNOWN: no usable identity (classification `unknown`, never `first_d1`).
   * A fresh official roster defines membership: an ESPN-only player it omits is STALE
     (`absent_from_official`) and is logged (amendment A1).
4. **Identity:** ESPN athlete id is canonical. Name-only official rows match only by
   exact normalized name (accents and suffixes stripped), unique on both sides within
   the same team. Nothing is fuzzy-matched.
5. **Experience:** D-I seasons, games and minutes and the previous team are observed
   from box scores before the season (`models/rosters/history_2026.parquet`). The class
   label is kept, and a FR label on a player with D-I history is flagged
   (`class_label_conflict`), never used.
6. **Team confidence:**
   * CONFIRMED: ≥ 2 fresh groups, or official;
   * LIKELY: one fresh group covering ≥ 80% of listed players;
   * STALE: otherwise;
   * CONFLICTED: any conflicted player.
   * UNKNOWN: < 80% of a fresh official listing matched to ESPN ids
     (`official_roster_unidentified`, amendment A1).

## Archive (append-only, `roster-archive` branch)

* `snapshots/`: ESPN site rosters (since Wave 4).
* `truth/YYYY/MM/DD/<stamp>_records.jsonl`: per player × team, with:
  * ids, sources, fresh sources and source seasons;
  * class labels and observed experience;
  * classification and status;
  * first_seen and last_confirmed.
* `truth/.../<stamp>_teams.json`, `_freshness.jsonl` and `_conflicts.jsonl`.
* `truth/.../<stamp>_proster_state.json`: the P-ROSTER-1 team state (expected
  rotation, continuity inputs). These are the archived T−7d / T−72h / T−24h / T−6h
  game-1 states.
* `evidence/core/<season>/`: ESPN core athlete-id lists.
* `reports/roster_quality_<stamp>.json`: the source-quality report:
  * teams current / stale per source;
  * players by status;
  * conflicts;
  * unresolved transfers;
  * first-seen changes.

Nothing is ever backfilled. A game result never alters an archived pregame record.

## Coverage path

The binding constraint is independent confirmation. Two ways to raise CONFIRMED
coverage:

1. ESPN refreshes rosters as the season nears. The staleness tests will then pass;
   the weekly quality report tracks this.
2. ~~Add official domains one at a time.~~ Superseded in Wave 7: the NCAA Membership
   Directory's Athletics Link gives every member's official domain, so the allowlist
   is generated (`cbb_edge/rosters/ncaa_directory.py`) and checksum-pinned; a hand
   list no longer exists.

## Wave 7: universe reconciliation (2026-10-05)

`models/rosters/ncaa_reconciliation.json`. 365 NCAA members, 365 current model teams:

* 257 matched by exact normalized name;
* 107 matched by verified alias (`models/rosters/ncaa_team_aliases.csv`, NCAA org id →
  team, each with its athletics domain as evidence);
* **in the model, not in the NCAA 2026-27 D-I MBB list**: Saint Francis (PA) (`T0293`),
  which left Division I after 2025-26;
* **in the NCAA list, not in the model**: University of West Florida (org 11740,
  ASUN, `goargos.com`), new to D-I in 2026-27. It has no canonical team or ESPN id in
  the lake yet, so it is reported, never guessed;
* reclassifying / recent programs handled explicitly: Le Moyne, Mercyhurst, West
  Georgia, New Haven (all mapped), Merrimack and North Alabama (NCAA reclass fields
  set), West Florida (unmapped).

Conference labels differ for 60 mapped schools; these are 2026-27 realignment and
abbreviations ("Southwestern Athletic Conf."). They are informational, never used to match.
