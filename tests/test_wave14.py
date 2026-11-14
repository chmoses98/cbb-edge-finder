"""Wave 14: prior-weight challenger - no lookahead, fail-closed inputs, bounds, score consistency,
frozen-record integrity, benchmark comparison and the preregistered decision rule."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cbb_edge.model import pw_level as pw
from cbb_edge.research import wave1 as w
from cbb_edge.research import wave14 as w14

T0 = datetime(2026, 11, 12, 18, tzinfo=UTC)
SPEC = json.loads((Path(__file__).parents[1] / "research/wave14/spec.json").read_text())


def mi(pace=0.6, eff=0.6, poss=70.0, cutoff="2026-11-12T10:00:00+00:00"):
    def blk(pwt, strength):
        return {"basis": pw.BASIS, "prior_weight": pwt, "current_weight": 1 - pwt,
                "prior_strength": strength, "effective_sample": strength / pwt}  # fmt: skip

    side = {"pace_weighting": blk(pace, 3.0), "efficiency_weighting": blk(eff, 225.0)}
    return {"version": pw.INPUTS_VERSION, "home": deepcopy(side), "away": deepcopy(side),
            "expected_possessions": {"value": poss}, "info_cutoff_utc": cutoff}  # fmt: skip


AS_OF = datetime(2026, 11, 12, 12, tzinfo=UTC)


def games(n, bias=0.05, seed=1, start=T0):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        poss, p = rng.uniform(64, 76), rng.uniform(0.55, 1.0)
        tip = start + timedelta(hours=6 * i)
        g = {"game_id": i, "tip": tip, "as_of": tip - timedelta(hours=4), "poss": poss, "pbar": p,
             "margin": rng.uniform(-12, 12), "margin_sd": 12.0, "total": 140.0, "total_sd": 16.0,
             "home_score": 70.0, "away_score": 70.0, "home_wp": 0.5}  # fmt: skip
        g["_t"] = g["total"] + bias * p * poss + rng.gauss(0, 14)
        out.append(g)
    return out


def finals_of(gs):
    return {g["game_id"]: {"home": round(g["_t"] / 2), "away": round(g["_t"] / 2) + 1,
                           "available_at": g["tip"] + timedelta(hours=3)} for g in gs}  # fmt: skip


# -------------------------------------------------------------------- inputs: fail closed, bounds
def test_valid_inputs_pass_and_pbar_is_mean_of_four():
    m = mi(pace=0.8, eff=0.4)
    assert pw.validate_inputs(m, as_of=AS_OF, possessions=70.0) == []
    assert pw.pbar(m) == pytest.approx(0.6)


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda m: m.pop("home"), "home.pace_weighting:missing_or_nonfinite"),
        (
            lambda m: m["home"]["pace_weighting"].update(prior_weight=1.2),
            "prior_weight_out_of_bounds",
        ),
        (
            lambda m: m["away"]["efficiency_weighting"].update(prior_weight=float("nan")),
            "missing_or_nonfinite",
        ),
        (
            lambda m: m["home"]["pace_weighting"].update(current_weight=0.9),
            "weights_do_not_sum_to_1",
        ),
        (
            lambda m: m["home"]["pace_weighting"].update(effective_sample=99.0),
            "inconsistent_with_ess",
        ),
        (lambda m: m["home"]["pace_weighting"].update(basis="exact"), "basis"),
        (lambda m: m.update(version="other"), "inputs_version"),
        (lambda m: m["expected_possessions"].update(value=60.0), "possessions_mismatch"),
        (
            lambda m: m.update(info_cutoff_utc="2026-11-12T13:00:00+00:00"),
            "info_cutoff_after_as_of",
        ),
        (lambda m: m.update(info_cutoff_utc="garbage"), "info_cutoff_unparseable"),
    ],
)
def test_invalid_inputs_fail_closed(mutate, reason):
    m = mi()
    mutate(m)
    assert any(reason in r for r in pw.validate_inputs(m, as_of=AS_OF, possessions=70.0))


def test_absent_inputs_fail_closed():
    assert pw.validate_inputs(None, as_of=AS_OF, possessions=70.0) == ["model_inputs_absent"]


def test_attach_inputs_marks_missing_and_mismatched_as_none():
    g = games(3)
    base = {x["game_id"]: x for x in g}
    inputs = {0: {"as_of": g[0]["as_of"], "mi": mi(poss=g[0]["poss"], cutoff=g[0]["as_of"].isoformat())},
              1: {"as_of": g[1]["as_of"], "mi": None}}  # fmt: skip
    w14.attach_inputs(base, inputs)
    assert base[0]["pbar"] == pytest.approx(0.6)
    assert (
        base[1]["pbar"] is None
        and base[2]["pbar"] is None
        and base[2]["input_issues"] == ["no_record"]
    )


# -------------------------------------------------------------------- fit / no lookahead / shrinkage
def hist(gs, fin):
    return [{"x": g["pbar"] * g["poss"], "total_err": fin[g["game_id"]]["home"] + fin[g["game_id"]]["away"] - g["total"]} for g in gs]  # fmt: skip


def test_beta_recovered_and_shrunk_below_raw():
    gs = games(600)
    st = pw.fit(hist(gs, finals_of(gs)))
    assert st["raw_beta"] == pytest.approx(0.05, abs=0.02)
    assert 0 < st["beta"] < st["raw_beta"]


def test_fewer_than_min_games_is_an_explicit_gap():
    gs = games(29)
    assert pw.fit(hist(gs, finals_of(gs))) is None


def test_walk_forward_uses_only_finals_available_before_as_of():
    gs = games(120)
    fin = finals_of(gs)
    st = pw.walk_forward(gs, fin)
    for g in gs[::17]:
        known = [h for h in gs if fin[h["game_id"]]["available_at"] <= g["as_of"]]
        expect = pw.fit(hist(known, fin))
        assert (st[g["game_id"]] is None) == (expect is None)
        if expect:
            assert st[g["game_id"]]["beta"] == pytest.approx(expect["beta"])


def test_future_outcome_perturbation_changes_nothing_earlier():
    gs = games(100)
    fin = finals_of(gs)
    base = pw.walk_forward(gs, fin)
    fin2 = deepcopy(fin)
    for gid in range(60, 100):
        fin2[gid]["home"] += 500
    pert = pw.walk_forward(gs, fin2)
    cut = gs[60]["as_of"]
    for g in gs:
        if g["as_of"] <= cut:
            assert pert[g["game_id"]] == base[g["game_id"]]
    assert pert[99]["beta"] != base[99]["beta"]


def test_invalid_input_games_are_excluded_from_fit():
    gs = games(100)
    fin = finals_of(gs)
    full = pw.walk_forward(gs, fin)[99]
    for g in gs[:50]:
        g["pbar"] = None
    reduced = pw.walk_forward(gs, fin)[99]
    assert reduced["n_games"] < full["n_games"] and reduced["n_games"] > 0


# -------------------------------------------------------------------- score consistency
def test_adjusted_scores_are_consistent_and_margin_untouched():
    g = games(1)[0]
    a = pw.adapt(g, {"beta": 0.04}, 0.8)
    shift = 0.04 * 0.8 * g["poss"]
    assert a["total"] == pytest.approx(g["total"] + shift)
    assert a["home_score"] + a["away_score"] == pytest.approx(a["total"])
    assert a["home_score"] - a["away_score"] == pytest.approx(g["home_score"] - g["away_score"])
    assert (
        a["margin"] == g["margin"]
        and a["margin_sd"] == g["margin_sd"]
        and a["total_sd"] == g["total_sd"]
    )


def test_zero_beta_is_identity():
    g = games(1)[0]
    a = pw.adapt(g, {"beta": 0.0}, 0.9)
    assert a["total"] == g["total"] and a["home_score"] == g["home_score"]


# -------------------------------------------------------------------- spec == code
def test_code_matches_frozen_spec():
    assert pw.Params().__dict__ == SPEC["params"]
    assert w14.PROSPECTIVE_FROM == SPEC["prospective_from"]
    e, d = SPEC["evaluation"], SPEC["decision"]
    assert (w14.REPS, w14.SEED, w14.CI, w14.MIN_GAMES, w14.MIN_DATES) == (e["bootstrap_reps"], e["seed"], e["interval"], e["min_games"], e["min_dates"])  # fmt: skip
    assert (w14.NONINF_TOTAL_VS_W12, w14.MARGIN_MAE_TOL, w14.LOGLOSS_TOL) == (d["noninferiority_total_mae_vs_w12_level_points"], d["margin_mae_upper_tol_points"], d["logloss_upper_tol"])  # fmt: skip


# -------------------------------------------------------------------- evaluation / benchmarks
def frozen_for(gs, shift_bias=0.0):
    """Frozen versions share the same base (pure-0.2.0 / roster get independent tiny offsets)."""
    base = {g["game_id"]: g for g in gs}
    return {
        "pure-0.5.0": base,
        "pure-0.2.0": {k: {**v, "total": v["total"] + 0.5} for k, v in base.items()},
        "pure-0.5.0_roster": {k: {**v, "total": v["total"] - 0.5} for k, v in base.items()},
    }


def run(n, bias=0.05, from_="2026-11-01T00:00:00+00:00"):
    gs = games(n, bias=bias, start=datetime(2026, 11, 20, 18, tzinfo=UTC))
    for g in gs:
        g["pbar"] = g["pbar"]
    return w14.build_rows(frozen_for(gs), finals_of(gs), prospective_from=from_)


def test_rows_identical_games_margin_and_calibration_equal_to_pure050():
    rows, funnel = run(300)
    assert funnel["eligible"] == len(rows) > 0
    for r in rows:
        assert r[pw.VERSION]["margin_err"] == r["pure-0.5.0"]["margin_err"]
        assert r[pw.VERSION]["p_home"] == r["pure-0.5.0"]["p_home"]
        assert r[pw.VERSION]["logloss"] == r["pure-0.5.0"]["logloss"]
        assert r[pw.VERSION]["home_err"] + r[pw.VERSION]["away_err"] == pytest.approx(r[pw.VERSION]["total_err"])  # fmt: skip


def test_prospective_boundary_excludes_earlier_records_and_missing_inputs():
    rows, funnel = run(200, from_="2999-01-01T00:00:00+00:00")
    assert rows == [] and funnel["record_before_registration"] == 200
    gs = games(100, start=datetime(2026, 11, 20, 18, tzinfo=UTC))
    for g in gs[:10]:
        g["pbar"] = None
    _, f = w14.build_rows(
        frozen_for(gs), finals_of(gs), prospective_from="2026-11-01T00:00:00+00:00"
    )
    assert f["inputs_invalid_or_missing"] == 10
    nofin = finals_of(gs)
    nofin.pop(99)
    _, f = w14.build_rows(frozen_for(gs), nofin, prospective_from="2026-11-01T00:00:00+00:00")
    assert f["no_verified_final_yet"] == 1


def test_challenger_beats_pure050_when_the_effect_is_real_and_not_when_absent():
    rows, _ = run(600, bias=0.12)
    c = w14.cluster_diff(rows[-300:], pw.VERSION, "pure-0.5.0", "abs:total_err", reps=500)
    assert c["diff"] < 0 and c["hi"] < 0
    rows0, _ = run(600, bias=0.0)
    c0 = w14.cluster_diff(rows0[-300:], pw.VERSION, "pure-0.5.0", "abs:total_err", reps=500)
    assert abs(c0["diff"]) < 0.3


def test_cluster_bootstrap_is_deterministic_and_clusters_by_date():
    rows, _ = run(200)
    a = w14.cluster_diff(rows, pw.VERSION, "pure-0.5.0", "abs:total_err", reps=300)
    assert a == w14.cluster_diff(rows, pw.VERSION, "pure-0.5.0", "abs:total_err", reps=300)
    assert a["n_dates"] == len({r["date"] for r in rows}) < a["n"]


# -------------------------------------------------------------------- decision rule
def fake_rows(n, dates, ch_total=-1.0):
    def f(te):
        return {"total_err": te, "margin_err": 3.0, "p_home": 0.6, "logloss": 0.5, "brier": 0.2}

    out = []
    for i in range(n):
        r = {"date": f"d{i % dates}", "game_id": i}
        for name in w14.FORECASTERS:
            r[name] = f(10.0)
        r[pw.VERSION] = f(10.0 + ch_total + (0.2 if i % 2 else -0.2))
        out.append(r)
    return out


def test_collecting_below_floor_never_claims_success():
    v = w14.verdict(fake_rows(149, 10))
    assert v["status"] == "COLLECTING / INSUFFICIENT EVIDENCE"
    assert w14.verdict(fake_rows(500, 4))["status"] == "COLLECTING / INSUFFICIENT EVIDENCE"
    assert w14.verdict([])["status"] == "COLLECTING / INSUFFICIENT EVIDENCE"


def test_improved_only_when_every_criterion_holds():
    rows = fake_rows(200, 8, ch_total=-1.0)
    # challenger beats pure-0.5.0 AND ties Wave 12 level-only => IMPROVED
    for r in rows:
        r["wf-level-0.5.0-v1:level-only"] = dict(r[pw.VERSION])
    assert w14.verdict(rows)["status"].startswith("IMPROVED")


def test_regression_vs_w12_blocks_improved_and_no_gain_is_not_improved():
    rows = fake_rows(200, 8, ch_total=-1.0)
    for r in rows:  # W12 level-only far better than challenger => cannot be IMPROVED
        r["wf-level-0.5.0-v1:level-only"] = {**r[pw.VERSION], "total_err": 5.0}
    assert not w14.verdict(rows)["status"].startswith("IMPROVED")
    assert w14.verdict(fake_rows(200, 8, ch_total=+1.0))["status"] == "NOT IMPROVED"


# -------------------------------------------------------------------- frozen-record integrity
def test_verify_manifests_detects_modification_and_missing(tmp_path):
    import hashlib

    f = tmp_path / "projections" / "pure-0.5.0" / "x.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    (tmp_path / "projections" / "manifests").mkdir()
    (tmp_path / "projections" / "manifests" / "m.json").write_text(json.dumps({"files": {"pure-0.5.0/x.json": hashlib.sha256(b"{}").hexdigest()}}))  # fmt: skip
    assert w14.verify_manifests(tmp_path)["ok"]
    f.write_text('{"edited": 1}')
    assert not w14.verify_manifests(tmp_path)["ok"]
    f.unlink()
    assert w14.verify_manifests(tmp_path)["missing"] == 1


def test_loader_reads_without_writing(tmp_path):
    d = tmp_path / "projections/pure-0.5.0/2027/2026-11-12/G1"
    d.mkdir(parents=True)
    rec = {"game": {"espn_game_id": 1, "start_time_utc": "2026-11-12T23:00:00+00:00"},
           "prospective": {"as_of": "2026-11-12T12:00:00+00:00"}, "model_inputs": mi()}  # fmt: skip
    p = d / "2026-11-12T120000Z.json"
    p.write_text(json.dumps(rec))
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    got = w14.load_inputs(tmp_path)
    assert got[1]["mi"]["version"] == pw.INPUTS_VERSION
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


# -------------------------------------------------------------------- freeze provenance (stricter only)
def _pushed(gs, delta):
    return {g["game_id"]: {"pushed_by": g["tip"] + delta, "reason": None} for g in gs}


def test_freeze_provenance_excludes_unprovable_and_late_pushes_only():
    gs = games(120, start=datetime(2026, 11, 20, 18, tzinfo=UTC))
    fr, fin, frm = frozen_for(gs), finals_of(gs), "2026-11-01T00:00:00+00:00"
    plain, f0 = w14.build_rows(fr, fin, prospective_from=frm)
    ok, f1 = w14.build_rows(fr, fin, prospective_from=frm, pushed=_pushed(gs, -timedelta(hours=1)))
    assert [r["game_id"] for r in ok] == [r["game_id"] for r in plain] and f1 == f0
    pushed = _pushed(gs, -timedelta(hours=1))
    late = [g["game_id"] for g in gs[-5:]]
    for gid in late[:2]:
        pushed[gid] = {"pushed_by": None, "reason": "manifest_push_time_unverified"}
    for gid in late[2:]:
        pushed[gid]["pushed_by"] = gs[gid]["tip"]  # pushed AT tip is not before tip
    rows, f = w14.build_rows(fr, fin, prospective_from=frm, pushed=pushed)
    assert f["freeze_time_not_provable"] == 2 and f["freeze_pushed_at_or_after_tip"] == 3
    assert not {r["game_id"] for r in rows} & set(late)


def test_freeze_pushed_at_requires_every_version_in_a_proven_manifest():
    gs = games(3, start=datetime(2026, 11, 20, 18, tzinfo=UTC))
    fr = frozen_for(gs)
    t = datetime(2026, 11, 20, 12, tzinfo=UTC)
    recm = {(v, g["game_id"], g["as_of"].isoformat()): "M1" for v in w14.VERSIONS for g in gs}
    recm.pop(("pure-0.5.0_roster", 1, gs[1]["as_of"].isoformat()))
    recm[("pure-0.2.0", 2, gs[2]["as_of"].isoformat())] = "M2"
    out = w14.freeze_pushed_at(fr, recm, {"M1": {"pushed_by": t.isoformat()}})
    assert out[0] == {"pushed_by": t, "reason": None}
    assert out[1]["pushed_by"] is None and out[1]["reason"] == "record_not_in_any_manifest"
    assert out[2]["pushed_by"] is None and out[2]["reason"] == "manifest_push_time_unverified"


def test_record_manifests_maps_version_game_and_as_of(tmp_path):
    (tmp_path / "projections" / "manifests").mkdir(parents=True)
    files = {"2027/2026-11-12/G7/a.json": "x", "pure-0.5.0/2027/2026-11-12/G7/a.json": "y"}
    (tmp_path / "projections" / "manifests" / "M.json").write_text(json.dumps({"as_of": "2026-11-12T21:10:53+00:00", "files": files}))  # fmt: skip
    got = w14.record_manifests(tmp_path)
    key = datetime(2026, 11, 12, 21, 10, 53, tzinfo=UTC).isoformat()
    assert got == {("pure-0.2.0", 7, key): "M", ("pure-0.5.0", 7, key): "M"}


# -------------------------------------------------------------------- market benchmark (never an input)
def test_market_benchmark_sign_pre_tip_only_and_verdict_unchanged():
    rows, _ = run(200)
    v0 = w14.verdict(rows)
    r0, r1 = rows[0], rows[1]
    market = {
        r0["game_id"]: {
            "captured_at": r0["tip"] - timedelta(minutes=30),
            "spread": -5.0,
            "total": 141.0,
        },
        r1["game_id"]: {"captured_at": r1["tip"], "spread": -5.0, "total": 141.0},  # not pre-tip
    }
    cnt = w14.attach_market(rows, market)
    assert cnt == {"with_line": 1, "no_pre_tip_line": len(rows) - 1}
    m = r0[w14.MARKET]
    assert m["margin_err"] == r0["actual_margin"] - 5.0  # market margin = -spread = +5
    assert m["total_err"] == r0["actual_total"] - 141.0
    assert w14.MARKET not in r1
    assert w14.verdict(rows) == v0
    assert w14.market_summary(rows)[w14.MARKET]["n"] == 1


def test_game_level_interval_is_descriptive_and_single_date_collapses():
    rows, _ = run(200)
    one = [{**r, "date": "d"} for r in rows[:40]]
    c = w14.cluster_diff(one, pw.VERSION, "pure-0.5.0", "abs:total_err", reps=200)
    assert c["lo"] == c["hi"] == c["diff"] and c["n_dates"] == 1
    gl = w14.game_level_diff(one, pw.VERSION, "pure-0.5.0", "abs:total_err")
    assert gl["diff"] == pytest.approx(c["diff"]) and gl["n_dates"] == 40


# -------------------------------------------------------------------- verified-push selection (amendment 5a)
def _arch(root, gid, tip, as_of, manifest):
    """One frozen record per compared version at ``as_of``, listed in ``manifest``."""
    proj = {"margin": 2.0, "total": 140.0, "margin_sd": 11.0, "total_sd": 15.0, "home_score": 71.0,
            "away_score": 69.0, "possessions": 70.0, "home_ppp": 1.01, "away_ppp": 0.99,
            "home_win_prob": 0.57}  # fmt: skip
    stamp = as_of.strftime("%Y%m%dT%H%M%SZ")
    mpath = root / "projections" / "manifests" / f"{manifest}.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    m = (
        json.loads(mpath.read_text())
        if mpath.exists()
        else {"as_of": as_of.isoformat(), "files": {}}
    )
    for v in w14.VERSIONS:
        rel = f"{'' if v == 'pure-0.2.0' else v + '/'}2027/{tip.date()}/G{gid}/{stamp}.json"
        rec = {"game": {"espn_game_id": gid, "start_time_utc": tip.isoformat()},
               "prospective": {"as_of": as_of.isoformat()}, "projection": proj,
               "model_inputs": mi(cutoff=(as_of - timedelta(hours=1)).isoformat())}  # fmt: skip
        f = root / "projections" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec))
        m["files"][rel] = "sha-not-checked-here"
    mpath.write_text(json.dumps(m))


def test_selection_falls_back_to_latest_verified_pre_tip_push_and_quarantines_the_rest(tmp_path):
    tip = datetime(2026, 11, 20, 23, tzinfo=UTC)
    a, b, c = tip - timedelta(hours=9), tip - timedelta(minutes=40), tip - timedelta(minutes=5)
    _arch(tmp_path, 1, tip, a, "MA")  # verified, pushed well before tip
    _arch(tmp_path, 1, tip, b, "MB")  # verified, but pushed AFTER tip (the 401916315 pattern)
    _arch(tmp_path, 1, tip, c, "MC")  # manifest has no provenance entry (unverified)
    _arch(tmp_path, 2, tip, b, "MB")  # only record pushed after tip: no admissible record
    _arch(tmp_path, 3, tip, a, "MA")
    _arch(tmp_path, 3, tip, b, "MB3")  # verified pre-tip latest: selected, no fallback
    prov = {"MA": {"pushed_by": (a + timedelta(minutes=3)).isoformat()},
            "MB": {"pushed_by": (tip + timedelta(minutes=2)).isoformat()},
            "MB3": {"pushed_by": (tip - timedelta(seconds=1)).isoformat()}}  # fmt: skip
    recm = w14.record_manifests(tmp_path)
    frozen, inputs, audit = w14.load_verified(tmp_path, recm, prov)
    for v in w14.VERSIONS:
        assert frozen[v][1]["as_of"] == a  # fell back past post-tip B and unverified C
        assert frozen[v][3]["as_of"] == b
        assert 2 not in frozen[v]
        assert audit["fallback"][v] == [1]
        assert audit["no_verified_pre_tip_record"][v] == [2]
        q = {(r["game_id"], r["as_of"]): r["reason"] for r in audit["quarantined"][v]}
        assert q == {(1, b.isoformat()): "pushed_at_or_after_tip",
                     (1, c.isoformat()): "manifest_push_time_unverified",
                     (2, b.isoformat()): "pushed_at_or_after_tip"}  # fmt: skip
    # inputs come from the SAME fallback record, so pbar is defined (not "no_record")
    assert inputs[1]["as_of"] == a and 2 not in inputs
    base = frozen[pw.BASE_VERSION]
    w14.attach_inputs(base, inputs)
    assert base[1]["input_issues"] == [] and base[1]["pbar"] is not None
    # the defence-in-depth gate agrees: every selected record is provably pushed before tip
    pushed = w14.freeze_pushed_at(frozen, recm, prov)
    assert all(p["reason"] is None and p["pushed_by"] < tip for p in pushed.values())


def test_quarantined_record_is_never_requalified(tmp_path):
    tip = datetime(2026, 11, 20, 23, tzinfo=UTC)
    a, b = tip - timedelta(hours=9), tip - timedelta(minutes=40)
    _arch(tmp_path, 1, tip, a, "MA")
    _arch(tmp_path, 1, tip, b, "MB")
    recm = w14.record_manifests(tmp_path)
    ok = {"MA": {"pushed_by": (a + timedelta(minutes=3)).isoformat()}}
    for mb in ({}, {"pushed_by": None}, {"pushed_by": "garbage"}, {"pushed_by": tip.isoformat()},
               {"pushed_by": (tip + timedelta(hours=5)).isoformat()}):  # fmt: skip
        frozen, _, audit = w14.load_verified(tmp_path, recm, {**ok, "MB": mb})
        assert all(frozen[v][1]["as_of"] == a for v in w14.VERSIONS), mb
    # no verified record at all -> the game is absent, never selected from unverified records
    frozen, _, audit = w14.load_verified(tmp_path, recm, {})
    assert all(1 not in frozen[v] for v in w14.VERSIONS)
    assert audit["no_verified_pre_tip_record"][pw.BASE_VERSION] == [1]


def test_load_frozen_without_allow_is_unchanged(tmp_path):
    from cbb_edge.research import wave1 as w

    tip = datetime(2026, 11, 20, 23, tzinfo=UTC)
    _arch(tmp_path, 1, tip, tip - timedelta(hours=9), "MA")
    _arch(tmp_path, 1, tip, tip - timedelta(minutes=5), "MB")
    assert w.load_frozen(tmp_path, pw.BASE_VERSION)[1]["as_of"] == tip - timedelta(minutes=5)
    assert w14.load_inputs(tmp_path)[1]["as_of"] == tip - timedelta(minutes=5)


def test_pre_registration_records_are_selected_unchanged_for_training_only(tmp_path):
    # provenance is only built from PROSPECTIVE_FROM on; earlier records are never eligible and
    # only train the walk-forward challengers, so their selection must not change
    tip = datetime(2026, 11, 10, 23, tzinfo=UTC)
    early, late = tip - timedelta(hours=9), tip - timedelta(minutes=5)
    _arch(tmp_path, 1, tip, early, "MA")
    _arch(tmp_path, 1, tip, late, "MB")
    frozen, inputs, audit = w14.load_verified(tmp_path, w14.record_manifests(tmp_path), {})
    assert all(frozen[v][1]["as_of"] == late for v in w14.VERSIONS) and inputs[1]["as_of"] == late
    assert audit["quarantined"][pw.BASE_VERSION] == [] and audit["fallback"][pw.BASE_VERSION] == []
    # a post-boundary record with no verified push falls back to a pre-boundary record, which is
    # then excluded as record_before_registration (never evaluated)
    tip2 = datetime(2026, 11, 12, 1, tzinfo=UTC)
    _arch(tmp_path, 2, tip2, datetime(2026, 11, 11, 20, tzinfo=UTC), "MC")
    _arch(tmp_path, 2, tip2, datetime(2026, 11, 11, 23, tzinfo=UTC), "MD")
    frozen, _, audit = w14.load_verified(tmp_path, w14.record_manifests(tmp_path), {})
    assert frozen[pw.BASE_VERSION][2]["as_of"] < w.parse_ts(w14.PROSPECTIVE_FROM)
    assert audit["fallback"][pw.BASE_VERSION] == [2]
