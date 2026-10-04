"""Cost-control tests: paid sources can never be invoked with default configuration."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest import mock

import pytest
import requests

from cbb_edge.data import cost_policy, http
from cbb_edge.data.cost_policy import CostClass, CostPolicyViolation, authorize
from cbb_edge.market import odds_api

REPO = Path(__file__).resolve().parents[1]
ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds"


def test_every_source_is_classified():
    for spec in cost_policy.SOURCES.values():
        assert isinstance(spec.cost_class, CostClass)
        assert spec.hosts
        if spec.cost_class in cost_policy.GATED_CLASSES:
            assert spec.allow_env and spec.budget_env


def test_odds_api_is_paid_and_gated():
    spec = cost_policy.SOURCES["the_odds_api"]
    assert spec.cost_class is CostClass.PAID_METERED
    assert spec.allow_env == "ALLOW_PAID_ODDS_API"
    assert spec.budget_env == "ODDS_API_MAX_REQUESTS"


def test_default_env_blocks_odds_api():
    with pytest.raises(CostPolicyViolation):
        authorize("the_odds_api", ODDS_URL)


def test_allow_flag_without_budget_is_hard_block(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_ODDS_API", "true")
    monkeypatch.setenv("ODDS_API_MAX_REQUESTS", "0")
    with pytest.raises(CostPolicyViolation, match="hard block"):
        authorize("the_odds_api", ODDS_URL)


def test_budget_without_allow_flag_is_blocked(monkeypatch):
    monkeypatch.setenv("ODDS_API_MAX_REQUESTS", "50")
    with pytest.raises(CostPolicyViolation):
        authorize("the_odds_api", ODDS_URL)


def test_budget_is_lifetime_and_enforced(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_ODDS_API", "true")
    monkeypatch.setenv("ODDS_API_MAX_REQUESTS", "2")
    authorize("the_odds_api", ODDS_URL)
    authorize("the_odds_api", ODDS_URL)
    with pytest.raises(CostPolicyViolation, match="exhausted"):
        authorize("the_odds_api", ODDS_URL)
    assert cost_policy.ledger_count("the_odds_api") == 2


def test_paid_host_cannot_be_laundered_through_free_source():
    with pytest.raises(CostPolicyViolation):
        authorize("github_raw", ODDS_URL)
    with pytest.raises(CostPolicyViolation):
        authorize("kalshi_public", "https://api.the-odds-api.com/v4/sports")


def test_unknown_host_blocked():
    with pytest.raises(CostPolicyViolation, match="not registered"):
        authorize("github_raw", "https://some-random-odds-vendor.example.com/x")


def test_unknown_cost_source_blocked_by_default():
    with pytest.raises(CostPolicyViolation):
        authorize("cbbd", "https://api.collegebasketballdata.com/games")


def test_all_paid_sources_blocked_by_default():
    for spec in cost_policy.SOURCES.values():
        if spec.cost_class in cost_policy.GATED_CLASSES:
            with pytest.raises(CostPolicyViolation):
                authorize(spec.key, f"https://{spec.hosts[0]}/anything")


def test_free_source_allowed():
    a = authorize("kalshi_public", "https://api.elections.kalshi.com/trade-api/v2/series")
    assert not a.gated


def test_fetch_never_sends_paid_request_by_default():
    """The critical test: the HTTP layer refuses BEFORE any request object is sent."""
    with (
        mock.patch.object(requests.Session, "get") as sget,
        mock.patch.object(requests.Session, "send") as ssend,
    ):
        with pytest.raises(CostPolicyViolation):
            http.fetch("the_odds_api", ODDS_URL, {"apiKey": "x"})
        sget.assert_not_called()
        ssend.assert_not_called()
    assert cost_policy.ledger_count("the_odds_api") == 0


def test_odds_api_client_refuses_with_default_config():
    with mock.patch.object(requests.Session, "get") as sget:
        with pytest.raises(CostPolicyViolation):
            odds_api.get_odds()
        with pytest.raises(CostPolicyViolation):
            odds_api.get_historical_odds("2025-01-15T00:00:00Z")
        sget.assert_not_called()


def test_assert_safe_environment_default_ok():
    cost_policy.assert_safe_environment()


def test_assert_safe_environment_detects_enabled(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_ODDS_API", "true")
    with pytest.raises(CostPolicyViolation):
        cost_policy.assert_safe_environment()
    assert cost_policy._main(["audit"]) == 1


def test_ledger_never_stores_query_strings(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_ODDS_API", "true")
    monkeypatch.setenv("ODDS_API_MAX_REQUESTS", "1")
    authorize("the_odds_api", ODDS_URL + "?apiKey=SECRET123")
    text = cost_policy.ledger_path().read_text()
    assert "SECRET123" not in text
    assert json.loads(text.splitlines()[0])["gated"] is True


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0] if node.level == 0 else "")
            if node.module.startswith("urllib.request"):
                mods.add("urllib.request")
    return mods


def test_http_clients_only_imported_by_chokepoint():
    """No module except cbb_edge/data/http.py may import an HTTP client."""
    banned = {"requests", "httpx", "urllib3", "aiohttp", "urllib.request", "http"}
    offenders = []
    for p in list((REPO / "cbb_edge").rglob("*.py")) + list((REPO / "scripts").rglob("*.py")):
        if p == REPO / "cbb_edge" / "data" / "http.py":
            continue
        mods = _imports(p)
        # 'http' collides with our own module name only via 'cbb_edge.data.http'
        bad = mods & banned
        if bad:
            offenders.append((str(p.relative_to(REPO)), sorted(bad)))
    assert not offenders, offenders


def test_workflows_never_enable_paid_sources():
    for wf in (REPO / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text()
        assert 'ALLOW_PAID_ODDS_API: "true"' not in text
        assert "ALLOW_PAID_ODDS_API=true" not in text
        assert "the-odds-api.com" not in text
        assert "ODDS_API_KEY" not in text
        # every workflow must run the cost audit before doing anything else
        assert "cbb_edge.data.cost_policy audit" in text, wf.name


def test_no_network_attempts_reached_paid_hosts():
    from tests.conftest import ATTEMPTS

    for _, addr in ATTEMPTS:
        assert "the-odds-api" not in str(addr)
