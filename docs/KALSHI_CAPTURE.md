# Kalshi CBB Capture, Identity and Projection History

Read-only; free public market-data endpoints. **No authentication or orders.** Model training
and betting authorization are outside this capture pipeline.

## Market completeness and immutable evidence

* Workflow: `.github/workflows/kalshi-capture.yml`, season schedule every 30 minutes
  (GitHub cron is best effort, not an SLA). Offseason every 6 hours.
* Discover every men's CBB series by transparent ticker/title rules; exclude women's
  basketball and other sports. Page every open/unopened market and recently closed
  contracts; preserve one raw API payload per ticker per run.
* Every snapshot is an immutable `kalshi-snapshot-v1` gzipped JSONL partition on
  `kalshi-archive` (`snapshots/YYYY/MM/DD/kalshi_cbb_<UTC>.jsonl.gz`), with
  counts by family and market status. Results and settlements are preserved when
  observed. The archive never silently drops markets that cannot match a game.
* Capture public event metadata (`/events`) for the dated game-contract series:
  `event.title`, `event.sub_title`, event ticker and raw event context are preserved
  alongside the original market. Enrichment failures are counted, with a fallback
  to the unchanged raw contract; enrichment must never destroy the market snapshot.
* Capture public bid/ask price, available sizes, volume, open interest, strike and
  status. **Full-depth orderbooks are not promised by the anonymous API**; the
  scheduled job does not request authenticated depth.
* **Self-chaining.** GitHub drops most scheduled ticks under load (about 4% of expected in 24 h on
  2026-11-04), so after each SUCCESSFUL production capture the job waits 12 minutes and dispatches the
  next one (`Chain the next capture`). It never chains from pull-request runs or failed captures and
  skips when another capture is queued or running, so duplicate chains cannot multiply. Scheduled
  ticks, the push kickoff and the research-side stale check remain as additional starters.
* The snapshot *timestamp* (not scheduled cron time) is the ground truth.
  A missing/skipped run is a coverage gap, not a fabricated quote.

Observed 2026-11-02T12:57:26Z: 125 CBB series, 829 Kalshi events and **18,649
contract snapshots** (all family types, including futures). That is NOT 18,649
independent games or 18,649 potential bets.

## Canonical game mapping (fail closed)

`cbb_edge/kalshi/mapping.py` resolves a contract using:

1. The exact date embedded in the Kalshi event ticker, with a ±1 ET-day
   search window for late-night games.
2. Both opponent names in the **Kalshi event title** (more reliable than an
   individual YES-side title), resolved by source-aware canonical team aliases.
3. For older snapshots without event metadata, an *exact concatenated pair* of
   known team ticker codes (`kalshi_code` or ESPN abbreviation), corroborated
   by a unique scheduled two-team matchup near that event date.

An ambiguous or unresolved contract stays in the raw archive with a reason.
No fuzzy aliases, price-derived opponent guesses, or cross-game model joins.
CBB futures and season-win markets remain archived but have no single-game
projection. The app publisher exposes `extensions.cbb.market_mapping` counts
so an empty SIFT market screen is distinguishable from absent Kalshi data.

## Every-market, as-of projection panel

`cbb_edge/kalshi/history.py` joins **each contract in each captured snapshot**
to its unique canonical game and to the existing frozen prospective model
records **as of that capture's timestamp**. It NEVER refits, simulates or
reconstructs a model. Every model row has version, as-of, archive path, SHA,
home/away projected points, margin/total and uncertainty/win probability.

Every market row records original ticker/event/family, timestamp, market
bid/ask, strike, size, volume/open interest, status and settlement result,
identity mapping verdict, game tip and capture phase, plus all eligible
historical model versions. Records without a unique game or existing
pre-tip model remain present with an explicit null; no hindsight filling.

* Archive: `kalshi-panel-archive/panels/YYYY/MM/DD/<snapshot>.panel.jsonl.gz`
  and corresponding immutable summary JSON.
* Workflow: `.github/workflows/kalshi-market-panel.yml` after a successful
  Kalshi capture, hourly catch-up and manual dispatch; processes 12 missing
  snapshots at a time to recover skipped triggers. Never overwrites a panel.
* Schema `cbb-kalshi-model-panel-v2`. Each mapped row carries `contract_semantics`
  (market type, period, overtime treatment, subject side, exact strike, YES condition;
  parsed from the series spec and cross-checked against Kalshi's structured strike)
  and `market_specific_model_probability`: per prospective model version,
  `{probability, method_or_gap}`.
  * Probability is produced ONLY for full-game winner (`home_win_prob`), spread and
    total (the frozen model's own `Phi((margin-line)/margin_sd)` / total analogue).
    Team totals, halves (incl. ties), overtime and race markets stay `null` with an
    explicit gap (`no_half_distribution_in_frozen_model`, ...). A projected mean is
    never treated as a probability; non-game markets get no projection at all.
  * Scope: known per-game series (see `cbb_edge/kalshi/semantics.py::SERIES`) map to games;
    season awards, stat leaders, polls (`KXNCAAMBAPRANK-26DEC07R2` is a poll date), win
    totals and tournament futures are `non_game_market`: archived and counted, never joined.
  * Identity: event title, Kalshi `rules_primary` matchup text and exact ticker code pairs.
    Two sources that resolve to different matchups fail closed (`identity_sources_disagree`).
    Unmatched reasons: `one_team_unresolved` (usually a non-D-I exhibition opponent),
    `teams_unresolved`, `teams_resolved_no_scheduled_game`, `no_game_on_date`,
    `ambiguous_game`, `unparsed_event_ticker`, `unresolved_event_identity`.
* `python -m cbb_edge.kalshi.evaluate` audits snapshot cadence/gaps, snapshots lacking a
  panel partition, and validates the settlement parsers against Kalshi's own settled
  `result` using archived final scores (`--calibration` adds Brier/log loss for settled,
  last-pretip, priced contracts; it is a report, not an edge claim).
* PRETIP observations may be used for calibration; IN_PLAY_OR_POSTTIP and
  TIP_UNVERIFIED observations are explicitly separated. Do not score them
  against a static pregame forecast.

## Reproducible smoke test

```sh
python -m cbb_edge.data.cost_policy audit
pytest -q tests/test_kalshi.py tests/test_sift_app.py
python -m cbb_edge.kalshi.history --season 2027 \
  --projections arch/projections-archive --rosters arch/roster-archive \
  --scores arch/prospective-scores --schedule-archive arch/schedule-archive \
  --kalshi arch/kalshi-archive --out market_panel_out --all-missing
```

Acceptance: every output partition's row count equals its source snapshot's
market count; exact and unambiguous game joins only; no archived projection with
`as_of > captured_at` or after tip; futures remain visible but unjoined; and
the market coverage audit reports unmapped counts instead of pretending zero
markets exist.

**Next research layer:** explicit payoff parsing for game winner, spread,
total, team total, period and player props; compare *settled* per-contract
outcomes and executable prices **after fees**, stratified by horizon, model
version, uncertainty, market family, liquidity and availability. Track CLV,
Brier/calibration, log loss and realized ROI only from strictly prospective,
deduplicated observations. Do not promote a betting strategy from this
data collection alone.
