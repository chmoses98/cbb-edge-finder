# Data Source Audit

Audit date: 2026-10-04. Every source below was actually requested or downloaded
(or deliberately **not** requested, with the reason). Requests ran either from the
development sandbox or from GitHub Actions (`.github/workflows/source-probe.yml`,
run [37240044342](https://github.com/chmoses98/cbb-edge-finder/actions/runs/37240044342)),
because the sandbox's egress policy blocks several sports hosts.

Cost classes come from `cbb_edge/data/cost_policy.py`, which is the only authority on
whether a request may run.

## Summary

| # | Source | Cost class | Status | Used for |
|---|---|---|---|---|
| 1 | SportsDataverse hoopR-mbb (ESPN-derived) GitHub release assets | FREE_BULK | **Ingested** | schedules, results, team box, player box, PBP, ESPN pregame WP, crosswalks |
| 2 | SportsDataverse ncaa-mbb-hoops (stats.ncaa.org-derived) release assets | FREE_BULK | **Ingested 2010–2026 (lineups, stints, possessions, schedule)**; not yet modeled | lineups, on-floor, matchup stints, possessions, rim/mid/3 shot zones |
| 3 | ESPN `pickcenter` odds inside hoopR-mbb-raw per-game JSON (raw.githubusercontent.com) | FREE_RATE_LIMITED | **Harvested** for 2018–2023 + 2026 | free historical closing spreads/totals/moneylines (2026: open + close) |
| 4 | ESPN public site API | FREE_RATE_LIMITED | Reachable from GitHub (200); blocked in sandbox | live scoreboard/summary (fallback only; bulk copy preferred) |
| 5 | Kalshi public market-data API | FREE_RATE_LIMITED | **Live capture working** (GitHub Actions) | prospective market archive |
| 6 | Sports Reference / CBB Reference | FREE_RATE_LIMITED | Reachable from GitHub (200, one page); not scraped | future validation source |
| 7 | Bart Torvik | FREE_RATE_LIMITED | **403 from GitHub Actions**, blocked in sandbox | benchmark only (not available yet) |
| 8 | CollegeBasketballData (CBBD) API | UNKNOWN_COST (gated) | **Not called** (blocked by policy) | — |
| 9 | cbbreadr / `john-b-edwards/cbbd-data` bulk mirror of CBBD | n/a | **Not used** — taken down at the CBBD owner's request | — |
| 10 | The Odds API | PAID_METERED (gated) | **Not called. Zero requests.** | — |
| 11 | KenPom, SportsDataIO, Sportradar | PAID_METERED (gated) | Not called | — |

## 1. SportsDataverse hoopR men's college basketball (ESPN-derived)

* Location: `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/<tag>/<file>`
  (producer repo `sportsdataverse/hoopR-mbb-data`). Bulk parquet, one file per season.
* Cost: free. GitHub release CDN; no API key; no meaningful rate limit at this volume.
* Update cadence: daily 07:00 UTC Nov–Apr (producer workflow `daily_mbb.yml`).
* Stable IDs: ESPN game, team, athlete ids (integers). Team crosswalk to Torvik / KenPom /
  Fox names; schedule crosswalk to Torvik/KenPom/Fox game ids (2026 only); player
  crosswalk (2026 only).
* Usage terms: ESPN-sourced data redistributed by SportsDataverse for research. We cache
  locally, do not redistribute raw files, and commit only manifests.

| Dataset (tag) | Seasons available | Downloaded | Rows (downloaded) | Notes |
|---|---|---|---|---|
| schedules | 2003–2027 | 2003–2027 | 123,520 games (silver) | 2027 = 1,629 pre-season scheduled games (Nov 2 2026 – Mar 6 2027) |
| team_box | 2003–2026 (2003–04 tiny) | 2003–2026 | 242,048 team-games | ~99% of D-I vs D-I games from 2009 |
| player_box | 2003–2026 | 2006–2026 | 3,563,942 player-games, 96,947 players | minutes, shooting, rebounds, assists, TO, fouls, starter |
| pbp | 2006–2026 | 2015–2026 (601 MB) | 22.9M plays | substitutions only 2025 (partial: 1,586 games) and 2026 (all 6,275 games); shot coordinates sparse before 2025 |
| shots | 2006–2026 | not downloaded | — | 1.8 GB across formats; needed for shot-location research |
| rosters / game_rosters | 2025–2026 | not downloaded | — | height, weight, class (`experience_years`) |
| player_core | 2003–2026 | not downloaded | — | biographical |
| team_crosswalk | 2026 mapping (published per season) | 2003–2026 | 362 teams | ESPN↔Torvik (`bart_team`)↔KenPom name↔Fox |
| schedule_crosswalk | 2026 | 2026 | 6,386 | ESPN↔Torvik/KenPom/Fox game ids |
| player_crosswalk | 2026 | 2026 | 5,442 | ESPN↔Fox/Yahoo players |
| standings, officials, team/player season stats | yes | not downloaded | — | not needed yet |

Missingness: D-I vs D-I games without a team box: 2006 4.2%, 2007 3.6%, 2008+ <0.6%.
`game_spread` in the PBP files is a placeholder (constant 2.5, `game_spread_available=False`)
for the seasons checked, so it is **not** a line source. `pregame_home_prob` is ESPN's
published tip-off win probability and is used only as a public benchmark.

## 2. SportsDataverse ncaa-mbb-hoops (stats.ncaa.org-derived)

* Same release mechanism (tags `ncaa_mbb_lineups`, `ncaa_mbb_matchup_stints`,
  `ncaa_mbb_possessions`, `ncaa_mbb_schedule`, `ncaa_mbb_pbp`, `ncaa_mbb_player_box`,
  `ncaa_mbb_shots`, `ncaa_mbb_rapm`). FREE_BULK.
* Coverage (producer's `ncaa_mbb_schedule_coverage.parquet`, downloaded and manifested):
  lineups ~95–97% of contests 2010–2026; matchup stints and possessions ~98–99.9% of
  contests 2011–2026 (2010: 3%); shots 2019+ (36% → 95%).
* Possession rows carry the five on-floor players for both teams, points, transition /
  garbage-time flags, and **both NCAA and ESPN team ids** (a free ESPN↔NCAA crosswalk).
  Lineup rows carry rim / mid-range / three attempts and makes.
* Stable IDs: NCAA contest ids (strings), NCAA team/player ids; ESPN team ids on
  possessions.
* Status: downloaded 2010–2026 (lineups, matchup stints, possessions, schedule) into
  bronze with manifests. Not yet joined into silver — this is the data for arm B6
  (lineups/on-off) and the rim-vs-rim matchup experiment.

## 3. Free historical lines: ESPN `pickcenter`

* Each SportsDataverse schedule row links the archived ESPN game summary JSON
  (`sportsdataverse/hoopR-mbb-raw`, `mbb/json/final/{game_id}.json`, ~1 MB each). The
  summary's `pickcenter` block holds the line ESPN displayed.
* Harvest: `python -m cbb_edge.market.espn_lines <seasons>`. One request per completed
  game, cached; we keep only the betting block plus the raw file's sha256 and discard the
  rest. Consolidated per season to `bronze/github_raw/espn_lines/espn_lines_{season}.parquet`.
* Coverage found (sampled 10 games per season, then full harvest):

| Season | Provider | Spread | Total | Open + close | Harvested games with a line |
|---|---|---|---|---|---|
| 2008, 2012 | — | no | no | no | not harvested (none in sample) |
| 2015–2017 | consensus / teamrankings | yes | rarely | no | not harvested |
| 2018 | consensus / teamrankings | yes | partial | no | see `research/baseline/metrics.json` |
| 2019–2020 | consensus / numberfire | yes | yes | no | harvested |
| 2021–2022 | Caesars (NJ) | yes | yes | no | harvested |
| 2023 | consensus (teamrankings 2%) | yes | yes | no | 5,714 (all games, incl. non-D-I) |
| 2024–2025 | — | **no** | **no** | — | none exist in the archive |
| 2026 | DraftKings | yes | yes | **yes** | 4,799 (of 5,752 completed D-I vs D-I) |

* Timestamp caveat: before 2026 the line has **no timestamp**; it was captured after the
  game and is treated as an approximate closing line. It is never used as an earlier
  snapshot, and CLV is only computed where open and close both exist (2026).
* Sign convention verified: `spread` is the home line (negative = home favored); we
  cross-check against the favorite flags and flip if inconsistent (tests in
  `tests/test_market.py`).

## 4. ESPN public site API

* `site.api.espn.com/.../mens-college-basketball/scoreboard` and `/summary`: 200 from
  GitHub Actions (scoreboard 22 events for 2025-03-15, summary includes `pickcenter`,
  `odds`, `winprobability`). Blocked by the sandbox egress policy.
* Unofficial, free, undocumented rate limits; registered as FREE_RATE_LIMITED with 1 s
  spacing. Not needed for history (SportsDataverse has the bulk copy); candidate for the
  live pre-game line capture during the season.

## 5. Kalshi public market data (primary live market)

* `https://api.elections.kalshi.com/trade-api/v2` — unauthenticated read-only endpoints
  (`/series`, `/markets`, `/markets/{ticker}/orderbook`). Free. No orders are ever sent.
* Probe (2026-10-04): 3,952 series in category Sports. Men's college basketball series
  include `KXNCAAMBGAME`, `KXNCAAMBSPREAD`, `KXNCAAMBTOTAL`, `KXNCAAMB1HSPREAD`,
  `KXNCAAMB1HTOTAL`, `KXNCAAMB1HWINNER`, `KXNCAAMB2HSPREAD`, `KXNCAAMB2HTOTAL`,
  `KXNCAAMB2ML`, ~30 conference series (`KXNCAAMBACC`, `KXNCAAMBSEC`, …, `…REG`,
  `…REGTOP`), awards (`KXNCAAMBNAISMITH`, `KXNCAAMBCOTY`, `KXNCAAMBMOP`), rankings
  (`KXNCAAMBAPRANK`, `KXNCAAMBKENPOMRANK`), and tournament futures (`KXMARMAD`,
  `KXMARMADSEED`, `KXMARMADROUND`, `KXMARMADREGION`, `KXMAKEMARMAD`, …).
* Look-alikes excluded by the taxonomy (tests): `KXNCAABB*` / `KXNCAABASEBALL`
  (college baseball), `KXNCAAWB*` / `KXWMARMAD*` (women), `KXNCAAMLAX*`,
  `KXNCAAMSOCCER*`, `KXNCAAMWRESTLING*`.
* First live capture (GitHub Actions run 37240044358, before the taxonomy fix): 3,259
  markets / 121 events, almost all futures (`FUTURES_CHAMPION` 1,549, `FUTURES_SEED` 515,
  `FUTURES_CONFERENCE` 495). No 2026-27 game markets were open yet on 2026-10-04.
* History: Kalshi does not give us years of past CBB prices, so the archive starts the
  day capture starts. Every snapshot is kept (see `docs/KALSHI_CAPTURE.md`).

## 6. Sports Reference / College Basketball Reference

* One page probed from GitHub Actions: `cbb/seasons/men/2025-school-stats.html` → 200
  (919 KB HTML). Blocked in the sandbox.
* Published limit: ≤ 20 requests/minute (enforced: 3.5 s spacing). Their terms restrict
  automated bulk collection and some downstream uses; review the current terms before
  any bulk pull. Planned use: independent validation of schedules/results/box totals for
  a sample of games, cached once. Not scraped in this build.

## 7. Bart Torvik

* `barttorvik.com/2025_team_results.csv`, `timemachine/team_results/20250115_team_results.json.gz`,
  `getgamestats.php?year=2025&csv=1`: **HTTP 403 from GitHub Actions** (bot/datacenter
  blocking); host blocked in the sandbox.
* Usable only as an external benchmark. The time-machine files (if retrievable from the
  owner's machine) are dated daily snapshots and would be timestamp-safe; final-season
  ratings must never be used for historical games. The SportsDataverse crosswalk already
  gives Torvik team and game identifiers, so a join is ready if the files are obtained.

## 8. CollegeBasketballData (CBBD)

* API key required. Per the CollegeFootballData/CBBD documentation, the free tier is
  quota-limited (1,000 calls/month for CFBD keys, same key system) and paid Patreon tiers
  raise the quota. Consuming calls reduces the owner's quota, so it is classified
  UNKNOWN_COST and blocked (`ALLOW_CBBD=false`, `CBBD_MAX_REQUESTS=0`).
* No key exists in the environment; the probe recorded `BLOCKED_BY_COST_POLICY`.
* The community bulk mirror (`cbbreadr` / `john-b-edwards/cbbd-data`) was taken down at the
  CBBD owner's request, so we do not use any copy of it.
* What CBBD would add: historical lines from multiple books with spreads/totals for
  2024–2025 (our free gap), recruiting rankings, and its own lineup data. See
  `docs/PAID_DATA_REQUESTS.md` for the approval request template.

## 9. Paid sources (blocked, not used)

* The Odds API (`api.the-odds-api.com`): PAID_METERED. `ALLOW_PAID_ODDS_API=false`,
  `ODDS_API_MAX_REQUESTS=0` → hard block. **Zero requests made.** Optional client in
  `cbb_edge/market/odds_api.py` refuses by default; tests prove no request object is
  ever sent.
* KenPom, SportsDataIO, Sportradar: PAID_METERED, blocked, not used.

## What the data supports (coverage matrix)

| Need | Free source | Seasons |
|---|---|---|
| schedules, results, neutral sites, venues | SDV ESPN schedules | 2003–2027 |
| team box scores | SDV ESPN team_box | 2005–2026 |
| player box scores | SDV ESPN player_box | 2005–2026 |
| play-by-play | SDV ESPN pbp; SDV NCAA pbp | 2006–2026 |
| substitutions / on-floor players / lineups / stints | SDV NCAA lineups, stints, possessions (ESPN pbp only 2025–26) | 2011–2026 |
| possessions | derived from box (all seasons); SDV NCAA possessions | 2006–2026 / 2011–2026 |
| shots with location / zones | SDV ESPN shots (sparse coords pre-2025); NCAA lineups rim/mid/3; NCAA shots | 2006– / 2010– / 2019– |
| recruiting | none free without CBBD quota | — |
| transfers | derived: player id appearing for a new D-I team | 2006–2026 |
| historical lines | ESPN pickcenter (free) | 2018–2023, 2026 (spread from 2015) |
| live market prices | Kalshi (free, prospective) | from 2026-10-04 |
| public benchmark | ESPN pregame WP | 2015–2026 |
