# Player availability and roster archives (Wave 4)

Availability ("who is going to play tonight") is basketball information. It may enter
PURE_BASKETBALL, but only from roster, injury and news sources, never from market
movement. `cbb_edge/availability` is listed in `PURE_PACKAGES`, so it cannot import
`cbb_edge.market` or `cbb_edge.kalshi` (CI scan).

## Free sources (probed 2026-10-05 from GitHub runners; `espn_public`, 1 req/s)

| endpoint | what it gives | offseason status |
|---|---|---|
| `site/v2/.../teams/{id}/roster` | per athlete: ESPN id, name, jersey, position, height, weight, class, birthplace, `status` (active …), `injuries[]` | works; 2026–27 rosters posted; injuries empty |
| `site/v2/.../injuries` | league-wide injury list | responds, empty |
| `core/v2/.../teams/{id}/injuries` | team injury items | responds, empty |
| `site/v2/.../summary?event=` | pregame `injuries` section when ESPN publishes one; post-game `starter` / `didNotPlay` | completed game: no injuries key; starters present |

ESPN's college injury coverage is **unknown until games start**. Every capture keeps the
source-native text, so coverage can be measured honestly during 2026–27. No paid feed,
no CBBD, no Odds API, no aggressive scraping.

## Capture (`.github/workflows/availability-capture.yml`, branch `availability-archive`)

* Every 30 minutes, November–April. For each D-I game whose time-to-tip falls in a
  checkpoint window it fetches:
  * the league injury list;
  * the game summary;
  * both team rosters.

  | checkpoint | window before tip |
  |---|---|
  | T-24h | 20–28 h |
  | T-6h | 4.5–7.5 h |
  | T-90m | 60–120 min |
  | T-30m | 20–50 min |
  | latest | 0–20 min |

* One JSONL row per (player, team, game, capture), schema `availability-capture-v1`:
  * identity: canonical `player_id` (`P` + ESPN id), `espn_athlete_id`,
    `espn_team_id`, `game_id`, `side`;
  * timing: `captured_at`, `minutes_to_tip`, `checkpoint`;
  * status: `status` (canonical), `p_play`, `native_status` (source text), `source`,
    `confidence` (`reported` / `no_report`), injury date and comment;
  * `status_changed` (versus the player's previous capture for that team);
  * `expected_minutes_adjustment`, left null here and filled by the model
    (replacement model).
* Raw league-injury and summary-injury payloads are kept gzipped. Snapshots are never
  rewritten. Only `state/` (last seen status per player) is updated.

Canonical status → P(plays), fixed before 2026–27 (WAVE4.md, P-AVAIL):

| status | P(plays) |
|---|---|
| out / suspended / inactive | 0.00 |
| doubtful | 0.25 |
| questionable | 0.50 |
| probable / day-to-day | 0.85 |
| available / no report | 1.00 |

## Roster snapshots (`.github/workflows/roster-capture.yml`, branch `roster-archive`)

* Schedule: a daily change check from September to November, then weekly. Every
  Monday also writes a full snapshot.
* A team's snapshot is written whenever its roster content hash changes.
* Rows follow schema `roster-snapshot-v1`: ESPN athlete id, name, jersey, position,
  height, weight, class, birthplace, roster status, injury fields, content hash and a
  changed flag.
* `capture.classify_roster` labels each player returning / transfer / new. It uses the
  repo's own player history from earlier seasons only (ESPN athlete id, no name
  matching), and records the previous team.
* Previous-college stats come from the same history.
* This gives future seasons a timestamped portal-era preseason roster dataset. Wave 3
  showed that historical rosters lack this.

## How availability changes a projection

* **Replacement model** (`cbb_edge/players/availability_model.py`, B19).
  * When player A's expected minutes drop, teammate B receives
    Δ ∝ cond_share_B^γ × (1 + β·same_position).
  * Shares are water-filled so the team sums to 5 on-court players and nobody exceeds
    40 minutes.
  * γ = 0.5 and β = 1.0 were chosen on DEV absences 2012–2014 (share RMSE 0.1630 vs
    0.1686 for plain proportional redistribution).
* **Team strength.** The changed shares feed the same walk-forward player-impact layer
  (RAPM + box prior), so offense and defense move through actual player values. There
  are no "star out = −5" rules. Pace is unchanged.
* **P-AVAIL overlay** (`prospective.availability_overlay`, PROSPECTIVE_ONLY).
  * For challengers, games with at least one *reported* status are re-projected.
  * They are archived as `<version>+avail`, with `availability.margin_base`,
    `total_base` and every changed player share.
  * Base records are untouched.

## Historical absence study (2011–2026, actual minutes; `research/wave4/absence_study.json`)

* A regular rotation player's first surprise absence happens in ~2% of games (21,904
  cases). It is not claimed knowable historically: no source recorded it.
* After one missed game only 49% of regulars play the next game; after two misses, 34%.
  The pure-0.3.0 rotation still keeps ~84% of a player's share after one miss.
