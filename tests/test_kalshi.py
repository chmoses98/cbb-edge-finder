"""Kalshi discovery/taxonomy/capture tests (network mocked; read-only)."""

from __future__ import annotations

import gzip
import json
from unittest import mock

from cbb_edge.kalshi import capture, taxonomy


def test_cbb_series_detection():
    assert taxonomy.is_cbb_series(
        {"ticker": "KXNCAAMBGAME", "title": "Men's college basketball game"}
    )
    assert taxonomy.is_cbb_series({"ticker": "KXMARMAD", "title": "March Madness champion"})
    assert not taxonomy.is_cbb_series(
        {"ticker": "KXNCAAWBGAME", "title": "Women's college basketball"}
    )
    assert not taxonomy.is_cbb_series({"ticker": "KXNBAGAME", "title": "NBA game"})
    # look-alikes observed in the live series list
    for t in (
        "KXNCAABBGAME",
        "KXNCAABASEBALL",
        "KXTEAMSINNCAABBWS",
        "KXWMARMAD",
        "KXNCAAWBSPREAD",
        "KXWMARMADROUND",
        "KXNCAAMLAXGAME",
        "KXNCAAMSOCCERGAME",
        "KXNCAAMWRESTLING125",
    ):
        assert not taxonomy.is_cbb_series({"ticker": t, "title": ""}), t
    for t in (
        "KXNCAAMBGAME",
        "KXNCAAMBSPREAD",
        "KXNCAAMBTOTAL",
        "KXNCAAMB1HSPREAD",
        "KXMARMADSEED",
        "KXMAKEMARMAD",
        "KXNCAABGAME",
    ):
        assert taxonomy.is_cbb_series({"ticker": t, "title": ""}), t
    assert not taxonomy.is_cbb_series({"ticker": "KXNCAAMX", "title": "NCAA Men's Wrestling"})
    assert taxonomy.is_cbb_series(
        {"ticker": "KXNCAAMACC", "title": "ACC men's basketball champion"}
    )


def test_family_classification():
    s = {"ticker": "KXNCAAMBSPREAD"}
    assert taxonomy.classify_market(s, {"title": "Duke wins by over 5.5 points?"}) == "SPREAD"
    assert (
        taxonomy.classify_market({"ticker": "KXNCAAMBTOTAL"}, {"title": "Total points"}) == "TOTAL"
    )
    assert (
        taxonomy.classify_market({"ticker": "KXNCAAMBGAME"}, {"title": "Duke at UNC Winner?"})
        == "GAME_WINNER"
    )
    assert (
        taxonomy.classify_market(
            {"ticker": "KXMARMAD"}, {"title": "Who will win the national championship?"}
        )
        == "FUTURES_CHAMPION"
    )


def test_yes_mid_both_price_styles():
    assert taxonomy.yes_mid_cents({"yes_bid": 40, "yes_ask": 44}) == 42
    assert taxonomy.yes_mid_cents({"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44"}) == 42
    assert taxonomy.yes_mid_cents({"yes_bid": 0, "yes_ask": 0, "last_price": 37}) == 37


def test_capture_writes_immutable_snapshot(tmp_path):
    series = {
        "series": [
            {"ticker": "KXNCAAMBGAME", "title": "College Basketball Game"},
            {"ticker": "KXNBAGAME", "title": "Pro Basketball"},
        ]
    }
    mk = {
        "ticker": "KXNCAAMBGAME-26NOV04DUKEUNC-DUKE",
        "event_ticker": "KXNCAAMBGAME-26NOV04DUKEUNC",
        "title": "Duke at UNC Winner?",
        "status": "active",
        "yes_bid": 55,
        "yes_ask": 57,
        "close_time": "2026-11-05T02:00:00Z",
    }

    def fake_get(path, params=None):
        if path == "/series":
            return series
        if path == "/markets":
            if params.get("status") == "open":
                return {"markets": [mk], "cursor": ""}
            return {"markets": [], "cursor": ""}
        raise AssertionError(path)

    with mock.patch.object(capture, "_get", side_effect=fake_get):
        summary = capture.capture(tmp_path)
    assert summary["n_series"] == 1 and summary["n_markets"] == 1
    assert summary["by_family"] == {"GAME_WINNER": 1}
    rows = [json.loads(x) for x in gzip.open(summary["file"], "rt")]
    assert rows[0]["market"]["ticker"] == mk["ticker"]
    assert rows[0]["schema_version"] == capture.SCHEMA_VERSION


def test_capture_goes_through_cost_policy():
    """Kalshi requests use the registered free source through the chokepoint."""
    with mock.patch.object(capture, "fetch") as f:
        f.return_value = mock.Mock(json=lambda: {"series": []})
        capture.discover_series()
    assert f.call_args.args[0] == "kalshi_public"
