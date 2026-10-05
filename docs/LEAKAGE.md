# Leakage Controls

For a game at time T, no post-T information may enter its features.

| Risk | Control | Test |
|---|---|---|
| later games / results | info set = rows with `available_at` < first tip of the day | `test_info_set_strictly_before_tipoff` |
| same-day results | all games on day D share one info set built before the first tip | `test_same_day_games_do_not_see_each_other` |
| late results (e.g. West Coast games) | strict timestamp filter, not date filter | `test_late_game_result_excluded_when_not_available` |
| future data via retroactive SOS | ratings are re-solved daily from the info set only; no stored season-wide fit is reused for earlier days | `test_future_results_cannot_change_past_states` (corrupts every future box score; past states must be bit-identical; later states must change) |
| season-wide league means in first-season priors | fixed league constants (`LEAGUE_PRIOR_MU`) — this leak was caught by the test above and fixed | same |
| final-season ratings (Torvik/KenPom/our own) | priors for season s use only the end-of-season fit of s-1 | engine structure; `priors_from_previous` |
| future roster info | returning share counts only players who already appeared before D | `returning_share` uses `pg_cur[available_at < cutoff]` |
| fitted layers (ridge, win-prob link, SDs, ensemble) | expanding windows over strictly earlier seasons | `_stack`, `win_prob`, `residual_sd`, `ensemble` loops |
| closing lines when testing earlier snapshots | pre-2026 lines are labelled close-only; CLV only where open+close exist | `espn_lines` docstring; report |
| tuning on test data | DEV 2007–2014 only; validation 2015–2024; holdout 2025–2026 | `research/REGISTRY.md` |
| reproducibility | deterministic solver + sorted inputs | `test_replay_is_reproducible` |

Every persisted pregame state row stores `cutoff`, `info_rows` and
`info_max_available_at` so any projection can be audited after the fact.

## Wave 2 additions

| Risk | Control | Test |
|---|---|---|
| player ratings using later possessions | RAPM normal equations accumulate only stints with `available_at` < the day's first tip; solved per game day | `tests/test_players.py::test_player_features_have_no_future_leakage` (future stints/minutes corrupted → past features bit-identical) |
| rotation from future games | EW minute shares use only the team's games available before the cutoff; first game uses last season's roster | `test_first_game_uses_no_current_season_minutes`, `test_team_shares_ewma_and_missed_games` |
| timestamp unit mismatch | all cutoff comparisons use explicit UTC epoch **nanoseconds** (`_ns`). A µs-vs-ns comparison bug that counted every game of the season as "already played" was caught during development (games-seen averaged 32) and fixed before any evaluation | same tests |
| team home-court from current season | `team_home_effect` uses residuals of the previous 3 seasons only | `tests/test_context.py::test_team_home_effect_uses_prior_seasons_only` |
| rest days | computed from dates of earlier scheduled games only | `test_rest_days_uses_only_earlier_games` |
| market data in PURE | import ban + column guard + mutation test | `tests/test_market_independence.py` |
| prospective records edited after results | append-only writer, refuses overwrite; workflow skips existing paths | `tests/test_prospective.py::test_archive_is_append_only` |
