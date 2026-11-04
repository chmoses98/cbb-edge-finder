"""Minutes-first player baseline: real identity and as-of protection, no invented prop prices."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from cbb_edge.players.prop_projection import player_stat_means


ASOF = datetime(2026, 11, 4, 18, tzinfo=UTC)
TIP = ASOF + timedelta(hours=3)


def rotation():
    return pd.DataFrame(
        {
            "player_id": [f"P{i}" for i in range(5)],
            "team_id": ["T1"] * 5,
            "minutes": [40.0] * 5,
            "p_rotation": [0.96] * 5,
        }
    )


def boxes():
    rows = []
    for i in range(5):
        for game in range(4):
            rows.append(
                {
                    "player_id": f"P{i}",
                    "game_id": 100 + game,
                    "available_at": ASOF - timedelta(days=game + 1),
                    "min": "35:00",
                    "pts": 14.0,
                    "orb": 1.0,
                    "drb": 4.0,
                    "ast": 3.5,
                    "fg3m": 2.0,
                }
            )
    return pd.DataFrame(rows)


def project(history=None, rot=None, **kw):
    return player_stat_means(
        boxes() if history is None else history,
        rotation() if rot is None else rot,
        as_of=ASOF,
        tip=TIP,
        rotation_as_of=ASOF - timedelta(minutes=5),
        **kw,
    )


def test_forecasts_real_stat_means_but_no_more_less_probability():
    out = project()
    p = out[0]
    assert len(out) == 5
    assert p["projected_minutes"] == 40.0
    assert p["projections"]["pts"] == pytest.approx(16.0)
    assert p["projections"]["reb"] == pytest.approx(40 * 5 / 35)
    assert p["projections"]["ast"] == pytest.approx(4.0)
    assert p["projections"]["fg3m"] == pytest.approx(40 * 2 / 35, abs=0.001)
    assert p["projections"]["pra"] == pytest.approx(16 + 40 * 5 / 35 + 4, abs=0.002)
    assert p["line_probability"] is None and p["authorized_bet"] is False


def test_future_result_cannot_improve_projection_or_history_sample():
    old = project()
    h = boxes()
    future = h.iloc[[0]].copy()
    future["game_id"] = 999
    future["available_at"] = ASOF + timedelta(hours=3)
    future["pts"] = 1000.0
    new = project(pd.concat([h, future], ignore_index=True))
    assert old == new


def test_freshman_without_history_reports_missing_not_zero_stat():
    h = boxes()
    h = h[h["player_id"] != "P0"]
    result = project(h)[0]
    assert result["projected_minutes"] == 40.0
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["projections"]["pts"] is None
    assert result["projections"]["pra"] is None


def test_rotation_and_asof_guards():
    bad = rotation()
    bad.loc[0, "minutes"] = 50
    with pytest.raises(ValueError, match="outside"):
        project(rot=bad)
    bad = rotation()
    bad.loc[0, "player_id"] = "P1"
    with pytest.raises(ValueError, match="duplicate"):
        project(rot=bad)
    with pytest.raises(ValueError, match="rotation must be known"):
        player_stat_means(boxes(), rotation(), as_of=ASOF, tip=TIP, rotation_as_of=TIP)


def test_corrupt_box_history_fails_closed():
    h = boxes()
    h.loc[0, "available_at"] = None
    with pytest.raises(ValueError, match="availability"):
        project(history=h)
    h = boxes()
    h.loc[0, "game_id"] = h.loc[1, "game_id"]
    with pytest.raises(ValueError, match="duplicate"):
        project(history=h)
