# cbb-edge-finder

A free-first research platform for NCAA Division I men's basketball projections.

**Status: research system.** It places no wagers, automatic or otherwise, and it does
not assume a betting edge exists. Prediction quality is measured before ROI.

## Principles

* **Free first.** The system uses only free, public or repository-hosted data.
  Paid and metered sources (The Odds API, CBBD quota, KenPom, …) are hard-blocked by
  `cbb_edge/data/cost_policy.py`. With the default configuration it makes zero paid
  requests, and the test suite proves this. See `docs/COST_POLICY.md`.
* **Opponent adjustment inside the fit.** Every predictive team statistic (efficiency,
  tempo, eFG%, TO%, ORB%, FTR, 2P%, 3P%, 3PA rate) is estimated jointly with opponent
  strength in a prior-anchored ridge regression. Strength of schedule is not added
  afterward. See `cbb_edge/ratings/adjusted.py`.
* **No leakage.** A day-by-day walk-forward engine builds each pregame state only from
  results available before tip-off, and automated tests verify it (`docs/LEAKAGE.md`).
* **Our own market archive.** Read-only Kalshi capture runs on a schedule, so we build
  a free price history from the day capture starts (`docs/KALSHI_CAPTURE.md`).

## Quick start

```bash
pip install -e ".[dev]"
python -m cbb_edge.data.cost_policy audit      # must print COST AUDIT OK
pytest                                          # network is blocked inside tests
```

The full rebuild (bronze → silver → tuning → backtest → Sift outputs) is in
`docs/ARCHITECTURE.md`.

## Docs

| Doc | What |
|---|---|
| `docs/DATA_SOURCE_AUDIT.md` | every source tested: coverage, IDs, limits, terms, cost |
| `docs/COST_POLICY.md` | cost classes, gates, ledger, proof of zero paid requests |
| `docs/PAID_DATA_REQUESTS.md` | paid data that might help, **awaiting owner approval** |
| `docs/ARCHITECTURE.md` | data lake layout, package map, identity, rebuild commands |
| `docs/LEAKAGE.md` | leakage risks and the tests that guard each one |
| `docs/KALSHI_CAPTURE.md` | Kalshi discovery, taxonomy, snapshot archive |
| `docs/SIFT_SCHEMA.md` | stable output contract for Sift Sports Intelligence |
| `docs/SIFT_APP.md` | the `edge_finder.app.v1` publication Sift reads (`app-data` branch), projection selection rules |
| `research/REGISTRY.md` | season roles, arms, preregistered hypotheses |
| `research/reports/BASELINE.md` | PR #1 walk-forward results |
| `research/reports/WAVE2.md` | wave-2 PURE_BASKETBALL results (player, shot, context, pace, uncertainty, residuals) |
| `docs/MODEL_FAMILIES.md` | PURE_BASKETBALL vs market separation and its CI enforcement |
| `docs/PROSPECTIVE.md` | immutable 2026–27 projection archive |
