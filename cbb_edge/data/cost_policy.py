"""Centralized cost policy: the ONLY authority on whether an external request may run.

Every outbound request in this repository goes through :func:`authorize` (via
``cbb_edge.data.http.fetch``). A static test (``tests/test_cost_policy.py``) enforces
that no other module imports an HTTP client, so this module is a true chokepoint.

Classification
--------------
FREE_BULK          allowed (bulk files downloaded once and cached forever).
FREE_RATE_LIMITED  allowed, with caching + per-source minimum request spacing.
UNKNOWN_COST       blocked until audited: needs ``allow_env == "true"`` AND a positive
                   request budget (``budget_env``).
PAID_METERED       blocked unless explicitly authorized by the owner: needs
                   ``allow_env == "true"`` AND a positive request budget. A budget of
                   0 (the default) is a HARD block. Requests are counted in a persistent
                   ledger, so the budget is a lifetime cap, not per-process.

Hosts that are not registered at all are treated as UNKNOWN_COST and blocked.
A request is also blocked if its host belongs to a paid source, regardless of which
source key the caller claims (prevents mislabelling a paid URL as "free").

CLI::

    python -m cbb_edge.data.cost_policy audit     # fail (exit 1) if env enables paid use
    python -m cbb_edge.data.cost_policy table     # print the source registry
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit


class CostClass(StrEnum):
    FREE_BULK = "FREE_BULK"
    FREE_RATE_LIMITED = "FREE_RATE_LIMITED"
    UNKNOWN_COST = "UNKNOWN_COST"
    PAID_METERED = "PAID_METERED"


GATED_CLASSES = frozenset({CostClass.UNKNOWN_COST, CostClass.PAID_METERED})


class CostPolicyViolation(PermissionError):
    """Raised when a request would violate the free-first cost policy."""


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    cost_class: CostClass
    hosts: tuple[str, ...]
    min_interval_s: float = 0.0
    allow_env: str | None = None
    budget_env: str | None = None
    notes: str = ""


# official athletics domains allowed for the roster-truth fallback (explicit allowlist;
# a school is added only when its structured sources are stale or in conflict)
SCHOOL_HOSTS: tuple[str, ...] = ("goduke.com", "bceagles.com", "umterps.com")

SOURCES: dict[str, SourceSpec] = {
    s.key: s
    for s in (
        SourceSpec(
            "sportsdataverse_releases",
            "SportsDataverse / hoopR GitHub release assets",
            CostClass.FREE_BULK,
            (
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            ),
            min_interval_s=0.25,
            notes="Public GitHub release assets (parquet). Bulk, free, cached permanently.",
        ),
        SourceSpec(
            "github_raw",
            "raw.githubusercontent.com (public repo files)",
            CostClass.FREE_RATE_LIMITED,
            ("raw.githubusercontent.com",),
            min_interval_s=0.08,
            notes="Public repo files, e.g. hoopR-mbb-raw per-game ESPN JSON (odds).",
        ),
        SourceSpec(
            "espn_public",
            "ESPN public site/core APIs",
            CostClass.FREE_RATE_LIMITED,
            ("site.api.espn.com", "sports.core.api.espn.com", "site.web.api.espn.com"),
            min_interval_s=1.0,
            notes="Unofficial, free. Prefer SportsDataverse bulk copies of the same data.",
        ),
        SourceSpec(
            "ncaa_stats",
            "stats.ncaa.org (official NCAA statistics / rosters)",
            CostClass.FREE_RATE_LIMITED,
            ("stats.ncaa.org",),
            min_interval_s=5.0,
            notes="Official NCAA. Roster-truth fallback only; cached; >= 5 s between requests.",
        ),
        SourceSpec(
            "school_athletics",
            "Official school athletics sites (roster pages, fallback only)",
            CostClass.FREE_RATE_LIMITED,
            SCHOOL_HOSTS,
            min_interval_s=5.0,
            notes="Only for teams whose structured sources are stale or conflict; explicit "
            "host allowlist (cbb_edge/rosters/school_sites.py); cached; >= 5 s spacing.",
        ),
        SourceSpec(
            "kalshi_public",
            "Kalshi public market-data API (read-only, unauthenticated)",
            CostClass.FREE_RATE_LIMITED,
            ("api.elections.kalshi.com", "trading-api.kalshi.com", "api.kalshi.com"),
            min_interval_s=0.12,
            notes="Free read-only endpoints. No orders are ever placed by this repo.",
        ),
        SourceSpec(
            "torvik",
            "Bart Torvik (barttorvik.com)",
            CostClass.FREE_RATE_LIMITED,
            ("barttorvik.com", "www.barttorvik.com"),
            min_interval_s=3.0,
            notes="Benchmark only. Final-season ratings must never leak into history.",
        ),
        SourceSpec(
            "sports_reference",
            "Sports Reference / College Basketball Reference",
            CostClass.FREE_RATE_LIMITED,
            ("www.sports-reference.com", "sports-reference.com"),
            min_interval_s=3.5,  # SR asks for <= 20 requests/minute
            notes="Validation source. Respect the published rate limit; cache everything.",
        ),
        SourceSpec(
            "cbbd",
            "CollegeBasketballData.com API",
            CostClass.UNKNOWN_COST,
            ("api.collegebasketballdata.com",),
            min_interval_s=1.0,
            allow_env="ALLOW_CBBD",
            budget_env="CBBD_MAX_REQUESTS",
            notes="API-key quota per plan. Gated until the owner confirms plan/quota.",
        ),
        SourceSpec(
            "the_odds_api",
            "The Odds API",
            CostClass.PAID_METERED,
            ("api.the-odds-api.com", "the-odds-api.com"),
            allow_env="ALLOW_PAID_ODDS_API",
            budget_env="ODDS_API_MAX_REQUESTS",
            notes="PAID quota. Disabled by default; zero budget is a hard block.",
        ),
        SourceSpec(
            "kenpom",
            "KenPom (subscription)",
            CostClass.PAID_METERED,
            ("kenpom.com", "www.kenpom.com"),
            allow_env="ALLOW_PAID_KENPOM",
            budget_env="KENPOM_MAX_REQUESTS",
            notes="Paid subscription. Not used.",
        ),
        SourceSpec(
            "sportsdataio",
            "SportsDataIO",
            CostClass.PAID_METERED,
            ("api.sportsdata.io",),
            allow_env="ALLOW_PAID_SPORTSDATAIO",
            budget_env="SPORTSDATAIO_MAX_REQUESTS",
            notes="Paid. Not used.",
        ),
        SourceSpec(
            "sportradar",
            "Sportradar",
            CostClass.PAID_METERED,
            ("api.sportradar.com", "api.sportradar.us"),
            allow_env="ALLOW_PAID_SPORTRADAR",
            budget_env="SPORTRADAR_MAX_REQUESTS",
            notes="Paid. Not used.",
        ),
    )
}


def _host(url: str) -> str:
    host = urlsplit(url).hostname
    if not host:
        raise CostPolicyViolation(f"URL has no host: {url!r}")
    return host.lower()


def _host_matches(host: str, pattern: str) -> bool:
    return host == pattern or host.endswith("." + pattern)


def source_for_host(host: str) -> SourceSpec | None:
    """Return the registered source owning ``host`` (paid sources checked first)."""
    ordered = sorted(SOURCES.values(), key=lambda s: s.cost_class not in GATED_CLASSES)
    for spec in ordered:
        if any(_host_matches(host, p) for p in spec.hosts):
            return spec
    return None


def _env_true(name: str | None) -> bool:
    if not name:
        return False
    return os.environ.get(name, "false").strip().lower() in {"1", "true", "yes"}


def _env_budget(name: str | None) -> int:
    if not name:
        return 0
    raw = os.environ.get(name, "0").strip()
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Persistent request ledger (lifetime budget for gated sources)
# ---------------------------------------------------------------------------
_LEDGER_LOCK = threading.Lock()


def ledger_path() -> Path:
    root = Path(os.environ.get("CBB_DATA_DIR", "data"))
    return root / "_cost" / "request_ledger.jsonl"


def ledger_count(source_key: str) -> int:
    path = ledger_path()
    if not path.exists():
        return 0
    n = 0
    with path.open() as fh:
        for line in fh:
            if line.strip() and json.loads(line).get("source") == source_key:
                n += 1
    return n


def _ledger_append(record: dict[str, object]) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


@dataclass(frozen=True)
class Authorization:
    source: SourceSpec
    url: str
    gated: bool


def authorize(source_key: str, url: str, *, record: bool = True) -> Authorization:
    """Authorize one request or raise :class:`CostPolicyViolation`.

    Must be called immediately before every network request. For gated sources the
    request is reserved in the ledger *before* it is sent, so a crash mid-request still
    counts against the budget (fail-safe toward over-counting, never under-counting).
    """
    if source_key not in SOURCES:
        raise CostPolicyViolation(f"Unregistered source {source_key!r}; register it first.")
    declared = SOURCES[source_key]
    host = _host(url)
    owner = source_for_host(host)
    if owner is None:
        raise CostPolicyViolation(
            f"Host {host!r} is not registered (treated as UNKNOWN_COST). Audit it and "
            "add it to cost_policy.SOURCES before use."
        )
    if owner.key != declared.key:
        # Release-asset CDNs are shared by several free sources, but a paid host never is.
        if owner.cost_class in GATED_CLASSES or declared.cost_class in GATED_CLASSES:
            raise CostPolicyViolation(
                f"URL host {host!r} belongs to {owner.key!r} ({owner.cost_class}), "
                f"not the declared source {declared.key!r}."
            )
    spec = owner if owner.cost_class in GATED_CLASSES else declared
    gated = spec.cost_class in GATED_CLASSES
    if gated:
        with _LEDGER_LOCK:
            if not _env_true(spec.allow_env):
                raise CostPolicyViolation(
                    f"{spec.name} is {spec.cost_class}. Blocked: {spec.allow_env} is not "
                    "'true'. Owner approval is required before any use."
                )
            budget = _env_budget(spec.budget_env)
            if budget <= 0:
                raise CostPolicyViolation(
                    f"{spec.name} is {spec.cost_class}. Blocked: {spec.budget_env}=0 is a "
                    "hard block."
                )
            used = ledger_count(spec.key)
            if used >= budget:
                raise CostPolicyViolation(
                    f"{spec.name} budget exhausted ({used}/{budget} lifetime requests)."
                )
            _ledger_append(_ledger_record(spec, url, gated=True))
    elif record:
        _ledger_append(_ledger_record(spec, url, gated=False))
    return Authorization(source=spec, url=url, gated=gated)


def _ledger_record(spec: SourceSpec, url: str, *, gated: bool) -> dict[str, object]:
    parts = urlsplit(url)
    # Never persist query strings: they may carry API keys.
    return {
        "ts": datetime.now(UTC).isoformat(),
        "source": spec.key,
        "cost_class": str(spec.cost_class),
        "host": parts.hostname,
        "path": parts.path,
        "gated": gated,
    }


def paid_sources_enabled() -> list[str]:
    """Names of gated sources whose env flags would currently permit a request."""
    out = []
    for spec in SOURCES.values():
        if spec.cost_class in GATED_CLASSES:
            if _env_true(spec.allow_env) or _env_budget(spec.budget_env) > 0:
                out.append(spec.key)
    return out


def assert_safe_environment() -> None:
    """Raise if any gated source is enabled. Run first in every CI / scheduled workflow."""
    enabled = paid_sources_enabled()
    if enabled:
        raise CostPolicyViolation(
            "Gated (paid/unknown-cost) sources are enabled in this environment: "
            + ", ".join(enabled)
        )


def _main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "audit"
    if cmd == "audit":
        try:
            assert_safe_environment()
        except CostPolicyViolation as exc:
            print(f"COST AUDIT FAILED: {exc}")
            return 1
        print("COST AUDIT OK: no paid or unknown-cost source is enabled.")
        for key in ("the_odds_api", "cbbd"):
            spec = SOURCES[key]
            print(
                f"  {spec.key}: {spec.allow_env}={os.environ.get(spec.allow_env or '', 'unset')}"
                f" {spec.budget_env}={os.environ.get(spec.budget_env or '', 'unset')}"
                f" lifetime_requests={ledger_count(spec.key)}"
            )
        return 0
    if cmd == "table":
        for spec in SOURCES.values():
            print(f"{spec.key:26s} {spec.cost_class:18s} {', '.join(spec.hosts)}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
