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
