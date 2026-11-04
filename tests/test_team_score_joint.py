"""Score-distribution challenger uses independent past games and honest shadow authority."""

from datetime import UTC, datetime, timedelta

import pytest

from cbb_edge.model.team_score_joint import fit_joint_scores, shadow_probability

CUTOFF = datetime(2026, 11, 4, 12, tzinfo=UTC)
TIP = CUTOFF + timedelta(hours=5)
MODEL = "pure-0.2.0"


def make_records(n=130):
    records = []
    for i in range(n):
        pred_h, pred_a = 73.0, 69.0
        dh = (i % 13) - 6
        da = (i % 17) - 8
        records.append(
            {
                "game_id": i,
                "verified": True,
                "model_version": MODEL,
                "prediction_as_of": CUTOFF - timedelta(days=i + 3, hours=5),
                "tip": CUTOFF - timedelta(days=i + 3),
                "outcome_available_at": CUTOFF - timedelta(days=i + 3) + timedelta(hours=3),
                "predicted_home": pred_h,
                "predicted_away": pred_a,
                "actual_home": pred_h + dh,
                "actual_away": pred_a + da,
            }
        )
    return records


def test_joint_score_fit_and_shadow_probabilities():
    fit = fit_joint_scores(make_records(), as_of=CUTOFF, frozen_model_version=MODEL)
    assert fit is not None and fit.games == 130
    assert fit.sd_home > 1 and fit.sd_away > 1
    home = shadow_probability(
        fit, {"home_score": 78, "away_score": 65},
        target="home_total", line=77.5, prediction_as_of=CUTOFF, tip=TIP
    )
    away = shadow_probability(
        fit, {"home_score": 78, "away_score": 65},
        target="away_total", line=69.5, prediction_as_of=CUTOFF, tip=TIP
    )
    assert home["model_probability"] > 0.5
    assert away["model_probability"] < 0.5
    assert home["status"] == "SHADOW_UNVALIDATED"
    assert home["authorized_bet"] is False
    assert home["independent_training_games"] == 130
    total = shadow_probability(
        fit, {"home_score": 78, "away_score": 65},
        target="game_total", line=142.5, prediction_as_of=CUTOFF, tip=TIP
    )
    assert total["mean"] == 143 and total["sd"] > 0


def test_duplicate_contracts_and_future_outcomes_do_not_inflate_sample():
    rows = make_records()
    fit = fit_joint_scores(rows, as_of=CUTOFF, frozen_model_version=MODEL)
    assert fit is not None
    assert fit_joint_scores([*rows, *rows], as_of=CUTOFF, frozen_model_version=MODEL) == fit
    future = {**rows[0], "game_id": 5000, "outcome_available_at": CUTOFF + timedelta(days=1)}
    x = fit_joint_scores([*rows, future], as_of=CUTOFF, frozen_model_version=MODEL)
    assert x == fit


def test_invalid_or_post_tip_projection_is_excluded():
    rows = make_records()
    late = {**rows[0], "game_id": 2000, "prediction_as_of": rows[0]["tip"]}
    fit = fit_joint_scores([*rows, late], as_of=CUTOFF, frozen_model_version=MODEL)
    assert fit is not None and fit.games == 130
    assert fit_joint_scores(rows[:40], as_of=CUTOFF, frozen_model_version=MODEL) is None


def test_guard_against_reusing_future_calibration():
    fit = fit_joint_scores(make_records(), as_of=CUTOFF, frozen_model_version=MODEL)
    assert fit is not None
    with pytest.raises(ValueError, match="chronology"):
        shadow_probability(
            fit, {"home_score": 78, "away_score": 65},
            target="home_total", line=77.5,
            prediction_as_of=CUTOFF - timedelta(days=1), tip=TIP,
        )
    with pytest.raises(ValueError, match="after tip"):
        shadow_probability(
            fit, {"home_score": 78, "away_score": 65},
            target="home_total", line=77.5,
            prediction_as_of=TIP, tip=TIP,
        )


def test_missing_means_do_not_imply_a_bet():
    fit = fit_joint_scores(make_records(), as_of=CUTOFF, frozen_model_version=MODEL)
    assert fit is not None
    result = shadow_probability(
        fit, {"away_score": 65},
        target="home_total", line=77.5, prediction_as_of=CUTOFF, tip=TIP,
    )
    assert result["model_probability"] is None and result["authorized_bet"] is False
