"""Wave 13: hierarchical level challenger (as-of discipline, shrinkage) and orientation-safe loaders."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from cbb_edge.model import level_hier as lh
from cbb_edge.research import wave13 as w13

T0 = datetime(2026, 11, 2, 18, tzinfo=UTC)


def games(n, bias=0.04, seed=0, min_gs=lambda i: min(i // 60, 2)):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        g = {"game_id": i, "tip": T0 + timedelta(hours=i), "as_of": T0 + timedelta(hours=i - 3),
             "margin": rng.uniform(-15, 15), "total": rng.uniform(130, 160), "poss": rng.uniform(64, 76),
             "margin_sd": 12.0, "total_sd": 16.0, "home_games_seen": min_gs(i), "away_games_seen": min_gs(i) + 1}  # fmt: skip
        g["home_score"] = g["away_score"] = g["total"] / 2
        g["_t"] = g["total"] + bias * g["poss"] + rng.gauss(0, 16)
        out.append(g)
    return out


def finals(gs):
    return {g["game_id"]: {"home": round(g["_t"] / 2), "away": round(g["_t"] / 2),
                           "available_at": g["tip"] + timedelta(hours=3)} for g in gs}  # fmt: skip


def hist(gs, fin):
    return [{"poss": g["poss"], "total_err": fin[g["game_id"]]["home"] * 2 - g["total"],
             "group": lh.group_of(g["home_games_seen"])} for g in gs]  # fmt: skip


def test_group_of_collapses_late_games():
    assert [lh.group_of(x) for x in (None, 0, 1, 2, 3, 9)] == [0, 0, 1, 2, 2, 2]


def test_pooled_level_recovered_and_margin_and_sd_untouched():
    gs = games(500)
    fin = finals(gs)
    st = lh.fit(hist(gs, fin))
    assert st["lambda_per_poss_by_group"][2] * 70 == pytest.approx(0.04 * 70, abs=1.2)
    a = lh.adapt(gs[0], st, 0)
    assert (
        a["margin"] == gs[0]["margin"]
        and a["margin_sd"] == gs[0]["margin_sd"]
        and a["total_sd"] == gs[0]["total_sd"]
    )
    assert a["home_score"] + a["away_score"] == pytest.approx(a["total"])


def test_thin_group_is_strongly_shrunk_toward_the_pooled_level():
    gs = games(300, bias=0.04, min_gs=lambda i: min(i // 150, 1))  # groups 0 and 1 only
    h = hist(gs, finals(gs))
    for i in range(6):  # six games in group 2 with a wildly different level
        h.append({"poss": 70.0, "total_err": -0.20 * 70.0, "group": 2})
    hier = lh.fit(h)
    indep = lh.fit(h, lh.Params(hierarchical=False))
    raw = hier["raw_group_mean_per_poss"][2]
    assert raw == pytest.approx(-0.20, abs=1e-9)
    # the hierarchy leaves group 3 near the others; independent per-group fits chase the 6 games harder
    assert hier["lambda_per_poss_by_group"][2] > indep["lambda_per_poss_by_group"][2]
    assert abs(hier["group_deviation"][2]) < 0.2 * abs(raw - hier["pooled"])


def test_large_groups_are_allowed_to_differ_but_only_partially():
    gs = games(600, bias=0.0)
    fin = finals(gs)
    h = hist(gs, fin)
    for x in h:
        if x["group"] == 1:
            x["total_err"] += 0.05 * x["poss"]
    st = lh.fit(h)
    d = st["group_deviation"][1]
    assert 0 < d < 0.05  # moves toward the raw group gap, never all the way


def test_min_history_and_as_of_discipline():
    gs = games(150)
    fin = finals(gs)
    assert lh.fit(hist(gs[:29], fin)) is None
    base = lh.walk_forward(gs, fin)
    target = gs[120]
    fin2 = {k: dict(v) for k, v in fin.items()}
    for g in gs:
        if fin[g["game_id"]]["available_at"] > target["as_of"]:
            fin2[g["game_id"]]["home"] += 50  # results not yet visible must not matter
    assert lh.walk_forward(gs, fin2)[target["game_id"]] == base[target["game_id"]]
    assert base[gs[5]["game_id"]] is None


def test_no_market_or_sd_dependency_in_source():
    import ast
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "cbb_edge/model/level_hier.py"
    tree = ast.parse(p.read_text())
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    assert not [m for m in mods if m.startswith(("cbb_edge.market", "cbb_edge.kalshi"))]


def _sched(tmp_path, rows):
    d = tmp_path / "rows/2026/11/07"
    d.mkdir(parents=True)
    (d / "a.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def test_finals_are_mapped_to_the_projected_teams_and_unverifiable_games_are_excluded(tmp_path):
    base = {
        1: {"home_tid": "T0013", "away_tid": "T0112"},  # California proj-home, Houston proj-away
        2: {"home_tid": "T0013", "away_tid": "T0112"},
        3: {"home_tid": "T0013", "away_tid": "T0112"},
    }
    common = {"status_type_completed": True, "observed_at": "2026-11-07T21:00:00+00:00"}
    _sched(tmp_path, [
        {**common, "game_id": 1, "home_id": 248, "away_id": 25, "neutral_site": True, "home_score": 86, "away_score": 68},
        {**common, "game_id": 2, "home_id": 248, "away_id": 25, "neutral_site": False, "home_score": 86, "away_score": 68},
        {**common, "game_id": 3, "home_id": 25, "away_id": 99999999, "neutral_site": True, "home_score": 70, "away_score": 60},
    ])  # fmt: skip
    fin, audit = w13.load_finals_oriented(tmp_path, base)
    assert fin[1]["home"] == 68 and fin[1]["away"] == 86 and fin[1]["orientation"] == "SWAPPED"
    assert 2 not in fin and audit["excluded"][2] == "reversed_at_non_neutral_site"
    assert 3 not in fin and audit["excluded"][3] == "schedule_team_id_unresolved"
    assert audit["swapped"] == [1] and audit["status"] == {"SWAPPED": 1, "UNVERIFIED": 2}


def test_market_line_is_flipped_with_the_same_identity():
    base = {1: {"home_tid": "T0013", "away_tid": "T0112"}}
    m = {
        1: {
            "spread": -19.5,
            "total": 140.0,
            "home_espn_id": 248,
            "away_espn_id": 25,
            "neutral": True,
        }
    }
    out, cnt = w13.orient_market(m, base)
    assert out[1]["spread"] == 19.5 and cnt == {"SWAPPED": 1}  # Houston -19.5 == California +19.5
    bad, cnt = w13.orient_market({1: {**m[1], "neutral": False}}, base)
    assert bad == {} and cnt == {"UNVERIFIED": 1}
