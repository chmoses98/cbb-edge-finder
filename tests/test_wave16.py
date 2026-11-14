import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cbb_edge.research import challenger_eval as ce
from cbb_edge.research import wave16 as w16

SPEC = json.loads((Path(__file__).parents[1] / "research/wave16/spec.json").read_text())
T0 = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)


def test_code_matches_spec():
    p = w16.Params()
    assert SPEC["params"] == {"k": p.k, "min_games": p.min_games, "link_slope": ce.LINK_SLOPE}
    assert SPEC["window"] == {"prospective_from": ce.PROSPECTIVE_FROM, "last_et_date": ce.LAST_ET_DATE,
                              "analysis_not_before": ce.ANALYSIS_NOT_BEFORE}  # fmt: skip
    assert SPEC["model_sha256"] == ce.MODEL_SHA
    assert (SPEC["base_version"], SPEC["reference_version"]) == (w16.ROSTER, w16.BASE)
    assert list(SPEC["challengers"]) == [w16.B]
    assert SPEC["challengers"][w16.B]["guards"] == {k: t for k, (_, t) in w16.GUARDS_B.items()}
    assert SPEC["family"]["tests"] == list(ce.FAMILY)
    ev = SPEC["evaluation"]
    assert (ev["bootstrap_reps"], ev["seed"], ev["min_games"], ev["min_dates"]) == (ce.REPS, ce.SEED, ce.MIN_GAMES, ce.MIN_DATES)  # fmt: skip
    assert math.isclose(ev["primary_quantile"], ce.PRIMARY_Q, abs_tol=1e-5)


def _g(gid, m, as_of):
    return {"game_id": gid, "margin": m, "margin_sd": 12.0, "home_wp": ce.sigmoid(ce.LINK_SLOPE * m),
            "as_of": as_of, "tip": as_of + timedelta(hours=2), "sha": ce.MODEL_SHA}  # fmt: skip


def test_fit_offset_is_shrunk_mean_residual():
    p = w16.Params()
    hist = [_g(i, 5.0, T0) for i in range(30)]
    roster = {i: _g(i, 6.0, T0) for i in range(30)}
    y = {i: 5.0 for i in range(30)}  # overlay 1 point too home-ward
    c = w16.fit_offset(hist, y, roster, p)
    assert c is not None and math.isclose(c, -30.0 / 60.0)
    assert w16.fit_offset(hist[:29], y, roster, p) is None


def test_adapt_keeps_sd_and_moves_prob_along_link():
    r = _g(1, 6.0, T0)
    a = w16.adapt(r, -1.0)
    assert a["margin"] == 5.0 and a["margin_sd"] == 12.0
    assert math.isclose(a["p_home"], ce.sigmoid(ce.LINK_SLOPE * 5.0), rel_tol=1e-9)


def test_build_rows_requires_both_versions_in_window_and_provable():
    late = T0 + timedelta(days=1)
    train = [_g(i, 5.0, T0 - timedelta(days=3)) for i in range(40)]
    ok, roster_old, unprov = _g(500, 5.0, late), _g(501, 5.0, late), _g(502, 5.0, late)
    base = {g["game_id"]: g for g in [*train, ok, roster_old, unprov]}
    roster = {gid: {**g, "margin": g["margin"] + 1.0} for gid, g in base.items()}
    roster[501] = {**roster[501], "as_of": T0 - timedelta(days=1)}  # roster record before window
    frozen = {w16.BASE: base, w16.ROSTER: roster}
    finals = {gid: {"home": 75, "away": 70, "available_at": g["tip"] + timedelta(hours=3)} for gid, g in base.items()}  # fmt: skip
    pushed = {500: late + timedelta(minutes=5), 501: late + timedelta(minutes=5)}
    rows, funnel = w16.build_rows(frozen, finals, pushed=pushed)
    assert [r["game_id"] for r in rows] == [500]
    assert funnel["freeze_time_not_provable"] == 1
    assert funnel["record_before_registration_or_missing"] == 41
    r = rows[0]
    assert r["offset_c"] < 0  # overlay was 1 point too home-ward
    assert r[w16.B]["abs_margin_err"] < r[w16.ROSTER]["abs_margin_err"]
