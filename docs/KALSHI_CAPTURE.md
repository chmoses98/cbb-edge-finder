# Kalshi CBB Capture

Read-only. No authentication, no orders, ever.

* Workflow: `.github/workflows/kalshi-capture.yml`.
  * Season (Nov–Apr): every 30 minutes. Offseason: every 6 hours.
  * Each run: discover men's CBB series → page all `open` + `unopened` markets and every
    market that closed in the last 72 h (so settlement results are archived) → top-of-book
    for all, order books (depth 10) for markets closing within 6 h → one immutable gzipped
    JSONL snapshot + a summary (counts by family/status/series).
  * Scheduled/dispatched runs commit the snapshot to the `kalshi-archive` branch
    (`snapshots/YYYY/MM/DD/kalshi_cbb_<UTC>.jsonl.gz`). PR runs only upload an artifact.
  * Cost: Kalshi public data is free; GitHub Actions minutes are free for public repos.
    Scheduled workflows only run from the default branch, so **the archive starts when
    this PR is merged** (or a maintainer dispatches the workflow on `main`).
* Discovery: `cbb_edge/kalshi/taxonomy.py` (`is_cbb_series`) — ticker and title rules,
  excluding women's basketball, college baseball and other NCAA men's sports.
* Families: GAME_WINNER, SPREAD, TOTAL, TEAM_TOTAL, HALF, PLAYER_PROP,
  FUTURES_CHAMPION / FINAL_FOUR / CONFERENCE / SEED / OTHER, OTHER.
* Snapshot record (`kalshi-snapshot-v1`): `captured_at`, `series_ticker`, `family`,
  `status_query`, raw `market` payload (all API fields preserved), optional `orderbook`.
* First live run (2026-10-04, PR run): 3,259 markets / 121 events (pre-fix taxonomy,
  included some non-basketball NCAA series). Board was futures-only; 2026-27 game
  markets were not yet listed.

## Next steps

* Map Kalshi game markets to canonical games: parse event tickers
  (`KXNCAAMBGAME-<YYMONDD><AWAY><HOME>`) into date + team codes and resolve codes through
  `teams.resolve(code, "kalshi")` using aliases learned from settled markets (exact only;
  unresolved codes are logged for manual mapping into `teams.csv: kalshi_code`).
* Model-vs-market: `cbb_edge.kalshi.taxonomy.yes_mid_cents` → implied probability; compare
  with projected win probability / spread-cover probability from the margin distribution.
