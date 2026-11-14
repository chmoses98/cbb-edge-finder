import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cbb_edge.research import challenger_eval as ce
from cbb_edge.research import wave15 as w15

SPEC = json.loads((Path(__file__).parents[1] / "research/wave15/spec.json").read_text())
T0 = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)


def test_code_matches_spec():
    p = w15.Params()
    assert SPEC["params"] == {"k": p.k, "m_ref": p.m_ref, "min_games": p.min_games,
                              "var_floor": p.var_floor, "link_slope": ce.LINK_SLOPE}  # fmt: skip
    assert SPEC["window"] == {"prospective_from": ce.PROSPECTIVE_FROM, "last_et_date": ce.LAST_ET_DATE,
                              "analysis_not_before": ce.ANALYSIS_NOT_BEFORE}  # fmt: skip
    assert SPEC["model_sha256"] == ce.MODEL_SHA and SPEC["base_version"] == w15.BASE
    assert set(SPEC["challengers"]) == {w15.A1, w15.A2}
    assert SPEC["family"]["tests"] == list(ce.FAMILY)
    ev = SPEC["evaluation"]
    assert (ev["bootstrap_reps"], ev["seed"], ev["min_games"], ev["min_dates"]) == (ce.REPS, ce.SEED, ce.MIN_GAMES, ce.MIN_DATES)  # fmt: skip
    assert math.isclose(ev["primary_quantile"], ce.PRIMARY_Q, abs_tol=1e-5) and ev["guard_quantile"] == ce.GUARD_Q  # fmt: skip
    for name, guards in ((w15.A1, w15.GUARDS_A1), (w15.A2, w15.GUARDS_A2)):
        assert SPEC["challengers"][name]["guards"] == {k: t for k, (_, t) in guards.items()}


def _g(gid, m, as_of, sd=12.0):
    return {"game_id": gid, "margin": m, "margin_sd": sd, "home_wp": ce.sigmoid(ce.LINK_SLOPE * m),
            "as_of": as_of, "tip": as_of + timedelta(hours=2), "sha": ce.MODEL_SHA}  # fmt: skip


def test_fit_stretch_shrinks_toward_one():
    p = w15.Params()
    hist = [_g(i, 10.0, T0) for i in range(40)]
    y = {i: 12.0 for i in range(40)}  # actual = 1.2 * projected
    s = w15.fit_stretch(hist, y, p)
    assert s is not None and 1.0 < s < 1.2
    assert w15.fit_stretch(hist[:10], y, p) is None


def test_fit_hsd_identity_when_calibrated_and_detects_slope():
    p = w15.Params()
    hist = [_g(i, 0.0 if i % 2 else 30.0, T0) for i in range(400)]
    # small games: |err| = 0.5 sd; big games: |err| = 1.5 sd  -> variance grows with |m|
    y = {g["game_id"]: g["margin"] + (6.0 if g["margin"] == 0 else 18.0) * (1 if g["game_id"] % 4 < 2 else -1) for g in hist}  # fmt: skip
    c = w15.fit_hsd(hist, y, p)
    assert c is not None and c[1] > 0.5
    big = w15.adapt_hsd(_g(999, 30.0, T0), c, p)
    small = w15.adapt_hsd(_g(998, 0.0, T0), c, p)
    assert big["margin_sd"] > 12.0 > small["margin_sd"] >= 12.0 * math.sqrt(p.var_floor)


def test_adapt_stretch_moves_prob_along_link_and_keeps_sd():
    g = _g(1, 10.0, T0)
    a = w15.adapt_stretch(g, 1.1)
    assert math.isclose(a["margin"], 11.0) and a["margin_sd"] == g["margin_sd"]
    assert math.isclose(a["p_home"], ce.sigmoid(ce.LINK_SLOPE * 11.0), rel_tol=1e-9)


def test_build_rows_no_leakage_and_fail_closed():
    late = T0 + timedelta(days=1)
    train = [_g(i, 8.0, T0 - timedelta(days=3)) for i in range(40)]
    target = _g(500, 8.0, late)
    unprovable = _g(501, 8.0, late)
    old_sha = {**_g(502, 8.0, late), "sha": "other"}
    frozen = {w15.BASE: {g["game_id"]: g for g in [*train, target, unprovable, old_sha]}}
    finals = {g["game_id"]: {"home": 80, "away": 70, "available_at": g["tip"] + timedelta(hours=3)} for g in frozen[w15.BASE].values()}  # fmt: skip
    # a training final observed AFTER the target's as_of must not be used
    finals[0]["available_at"] = late + timedelta(minutes=1)
    pushed = {500: target["as_of"] + timedelta(minutes=5), 502: late + timedelta(minutes=5)}
    rows, funnel = w15.build_rows(frozen, finals, pushed=pushed)
    assert [r["game_id"] for r in rows] == [500]
    assert rows[0]["n_train"] == 39  # game 0 excluded (final not yet observed), targets excluded
    assert funnel["freeze_time_not_provable"] == 1
    assert funnel["model_sha_differs_from_registered"] == 1
    assert funnel["record_before_registration_or_missing"] == 40
    for name in w15.FORECASTERS:
        assert set(rows[0][name]) >= {"abs_margin_err", "logloss", "brier", "margin_nll"}
    assert (
        rows[0][w15.A2]["abs_margin_err"] == rows[0][w15.BASE]["abs_margin_err"]
    )  # A2 keeps margin
