"""Prospective archive immutability + downstream Kalshi comparison."""

from __future__ import annotations

import copy

import pytest

from cbb_edge.app import sift
from cbb_edge.app.prospective import ArchiveOverwriteError, write_archive
from cbb_edge.market.compare import disagreement, model_probability


def _rec(margin=3.3):
    r = sift.SiftProjection(
        game=sift.GameRef("G1", 1, 2027, "2026-11-04T00:00:00+00:00", "home"),
        home=sift.TeamRef("T0001", 2, "Auburn Tigers"),
        away=sift.TeamRef("T0002", 333, "Alabama Crimson Tide"),
        projection=sift.Projection(70.0, 1.13, 1.09, 79.4, 76.1, margin, 155.5, 0.618, 11.0, 17.0),
        model=sift.ModelRef("m", "0.2.0", "PURE"),
        freshness=sift.Freshness("2026-11-03T00:00:00+00:00", 0, 0, 0),
    ).to_dict()
    r["prospective"] = {"as_of": "2026-11-03T14:10:00+00:00"}
    return r


def test_archive_is_append_only(tmp_path):
    r = _rec()
    assert write_archive([r], tmp_path)["written"] == 1
    assert write_archive([r], tmp_path)["written"] == 0  # identical rerun: no-op
    changed = copy.deepcopy(r)
    changed["projection"]["margin"] = 9.9
    with pytest.raises(ArchiveOverwriteError):
        write_archive([changed], tmp_path)
    later = copy.deepcopy(changed)
    later["prospective"]["as_of"] = "2026-11-03T21:10:00+00:00"
    assert write_archive([later], tmp_path)["written"] == 1  # new run -> new file


def test_model_probability_mapping():
    r = _rec(margin=0.0)
    assert abs(model_probability(r, "GAME_WINNER", {}, True) - 0.5) < 1e-9
    assert model_probability(r, "SPREAD", {"floor_strike": 0.0}, True) == pytest.approx(0.5)
    assert model_probability(r, "TOTAL", {"floor_strike": 155.5}, None) == pytest.approx(0.5)
    assert model_probability(r, "GAME_WINNER", {}, None) is None  # unmapped -> no guess


def test_disagreement_does_not_touch_projection():
    r = _rec()
    before = copy.deepcopy(r)
    d = disagreement(r, "GAME_WINNER", {"ticker": "X", "yes_bid": 40, "yes_ask": 44}, True)
    assert d is not None and d["market_prob"] == pytest.approx(0.42)
    assert r == before


def test_challenger_records_are_archived_separately(tmp_path):
    inc = _rec()
    ch = copy.deepcopy(inc)
    ch["model"]["version"] = "pure-0.3.0"
    ch["projection"]["margin"] = 5.0
    assert write_archive([inc], tmp_path)["written"] == 1
    assert write_archive([ch], tmp_path)["written"] == 1  # same game/time, no collision
    files = sorted(p.relative_to(tmp_path).parts[0] for p in tmp_path.rglob("*.json"))
    assert files == ["2027", "pure-0.3.0"]  # incumbent keeps the legacy layout


def test_default_model_is_incumbent_not_latest_file():
    from cbb_edge.app.prospective import active_models, load_model

    assert load_model()["version"] == active_models()["incumbent"]
