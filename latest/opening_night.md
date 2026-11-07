# Opening night 2026-11-02 - contract-level coverage audit

* contracts: **5366** across **133** games/clusters
* fully clean (nothing missing): **824**; with at least one issue: **4542**
* by family: {'HALF': 499, 'GAME_WINNER': 266, 'OTHER': 14, 'SPREAD': 2021, 'TEAM_TOTAL': 94, 'TOTAL': 2472}
* status flags (overlap by design): {'EVALUATED': 5041, 'UNMODELED': 787, 'PARTIAL': 325, 'UNMATCHED': 28, 'UNSUPPORTED': 36, 'UNSETTLED': 2}
* official-check vs Kalshi settlement: {'CONFIRMED': 5322, 'NOT_CHECKABLE:tied_period_two_way_market': 2, 'NOT_APPLICABLE': 36, 'NOT_CHECKABLE:needs_play_by_play': 6} (disagreements: 0)
* unmatched: 28; unsettled: 2

## Issue counts

* `OPEN_OBSERVED_LATE_GT_1H_AFTER_LISTING`: 4214
* `MISSING_HORIZONS:H24`: 1064
* `MODEL`: 787
* `MODEL:game_inside_fit_window_no_out_of_sample_value;no_half_distribution_in_frozen_model`: 185
* `MODEL:no_pretip_frozen_projection_available`: 160
* `NO_PRETIP_QUOTE:listed_after_tip_live_line_no_pregame_quote_exists`: 156
* `MODEL:game_inside_fit_window_no_out_of_sample_value;no_base_projection;no_half_distribution_in_frozen_model`: 135
* `MISSING_HORIZONS:H24+H6`: 108
* `MODEL:no_half_distribution_in_frozen_model;unsupported_contract_for_challenger`: 104
* `MODEL:no_base_projection;no_half_distribution_in_frozen_model;unsupported_contract_for_challenger`: 63
* `MODEL:game_inside_fit_window_no_out_of_sample_value;no_team_score_distribution_in_frozen_model`: 60
* `OFFICIAL_CHECK:NOT_APPLICABLE`: 36
* `MODEL:no_team_score_distribution_in_frozen_model;unsupported_contract_for_challenger`: 30
* `SUPPORT:UNSUPPORTED:unmapped_so_payoff_unparsed`: 28
* `TIP_UNVERIFIED`: 28
* `MAPPING:UNMATCHED:one_team_unresolved`: 26
* `MODEL:cannot_link_to_game:one_team_unresolved`: 26
* `MISSING_HORIZONS:H24+H6+H1`: 17
* `SUPPORT:UNSUPPORTED:unsupported_series`: 8
* `MODEL:game_inside_fit_window_no_out_of_sample_value;parse:unsupported_series`: 8
* `OFFICIAL_CHECK:NOT_CHECKABLE:needs_play_by_play`: 6
* `MODEL:game_inside_fit_window_no_out_of_sample_value;no_base_projection;no_overtime_model`: 5
* `MODEL:game_inside_fit_window_no_out_of_sample_value;no_race_to_points_model`: 4
* `NO_PRETIP_QUOTE:capture_gap_first_captured_after_tip`: 4
* `MODEL:no_base_projection;no_overtime_model;unsupported_contract_for_challenger`: 3
* `OFFICIAL_CHECK:NOT_CHECKABLE:tied_period_two_way_market`: 2
* `OUTCOME`: 2
* `MAPPING:UNMATCHED:teams_unresolved`: 2
* `MODEL:cannot_link_to_game:teams_unresolved`: 2
* `MODEL:no_race_to_points_model;unsupported_contract_for_challenger`: 2
* `NO_PRETIP_QUOTE:captured_pretip_but_book_empty_or_non_live_status`: 2

Per-contract detail: `opening_night.csv` (one row per contract, every issue listed).
