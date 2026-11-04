"""Only independently verified past half scores contribute to prospective means."""

from datetime import UTC, datetime, timedelta

import pytest

from cbb_edge.model.period_forecast import fit_half_share, forecast_half_means

ASOF = datetime(2026, 11, 4, 18, tzinfo=UTC)
TIP = ASOF + timedelta(hours=3)


def history(n=80):
    return [
        {
            "espn_game_id": i,
            "verified": True,
            "flags": [],
            "observed_at": ASOF - timedelta(days=i + 1),
            "home_periods": [32, 48],
            "away_periods": [27, 43],
            "final_home": 80,
            "final_away": 70,
        }
        for i in range(n)
    ]


def test_prior_only_training_and_replay_mean():
    fit = fit_half_share(history(), as_of=ASOF)
    assert fit is not None
    assert fit.games == 80
    assert fit.home_share == pytest.approx(0.4)
    assert fit.away_share == pytest.approx(27 / 70)
    result = forecast_half_means(
        {"home_score": 82, "away_score": 71},
        fit,
        forecast_as_of=ASOF,
        tip=TIP,
    )
    assert result["home_points_mean"] == pytest.approx(32.8)
    assert result["away_points_mean"] == pytest.approx(71 * 27 / 70, abs=0.01)
    assert result["total_mean"] == pytest.approx(
        result["home_points_mean"] + result["away_points_mean"], abs=0.02
    )
    assert result["status"] == "EXPLORATORY_MEANS_ONLY"
    assert result["line_probability"] is None and result["authorized_bet"] is False


def test_future_results_and_duplicate_replays_do_not_change_fit():
    h = history()
    fit = fit_half_share(h, as_of=ASOF)
    future = {
        **h[0],
        "espn_game_id": 999,
        "observed_at": ASOF + timedelta(minutes=1),
        "home_periods": [60, 20],
    }
    assert fit_half_share([*h, future, h[0]], as_of=ASOF) == fit


def test_conflicting_official_score_revisions_are_not_double_counted():
    h = history()
    conflicting = {**h[0], "home_periods": [30, 50]}
    x = fit_half_share([*h, conflicting], as_of=ASOF)
    assert x is not None and x.games == 79


def test_insufficient_verified_history_does_not_guess_fifty_percent():
    assert fit_half_share(history(30), as_of=ASOF) is None
    assert forecast_half_means({}, None, forecast_as_of=ASOF, tip=TIP)["total_mean"] is None


def test_asof_and_full_team_score_guards():
    fit = fit_half_share(history(), as_of=ASOF)
    with pytest.raises(ValueError, match="future information"):
        forecast_half_means(
            {"home_score": 80, "away_score": 70},
            fit,
            forecast_as_of=ASOF - timedelta(days=1),
            tip=TIP,
        )
    with pytest.raises(ValueError, match="after tip"):
        forecast_half_means({"home_score": 80}, fit, forecast_as_of=TIP, tip=TIP)
    out = forecast_half_means({"home_score": 80}, fit, forecast_as_of=ASOF, tip=TIP)
    assert out["status"] == "UNAVAILABLE" and out["line_probability"] is None
