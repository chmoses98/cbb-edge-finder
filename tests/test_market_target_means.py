"""Research targets distinguish team scoring means from line hit probabilities."""

import pytest

from cbb_edge.kalshi.research.target_means import projected_target_mean


def test_team_total_uses_actual_archived_home_and_away_means():
    p = {"home_score": 80.25, "away_score": 67.75, "total": 148.0, "margin": 12.5}
    h = projected_target_mean({"status": "parsed", "market_type": "TEAM_TOTAL",
                               "period": "FULL", "subject_side": "home"}, p)
    a = projected_target_mean({"status": "parsed", "market_type": "TEAM_TOTAL",
                               "period": "FULL", "subject_side": "away"}, p)
    assert h["value"] == pytest.approx(80.25)
    assert a["value"] == pytest.approx(67.75)
    assert h["status"] == "MEAN_ONLY"
    assert not h["probability_available"] and not a["probability_available"]
    assert h["reason"] == "team_score_distribution_not_calibrated"


@pytest.mark.parametrize("sem,reason", [
    ({"status": "parsed", "market_type": "TEAM_TOTAL", "period": "1H",
      "subject_side": "home"}, "no_period_scoring_mean_in_frozen_model"),
    ({"status": "parsed", "market_type": "TOTAL", "period": "FULL"},
     "not_team_total_market"),
    ({"status": "subject_unresolved", "market_type": "TEAM_TOTAL", "period": "FULL"},
     "contract_parse_subject_unresolved"),
])
def test_does_not_invent_other_market_means(sem, reason):
    q = projected_target_mean(sem, {"home_score": 80, "away_score": 68, "total": 148})
    assert q["value"] is None and q["reason"] == reason


def test_missing_future_and_inconsistent_projection_fail_closed():
    s = {"status": "parsed", "market_type": "TEAM_TOTAL",
         "period": "FULL", "subject_side": "home"}
    assert projected_target_mean(s, None)["reason"] == "no_pretip_frozen_projection_for_this_game"
    assert projected_target_mean(s, {"total": 150, "margin": 10})["value"] is None
    assert projected_target_mean(s, {"home_score": 80, "away_score": 65, "total": 150})[
        "reason"
    ] == "inconsistent_frozen_team_scores"
    assert projected_target_mean(s, {"home_score": float("nan")})["value"] is None
    assert projected_target_mean(s, {"home_score": True})["value"] is None
