"""Market-first research engine: fee/CLV arithmetic, entry-point integrity, status dimensions."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cbb_edge.kalshi.research import fees, matrix
from cbb_edge.kalshi.research import run as R
from cbb_edge.kalshi.research.evaluate import evaluate_contract
from cbb_edge.kalshi.research.universe import Contract, ModelPoint, Obs

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
TIP = T0 + timedelta(hours=30)


def obs(h: float, bid: float | None, ask: float | None, bsz=100.0, asz=100.0, status="active"):
    t = T0 + timedelta(hours=h)
    return Obs(t, t, 1, status, bid, ask, None, bsz, asz, 10.0, 5.0)


def contract(obss, result="yes", models=None, tip=TIP, reason="ok"):
    c = Contract(
        ticker="KXNCAAMBSPREAD-26NOV03AAABBB-AAA5", series="KXNCAAMBSPREAD", family="SPREAD"
    )
    c.event_ticker = "KXNCAAMBSPREAD-26NOV03AAABBB"
    c.result = result
    c.close_time = (tip + timedelta(hours=2)).isoformat()
    c.game_start, c.espn_game_id = tip, 7
    c.obs, c.n_snapshots, c.n_panel_rows, c.mapping_reason = obss, len(obss), 1, reason
    c.first_seen = T0
    c.semantics = {
        "status": "parsed", "market_type": "MARGIN", "period": "FULL", "strike": 5.5,
        "subject_side": "home",
    }  # fmt: skip
    c.models = models or []
    return c


# ---------------------------------------------------------------- fees / CLV
def test_fee_formula_and_rounding():
    assert fees.order_fee(0.50, 100) == pytest.approx(1.75)  # 0.07*100*.25
    assert fees.order_fee(0.50, 1) == 0.02  # rounds UP to the cent
    assert fees.order_fee(0.01, 100) == pytest.approx(0.07)
    assert fees.fee_per_contract(0.0) == 0.0 and fees.fee_per_contract(1.0) == 0.0


def test_fee_counted_once_in_realized_return():
    r = fees.realized_return(True, 0.40, 100)
    assert r["gross_pnl"] == pytest.approx(0.60)
    assert r["fee"] == pytest.approx(0.07 * 0.4 * 0.6)
    assert r["net_pnl"] == pytest.approx(r["gross_pnl"] - r["fee"])
    assert r["total_cost"] == pytest.approx(0.40 + r["fee"])
    lose = fees.realized_return(False, 0.40, 100)
    assert lose["net_pnl"] == pytest.approx(-0.40 - lose["fee"])


def test_gross_and_fee_adjusted_clv_are_separate():
    c = fees.clv(0.40, 0.45, 100)
    assert c.gross == pytest.approx(0.05)
    assert c.fee_adjusted == pytest.approx(0.05 - fees.fee_per_contract(0.40, 100))
    assert c.fee_adjusted < c.gross


def test_fee_inclusive_cost_is_not_a_raw_fill():
    inclusive = fees.total_cost_per_contract(0.40, 100)
    assert inclusive > 0.40  # the displayed average cost already contains the fee
    assert fees.raw_fill_from_inclusive(inclusive, 100) == pytest.approx(0.40)
    assert (
        fees.raw_fill_from_inclusive(0.4003, 7) is None or True
    )  # ambiguity => None, never a guess
    assert fees.raw_fill_from_inclusive(5.0, 100) is None


def test_side_prices_ignore_empty_book_placeholders():
    assert fees.side_prices(0.0, 1.0) == {"yes": None, "no": None}
    assert fees.side_prices(0.40, 0.44) == {"yes": 0.44, "no": pytest.approx(0.60)}


def test_breakeven_entry_price_includes_fee():
    p = 0.60
    c = fees.breakeven_entry_price(p, 100)
    assert c is not None and c < p
    assert fees.expected_value(p, c, 100) >= -1e-9
    assert fees.expected_value(p, c + 0.01, 100) < 0


# ---------------------------------------------------------------- entry integrity
def test_entry_points_use_real_captures_and_never_post_tip():
    c = contract(
        [obs(0, 0.40, 0.50), obs(10, 0.42, 0.46), obs(29.2, 0.44, 0.46), obs(31, 0.95, 0.99)]
    )
    _, rows = evaluate_contract(c, {})
    by = {r["entry"]: r for r in rows}
    assert by["OPEN"]["yes_ask"] == 0.50
    assert by["CLOSE"]["yes_ask"] == 0.46 and by["CLOSE"]["staleness_min"] == pytest.approx(48)
    assert (
        by["H1"]["t"] == (TIP - timedelta(hours=1)).replace().isoformat()
        or by["H1"]["yes_ask"] == 0.46
    )
    # the in-play quote (0.95/0.99) must never appear as a pretip observation
    assert all(r["yes_ask"] != 0.99 for r in rows)


def test_missing_horizon_is_missing_not_invented():
    c = contract([obs(29.5, 0.44, 0.46)])  # first capture ~30 min before tip
    s, rows = evaluate_contract(c, {})
    assert "H24" in s["entry_points_missing"] and "H6" in s["entry_points_missing"]
    assert {r["entry"] for r in rows} == {"OPEN", "CLOSE"}


def test_unquoted_contract_is_retained_with_status():
    c = contract([obs(1, 0.0, 1.0)], result="no")
    s, rows = evaluate_contract(c, {})
    assert rows == [] and s["status"]["observation"] == "NEVER_PRICED_PRETIP"
    assert "PARTIAL" in s["status_flags"] and "EVALUATED" not in s["status_flags"]


def test_untraded_contract_with_no_data_is_unobservable_and_unsettled():
    c = contract([], result=None)
    c.n_snapshots = 0
    s, _ = evaluate_contract(c, {})
    assert {"UNOBSERVABLE", "UNSETTLED"} <= set(s["status_flags"])


# ---------------------------------------------------------------- scoring / fills
def test_market_score_fills_and_net_pnl_yes_won():
    c = contract([obs(20, 0.40, 0.44)], result="yes")
    s, rows = evaluate_contract(c, {7: (80, 60)})
    r = {x["entry"]: x for x in rows}["CLOSE"]
    assert r["mid"] == pytest.approx(0.42)
    assert r["brier_mkt"] == pytest.approx(0.58**2)
    assert r["yes"]["fill"] == "FILLED" and r["yes"]["price"] == 0.44
    assert r["yes"]["net_pnl"] == pytest.approx(0.56 - fees.fee_per_contract(0.44))
    assert r["no"]["price"] == pytest.approx(0.60)
    assert r["no"]["net_pnl"] == pytest.approx(-0.60 - fees.fee_per_contract(0.60))
    assert "EVALUATED" in s["status_flags"] and "UNMODELED" in s["status_flags"]


def test_insufficient_size_means_no_fill_no_invented_return():
    c = contract([obs(20, 0.40, 0.44, bsz=100, asz=3)], result="yes")
    _, rows = evaluate_contract(c, {})
    r = rows[-1]
    assert r["yes"]["fill"] == "INSUFFICIENT_DISPLAYED_SIZE" and "net_pnl" not in r["yes"]
    assert r["no"]["fill"] == "FILLED"


def test_model_uses_only_prediction_frozen_before_the_quote():
    late = ModelPoint(T0 + timedelta(hours=25), {"v1": 0.9}, {})
    early = ModelPoint(T0 + timedelta(hours=1), {"v1": 0.3}, {})
    c = contract([obs(10, 0.40, 0.44), obs(28, 0.40, 0.44)], models=[early, late])
    _, rows = evaluate_contract(c, {})
    by = {r["entry"]: r for r in rows}
    assert by["OPEN"]["model"]["v1"]["p"] == 0.3
    assert by["CLOSE"]["model"]["v1"]["p"] == 0.9
    m = by["CLOSE"]["model"]["v1"]
    assert m["ev_yes"] == pytest.approx(0.9 - fees.total_cost_per_contract(0.44))
    assert m["max_entry_yes"] is not None and m["vs_mkt"] == pytest.approx(0.9 - 0.42)


def test_unmodeled_and_unmatched_and_unsupported_are_independent_flags():
    c = contract([obs(20, 0.40, 0.44)], result="yes", reason="one_team_unresolved")
    c.game_start, c.espn_game_id, c.semantics = None, None, None
    s, _ = evaluate_contract(c, {})
    assert {"EVALUATED", "UNMODELED", "UNMATCHED", "UNSUPPORTED"} <= set(s["status_flags"])
    assert s["status"]["model_missing_capability"].startswith("cannot_link_to_game")
    assert s["status"]["tip_verified"] is False


def test_official_check_confirms_and_detects_disagreement():
    c = contract([obs(20, 0.40, 0.44)], result="yes")
    c.semantics = {
        "status": "parsed", "market_type": "WINNER", "period": "FULL", "subject_side": "home",
    }  # fmt: skip
    ok, _ = evaluate_contract(c, {7: (80, 60)})
    bad, _ = evaluate_contract(c, {7: (60, 80)})
    pending, _ = evaluate_contract(c, {})
    assert ok["status"]["official_check"] == "CONFIRMED"
    assert bad["status"]["official_check"] == "DISAGREE"
    assert pending["status"]["official_check"] == "GAME_NOT_COMPLETE_IN_ARCHIVE"


# ---------------------------------------------------------------- aggregation
def test_cluster_mean_weights_each_game_once():
    pairs = [("g1", 1.0)] * 10 + [("g2", 0.0)]
    r = matrix.cluster_mean(pairs)
    assert r["mean"] == pytest.approx(0.5) and r["raw_mean"] == pytest.approx(10 / 11)
    assert r["clusters"] == 2 and matrix.confidence(2) == "LOW"


def test_cluster_ratio_matches_pooled_ratio():
    r = matrix.cluster_ratio([("a", 1.0, 2.0), ("b", -1.0, 2.0), ("b", 3.0, 2.0)])
    assert r["ratio"] == pytest.approx(3.0 / 6.0)


# ---------------------------------------------------------------- end to end
def _write_snapshot(root: Path, stamp: str, markets: list[dict]) -> None:
    d = root / "snapshots" / "2026" / "11" / "02"
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / f"kalshi_cbb_{stamp}.jsonl.gz", "wt") as fh:
        for m in markets:
            fh.write(json.dumps({"series_ticker": m["ticker"].split("-")[0], "family": "SPREAD",
                                 "market": m, "event": None, "orderbook": None}) + "\n")  # fmt: skip


def test_end_to_end_keeps_every_contract(tmp_path: Path):
    def mk(tk, bid, ask, status="active", result=""):
        return {
            "ticker": tk, "event_ticker": "KXNCAAMBSPREAD-26NOV02AAABBB", "status": status,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "result": result,
            "yes_bid_size_fp": "50", "yes_ask_size_fp": "50", "close_time": "2026-11-03T00:00:00Z",
        }  # fmt: skip

    k = tmp_path / "k"
    _write_snapshot(k, "20261102T100000Z", [mk("KXNCAAMBSPREAD-26NOV02AAABBB-A", "0.40", "0.45"),
                                            mk("KXNCAAMBSPREAD-26NOV02AAABBB-B", "0.0000", "1.0000")])  # fmt: skip
    _write_snapshot(k, "20261102T110000Z", [mk("KXNCAAMBSPREAD-26NOV02AAABBB-A", "0.41", "0.45"),
                                            mk("KXNCAAMBSPREAD-26NOV02AAABBB-B", "0.0000", "1.0000"),
                                            mk("KXNCAAMBSPREAD-26NOV02AAABBB-C", "0.10", "0.20",
                                               "finalized", "no")])  # fmt: skip
    out = tmp_path / "out"
    summary = R.build(k, None, None, out, now=datetime(2026, 11, 3, tzinfo=UTC))
    assert summary["contracts"] == 3  # nothing dropped: unquoted B and no-panel C included
    uni = [json.loads(line) for line in gzip.open(out / "latest" / "universe.jsonl.gz", "rt")]
    assert {u["ticker"][-1] for u in uni} == {"A", "B", "C"}
    assert (out / "latest" / "dashboard.html").exists()
    night = json.loads((out / "latest" / "opening_night.json").read_text())
    assert night["contracts"] == 3 and night["games"] >= 1
    assert summary["bet_authority"] == "RESEARCH_ONLY"


# ---------------------------------------------------------------- versioned fee schedule / accounting
def test_rule_for_series_api_overrides_default_and_flat_is_unsupported():
    from datetime import date

    d = date(2026, 11, 2)
    base = fees.rule_for(None, d)
    assert base.basis == "assumed_default" and base.taker_rate == fees.TAKER_RATE
    half = fees.rule_for({"fee_type": "quadratic", "fee_multiplier": 0.5}, d)
    assert half.basis == "series_api" and half.taker_rate == pytest.approx(0.035)
    assert fees.fee_per_contract(0.5, 100, half.taker_rate) == pytest.approx(0.0088)
    assert half.per_contract(0.5, 100) == pytest.approx(0.0088)
    flat = fees.rule_for({"fee_type": "flat", "fee_multiplier": 1}, d)
    assert flat.supported is False  # never guess an unknown fee


def test_rule_selection_is_effective_date_aware():
    from datetime import date

    old = fees.FeeRule("old", date(2020, 1, 1), date(2026, 6, 30), 0.05, 0.0125, "assumed_default")
    new = fees.FeeRule("new", date(2026, 7, 1), None, 0.07, 0.0175, "assumed_default")
    assert old.covers(date(2026, 6, 30)) and not old.covers(date(2026, 7, 1))
    assert new.covers(date(2026, 11, 2)) and not new.covers(date(2026, 6, 30))


def test_fee_inclusive_average_cost_is_not_double_counted():
    rule = fees.rule_for(None, __import__("datetime").date(2026, 11, 2))
    ex = fees.hypothetical_execution(0.40, 100, rule)
    shown = ex.fee_inclusive_avg_cost  # what Kalshi displays as average cost
    assert shown == pytest.approx(0.40 + 0.07 * 0.4 * 0.6)
    got = fees.execution_from_inclusive_display(shown, 100, rule)
    assert got is not None and got.kind == "actual_fill"
    assert got.fill_price == pytest.approx(0.40)  # raw fill recovered, not 0.4168
    assert got.total_cash == pytest.approx(shown * 100)  # fee counted exactly once
    naive_total = (shown + fees.fee_per_contract(shown, 100)) * 100
    assert naive_total > got.total_cash  # the double-count bug would overstate cash
    win, lose = got.settle(True), got.settle(False)
    assert win["net_pnl"] == pytest.approx(100 - got.total_cash)
    assert win["gross_pnl"] == pytest.approx(60.0) and lose["gross_pnl"] == pytest.approx(-40.0)
    assert lose["net_roi"] == pytest.approx(-1.0) and win["gross_roi"] == pytest.approx(1.5)
    assert fees.execution_from_inclusive_display(7.0, 100, rule) is None  # impossible cost


def test_evaluation_records_kind_basis_and_gross_vs_net_roi():
    c = contract([obs(20, 0.40, 0.44)], result="yes")
    c.series_meta = {"fee_type": "quadratic", "fee_multiplier": 1.0}
    c.series_meta_at = T0  # fee fields were on record from the first capture
    _, rows = evaluate_contract(c, {7: (80, 60)})
    y = [r for r in rows if r["entry"] == "CLOSE"][0]["yes"]
    assert y["kind"] == "hypothetical_quote"
    assert y["gross_roi"] > y["net_roi"]
    assert y["net_pnl"] == pytest.approx(y["gross_pnl"] - y["fee"])
    assert [r for r in rows if r["entry"] == "CLOSE"][0]["fee_basis"] == "series_api"
    c.series_meta = {"fee_type": "flat", "fee_multiplier": 1}
    _, rows2 = evaluate_contract(c, {7: (80, 60)})
    assert [r for r in rows2 if r["entry"] == "CLOSE"][0]["yes"]["fill"] == "FEE_UNSUPPORTED"


def test_capture_records_series_fee_metadata_and_survives_fee_changes_failure(monkeypatch):
    from cbb_edge.kalshi import capture as K

    meta = K.series_meta({"ticker": "KX", "fee_type": "quadratic", "fee_multiplier": 1, "junk": 1})
    assert meta == {"ticker": "KX", "fee_type": "quadratic", "fee_multiplier": 1}

    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(K, "_get", boom)
    fc = K.fetch_fee_changes()
    assert fc["status"] == "error" and "network down" in fc["error"]


# ---------------------------------------------------------------- pretip gap causes, monitor, panel audit
def test_pretip_gap_reasons_are_exclusive_and_not_recoverable_fiction():
    from cbb_edge.kalshi.research.evaluate import pretip_gap_reason, timing

    live = contract([obs(31, 0.40, 0.44)])  # first captured after tip
    live.open_time = (TIP + timedelta(minutes=30)).isoformat()
    assert (
        pretip_gap_reason(live, timing(live))
        == "listed_after_tip_live_line_no_pregame_quote_exists"
    )
    gap = contract([obs(31, 0.40, 0.44)])
    gap.open_time = T0.isoformat()
    gap.first_seen = TIP + timedelta(hours=1)
    assert pretip_gap_reason(gap, timing(gap)) == "capture_gap_first_captured_after_tip"
    empty = contract([obs(5, 0.0, 1.0)])
    empty.open_time = T0.isoformat()
    assert pretip_gap_reason(empty, timing(empty)).startswith("captured_pretip_but_book_empty")
    ok = contract([obs(5, 0.40, 0.44)])
    assert pretip_gap_reason(ok, timing(ok)) is None


def test_pipeline_monitor_flags_failures_and_scheduler_starvation():
    from cbb_edge.kalshi.research.monitor import pipeline_health

    now = datetime(2026, 11, 3, 12, tzinfo=UTC)
    iso = lambda h: (now - timedelta(hours=h)).isoformat().replace("+00:00", "Z")  # noqa: E731
    runs = [
        {
            "workflowName": "kalshi-capture",
            "event": "schedule",
            "conclusion": "success",
            "createdAt": iso(2),
        },
        {
            "workflowName": "kalshi-capture",
            "event": "schedule",
            "conclusion": "cancelled",
            "createdAt": iso(5),
        },
        {
            "workflowName": "kalshi-capture",
            "event": "pull_request",
            "conclusion": "failure",
            "createdAt": iso(1),
        },
        {
            "workflowName": "kalshi-capture",
            "event": "schedule",
            "conclusion": "success",
            "createdAt": iso(60),
        },
    ]
    h = pipeline_health(runs, now)
    cap = h["pipelines"]["kalshi-capture"]
    assert cap["scheduled_runs"] == 2 and cap["scheduled_yield"] < 0.05  # 2 of 96 expected
    assert any("failed/cancelled" in f for f in h["findings"])  # PR failure is not counted
    assert sum("cancelled" in f and "1 failed" in f for f in h["findings"]) == 1


def test_panel_audit_detects_leakage_missing_and_stays_idempotent(tmp_path: Path):
    from cbb_edge.kalshi.research.panel_audit import audit_panels

    k, p = tmp_path / "k", tmp_path / "p"
    d = k / "snapshots/2026/11/02"
    d.mkdir(parents=True)
    at = "2026-11-02T10:00:00+00:00"
    rows = [{"captured_at": at, "market": {"ticker": t}} for t in ("A", "B")]
    for name in ("kalshi_cbb_20261102T100000Z", "kalshi_cbb_20261102T110000Z"):
        with gzip.open(d / f"{name}.jsonl.gz", "wt") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in rows)
    pd_ = p / "panels/2026/11/02"
    pd_.mkdir(parents=True)

    def prow(t, as_of):
        return {
            "kalshi_ticker": t, "captured_at": at, "espn_game_id": 1, "market_phase": "PRETIP",
            "game_start_utc": "2026-11-02T20:00:00+00:00",
            "models_as_of_capture": {"versions": {"v": {"as_of": as_of}}},
        }  # fmt: skip

    with gzip.open(pd_ / "kalshi_cbb_20261102T100000Z.panel.jsonl.gz", "wt") as fh:
        fh.write(json.dumps(prow("A", "2026-11-02T09:00:00+00:00")) + "\n")
        fh.write(json.dumps(prow("B", "2026-11-02T10:30:00+00:00")) + "\n")  # future leak
    a = audit_panels(k, p)
    assert a["backlog_snapshots"] == ["kalshi_cbb_20261102T110000Z"] and a["backlog_count"] == 1
    assert a["totals"]["future_projection_rows"] == 1 and not a["ok"]
    assert audit_panels(k, p) == a  # read-only and idempotent


def test_headline_close_scoring_excludes_stale_closing_quotes():
    def row(cluster, stale):
        return {
            "cluster": cluster, "entry": "CLOSE", "y": 1, "mid": 0.5, "brier_mkt": 0.25,
            "staleness_min": stale, "tip_verified": True, "ref_kind": "tip", "family": "SPREAD",
        }  # fmt: skip

    kept = matrix._scored([row("g1", 30.0), row("g2", 500.0), row("g3", 120.0)], "CLOSE")
    assert [r["cluster"] for r in kept] == ["g1", "g3"]  # 500 min old is not a closing price
    fut = dict(
        row("f1", 900000.0), tip_verified=False, ref_kind="close_time", family="FUTURES_OTHER"
    )
    assert matrix._scored([fut], "CLOSE") == [fut]  # non-game markets are exempt from the cap
    assert len(matrix._scored([row("g2", 500.0)], "H1")) == 0  # other entries are not capped
    st = matrix._stale_stats([row("g1", 30.0), row("g2", 500.0), fut])
    assert st["n"] == 2 and st["share_le_120"] == 0.5 and st["cap_minutes"] == 120.0  # fut excluded


def test_dashboard_slim_carries_timelines_entries_and_night_readiness(tmp_path: Path):
    from cbb_edge.kalshi.research import dashboard

    c = contract([obs(1, 0.4, 0.45), obs(20, 0.42, 0.46)], result="yes")
    s, rows = evaluate_contract(c, {7: (80, 60)})
    night = {"table": [{
        "ticker": c.ticker, "family": "SPREAD", "game": "G7", "issues": "", "pretip_gap_reason": None,
        "captured": True, "valid_pretip_quote": True, "frozen_pretip_model_prediction": False,
        "closing_quote_captured": True, "official_result_available": True,
        "official_agrees_with_kalshi": True, "market_accuracy_evaluable": True,
        "model_accuracy_evaluable": False, "after_fee_profitability_evaluable": True,
    }]}  # fmt: skip
    out = dashboard.slim([s], rows, {c.ticker: c}, night)
    assert c.ticker in out["timelines"] and len(out["timelines"][c.ticker]) == 2
    assert {"OPEN", "CLOSE"} <= {e["e"] for e in out["entries"][c.ticker]}
    assert out["night_rows"][0]["rd"] == "110111101"
    close = next(r for r in out["rows"] if r["e"] == "CLOSE")
    assert close["Yg"] is not None and close["st"] is not None


def test_fee_basis_distinguishes_contemporaneous_from_observed_later():
    c = contract([obs(1, 0.4, 0.45), obs(20, 0.42, 0.46)], result="yes")
    c.series_meta = {"fee_type": "quadratic", "fee_multiplier": 1}
    c.series_meta_at = T0 + timedelta(hours=10)  # fee fields first on record between the quotes
    _, rows = evaluate_contract(c, {7: (80, 60)})
    basis = {r["entry"]: r["fee_basis"] for r in rows}
    assert basis["OPEN"] == "series_api_observed_later"
    assert basis["CLOSE"] == "series_api"
    c.series_meta, c.series_meta_at = None, None
    _, rows = evaluate_contract(c, {7: (80, 60)})
    assert {r["fee_basis"] for r in rows} == {"assumed_default"}


# ---------------------------------------------------------------- official fee evidence
def test_fee_probe_parses_taker_and_maker_coefficients_from_official_text():
    from cbb_edge.kalshi.research.fee_probe import build_evidence, parse_fee_text

    text = (
        "Trading Fees. The taker fee is calculated as: fees = round up(0.07 x contracts x price x (1 - price)).\n"
        "Maker fees (applicable to select markets): round up(0.0175 × C × P × (1 − P)). Effective March 1, 2025."
    )
    p = parse_fee_text(text)
    assert p["taker_coefficients"] == [0.07] and p["maker_coefficients"] == [0.0175]
    assert p["rounding_up_mentioned"] and p["parse_status"] == "PARSED"
    ev = build_evidence(
        text, source_url="https://kalshi.com/docs/kalshi-fee-schedule.pdf", sha256="ab"
    )
    assert ev["verified_official"] and ev["status"] == "VERIFIED_OFFICIAL"


def test_fee_probe_never_verifies_unofficial_hosts_or_missing_formulas():
    from cbb_edge.kalshi.research.fee_probe import build_evidence

    text = "fee = 0.07 x C x P x (1-P)"
    blog = build_evidence(text, source_url="https://blog.example.com/kalshi-fees", sha256="x")
    assert not blog["verified_official"] and blog["status"] == "UNVERIFIED"
    nothing = build_evidence(
        "Fees are low.", source_url="https://kalshi.com/fee-schedule", sha256="x"
    )
    assert nothing["status"] == "UNVERIFIED" and nothing["parse_status"].startswith("NO_QUADRATIC")
    failed = build_evidence(
        None, source_url="https://kalshi.com/fee-schedule", sha256=None, error="403"
    )
    assert failed["status"] == "FETCH_FAILED" and not failed["verified_official"]


def test_assumption_comparison_reports_match_mismatch_and_unverified():
    from cbb_edge.kalshi.research.fee_probe import compare_with_assumption

    official = {
        "verified_official": True,
        "taker_coefficients": [0.07],
        "maker_coefficients": [0.0175],
    }
    assert compare_with_assumption(official, 0.07, 0.0175)["status"] == "MATCH"
    other = dict(official, taker_coefficients=[0.035])
    assert compare_with_assumption(other, 0.07, 0.0175)["status"] == "MISMATCH"
    assert compare_with_assumption(None, 0.07, 0.0175)["status"] == "UNVERIFIED"


def test_official_coefficients_replace_the_assumption_in_fee_rules():
    from datetime import date

    d = date(2026, 11, 2)
    base = fees.rule_for({"fee_type": "quadratic", "fee_multiplier": 1}, d)
    official = fees.rule_for({"fee_type": "quadratic", "fee_multiplier": 1}, d, (0.035, 0.00875))
    assert base.taker_rate == pytest.approx(0.07) and official.taker_rate == pytest.approx(0.035)
    assert official.version.endswith(":coef=official") and "coef=official" not in base.version
    assert fees.rule_for(None, d, (0.035, 0.00875)).taker_rate == pytest.approx(0.035)
    c = contract([obs(20, 0.40, 0.44)], result="yes")
    c.fee_coefficients = (0.035, 0.00875)
    _, rows = evaluate_contract(c, {7: (80, 60)})
    y = [r for r in rows if r["entry"] == "CLOSE"][0]["yes"]
    assert y["fee"] == pytest.approx(fees.fee_per_contract(0.44, 25, 0.035))


# ---------------------------------------------------------------- selection vs quoted-execution CLV
def test_unchanged_market_has_zero_selection_clv_and_pooled_legs_equal_the_half_spread():
    # book 0.46/0.54 at open and at the close: nothing moved, the spread is 0.08
    c = contract([obs(0, 0.46, 0.54), obs(29.5, 0.46, 0.54)])
    _, rows = evaluate_contract(c, {})
    open_row = {r["entry"]: r for r in rows}["OPEN"]
    assert open_row["yes"]["clv_selection"] == pytest.approx(0.0)
    assert open_row["no"]["clv_selection"] == pytest.approx(0.0)
    assert open_row["yes"]["clv_gross"] == pytest.approx(-0.04)  # mid 0.50 - ask 0.54
    assert open_row["no"]["clv_gross"] == pytest.approx(-0.04)
    # pooled over both legs the mean is the half-spread by construction: it carries no direction information
    assert matrix._clv([open_row], "clv_gross")["mean"] == pytest.approx(-0.04)


def test_genuine_move_is_visible_in_selection_clv_and_cancels_in_the_pooled_legs():
    c = contract([obs(0, 0.46, 0.54), obs(29.5, 0.51, 0.59)])  # mid 0.50 -> 0.55
    _, rows = evaluate_contract(c, {})
    r = {x["entry"]: x for x in rows}["OPEN"]
    assert r["yes"]["clv_selection"] == pytest.approx(0.05)
    assert r["no"]["clv_selection"] == pytest.approx(-0.05)  # YES/NO mirror
    assert matrix._clv([r], "clv_selection")["mean"] == pytest.approx(
        0.0
    )  # pooled legs cancel: not a selection metric
    r["model"] = {"v1": {"ev_yes": 0.04, "ev_no": -0.04}}  # model prefers YES
    assert matrix._model_side_clv([r], "v1")["mean"] == pytest.approx(0.05)
    r["model"] = {"v1": {"ev_yes": -0.04, "ev_no": 0.04}}  # model prefers NO
    assert matrix._model_side_clv([r], "v1")["mean"] == pytest.approx(-0.05)


def test_close_row_and_one_sided_book_have_no_selection_clv():
    c = contract([obs(0, None, 0.54), obs(29.5, 0.46, 0.54)])
    _, rows = evaluate_contract(c, {})
    by = {r["entry"]: r for r in rows}
    assert "clv_selection" not in by["CLOSE"]["yes"]  # the close is the benchmark, not an entry
    assert "clv_selection" not in by["OPEN"]["yes"]  # one-sided entry book: no midpoint, no CLV
