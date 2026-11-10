"""Canonical orientation identity: the four Wave 12 neutral-site games, fail-closed behaviour."""

from __future__ import annotations

import pytest

from cbb_edge.data.ids.orientation import (
    Orientation,
    check_orientation,
    check_record,
    to_projection_frame,
)

# (espn game, projection home T-id, projection away T-id, schedule home ESPN id, schedule away ESPN id,
#  schedule home score, schedule away score, projected margin of the PROJECTED home team)
# Values are copied from the frozen projections-archive and schedule-archive records of Wave 12.
WAVE12_SWAPPED = [
    (401921704, "T0270", "T0213", 2250, 2509, 78, 72, 7.57),  # Purdue (proj home) vs Gonzaga
    (401909694, "T0028", "T0027", 50, 52, 69, 112, 23.38),  # Florida State vs Florida A&M
    (401918053, "T0013", "T0112", 248, 25, 86, 68, -17.10),  # California vs Houston
    (401919029, "T0322", "T0016", 30, 2724, 93, 86, -1.04),  # Wichita State vs USC
]


@pytest.mark.parametrize("gid,ph,pa,sh,sa,hs,as_,pm", WAVE12_SWAPPED)
def test_wave12_neutral_site_games_are_swapped_and_remapped(gid, ph, pa, sh, sa, hs, as_, pm):
    c = check_orientation(ph, pa, sh, sa, neutral=True, season=2027)
    assert c.status is Orientation.SWAPPED and c.scorable, gid
    proj_home_score, proj_away_score = to_projection_frame(c, hs, as_)
    assert (proj_home_score, proj_away_score) == (as_, hs)  # results follow the projected teams
    # the naive positional margin has the wrong sign; the mapped one is the real error
    naive_err = (hs - as_) - pm
    mapped_err = (proj_home_score - proj_away_score) - pm
    assert abs(naive_err) != pytest.approx(abs(mapped_err))
    # the same schedule row without the neutral flag must not be "fixed": fail closed
    bad = check_orientation(ph, pa, sh, sa, neutral=False, season=2027)
    assert bad.status is Orientation.UNVERIFIED and bad.reason == "reversed_at_non_neutral_site"
    with pytest.raises(ValueError):
        to_projection_frame(bad, hs, as_)


def test_california_houston_regression_numbers():
    # Houston (schedule home) beat California 86-68; the projection had California at home by -17.1,
    # i.e. it already favoured Houston by 17.1. Positional scoring invented a +35.1 "miss".
    c = check_orientation("T0013", "T0112", 248, 25, neutral=True, season=2027)
    h, a = to_projection_frame(c, 86, 68)
    assert (h - a) - (-17.10) == pytest.approx(-0.9, abs=0.01)  # California margin -18 vs -17.1


def test_same_orientation_is_unchanged():
    c = check_orientation("T0013", "T0112", 25, 248, neutral=True, season=2027)
    assert c.status is Orientation.SAME
    assert to_projection_frame(c, 70, 60) == (70, 60)


@pytest.mark.parametrize(
    "ph,pa,sh,sa,reason",
    [
        (None, "T0112", 25, 248, "projection_team_ids_missing_or_equal"),
        ("T0013", "T0013", 25, 248, "projection_team_ids_missing_or_equal"),
        ("T0013", "T0112", None, 248, "schedule_team_ids_missing"),
        ("T0013", "T0112", 25, 99999999, "schedule_team_id_unresolved"),
        ("T0013", "T0112", 25, 25, "schedule_teams_identical"),
        ("T0013", "T0112", 25, 2250, "team_set_mismatch"),  # a different opponent: not a swap
        ("T0013", "T0112", "abc", 248, "schedule_team_id_unparseable"),
    ],
)
def test_unverifiable_identity_fails_closed(ph, pa, sh, sa, reason):
    c = check_orientation(ph, pa, sh, sa, neutral=True, season=2027)
    assert c.status is Orientation.UNVERIFIED and not c.scorable
    assert c.reason == reason
    with pytest.raises(ValueError):
        to_projection_frame(c, 1, 2)


def test_check_record_reads_record_and_schedule_row():
    rec = {"home": {"team_id": "T0013"}, "away": {"team_id": "T0112"}}
    row = {"home_id": 248, "away_id": 25, "neutral_site": True}
    assert check_record(rec, row, season=2027).status is Orientation.SWAPPED
    assert check_record(rec, {**row, "neutral_site": False}, season=2027).scorable is False
