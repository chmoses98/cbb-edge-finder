# Sift output schema (`sift-cbb-projection-1.0`)

Producer: `cbb_edge/app/project.py`; contract + validator: `cbb_edge/app/sift.py`
(`json_schema()` emits JSON Schema 2020-12). One JSON object per game (JSONL files).
Example: `docs/examples/sift_projection_example.json`.

| Block | Fields |
|---|---|
| `game` | `game_id` (canonical `G<espn id>`), `espn_game_id`, `season`, `start_time_utc`, `site` (`home`/`neutral`), venue name/city/state, `status` |
| `home`, `away` | `team_id` (canonical `T####`), `espn_team_id`, `name`, `conference` |
| `projection` | `possessions`, `home_ppp`, `away_ppp`, `home_score`, `away_score`, `margin` (home − away), `total`, `home_win_prob` ∈ (0,1), `margin_sd`, `total_sd` |
| `ratings.home/away` | `adj_off`, `adj_def` (pts/100 vs average D-I), `adj_tempo`, `four_factors` (adjusted eFG/TO/ORB/FTR/2P/3P/3PA-rate, off & def) |
| `matchup_factors` | projected factor values for this matchup (`efg_h`, `to_a`, …) |
| `player_context` | reserved (roster continuity, injuries) — `null` for now |
| `market` | reserved (Kalshi prices joined by canonical game) — `null` for now |
| `freshness` | `info_cutoff_utc`, `info_games`, games seen per team, `sources` |
| `model` | `name`, `version`, `arm`, `research_state` (`research`/`shadow`/`production`) |

Guarantees (validated before writing): scores reconcile with margin/total to ±0.05,
probabilities strictly inside (0,1), positive SDs, `home != away`. Additive changes bump
the minor version; breaking changes bump the major version.
