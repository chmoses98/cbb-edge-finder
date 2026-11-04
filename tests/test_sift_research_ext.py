"""SIFT research block: model probability, fee-adjusted edge and max price; never a bet authorization."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from cbb_edge.app.sift_app import build as B
from cbb_edge.app.sift_app.inputs import KalshiCapture
from cbb_edge.app.sift_app.quotes import classify_quote
from cbb_edge.app.sift_app.research_ext import research_block
from cbb_edge.kalshi.research import fees

NOW = datetime(2026, 11, 4, 20, tzinfo=UTC)
D = date(2026, 11, 4)
PROJ = {"margin": 8.0, "margin_sd": 10.0, "total": 145.0, "total_sd": 15.0, "home_win_prob": 0.79}
SPREAD = {
    "status": "parsed",
    "market_type": "MARGIN",
    "period": "FULL",
    "subject_side": "home",
    "strike": 3.5,
}


def live_quote(age=5):
    return classify_quote("OPEN", 0.60, 0.64, NOW - timedelta(minutes=age), NOW)


def test_supported_market_gets_probability_edge_and_max_price():
    b = research_block(
        SPREAD, PROJ, "pure-0.2.0", "2026-11-04T15:00:00+00:00", live_quote(), 0.60, 0.64, None, D
    )
    p = b["model_probability"]
    assert p == pytest.approx(0.5 * (1 + math.erf(0.45 / math.sqrt(2)))) and b["model_gap"] is None
    assert b["market_implied_probability"] == pytest.approx(0.62)
    yes = b["net_edge"]["yes"]
    assert yes["price"] == 0.64 and yes["net_edge"] == pytest.approx(
        p - fees.total_cost_per_contract(0.64, 25)
    )
    no = b["net_edge"]["no"]
    assert no["price"] == pytest.approx(0.40) and no["net_edge"] == pytest.approx(
        (1 - p) - fees.total_cost_per_contract(0.40, 25)
    )
    assert b["max_acceptable_price"]["yes"] < p and b["max_acceptable_price"]["yes"] is not None
    v = b["validation"]
    assert v["status"] == "RESEARCH_ONLY" and v["authorized_bet"] is False
    assert b["fee_basis"] == "assumed_default" and b["order_contracts"] == 25


def test_unsupported_market_stays_null_with_the_exact_gap():
    half = {
        "status": "parsed",
        "market_type": "TOTAL",
        "period": "1H",
        "strike": 70.5,
        "model_gap": "no_half_distribution_in_frozen_model",
    }
    b = research_block(half, PROJ, "pure-0.2.0", "t", live_quote(), 0.5, 0.55, None, D)
    assert (
        b["model_probability"] is None and b["model_gap"] == "no_half_distribution_in_frozen_model"
    )
    assert (
        b["net_edge"]["yes"]["net_edge"] is None
        and b["net_edge"]["yes"]["reason"] == "no_model_probability"
    )
    assert b["max_acceptable_price"] == {"yes": None, "no": None}
    nogame = research_block(SPREAD, None, None, None, live_quote(), 0.5, 0.55, None, D)
    assert nogame["model_gap"] == "no_pretip_frozen_projection_for_this_game"


def test_stale_or_empty_quotes_never_yield_a_tradable_edge():
    stale = classify_quote("OPEN", 0.60, 0.64, NOW - timedelta(minutes=200), NOW)
    b = research_block(SPREAD, PROJ, "v", "t", stale, 0.60, 0.64, None, D)
    assert (
        b["market_implied_probability"] is None
        and b["market_probability_reason"] == "quote_not_live"
    )
    assert (
        b["net_edge"]["yes"]["net_edge"] is None
        and b["net_edge"]["yes"]["reason"] == "quote_not_live_or_empty_side"
    )
    assert (
        b["model_probability"] is not None and b["max_acceptable_price"]["yes"] is not None
    )  # price ceiling stays
    empty = classify_quote("OPEN", 0.0, 1.0, NOW, NOW)
    assert (
        research_block(SPREAD, PROJ, "v", "t", empty, 0.0, 1.0, None, D)["net_edge"]["no"][
            "net_edge"
        ]
        is None
    )


def test_unknown_fee_type_refuses_to_state_an_edge():
    b = research_block(
        SPREAD,
        PROJ,
        "v",
        "t",
        live_quote(),
        0.60,
        0.64,
        {"fee_type": "flat", "fee_multiplier": 1},
        D,
    )
    assert (
        b["net_edge"]["yes"]["reason"] == "fee_rule_unsupported"
        and b["max_acceptable_price"]["yes"] is None
    )


def _part(pid, nm):
    return {"participant_id": pid, "display_name": nm, "short_name": nm, "metadata": {}}


def test_published_market_carries_the_research_block_next_to_the_quote_state():
    def ev():
        return {"event_id": "evt_test1", "home_participant": "prt_home1", "away_participant": "prt_away1",
                "participants": [_part("prt_home1", "Kansas"), _part("prt_away1", "Duke")]}  # fmt: skip

    raw = {
        "family": "GAME_WINNER", "series_ticker": "KXNCAAMBGAME",
        "market": {"ticker": "KXNCAAMBGAME-26NOV02DUKEKU-KU", "event_ticker": "KXNCAAMBGAME-26NOV02DUKEKU",
                   "title": "Duke at Kansas Winner?", "yes_sub_title": "Kansas", "status": "active",
                   "yes_bid_dollars": "0.6100", "yes_ask_dollars": "0.6300", "no_bid_dollars": "0.3700",
                   "no_ask_dollars": "0.3900", "close_time": "2026-11-05T05:00:00Z"},
    }  # fmt: skip
    cap = KalshiCapture((NOW - timedelta(minutes=5)).isoformat(), "f.jsonl.gz", [], {})
    out = B._market(
        raw, ev(), {}, cap, pd.Timestamp(NOW), {"version": "v", "as_of": "t", "projection": PROJ}
    )
    ext = out["extensions"]
    assert ext["cbb_quote"]["state"] == "LIVE" and "cbb_research" in ext
    assert ext["cbb_research"]["validation"]["authorized_bet"] is False
    assert (
        ext["cbb_research"]["model_gap"] is not None
    )  # teams unresolved in this fixture: explicit, not invented


def test_frozen_team_total_mean_published_without_inventing_probability():
    from cbb_edge.kalshi.research.target_means import projected_target_mean

    sem = {
        "status": "parsed",
        "market_type": "TEAM_TOTAL",
        "period": "FULL",
        "subject_side": "away",
        "model_gap": "no_team_score_distribution_in_frozen_model",
    }
    proj = {**PROJ, "home_score": 76.5, "away_score": 68.5}
    b = research_block(
        sem, proj, "pure-0.2.0", "2026-11-04T15:00:00+00:00", live_quote(), 0.50, 0.55, None, D
    )
    assert b["projected_target_mean"]["value"] == pytest.approx(68.5)
    assert b["projected_target_mean"]["status"] == "MEAN_ONLY"
    assert b["model_probability"] is None
    assert b["model_gap"] == "no_team_score_distribution_in_frozen_model"
    assert b["max_acceptable_price"] == {"yes": None, "no": None}
    assert b["net_edge"]["yes"]["net_edge"] is None
    assert b["validation"]["authorized_bet"] is False
    assert projected_target_mean(sem, proj)["value"] == pytest.approx(68.5)


def test_game_projection_info_exposes_team_score_fields():
    from types import SimpleNamespace

    record = {
        "projection": {"home_score": 82.25, "away_score": 75.25, "margin": 7.0, "total": 157.5}
    }
    choice = SimpleNamespace(as_of=pd.Timestamp(NOW), record=record)
    selection = SimpleNamespace(chosen={"pure-0.2.0": choice}, identity_changed=[])
    world = SimpleNamespace(active={"incumbent": "pure-0.2.0"})
    got = B._proj_info(selection, world)["projection"]
    assert got["home_score"] == pytest.approx(82.25)
    assert got["away_score"] == pytest.approx(75.25)
