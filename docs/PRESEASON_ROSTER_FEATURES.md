# Preseason roster / transfer features (research builder)

Status: RESEARCH ONLY. Nothing here is imported by any production path, workflow, model
version or archive writer; no new schedule was added. Production projections are unchanged.

Code: `cbb_edge/rosters/preseason_features.py`, CLI `scripts/research/build_preseason_roster_features.py`,
tests `tests/test_preseason_roster_features.py`.

## What it builds
One row per (ESPN season `S`, team): returning share of S-1 minutes / points / game-score
production (`ret_*_share`), incoming-transfer S-1 production relative to the team's S-1 totals
(`tr_in_*_rel`, absolute `tr_in_minutes`, `tr_in_prod`), counts (`n_roster`, `n_returners`,
`n_transfers_in`, `n_newcomers_no_hist`, `n_freshmen_class`), `d1_prev`, and provenance
(`membership_source`, `membership_pit`, `membership_as_of`, `stats_source`, `stats_through_season`).

## Point-in-time rules
* Statistics: player box scores of seasons < S only (a test enforces that season-S stats
  cannot change any season-S feature).
* Membership, `espn_roster_snapshot` (2026-27 on): latest `roster-archive` snapshot holding the
  team captured strictly before the team's first tip. PIT (`membership_pit = true`).
* Membership, `box_appearance_proxy` (2006-2026): players who logged minutes for the team in S.
  No free historical preseason rosters exist, so this uses hindsight about WHO played (never how
  well): `membership_pit = false`. Misses never-used players, adds mid-season arrivals.
* A transfer is a rostered player whose largest S-1 minutes were for another team. Before the
  2021 one-time-transfer rule, sit-out transfers have no S-1 minutes and are not counted.

## Inputs
* Player boxes: `sift-data-vault/archives/CBB/espn_player_box_pbp_early_seasons` (sportsdataverse
  ESPN, 2003-2027; 2027 through 2026-11-15). ESPN athlete ids are shared with the roster capture.
* Rosters: `roster-archive` `snapshots/YYYY/MM/DD/*.jsonl` (ESPN public team-roster endpoint,
  captured by the existing roster-capture workflow since 2026-10-05).

## Run
    python scripts/research/build_preseason_roster_features.py --box-dir <player_box dir> \
        --seasons 2006-2027 --snapshots 2027=<dir of roster snapshot jsonl> --out <dir>
Writes `preseason_roster_features.parquet` and `coverage_report.json` (per-season D-I team counts,
identity match rate of rostered non-freshmen to D-I box history, and for snapshot seasons the
agreement between the appearance proxy and the official roster).

## Coverage observed (2026-11-18 build)
* 2006-2026: 327-364 D-I teams per season (proxy membership).
* 2026-27: 364 D-I teams with S-1 stats (365 rostered), 5,528 rostered players; 81.7% of
  non-freshman rostered players match a prior D-I box record (rest: redshirts, JUCO / D-II /
  international arrivals). 98.8% of players seen in 2026-27 boxes were on the preseason roster;
  87.3% of rostered players have appeared so far.
