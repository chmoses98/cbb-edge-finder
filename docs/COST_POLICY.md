# Cost Policy

**Default: PAID / METERED DATA = DO NOT USE.** A paid source being configured in an
environment is not permission to use it.

## Mechanism

* `cbb_edge/data/cost_policy.py` classifies every external source:
  `FREE_BULK`, `FREE_RATE_LIMITED`, `UNKNOWN_COST`, `PAID_METERED`.
* `cbb_edge/data/http.py::fetch` is the **only** code path that performs network I/O.
  It calls `cost_policy.authorize()` before every attempt, including retries.
  `tests/test_cost_policy.py::test_http_clients_only_imported_by_chokepoint` fails the
  build if any other module imports `requests`, `httpx`, `urllib3`, `aiohttp`,
  `urllib.request` or `http`.
* Unregistered hosts are treated as `UNKNOWN_COST` and refused.
* A URL whose host belongs to a gated source is refused even if the caller labels it as
  a free source (no "laundering").
* Gated sources (`UNKNOWN_COST`, `PAID_METERED`) need BOTH `<ALLOW_ENV>=true` AND
  `<BUDGET_ENV>` > 0. A budget of `0` is a hard block. The budget is a **lifetime** cap,
  counted in a persistent ledger (`$CBB_DATA_DIR/_cost/request_ledger.jsonl`), and the
  request is reserved in the ledger *before* it is sent. Query strings (API keys) are
  never written to the ledger.

| Source | Class | Flags (defaults) |
|---|---|---|
| The Odds API | PAID_METERED | `ALLOW_PAID_ODDS_API=false`, `ODDS_API_MAX_REQUESTS=0` |
| CollegeBasketballData | UNKNOWN_COST | `ALLOW_CBBD=false`, `CBBD_MAX_REQUESTS=0` |
| KenPom / SportsDataIO / Sportradar | PAID_METERED | `ALLOW_PAID_*=false`, budget 0 |

## Proof that default configuration makes zero paid requests

* `tests/conftest.py` blocks all sockets for the whole test session and records attempts.
* `test_fetch_never_sends_paid_request_by_default`: `requests.Session.get/send` are
  asserted never called for The Odds API; the ledger stays at 0.
* `test_odds_api_client_refuses_with_default_config`: the optional client refuses.
* `test_all_paid_sources_blocked_by_default`, `test_allow_flag_without_budget_is_hard_block`,
  `test_budget_without_allow_flag_is_blocked`, `test_budget_is_lifetime_and_enforced`.
* `test_workflows_never_enable_paid_sources`: every workflow must run
  `python -m cbb_edge.data.cost_policy audit` and must not reference the Odds API host,
  key, or enable the flag.
* Every workflow sets the four flags to their safe values in `env:` and runs the audit
  first; the audit exits non-zero if any gated source is enabled.

## Caching ("never pay twice")

Every response is written once under `$CBB_DATA_DIR/bronze/<source>/…` with a sidecar
`.meta.json` (source, URL, redacted params, retrieved_at, sha256, bytes, schema_version).
A cached file is returned without touching the network. 404s are cached too. Bulk files
are recorded in committed manifests under `manifests/bronze/`.

## Requesting paid data

Use `docs/PAID_DATA_REQUESTS.md`. Nothing is consumed until the owner approves the
exact request, and then only by setting the flag + a finite budget for that run.
