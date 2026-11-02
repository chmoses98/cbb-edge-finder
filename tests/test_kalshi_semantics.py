"""Settlement semantics, scope and probability gating for Kalshi CBB contracts."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from cbb_edge.data.ids import teams
from cbb_edge.kalshi import mapping
from cbb_edge.kalshi import semantics as S

DUKE = teams.resolve("Duke", "espn")
UNC = teams.resolve("North Carolina", "espn")
RULES = (
    "If Duke wins by more than 12.5 points in the Duke vs North Carolina men's college "
    "basketball game originally scheduled for Nov 4, 2026, then the market resolves to Yes."
)


def spread(sub="Duke wins by over 12.5 points", floor=12.5, stype="greater"):
    return {
        "title": sub,
        "yes_sub_title": sub,
        "floor_strike": floor,
        "strike_type": stype,
        "rules_primary": RULES,
    }


def test_rules_matchup_reads_both_teams_without_order():
    assert S.rules_matchup(spread()) == ("Duke", "North Carolina")
    assert S.rules_matchup({"rules_primary": "season wins"}) is None


def test_spread_parse_and_settle_semantics():
    p = S.parse_contract("KXNCAAMBSPREAD", spread(), UNC, DUKE)  # Duke is away
    assert p["status"] == "parsed" and p["subject_side"] == "away" and p["strike"] == 12.5
    assert S.settle(p, 60, 75) == ("yes", "final_score")  # Duke +15
    assert S.settle(p, 60, 72)[0] == "no"  # Duke +12 does not exceed 12.5
    assert S.settle(p, None, 70) == (None, "no_final_score")


def test_strike_text_must_match_structured_strike_and_type():
    assert S.parse_contract("KXNCAAMBSPREAD", spread(floor=11.5), UNC, DUKE)["status"] == (
        "strike_mismatch"
    )
    assert S.parse_contract("KXNCAAMBSPREAD", spread(stype="less"), UNC, DUKE)["status"] == (
        "unsupported_strike_type"
    )


def test_subject_must_be_in_mapped_game():
    other = teams.resolve("Kansas", "espn")
    p = S.parse_contract("KXNCAAMBSPREAD", spread(), other, UNC)
    assert p["status"] == "subject_not_in_mapped_game"


def test_total_winner_team_total_and_halves_semantics():
    tot = {"title": "Full Game: Over 121.5 points scored", "floor_strike": 121.5,
           "yes_sub_title": "Over 121.5 points", "strike_type": "greater"}  # fmt: skip
    p = S.parse_contract("KXNCAAMBTOTAL", tot, UNC, DUKE)
    assert S.settle(p, 60, 62) == ("yes", "final_score")  # 122
    assert S.settle(p, 60, 61)[0] == "no"  # 121
    win = {"title": "Duke wins", "yes_sub_title": "Duke"}
    w = S.parse_contract("KXNCAAMBGAME", win, UNC, DUKE)
    assert S.settle(w, 70, 71)[0] == "yes" and S.settle(w, 71, 70)[0] == "no"
    assert S.settle(w, 70, 70)[0] is None  # tie impossible; never guessed
    tt = {"title": "Duke over 50.5 points scored", "yes_sub_title": "Duke over 50.5 points",
          "floor_strike": 50.5, "strike_type": "greater"}  # fmt: skip
    t = S.parse_contract("KXNCAAMBTEAMTOTAL", tt, UNC, DUKE)
    assert S.settle(t, 40, 51)[0] == "yes"
    half = S.parse_contract("KXNCAAMB1H", win, UNC, DUKE)
    assert S.settle(half, 30, 31) == (None, "needs_half_scores")
    assert half["overtime"] == "n/a" and S.SERIES["KXNCAAMB2H"].overtime == "included"


def test_probability_only_for_validated_families_and_never_from_mean():
    proj = {"home_win_prob": 0.8, "margin": 10.0, "margin_sd": 10.0, "total": 140.0, "total_sd": 15}
    win = S.parse_contract("KXNCAAMBGAME", {"yes_sub_title": "Duke"}, UNC, DUKE)  # away
    assert S.probability(win, proj)[0] == pytest.approx(0.2)
    sp = S.parse_contract("KXNCAAMBSPREAD", spread(), UNC, DUKE)  # Duke is away: mean -10
    p, method = S.probability(sp, proj)
    assert (
        p is not None
        and p == pytest.approx(0.0122, abs=1e-4)
        and method == "Phi((margin-line)/margin_sd)"
    )
    tt = {"title": "Duke over 50.5 points scored", "yes_sub_title": "Duke over 50.5 points",
          "floor_strike": 50.5, "strike_type": "greater"}  # fmt: skip
    t = S.parse_contract("KXNCAAMBTEAMTOTAL", tt, UNC, DUKE)
    assert S.probability(t, proj) == (None, "no_team_score_distribution_in_frozen_model")
    ot = S.parse_contract("KXNCAAMBOT", {"title": "Game goes to overtime"}, UNC, DUKE)
    assert S.probability(ot, proj)[0] is None
    assert S.probability(sp, {"margin": 3.0})[0] is None  # no sd -> no probability
    unk = S.parse_contract("KXNCAAMBNEWTHING", {}, UNC, DUKE)
    assert unk["status"] == "unsupported_series" and S.probability(unk, proj)[0] is None


def _raw(series, family, event, **market):
    return {
        "series_ticker": series,
        "family": family,
        "market": {"event_ticker": event, **market},
    }


def test_scope_keeps_season_markets_out_of_game_mapping():
    assert (
        mapping.market_scope(_raw("KXNCAAMBGAME", "GAME_WINNER", "KXNCAAMBGAME-26NOV04DUKEUNC"))
        == "GAME"
    )
    assert mapping.market_scope(
        _raw("KXNCAAMBAPRANK", "FUTURES_OTHER", "KXNCAAMBAPRANK-26DEC07R2")
    ) == ("NON_GAME")
    # a date-like token in an award/stat series is never a game
    assert mapping.market_scope(_raw("KXNCAAMBAWARD", "OTHER", "KXNCAAMBAWARD-26NOV04X")) == (
        "NON_GAME"
    )
    assert (
        mapping.market_scope(
            _raw("KXNCAAMBUNDEFEATEDHOME", "GAME_WINNER", "KXNCAAMBUNDEFEATEDHOME-27")
        )
        == "NON_GAME"
    )
    # a brand-new dated game-family series is still attempted (and explained if unmatched)
    assert (
        mapping.market_scope(
            _raw("KXNCAAMBNEWPROP", "PLAYER_PROP", "KXNCAAMBNEWPROP-26NOV04DUKEUNC")
        )
        == "GAME_CANDIDATE"
    )


def test_rules_text_identifies_game_for_old_captures_with_one_sided_titles():
    games = pd.DataFrame(
        {
            "game_id": [5],
            "game_date_et": [date(2026, 11, 4)],
            "home_team_id": [UNC],
            "away_team_id": [DUKE],
        }
    )
    raw = _raw(
        "KXNCAAMBSPREAD",
        "SPREAD",
        "KXNCAAMBSPREAD-26NOV04ZZZYYY",
        title="Duke wins by over 12.5 points",
        rules_primary=RULES,
    )
    assert mapping.map_raw(raw, games, {}) == (5, "ok")
    raw["market"]["rules_primary"] = RULES.replace("North Carolina", "Kansas")
    assert mapping.map_raw(raw, games, {})[0] is None  # a different matchup never matches


GAME_RULES = (
    "If Duke wins the Duke vs North Carolina men's college basketball game originally "
    "scheduled for Nov 4, 2026, then the market resolves to Yes."
)


def _games(h=UNC, a=DUKE):
    return pd.DataFrame(
        {
            "game_id": [5],
            "game_date_et": [date(2026, 11, 4)],
            "home_team_id": [h],
            "away_team_id": [a],
        }
    )


def test_rules_regex_handles_game_half_and_at_in_team_names():
    assert S.rules_matchup({"rules_primary": GAME_RULES}) == ("Duke", "North Carolina")
    half = "If Duke wins the 1st half of the Duke vs North Carolina men's college basketball game"
    assert S.rules_matchup({"rules_primary": half}) == ("Duke", "North Carolina")
    uni = "in the University at Albany vs Manhattan men's college basketball game originally"
    assert S.rules_matchup({"rules_primary": uni}) == ("University at Albany", "Manhattan")
    assert S.resolve_team("University at Albany") == teams.resolve("Albany", "espn")
    assert S.resolve_team("NC St.") == teams.resolve("NC State", "espn")
    assert S.resolve_team("Not A Real Team") is None


def test_event_ticker_with_suffix_and_one_sided_exhibition_reasons():
    assert mapping.event_date("KXNCAAMBRACE-26NOV02ARIZUCLA-10") == date(2026, 11, 2)
    raw = _raw("KXNCAAMBGAME", "GAME_WINNER", "KXNCAAMBGAME-26NOV04ZZZYYY", title="Fisk wins")
    raw["market"]["rules_primary"] = GAME_RULES.replace("Duke vs North Carolina", "Fisk vs Duke")
    assert mapping.map_raw(raw, _games(), {}) == (None, "one_team_unresolved")
    raw["market"]["rules_primary"] = GAME_RULES.replace("North Carolina", "Kansas")
    assert mapping.map_raw(raw, _games(), {}) == (None, "teams_resolved_no_scheduled_game")


def test_conflicting_identity_sources_fail_closed():
    raw = _raw(
        "KXNCAAMBGAME", "GAME_WINNER", "KXNCAAMBGAME-26NOV04DUKEUNC", rules_primary=GAME_RULES
    )
    raw["event"] = {"title": "Kansas at North Carolina"}
    assert mapping.map_raw(raw, _games(), {}) == (None, "identity_sources_disagree")
    raw["event"] = {"title": "Duke at North Carolina"}
    assert mapping.map_raw(raw, _games(), {}) == (5, "ok")


def test_tie_outcome_and_verified_name_overrides():
    t = S.parse_contract("KXNCAAMB1H", {"yes_sub_title": "Tie", "title": "Tie 1st half"}, UNC, DUKE)
    assert t["status"] == "parsed" and t["subject_side"] == "tie"
    assert S.probability(t, {"home_win_prob": 0.5}) == (
        None,
        "no_half_distribution_in_frozen_model",
    )
    assert S.settle(t, 30, 30) == (None, "needs_half_scores")
    assert S.resolve_team("Central Connecticut St.") == teams.resolve("Central Connecticut", "espn")
    assert S.resolve_team("Southern University") == teams.resolve("Southern Jaguars", "espn")
    assert S.resolve_team("Kansas St.") == teams.resolve("Kansas State", "espn")
