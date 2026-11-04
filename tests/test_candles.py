"""Kalshi candle recovery: selection, parsing, archive invariants, helpers, report."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cbb_edge.kalshi import candles as cd

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
TIP = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)


def row(ticker="T1", gap=None, missing=(), tip=TIP, series="KXNCAAMBGAME", family="MONEYLINE"):
    return {
        "ticker": ticker, "series": series, "family": family,
        "game_start": tip.isoformat() if tip else None,
        "pretip_gap_reason": gap, "entry_points_missing": list(missing),
    }  # fmt: skip


def test_selection_rules():
    rows = [
        row("A", "capture_gap_first_captured_after_tip"),
        row("B", "captured_pretip_but_book_empty_or_non_live_status"),
        row("C", None, ["H1"]),
        row("D", None, ["OPEN", "24h"]),  # H1/CLOSE present: not a target
        row("E", "listed_after_tip_live_line_no_pregame_quote_exists", ["H1", "CLOSE"]),
        row("F", "non_game_market_never_quoted", ["CLOSE"]),
        row("G", "no_verified_tip", ["CLOSE"], tip=None),
        row("H", "capture_gap_first_captured_after_tip", tip=NOW + timedelta(hours=3)),  # future
    ]
    got = {t.ticker: t.reason for t in cd.select_targets(rows, now=NOW)}
    assert got == {
        "A": "capture_gap_first_captured_after_tip",
        "B": "captured_pretip_but_book_empty_or_non_live_status",
        "C": "entry_points_missing:H1",
    }


def test_cap_order_and_skip_before_cap():
    rows = [row(f"T{i}", "capture_gap_first_captured_after_tip", tip=TIP - timedelta(hours=i))
            for i in range(10)]  # fmt: skip
    got = cd.select_targets(rows, max_targets=3, now=NOW)
    assert [t.ticker for t in got] == ["T9", "T8", "T7"]  # oldest tip first
    s, e = got[0].window()
    assert e == int(got[0].game_start.timestamp()) and e - s == 24 * 3600
    skip = {cd.window_key("T9", 60, s, e)}
    assert [t.ticker for t in cd.select_targets(rows, max_targets=3, now=NOW, skip=skip)] == [
        "T8", "T7", "T6"]  # fmt: skip
    assert cd.select_targets(rows, max_targets=0, now=NOW) == []
    assert len(cd.select_targets(rows, now=NOW)) == 10  # default cap 150 > 10


def test_select_from_gz_file(tmp_path):
    p = tmp_path / "universe.jsonl.gz"
    with gzip.open(p, "wt") as fh:
        fh.write(json.dumps(row("A", "capture_gap_first_captured_after_tip")) + "\n\n")
    assert [t.ticker for t in cd.select_targets(p, now=NOW)] == ["A"]


def test_parse_dollars_cents_and_missing():
    raw = {
        "ticker": "T",
        "candlesticks": [
            {
                "end_period_ts": 1000,
                "yes_bid": {"open_dollars": "0.4100", "close_dollars": "0.4300",
                            "high": 45, "low": 40},  # fmt: skip
                "yes_ask": {"close": 47},
                "price": {"close_dollars": None, "open": None},
                "volume": 12, "open_interest": 7,
            },
            {"end_period_ts": "2000", "volume_fp": "3.5", "open_interest_fp": "9"},
            {"yes_bid": {"close": 5}},  # no end_period_ts -> skipped
            "garbage",
        ],
    }  # fmt: skip
    c = cd.parse_candles(raw)
    assert [x["end_period_ts"] for x in c] == [1000, 2000]
    assert c[0]["yes_bid"] == {"open": 0.41, "high": 0.45, "low": 0.40, "close": 0.43}
    assert c[0]["yes_ask"]["close"] == 0.47 and c[0]["yes_ask"]["open"] is None
    assert c[0]["price"] == dict.fromkeys(cd.OHLC)
    assert c[0]["volume"] == 12 and c[0]["open_interest"] == 7
    assert c[1]["yes_bid"] == dict.fromkeys(cd.OHLC)
    assert c[1]["volume"] == 3.5 and c[1]["open_interest"] == 9
    assert cd.parse_candles({}) == [] and cd.parse_candles(None) == []
    assert cd.parse_candles({"candlesticks": None}) == []


def _universe():
    return [row("A", "capture_gap_first_captured_after_tip"),
            row("B", "capture_gap_first_captured_after_tip")]  # fmt: skip


def _raw(end_ts):
    return {"ticker": "x", "candlesticks": [
        {"end_period_ts": end_ts, "yes_bid": {"close_dollars": "0.40"},
         "yes_ask": {"close_dollars": "0.44"}, "price": {"close_dollars": "0.42"},
         "volume": 5, "open_interest": 2}]}  # fmt: skip


def test_collect_archives_errors_and_is_idempotent(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake(series, ticker, s, e, interval=60):
        calls.append(ticker)
        if ticker == "B":
            raise RuntimeError("boom 500")
        return _raw(e - 1800)

    monkeypatch.setattr(cd, "fetch_candles", fake)
    out = tmp_path / "arch"
    s1 = cd.collect(_universe(), out, now=NOW, sleep_s=0)
    assert (s1["ok"], s1["errors"], s1["targets"]) == (1, 1, 2)
    part = Path(s1["partition"])
    assert part.relative_to(out).parts[:4] == ("candles", "2026", "11", "05")
    recs = [json.loads(x) for x in part.read_text().splitlines()]
    by = {r["ticker"]: r for r in recs}
    ok, err = by["A"], by["B"]
    for r in recs:
        assert r["source"] == "kalshi_candlestick_api"
        assert r["executable"] is False
        assert r["provenance"] == "recovered_candle_not_top_of_book"
    assert ok["status"] == "ok" and ok["raw_response"] == _raw(ok["window"]["end_ts"] - 1800)
    assert ok["candles"][0]["yes_ask"]["close"] == 0.44
    assert err["status"] == "error" and "boom" in err["error"] and err["candles"] == []
    before = part.read_text()

    # second run: A done; B retried (error budget), a NEW partition, old one untouched
    calls.clear()
    s2 = cd.collect(_universe(), out, now=NOW + timedelta(minutes=1), sleep_s=0)
    assert calls == ["B"] and s2["partition"] != s1["partition"]
    assert part.read_text() == before
    # same stamp must never overwrite an existing partition
    other = tmp_path / "other"
    pa, pb = cd.write_partition(other, [{"x": 1}], NOW), cd.write_partition(other, [{"x": 2}], NOW)
    assert pa is not None and pb is not None and pa != pb
    assert json.loads(pa.read_text()) == {"x": 1}
    # error budget: after MAX_ERROR_ATTEMPTS failures B is never requested again
    cd.collect(_universe(), out, now=NOW + timedelta(minutes=2), sleep_s=0)
    calls.clear()
    s4 = cd.collect(_universe(), out, now=NOW + timedelta(minutes=3), sleep_s=0)
    assert calls == [] and s4["targets"] == 0 and s4["partition"] is None


def test_collect_404_is_error_and_cap_and_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "fetch", lambda *a, **k: None)
    rows = [row(f"T{i}", "capture_gap_first_captured_after_tip") for i in range(5)]
    s = cd.collect(rows, tmp_path / "a", now=NOW, sleep_s=0, max_targets=2)
    assert s["targets"] == 2 and s["errors"] == 2
    rec = json.loads(Path(s["partition"]).read_text().splitlines()[0])
    assert "http_404_not_found" in rec["error"]
    d = cd.collect(rows, tmp_path / "b", now=NOW, dry_run=True)
    assert d["targets"] == 5 and not (tmp_path / "b" / "candles").exists()


def test_fetch_candles_uses_http_fetch(monkeypatch):
    seen = {}

    class R:
        def json(self):
            return {"candlesticks": []}

    def fake(source, url, params=None, **kw):
        seen.update(source=source, url=url, params=params, kw=kw)
        return R()

    monkeypatch.setattr(cd, "fetch", fake)
    assert cd.fetch_candles("SER", "TK", 10, 20, 60) == {"candlesticks": []}
    assert seen["source"] == "kalshi_public"
    assert seen["url"].endswith("/series/SER/markets/TK/candlesticks")
    assert seen["params"] == {"start_ts": 10, "end_ts": 20, "period_interval": 60}
    assert seen["kw"]["max_attempts"] == cd.FETCH_ATTEMPTS
    with pytest.raises(ValueError):
        cd.fetch_candles("SER", "TK", 10, 20, 5)


def _archive(tmp_path, monkeypatch, end_offsets_min, ticker="A"):
    def fake(series, t, s, e, interval=60):
        return {"candlesticks": [
            {"end_period_ts": e - m * 60, "yes_bid": {"close": 40}, "yes_ask": {"close": 44}}
            for m in end_offsets_min]}  # fmt: skip

    monkeypatch.setattr(cd, "fetch_candles", fake)
    cd.collect([row(ticker, "capture_gap_first_captured_after_tip")], tmp_path, now=NOW,
               sleep_s=0)  # fmt: skip
    return cd.load_candle_quotes(tmp_path)


def test_loader_invariants(tmp_path, monkeypatch):
    q = _archive(tmp_path, monkeypatch, [120, 60])
    obs = q["A"]
    assert [o.end_period_ts for o in obs] == sorted(o.end_period_ts for o in obs) and len(obs) == 2
    for o in obs:
        assert o.source == "candle" and o.executable is False
        assert o.bid_size is None and o.ask_size is None
        assert o.yes_bid["close"] == 0.40 and o.yes_ask["close"] == 0.44
    assert cd.load_candle_quotes(tmp_path / "missing") == {}


def test_candle_close_before_boundaries(tmp_path, monkeypatch):
    obs = _archive(tmp_path, monkeypatch, [120, 60, 0])["A"]
    tip = TIP.timestamp()
    exact = cd.candle_close_before(obs, TIP)
    assert exact is not None and exact["end_period_ts"] == tip  # ending exactly at cutoff counts
    assert exact["minutes_before_cutoff"] == 0 and exact["executable"] is False
    assert exact["bid_size"] is None and exact["ask_size"] is None
    assert (
        exact["label"] == "approximate_close_not_top_of_book" and exact["tolerance_minutes"] == 60
    )
    just_before = cd.candle_close_before(obs, tip - 1)
    assert just_before is not None and just_before["end_period_ts"] == tip - 3600
    assert just_before["minutes_before_cutoff"] == pytest.approx(3599 / 60)
    assert cd.candle_close_before(obs, tip - 7200 - 1) is None  # nothing at/before cutoff
    assert cd.candle_close_before([], TIP) is None
    assert cd.candle_close_before(obs, tip - 3600)["end_period_ts"] == tip - 3600  # type: ignore[index]


def test_report_counts(tmp_path, monkeypatch):
    def fake(series, t, s, e, interval=60):
        if t == "ERR":
            raise RuntimeError("x")
        if t == "EMPTY":
            return {"candlesticks": []}
        if t == "LATE":  # only a candle after tip
            return {"candlesticks": [{"end_period_ts": e + 3600, "price": {"close": 50}}]}
        return {"candlesticks": [{"end_period_ts": e - 1800, "yes_bid": {"close": 50}},
                                 {"end_period_ts": e - 7200, "yes_bid": {"close": 48}}]}  # fmt: skip

    monkeypatch.setattr(cd, "fetch_candles", fake)
    g = "capture_gap_first_captured_after_tip"
    rows = [row("OK1", g), row("OK2", g, family="SPREAD"), row("ERR", g), row("EMPTY", g),
            row("LATE", g), row("NOTARGET", None, ["OPEN"]), row("PENDING", g)]  # fmt: skip
    cd.collect(rows[:-1], tmp_path, now=NOW, sleep_s=0)
    rep = cd.candle_recovery_report(rows, tmp_path)
    ml = rep["families"]["MONEYLINE"]
    assert ml["gap_contracts"] == 5 and ml["recoverable"] == 1
    assert ml["fetched_ok"] == 3 and ml["fetch_errors_only"] == 1
    assert ml["minutes_before_tip"] == {"min": 30.0, "median": 30.0, "max": 30.0}
    sp = rep["families"]["SPREAD"]
    assert sp["recoverable"] == 1 and sp["gap_contracts"] == 1
    assert rep["executable"] is False
    assert rep["totals"]["gap_contracts"] == 6 and rep["totals"]["recoverable"] == 2
    assert rep["families"]["MONEYLINE"] and "NOTARGET" not in json.dumps(rep)


def test_run_candles_flag(tmp_path):
    import inspect

    from cbb_edge.kalshi.research import run

    assert inspect.signature(run.build).parameters["candles"].default is None
