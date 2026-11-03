"""SIFT publication: stale, settled and empty-book Kalshi quotes are never shown as live."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from cbb_edge.app.sift_app import build as B
from cbb_edge.app.sift_app.inputs import KalshiCapture
from cbb_edge.app.sift_app.quotes import classify_quote, two_sided

NOW = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)


def q(status="OPEN", bid="0.40", ask="0.44", age_min=10):
    return classify_quote(status, bid, ask, NOW - timedelta(minutes=age_min), NOW)


def test_live_fresh_two_sided_only():
    assert q()["state"] == "LIVE" and q()["live_probability_ok"]
    assert q(age_min=46)["state"] == "STALE" and not q(age_min=46)["live_probability_ok"]
    assert q(age_min=45)["state"] == "LIVE"  # boundary is inclusive-live at exactly 45 min


@pytest.mark.parametrize(
    "bid,ask", [("0.0000", "1.0000"), (None, "0.5"), ("0.4", None), ("0.6", "0.5")]
)
def test_empty_or_crossed_books_are_not_two_sided(bid, ask):
    assert not two_sided(bid, ask)
    assert q(bid=bid, ask=ask)["state"] == "EMPTY_BOOK"


def test_non_open_statuses_are_never_live():
    for st in ("SETTLED", "CLOSED", "UNOPENED"):
        r = q(status=st)
        assert r["state"] == st and not r["live_probability_ok"]
    assert classify_quote("OPEN", "0.4", "0.5", None, NOW)["state"] == "NO_CAPTURE_TIME"
    assert q(status="WEIRD")["state"] == "UNKNOWN_STATUS"


def _part(pid, name):
    return {"participant_id": pid, "display_name": name, "short_name": name, "metadata": {}}


def _ev():
    return {
        "event_id": "evt_test1", "home_participant": "prt_home1", "away_participant": "prt_away1",
        "participants": [_part("prt_home1", "Kansas"), _part("prt_away1", "Duke")],
    }  # fmt: skip


def _raw(status="active", bid="0.6100", ask="0.6300"):
    return {
        "family": "GAME_WINNER", "series_ticker": "KXNCAAMBGAME",
        "market": {
            "ticker": "KXNCAAMBGAME-26NOV02DUKEKU-KU", "event_ticker": "KXNCAAMBGAME-26NOV02DUKEKU",
            "title": "Duke at Kansas Winner?", "yes_sub_title": "Kansas", "status": status,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "no_bid_dollars": "0.3700",
            "no_ask_dollars": "0.3900", "close_time": "2026-11-03T05:00:00Z",
        },
    }  # fmt: skip


def _pub(raw, captured_min_ago):
    now = pd.Timestamp(NOW)
    cap = KalshiCapture(
        (NOW - timedelta(minutes=captured_min_ago)).isoformat(), "f.jsonl.gz", [], {}
    )
    return B._market(raw, _ev(), {}, cap, now)


def test_published_market_probability_only_when_live():
    live = _pub(_raw(), 10)
    assert live["market_probability"] == pytest.approx(0.62)
    assert live["extensions"]["cbb_quote"]["state"] == "LIVE"
    stale = _pub(_raw(), 200)
    assert stale["market_probability"] is None  # no stale mid presented as current
    assert stale["yes_bid"] == 0.61 and stale["captured_at"] is not None  # evidence kept
    assert stale["extensions"]["cbb_quote"]["state"] == "STALE"
    assert stale["extensions"]["cbb_quote"]["age_minutes"] == 200.0
    settled = _pub(_raw(status="finalized", bid="0.0000", ask="1.0000"), 10)
    assert settled["market_probability"] is None  # the 0/1 placeholder mid of 0.5 is gone
    assert settled["market_status"] == "SETTLED"
    empty = _pub(_raw(bid="0.0000", ask="1.0000"), 10)
    assert empty["market_probability"] is None
    assert empty["extensions"]["cbb_quote"]["state"] == "EMPTY_BOOK"
