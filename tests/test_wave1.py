"""Wave 1: exact error decomposition, walk-forward (time-respecting) challenger, scoring guards."""

from __future__ import annotations

import ast
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cbb_edge.model import level_adapt as la
from cbb_edge.research import wave1 as w
from cbb_edge.research import wave1_market as wm

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 2, 18, tzinfo=UTC)


def proj(i, *, margin=5.0, total=140.0, poss=70.0, as_of=None):
    return {
        "game_id": i, "tip": T0 + timedelta(hours=i), "as_of": as_of or T0 + timedelta(hours=i - 3),
        "margin": margin, "total": total, "margin_sd": 12.0, "total_sd": 16.0, "poss": poss,
        "home_score": (total + margin) / 2, "away_score": (total - margin) / 2,
        "home_ppp": (total + margin) / 2 / poss, "away_ppp": (total - margin) / 2 / poss,
    }  # fmt: skip


def test_decomposition_is_exact():
    p = proj(1)
    act = {"poss": 73.0, "home_pts": 80.0, "away_pts": 71.0}
    d = w.decompose(p, act)
    assert d["total_pace_term"] + d["total_eff_term"] == pytest.approx(151.0 - 140.0)
    assert d["total_err_check"] == pytest.approx(11.0)
    home_err, away_err = 80.0 - p["home_score"], 71.0 - p["away_score"]
    assert d["margin_pace_term"] + d["margin_eff_term"] == pytest.approx(home_err - away_err)


def _hist(n, bias=3.0, seed=0):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        g = proj(
            i, margin=rng.uniform(-15, 15), total=rng.uniform(130, 160), poss=rng.uniform(64, 76)
        )
        g["_actual_total"] = g["total"] + bias * g["poss"] / 70 + rng.gauss(0, 16)
        g["_actual_margin"] = g["margin"] + rng.gauss(0, 12)
        out.append(g)
    return out


def _finals(games, lag_hours=3):
    fin = {}
    for g in games:
        t, m = g["_actual_total"], g["_actual_margin"]
        fin[g["game_id"]] = {
            "home": round((t + m) / 2), "away": round((t - m) / 2),
            "available_at": g["tip"] + timedelta(hours=lag_hours),
        }  # fmt: skip
    return fin


def test_fit_needs_min_games_and_recovers_level():
    g = _hist(600)
    fin = _finals(g)
    hist = [
        {**x, "margin_err": (fin[x["game_id"]]["home"] - fin[x["game_id"]]["away"]) - x["margin"],
         "total_err": (fin[x["game_id"]]["home"] + fin[x["game_id"]]["away"]) - x["total"]}
        for x in g
    ]  # fmt: skip
    assert la.fit(hist[:29]) is None
    st = la.fit(hist)
    assert st["lambda_per_poss"] * 70 == pytest.approx(3.0, abs=0.9)
    a = la.adapt(g[0], st)
    assert a["margin"] == g[0]["margin"]  # margin mean untouched
    assert a["total"] - g[0]["total"] == pytest.approx(st["lambda_per_poss"] * g[0]["poss"])
    assert a["home_score"] + a["away_score"] == pytest.approx(a["total"])


def test_shrinkage_pulls_small_samples_toward_zero():
    g = _hist(40, bias=6.0)
    fin = _finals(g)
    hist = [
        {
            **x,
            "margin_err": 0.0,
            "total_err": (fin[x["game_id"]]["home"] + fin[x["game_id"]]["away"]) - x["total"],
        }
        for x in g
    ]
    weak = la.fit(hist, la.Params(k_level=400))
    strong = la.fit(hist, la.Params(k_level=1))
    assert abs(weak["lambda_per_poss"]) < abs(strong["lambda_per_poss"])


def test_walk_forward_uses_only_finals_available_before_as_of():
    games = _hist(120)
    fin = _finals(games)
    base = la.walk_forward(games, fin)
    target = games[100]
    # tamper with every final that was NOT yet available at the target's as_of: nothing may change
    fin2 = {k: dict(v) for k, v in fin.items()}
    for g in games:
        if fin[g["game_id"]]["available_at"] > target["as_of"]:
            fin2[g["game_id"]]["home"] += 40
    again = la.walk_forward(games, fin2)
    assert again[target["game_id"]] == base[target["game_id"]]
    # and a game's own result can never inform its own projection
    own = fin[target["game_id"]]["available_at"]
    assert own > target["as_of"]
    # early games lack history: explicit gap, not a silent default
    assert base[games[5]["game_id"]] is None


def test_walk_forward_state_changes_when_an_earlier_final_changes():
    games = _hist(120)
    fin = _finals(games)
    a = la.walk_forward(games, fin)[games[100]["game_id"]]
    fin[games[10]["game_id"]]["home"] += 60
    b = la.walk_forward(games, fin)[games[100]["game_id"]]
    assert a != b  # earlier finished games do matter (the rule is not constant)


def test_level_adapt_has_no_market_dependency():
    tree = ast.parse((REPO / "cbb_edge/model/level_adapt.py").read_text())
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.append(n.module)
    assert not [x for x in names if x.startswith(("cbb_edge.market", "cbb_edge.kalshi"))]
    src = (REPO / "cbb_edge/model/level_adapt.py").read_text().lower()
    for word in ("spread", "moneyline", "yes_ask", "odds"):
        assert word not in src.replace("kalshi", "")


def test_challenger_is_registered_but_not_promoted():
    active = json.loads((REPO / "models/pure/active.json").read_text())
    assert active["incumbent"] == "pure-0.2.0"
    assert la.VERSION not in json.dumps(active)
    reg = json.loads((REPO / "models/challengers/wf-level-0.5.0-v1.json").read_text())
    assert reg["status"] == "SHADOW_RESEARCH_ONLY" and reg["market_inputs"] == "none"
    assert reg["params"] == {**la.Params().__dict__, "margin_bins": list(la.Params().margin_bins)}


def _write(root: Path, rel: str, as_of: str, tip: str, margin=3.0):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "game": {"espn_game_id": 9, "start_time_utc": tip, "site": "home"},
        "home": {"name": "A State"}, "away": {"name": "B Tech"},
        "prospective": {"as_of": as_of, "model_sha256": "x"},
        "projection": {"margin": margin, "total": 140, "margin_sd": 12, "total_sd": 16,
                       "home_score": 71.5, "away_score": 68.5, "possessions": 70,
                       "home_ppp": 1.02, "away_ppp": 0.98, "home_win_prob": 0.6},
        "freshness": {"home_games_seen": 0, "away_games_seen": 1},
    }))  # fmt: skip


def test_load_frozen_picks_latest_pregame_record_and_ignores_post_tip(tmp_path):
    d = tmp_path / "projections/2027/2026-11-03/G9"
    tip = "2026-11-03T00:00:00+00:00"
    _write(
        d.parent.parent.parent.parent,
        "projections/2027/2026-11-03/G9/a.json",
        "2026-11-02T10:00:00+00:00",
        tip,
        1.0,
    )
    _write(
        d.parent.parent.parent.parent,
        "projections/2027/2026-11-03/G9/b.json",
        "2026-11-02T20:00:00+00:00",
        tip,
        2.0,
    )
    _write(
        d.parent.parent.parent.parent,
        "projections/2027/2026-11-03/G9/c.json",
        "2026-11-03T00:05:00+00:00",
        tip,
        9.0,
    )
    got = w.load_frozen(tmp_path, "pure-0.2.0")
    assert got[9]["margin"] == 2.0  # the post-tip record (9.0) is never a pregame projection


def test_orientation_swap_is_detected_and_aliases_are_not():
    p = {"home_name": "California Golden Bears", "away_name": "Houston Cougars"}
    assert w.orientation_swapped(p, {"home_loc": "Houston", "away_loc": "California"})
    assert not w.orientation_swapped(p, {"home_loc": "California", "away_loc": "Houston"})
    assert not w.orientation_swapped(
        p, {"home_loc": "Cal", "away_loc": "UH"}
    )  # alias noise: not a swap
    assert not w.orientation_swapped(p, {})


def test_load_finals_takes_last_score_but_first_availability(tmp_path):
    r = tmp_path / "rows/2026/11/07"
    r.mkdir(parents=True)
    base = {"game_id": 5, "status_type_completed": True, "home_location": "A", "away_location": "B"}
    lines = [
        {**base, "home_score": 83, "away_score": 82, "observed_at": "2026-11-07T21:26:00+00:00"},
        {**base, "home_score": 83, "away_score": 81, "observed_at": "2026-11-08T10:42:00+00:00"},
    ]
    (r / "x.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    f = w.load_finals(tmp_path)[5]
    assert (f["home"], f["away"]) == (83, 81)
    assert f["available_at"] == datetime(2026, 11, 7, 21, 26, tzinfo=UTC)


def test_paired_bootstrap_sign_and_interval():
    a = [1.0] * 50
    b = [2.0] * 50
    r = w.paired_bootstrap(a, b, reps=200)
    assert r["diff"] == -1.0 and r["hi"] < 0


def test_settlement_semantics():
    win = {"status": "parsed", "period": "FULL", "market_type": "WINNER", "subject_side": "away"}
    assert wm.settle(win, 70, 75) == 1 and wm.settle(win, 75, 70) == 0
    mar = {
        "status": "parsed",
        "period": "FULL",
        "market_type": "MARGIN",
        "subject_side": "home",
        "strike": 5.5,
    }
    assert wm.settle(mar, 80, 74) == 1 and wm.settle(mar, 79, 74) == 0
    tot = {"status": "parsed", "period": "FULL", "market_type": "TOTAL", "strike": 150.5}
    assert wm.settle(tot, 80, 71) == 1 and wm.settle(tot, 80, 70) == 0
    assert (
        wm.settle({**tot, "period": "1H"}, 80, 71) is None
    )  # halves are never settled from a final
    assert wm.settle({"status": "unparsed"}, 80, 71) is None


def test_contract_probabilities_use_the_adapted_distribution_and_keep_unmodelled_markets():
    rec = {"game_id": 1, "proj": {"base": {"margin": 4.0, "margin_sd": 12.0, "total": 140.0, "total_sd": 16.0}},
           "adapted": {"wf": {"margin": 4.0, "margin_sd": 12.0, "total": 143.0, "total_sd": 16.0}}}  # fmt: skip
    sem = {
        "status": "parsed",
        "period": "FULL",
        "market_type": "TOTAL",
        "strike": 141.5,
        "direction": "greater",
    }
    p_base = wm.contract_probability(sem, rec["proj"]["base"], wm.IDENTITY)
    p_wf = wm.contract_probability(sem, rec["adapted"]["wf"], wm.IDENTITY)
    assert p_wf > p_base  # a higher level raises P(over) on every rung of the ladder
    half = {**sem, "period": "1H"}
    assert (
        wm.contract_probability(half, rec["adapted"]["wf"], wm.IDENTITY) is None
    )  # kept, not modelled


def test_ev_keeps_quote_fee_and_side_separate():
    rec = {"yes_exec_price": 0.40, "no_exec_price": 0.62}
    ev = wm._ev_net(0.50, rec)
    assert ev["side"] == "yes" and ev["price"] == 0.40
    assert (
        ev["ev_net"] < 0.50 - 0.40
    )  # the fee is deducted exactly once, never added to the price twice
    assert ev["fee"] > 0
