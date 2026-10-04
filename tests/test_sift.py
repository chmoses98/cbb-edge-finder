"""Sift schema contract + probability bounds."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from cbb_edge.app import sift
from cbb_edge.model.arms import win_prob


def _rec():
    return sift.SiftProjection(
        game=sift.GameRef("G1", 1, 2027, "2026-11-04T00:00:00+00:00", "home"),
        home=sift.TeamRef("T0001", 2, "Auburn Tigers"),
        away=sift.TeamRef("T0002", 333, "Alabama Crimson Tide"),
        projection=sift.Projection(70.0, 1.13, 1.09, 79.4, 76.1, 3.3, 155.5, 0.618, 11.0, 17.0),
        model=sift.ModelRef("m", "0.1.0", "B2"),
        freshness=sift.Freshness("2026-11-03T00:00:00+00:00", 0, 0, 0),
    ).to_dict()


def test_valid_record_passes():
    sift.validate(_rec())


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.2, float("nan")])
def test_probability_bounds_enforced(p):
    r = _rec()
    r["projection"]["home_win_prob"] = p
    with pytest.raises(sift.SchemaError):
        sift.validate(r)


def test_score_consistency_enforced():
    r = copy.deepcopy(_rec())
    r["projection"]["margin"] = 10.0
    with pytest.raises(sift.SchemaError):
        sift.validate(r)


def test_json_schema_shape():
    js = sift.json_schema()
    assert "projection" in js["required"]
    assert js["properties"]["game"]["properties"]["site"]["enum"] == ["home", "neutral"]


def test_win_prob_strictly_inside_unit_interval():
    rng = np.random.default_rng(0)
    n = 3000
    df = pd.DataFrame({"season": np.repeat([2018, 2019], n // 2)})
    margin = pd.Series(rng.normal(0, 60, n))  # extreme margins
    df["home_win"] = (margin + rng.normal(0, 11, n) > 0).astype(float)
    p = win_prob(df, margin)
    assert p.notna().all() and (p > 0).all() and (p < 1).all()
