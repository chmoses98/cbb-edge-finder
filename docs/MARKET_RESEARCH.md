# Market-first CBB research engine

`cbb_edge/kalshi/research/` evaluates **every** observed Kalshi men's-CBB contract, whether or not it
was recommended, bet, or modelled. Authority is `RESEARCH_ONLY`: no orders, no authentication, no
model or strategy change. It reads only immutable archives and is independent of the SIFT/app
recommendation publisher.

## Datasets (linked by Kalshi ticker)

| # | Dataset | Source / output |
|---|---|---|
| 1 | Market universe | `latest/universe.jsonl.gz` - one row per ticker ever captured (raw payload stays in `kalshi-archive`; pointers: first/last snapshot) |
| 2 | Observations | `kalshi-archive` raw snapshots (bid/ask/size/volume/OI, status, times). Consecutive identical quotes are run-length merged in memory only |
| 3 | Predictions | `kalshi-panel-archive` frozen as-of probabilities (sha-pinned projection records); the engine uses the latest prediction frozen **at or before** each quote |
| 4 | Outcomes | Kalshi `result`/`settlement_ts`, cross-checked against official final scores in `schedule-archive` |
| 5 | Market evaluations | `latest/evaluations.jsonl.gz` (one row per contract x entry point) + `latest/matrix.json` |
| 6 | Bet evaluations | Not built: no wagers exist. Kept separate; nothing here depends on it |

## Independent status dimensions (never one mutually exclusive label)

`status.observation | mapping | support | model (+ missing capability) | outcome | official_check`,
plus overlapping `status_flags`: `EVALUATED` (valid pre-tip quote + binary outcome), `PARTIAL`,
`UNMODELED` (with the exact gap, e.g. `no_half_distribution_in_frozen_model`), `UNSETTLED`,
`UNMATCHED`, `UNSUPPORTED`, `UNOBSERVABLE`. Contracts are never removed from the universe.

## Entry points and honesty rules

`OPEN` (first usable capture; `open_observed_late_minutes` reports the gap since listing), `H24/H6/H1`
(last capture at least that long before tip, or before close for non-game markets), `CLOSE` (last
capture before `min(tip, close_time)`, with `staleness_min`). A horizon with no real capture is
**missing**, never interpolated. Post-tip quotes are never scored. Contracts without a verified tip
(unmatched games) carry `tip_verified=false` and are excluded from headline scoring.

## Fees, fills, CLV (`fees.py`)

* Quote, raw fill, fee, total cost, close price and payout are separate fields.
* Fee = `ceil_to_cent(multiplier * 0.07 * C * P * (1-P))` (taker; maker uses 0.0175 and only on
  series Kalshi lists with maker fees). Rules are versioned and effective-dated (`FeeRule`,
  `rule_for`). **Verification status:** kalshi.com and the API host are unreachable from the
  development sandbox, so the general formula is corroborated only by third-party summaries. The
  capture workflow now stores each series' `fee_type`/`fee_multiplier` from the Kalshi API in every
  snapshot row (`series_meta`) and the raw `/series/fee_changes` response in the snapshot summary.
  When a contract's series carries them the evaluation uses them (`fee_basis = series_api`);
  otherwise it falls back to the default and says so (`fee_basis = assumed_default`). `flat`/unknown
  fee types are `FEE_UNSUPPORTED` (no ROI is computed). Every row stores `fee_rule` and `fee_basis`.
* `Execution` keeps `quote`, raw `fill`, `fee_total`, `total_cash`, Kalshi's fee-inclusive average
  cost, `gross_roi`, `net_roi` and a `kind` (`actual_fill` vs `hypothetical_quote`).
  `execution_from_inclusive_display` recovers a raw fill from the fee-inclusive display or refuses.
* Hypothetical fill: taker order of 25 contracts at the best displayed price, filled only if the
  displayed top-of-book size covers it; BUY YES at `yes_ask` (size `yes_ask_size`), BUY NO at
  `1 - yes_bid` (size `yes_bid_size`). No partial fills, queue or impact. Anything else is
  `NO_QUOTE` / `INSUFFICIENT_DISPLAYED_SIZE` - never an invented fill.
* Gross CLV = closing side midpoint - raw entry price (includes crossing the spread);
  fee-adjusted CLV subtracts the entry fee once. Kalshi's fee-inclusive average cost must not be
  used as a raw fill: `raw_fill_from_inclusive` recovers it or refuses.
* Max acceptable entry price = highest cent price with `p - price - fee >= 0` for the model `p`.

## Aggregation without correlation inflation

Headline means are **cluster-weighted** (cluster = game, or event for non-game markets) with a
cluster-bootstrap 90% interval; contract-weighted means are reported beside them. Model-vs-market is
a paired comparison on the same contracts and quote. `confidence` is `LOW` (<30 clusters),
`MEDIUM` (<100), else `HIGH`.

## Pipelines (all existing workflows + this one)

capture (`kalshi-capture`, 15 min) -> frozen predictions (`prospective-projections`) -> as-of join
(`kalshi-market-panel`, hourly backfill) -> official results (`espn-line-capture`/schedule archive,
`prospective-scores`) -> **`market-research`** (after each panel run + hourly): rebuilds universe,
evaluations, matrix, opening-night audit, health monitor, dashboard and publishes to branch
`market-research` (`latest/` replaced, `daily/` append-only). `latest/health.json` lists capture
gaps, snapshots lacking panel partitions, stale capture and overdue settlements, each with the job
that repairs it (gaps themselves are irrecoverable and stay gaps).

Recovery: if `health.json` reports the newest snapshot older than 120 min, the workflow dispatches `kalshi-capture` once per run (scheduled ticks are frequently dropped by GitHub under load).

## Run locally

```sh
python -m cbb_edge.kalshi.research.run --kalshi arch/kalshi-archive \
  --panel arch/kalshi-panel-archive --schedule arch/schedule-archive --out research_out
```

Outputs: `latest/{universe,evaluations}.jsonl.gz`, `matrix.json`, `opening_night.{json,csv,md}`,
`health.json`, `dashboard.html` (filters: family, entry point/time before tip, game date, price
range, model version, quality tier; click a family for contract drill-down).

## Pretip gaps, panel integrity, pipeline monitor

* Every contract with no usable pre-tip quote gets one exclusive cause: `listed_after_tip_live_line_
  no_pregame_quote_exists` (not a capture problem and never reconstructed), `capture_gap_first_
  captured_after_tip`, `captured_pretip_but_book_empty_or_non_live_status`, `no_verified_tip`.
* `panel_audit.py` verifies, read-only, that every raw snapshot has a panel partition, row sets are
  identical, capture times match, and no projection version has `as_of` after the capture or (for
  PRETIP rows) after the tip. Results land in `health.json -> panel_integrity`.
* `monitor.py` turns `gh run list` into failed/cancelled-run findings and scheduler yield per
  pipeline (`health.json -> pipelines`).

## Known limits

* Anonymous API gives top-of-book only; no depth. Cadence is capture-limited (15 min target; gaps
  recorded in `health.json`).
* Half/overtime/team-total/race markets have no official score check (period scores are not
  archived) and no model probability; futures/awards/leaders have no model capability. They are still
  scored against price and Kalshi's settlement.
* No per-game player-prop series was observed in the archive as of the first build; player markets
  seen are awards/leaders (non-game). The engine discovers families dynamically and will inventory
  them if they appear.
