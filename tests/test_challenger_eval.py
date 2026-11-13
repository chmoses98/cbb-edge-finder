import math
from datetime import UTC, datetime, timedelta

from cbb_edge.research import challenger_eval as ce

T0 = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)


def test_family_level_and_quantiles():
    assert ce.FAMILY_ALPHA == 0.05 and len(ce.FAMILY) == 3
    assert math.isclose(ce.PRIMARY_Q, 1 - 0.05 / 3)


def test_shift_prob_moves_along_link():
    p = 0.7
    assert math.isclose(ce.shift_prob(p, 0.0), p, rel_tol=1e-12)
    assert ce.shift_prob(p, 5.0) > p > ce.shift_prob(p, -5.0)
    assert math.isclose(ce.logit(ce.shift_prob(p, 2.0)) - ce.logit(p), 2 * ce.LINK_SLOPE, rel_tol=1e-9)  # fmt: skip


def test_score_metrics():
    s = ce.score({"margin": 5.0, "margin_sd": 10.0, "p_home": 0.6}, 8.0)
    assert s["margin_err"] == 3.0 and s["abs_margin_err"] == 3.0 and s["in80"] == 1.0
    assert math.isclose(s["logloss"], -math.log(0.6)) and math.isclose(s["brier"], 0.16)
    assert math.isclose(s["margin_nll"], 0.5 * math.log(2 * math.pi * 100) + 0.5 * 0.09)


def test_walk_forward_history_excludes_unobserved_finals():
    g1 = {"game_id": 1}
    g2 = {"game_id": 2}
    finals = {1: {"available_at": T0}, 2: {"available_at": T0 + timedelta(hours=5)}}
    hist = ce.training_history([g1, g2], finals)
    assert [g["game_id"] for g in ce.before(hist, T0 + timedelta(hours=1))] == [1]
    assert [g["game_id"] for g in ce.before(hist, T0 - timedelta(seconds=1))] == []


def _rows(diffs_by_date):
    rows = []
    for d, vals in diffs_by_date.items():
        for v in vals:
            rows.append({"date": d, "a": {"m": v}, "b": {"m": 0.0}})
    return rows


def test_cluster_boot_resamples_dates():
    rows = _rows({f"2026-11-{i:02d}": [-1.0, -1.2] for i in range(15, 30)})
    c = ce.cluster_boot(rows, "a", "b", "m", reps=500)
    assert c["n"] == 30 and c["n_dates"] == 15 and c["hi_primary"] < 0 and c["p_ge0"] == 0.0


def _vrows(n_dates, per, delta):
    rows = []
    for i in range(n_dates):
        for j in range(per):
            base = {"abs_margin_err": 10.0, "logloss": 0.4, "brier": 0.13}
            ch = {"abs_margin_err": 10.0 + delta + (0.01 if j % 2 else -0.01), "logloss": 0.4, "brier": 0.13}  # fmt: skip
            rows.append({"date": f"d{i:02d}", "C": ch, "B": base})
    return rows


def test_primary_verdict_collecting_before_analysis_time_even_with_strong_data():
    rows = _vrows(12, 30, -0.5)
    v = ce.primary_verdict(rows, "C", "B", "abs_margin_err", {}, now=T0)
    assert v["status"] == "COLLECTING / INSUFFICIENT EVIDENCE"


def test_primary_verdict_rules_after_window():
    late = ce.w.parse_ts(ce.ANALYSIS_NOT_BEFORE)
    guards = {"logloss": ("logloss", 0.005)}
    assert ce.primary_verdict(_vrows(12, 30, -0.5), "C", "B", "abs_margin_err", guards, now=late)["status"] == "IMPROVED"  # fmt: skip
    assert ce.primary_verdict(_vrows(12, 30, +0.5), "C", "B", "abs_margin_err", guards, now=late)["status"] == "NOT IMPROVED"  # fmt: skip
    assert ce.primary_verdict(_vrows(5, 30, -0.5), "C", "B", "abs_margin_err", guards, now=late)["status"] == "INSUFFICIENT EVIDENCE"  # fmt: skip
