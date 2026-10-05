# Model families

| Family | Purpose | Inputs | Default? |
|---|---|---|---|
| **PURE_BASKETBALL** | the projection engine | results, box scores, possessions, lineups/stints, players, schedule, venue/site | **yes** — Sift, prospective archive, reports |
| MARKET_BENCHMARK | "how close are we to the market?" | free closing lines (ESPN pickcenter), later Kalshi | never an input |
| MARKET_ENSEMBLE | diagnostic only | PURE + market | never |

Objective: the most accurate independent projection. The market is an external
benchmark (`market_gap = PURE RMSE − MARKET RMSE`) and later a comparison layer; it is
never a predictive input. Features are never selected by historical ATS results.

## Enforcement (CI)

1. `tests/test_market_independence.py::test_pure_modules_never_import_market_code` —
   modules listed in `cbb_edge/model/families.py::PURE_PACKAGES` cannot import
   `cbb_edge.market` or `cbb_edge.kalshi`.
2. `assert_pure_frame` rejects any PURE input frame with a market-looking column
   (spread, total_close, moneyline, kalshi, yes_bid, odds, implied, consensus, ESPN WP …).
3. `test_pure_projection_bit_identical_after_market_mutation` — run PURE projections,
   overwrite every stored line, ESPN pregame probability and Kalshi price with random
   values, rerun: projections must be bit-identical.
4. `test_sift_projection_unchanged_by_market_block` — the Sift `projection` block never
   depends on the `market` block.

## Data flow

```text
free basketball data -> silver -> PURE_BASKETBALL -> projection distribution (archived)
                                                          |
Kalshi / free lines ------------------------------------> compare (cbb_edge/market/compare.py)
                                                          -> disagreement
```
