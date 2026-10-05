# Architecture

```text
external (free)                 bronze (immutable)          silver                 research
-----------------------------   ------------------------    --------------------   ----------------------
SportsDataverse releases  --->  bronze/sportsdataverse_     games.parquet          states_*.parquet
  (FREE_BULK)                     releases/<dataset>/       team_games.parquet     (pregame rating
hoopR-mbb-raw JSON odds   --->  bronze/github_raw/          player_games.parquet    states per game)
  (FREE_RATE_LIMITED)             espn_lines/               espn_pregame.parquet   predictions.parquet
Kalshi public API         --->  kalshi snapshots            (+ canonical IDs)      metrics.json
  (FREE_RATE_LIMITED)             (kalshi-archive branch)                          reports/*.md
        ^
        | every request: cbb_edge.data.http.fetch -> cost_policy.authorize -> cache
```

* `$CBB_DATA_DIR` (default `data/`, gitignored) is the data lake. Git holds code,
  manifests (`manifests/bronze/*.jsonl`: URL, sha256, bytes, retrieved_at, schema),
  the team registry (`cbb_edge/data/ids/*.csv`), small research outputs, and docs.
* Rebuild from scratch:

```bash
pip install -e ".[dev]"
python -m cbb_edge.data.cost_policy audit
python -m cbb_edge.data.bronze.sportsdataverse schedules team_box player_box team_crosswalk --seasons 2006-2027
python -m cbb_edge.data.bronze.sportsdataverse pbp --seasons 2015-2026        # ESPN pregame WP benchmark
python -m cbb_edge.market.espn_lines 2026 2023 2022 2021 2020 2019 2018       # free closing lines
python -m cbb_edge.data.silver.build --seasons 2006-2027
python scripts/research/tune_dev.py                                           # DEV seasons only
python scripts/research/roster_prior_dev.py                                   # DEV seasons only
python scripts/backtest/run_baseline.py                                       # walk-forward study
python -m cbb_edge.app.project --season 2027 --as-of 2026-11-01T00:00:00Z     # Sift records
```

## Package map

| Module | Role |
|---|---|
| `cbb_edge/data/cost_policy.py` | source registry, cost classes, gate, ledger, CI audit |
| `cbb_edge/data/http.py` | the single network chokepoint + immutable cache |
| `cbb_edge/data/bronze/` | bulk downloaders + manifests |
| `cbb_edge/data/ids/` | canonical team registry (`T0001…`), exact source-scoped aliases, unresolved log |
| `cbb_edge/data/silver/build.py` | canonical games / team-games / player-games with `available_at` |
| `cbb_edge/features/possessions.py` | possessions, tempo, raw Four Factors, box sanity flags |
| `cbb_edge/ratings/adjusted.py` | prior-anchored opponent-adjusted ridge solver (all stats) |
| `cbb_edge/backtest/walkforward.py` | day-by-day replay engine, priors, roster continuity |
| `cbb_edge/model/arms.py`, `elo.py` | research arms B0–B5, Elo, win-prob link, uncertainty |
| `cbb_edge/backtest/evaluate.py` | MAE/RMSE/bias, log loss/Brier, calibration, Wilson CIs |
| `cbb_edge/market/` | ESPN line harvest/parse, ESPN pregame WP, optional (blocked) Odds API |
| `cbb_edge/kalshi/` | read-only discovery, taxonomy, full-board snapshot capture |
| `cbb_edge/app/` | Sift output schema + projector for upcoming games |

## Identity

* Teams: `T` + 4 digits, assigned once (ordered by first D-I season, then ESPN id) and
  never renumbered. Crosswalk columns: ESPN id/slug/names/abbreviation, Torvik name,
  KenPom name, Fox id, conference, first/last D-I season, `kalshi_code` and
  `sports_reference_slug` (to be filled from captured data — never by fuzzy matching).
* Non-D-I opponents get no canonical id; their games are excluded from ratings.
* Players: `P` + ESPN athlete id (ESPN is the only player source modeled so far; NCAA
  lineup data uses NCAA player ids and will be crosswalked via the SDV player crosswalk
  plus team-season-jersey exact keys).
* Joins between sources are on ids, never loose strings. `resolve()` is exact on a
  normalized string, source-scoped; misses and ambiguities are logged and return `None`.

## Information timing

Every silver row carries `available_at` (start + 3 h for results). The engine's
information set for day D is `available_at < first tip-off of D`. See `docs/LEAKAGE.md`.
