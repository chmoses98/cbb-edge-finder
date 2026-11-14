import hashlib
import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cbb_edge.research import challenger_eval as ce
from cbb_edge.research import wave1 as w

ROOT = Path(__file__).parents[1]

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


# ---------------------------------------------- AMENDMENT 1: verified pre-tip push selection (5a)
BASE, ROSTER = "pure-0.5.0", "pure-0.5.0_roster"
W15_VERSIONS, W16_VERSIONS = (BASE,), (BASE, ROSTER)
BOUNDARY = datetime(2026, 11, 15, tzinfo=UTC)


def _arch(root, gid, tip, as_of, manifest, versions=(BASE, ROSTER), sha=ce.MODEL_SHA):
    """One frozen record per version at ``as_of`` (archive layout), listed in ``manifest``."""
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
    for v in versions:
        rel = f"{v}/2027/{tip.date()}/G{gid}/{stamp}.json"
        rec = {"game": {"espn_game_id": gid, "start_time_utc": tip.isoformat()},
               "prospective": {"as_of": as_of.isoformat(), "model_sha256": sha}, "projection": proj}  # fmt: skip
        f = root / "projections" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec))
        m["files"][rel] = "sha-not-checked-here"
    mpath.write_text(json.dumps(m))


def _prov(**k):
    return {m: {"pushed_by": t.isoformat()} for m, t in k.items()}


def test_amendment_selects_latest_verified_pre_tip_record_and_quarantines_the_rest(tmp_path):
    tip = datetime(2026, 11, 20, 23, tzinfo=UTC)
    a, b, c = tip - timedelta(hours=9), tip - timedelta(minutes=40), tip - timedelta(minutes=5)
    _arch(tmp_path, 1, tip, a, "MA")  # verified, pushed well before tip
    _arch(tmp_path, 1, tip, b, "MB")  # verified, pushed AFTER tip
    _arch(tmp_path, 1, tip, c, "MC")  # no provenance entry (unverifiable)
    _arch(tmp_path, 2, tip, b, "MB")  # only record pushed after tip
    prov = _prov(MA=a + timedelta(minutes=3), MB=tip + timedelta(minutes=2))
    frozen, audit = ce.load_verified(tmp_path, W16_VERSIONS, prov)
    for v in W16_VERSIONS:
        assert frozen[v][1]["as_of"] == a and 2 not in frozen[v]
        assert audit["fallback"][v] == [1] and audit["no_verified_pre_tip_record"][v] == [2]
        q = {(r["game_id"], r["as_of"]): r["reason"] for r in audit["quarantined"][v]}
        assert q == {(1, b.isoformat()): "pushed_at_or_after_tip",
                     (1, c.isoformat()): "manifest_push_time_unverified",
                     (2, b.isoformat()): "pushed_at_or_after_tip"}  # fmt: skip
    recm = __import__("cbb_edge.research.wave14", fromlist=["x"]).record_manifests(tmp_path)
    pushed = ce.pushed_by(frozen, W16_VERSIONS, recm, prov)
    finals = {1: {"available_at": tip + timedelta(hours=3)}}
    assert ce.eligibility(1, frozen, W16_VERSIONS, finals, pushed, 50, 30) == "eligible"


def test_amendment_never_requalifies_or_admits_unverified_records(tmp_path):
    tip = datetime(2026, 11, 20, 23, tzinfo=UTC)
    a, b = tip - timedelta(hours=9), tip - timedelta(minutes=40)
    _arch(tmp_path, 1, tip, a, "MA")
    _arch(tmp_path, 1, tip, b, "MB")
    ok = _prov(MA=a + timedelta(minutes=3))
    for mb in ({}, {"pushed_by": None}, {"pushed_by": "garbage"}, {"pushed_by": tip.isoformat()},
               {"pushed_by": (tip + timedelta(hours=5)).isoformat()}):  # fmt: skip
        frozen, _ = ce.load_verified(tmp_path, W16_VERSIONS, {**ok, "MB": mb})
        assert all(frozen[v][1]["as_of"] == a for v in W16_VERSIONS), mb
    frozen, audit = ce.load_verified(tmp_path, W16_VERSIONS, {})
    assert all(1 not in frozen[v] for v in W16_VERSIONS)
    assert audit["no_verified_pre_tip_record"][BASE] == [1]


def test_amendment_fallback_to_pre_boundary_record_is_never_eligible(tmp_path):
    tip = BOUNDARY + timedelta(hours=1)
    early, late = BOUNDARY - timedelta(hours=2), BOUNDARY + timedelta(minutes=10)
    _arch(tmp_path, 1, tip, early, "ME")  # before the family boundary: admitted unchanged (trains)
    _arch(tmp_path, 1, tip, late, "ML")  # post-boundary, pushed after tip -> quarantined
    prov = _prov(ME=early + timedelta(minutes=3), ML=tip + timedelta(minutes=1))
    frozen, audit = ce.load_verified(tmp_path, W16_VERSIONS, prov)
    assert frozen[BASE][1]["as_of"] == early and audit["fallback"][BASE] == [1]
    recm = __import__("cbb_edge.research.wave14", fromlist=["x"]).record_manifests(tmp_path)
    pushed = ce.pushed_by(frozen, W16_VERSIONS, recm, prov)
    finals = {1: {"available_at": tip + timedelta(hours=3)}}
    stage = ce.eligibility(1, frozen, W16_VERSIONS, finals, pushed, 50, 30)
    assert stage == "record_before_registration_or_missing"


def test_amendment_leaves_pre_boundary_selection_unchanged(tmp_path):
    # no provenance at all: records before the family boundary are selected exactly as registered
    tip = datetime(2026, 11, 12, 23, tzinfo=UTC)
    _arch(tmp_path, 1, tip, tip - timedelta(hours=9), "MA")
    _arch(tmp_path, 1, tip, tip - timedelta(minutes=5), "MB")
    frozen, audit = ce.load_verified(tmp_path, W16_VERSIONS, {})
    for v in W16_VERSIONS:
        assert frozen[v] == w.load_frozen(tmp_path, v)
        assert audit["quarantined"][v] == [] and audit["fallback"][v] == []


def test_waves_15_and_16_select_identical_base_records(tmp_path):
    rng = random.Random(7)
    tip0 = datetime(2026, 11, 16, 1, tzinfo=UTC)
    prov = {}
    for gid in range(1, 40):
        tip = tip0 + timedelta(hours=gid)
        for k in range(rng.randint(1, 4)):
            as_of = tip - timedelta(minutes=rng.randint(1, 900))
            m = f"M{gid}_{k}"
            # some runs wrote only the base version (roster missing), as can happen in production
            _arch(
                tmp_path,
                gid,
                tip,
                as_of,
                m,
                versions=(BASE, ROSTER) if rng.random() < 0.8 else (BASE,),
            )
            r = rng.random()
            if r < 0.6:
                prov[m] = {"pushed_by": (as_of + timedelta(minutes=rng.randint(1, 60))).isoformat()}
            elif r < 0.8:
                prov[m] = {"pushed_by": (tip + timedelta(minutes=rng.randint(0, 30))).isoformat()}
    root = tmp_path
    f15, a15 = ce.load_verified(root, W15_VERSIONS, prov)
    f16, a16 = ce.load_verified(root, W16_VERSIONS, prov)
    assert f15[BASE] == f16[BASE] and a15["base_selection_digest"] == a16["base_selection_digest"]
    assert a15["quarantined"][BASE] == a16["quarantined"][BASE]
    assert a15["quarantined"][BASE] and a15["fallback"][BASE]  # the scenario exercises both paths
    # no selected post-boundary record lacks a verified push strictly before its tip
    recm = __import__("cbb_edge.research.wave14", fromlist=["x"]).record_manifests(root)
    for v, recs in f16.items():
        for gid, r in recs.items():
            stem = recm[(v, gid, r["as_of"].isoformat())]
            assert w.parse_ts(prov[stem]["pushed_by"]) < r["tip"]
    # and Wave 16's eligible games are a subset of Wave 15's (it also needs a verified roster record)
    finals = {g: {"available_at": r["tip"] + timedelta(hours=3)} for g, r in f15[BASE].items()}
    p15 = ce.pushed_by(f15, W15_VERSIONS, recm, prov)
    p16 = ce.pushed_by(f16, W16_VERSIONS, recm, prov)
    e15 = {
        g
        for g in f15[BASE]
        if ce.eligibility(g, f15, W15_VERSIONS, finals, p15, 50, 30) == "eligible"
    }
    e16 = {
        g
        for g in f16[BASE]
        if ce.eligibility(g, f16, W16_VERSIONS, finals, p16, 50, 30) == "eligible"
    }
    assert e16 <= e15 and e15


def test_amendment_is_registered_before_the_boundary_and_originals_are_untouched():
    am = json.loads((ROOT / "research/waves15_16/amendment_1.json").read_text())
    assert (
        am["must_precede"] == ce.PROSPECTIVE_FROM and am["registered_on"] < ce.PROSPECTIVE_FROM[:10]
    )
    assert am["outcome_blind"] is True and am["parameters_changed"] == []
    assert am["rule"] == ce.AMENDMENT_1 and (ROOT / am["document"]).exists()
    present = 0
    for rel, sha in am["original_protocol_sha256"].items():
        f = ROOT / rel
        if not f.exists():  # each wave's PR carries only its own protocol files
            continue
        present += 1
        assert hashlib.sha256(f.read_bytes()).hexdigest() == sha, (
            f"{rel} changed after registration"
        )
    if present == 0:
        pytest.fail("no registered protocol file found")
