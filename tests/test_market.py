"""Free historical line parsing + market joins."""

from __future__ import annotations

import pandas as pd

from cbb_edge.market.espn_lines import _num, parse_pickcenter


def _rec(pc):
    return {"game_id": 1, "pickcenter": pc}


def test_parse_legacy_consensus_line_sign():
    # away favored by 17: ESPN spread +17 from home perspective
    pc = [
        {
            "provider": {"name": "consensus", "priority": 0},
            "spread": 17.0,
            "awayTeamOdds": {"favorite": True},
            "homeTeamOdds": {"favorite": False},
        }
    ]
    p = parse_pickcenter(_rec(pc))
    assert p["home_spread_close"] == 17.0 and p["total_close"] is None
    assert not p["has_open_close"]


def test_parse_flips_inconsistent_sign():
    pc = [
        {
            "provider": {"name": "x", "priority": 0},
            "spread": 9.5,
            "overUnder": 154.0,
            "homeTeamOdds": {"favorite": True},
            "awayTeamOdds": {"favorite": False},
        }
    ]
    p = parse_pickcenter(_rec(pc))
    assert p["home_spread_close"] == -9.5 and p["total_close"] == 154.0


def test_parse_draftkings_open_close():
    pc = [
        {
            "provider": {"name": "DraftKings", "priority": 1},
            "spread": -16.5,
            "overUnder": 162.5,
            "homeTeamOdds": {"favorite": True, "moneyLine": -2100},
            "awayTeamOdds": {"favorite": False, "moneyLine": 1100},
            "pointSpread": {
                "home": {"open": {"line": "-14.5"}, "close": {"line": "-16.5"}},
                "away": {"open": {"line": "+14.5"}, "close": {"line": "+16.5"}},
            },
            "total": {"over": {"open": {"line": "o157.5"}, "close": {"line": "o162.5"}}},
            "moneyline": {
                "home": {"open": {"odds": "-1450"}, "close": {"odds": "-2100"}},
                "away": {"open": {"odds": "+850"}, "close": {"odds": "+1100"}},
            },
        }
    ]
    p = parse_pickcenter(_rec(pc))
    assert p["has_open_close"]
    assert p["home_spread_open"] == -14.5 and p["home_spread_close"] == -16.5
    assert p["total_open"] == 157.5 and p["total_close"] == 162.5
    assert p["home_ml_open"] == -1450 and p["away_ml_close"] == 1100


def test_parse_empty():
    assert parse_pickcenter(_rec([])) is None


def test_num_parsing():
    assert _num("o141.5") == 141.5 and _num("u141.5") == 141.5
    assert _num("+8.5") == 8.5 and _num("OFF") is None and _num(None) is None


def test_market_join_is_exact_on_game_id():
    games = pd.DataFrame({"game_id": [1, 2, 3], "home_score": [70, 60, 80]})
    lines = pd.DataFrame({"game_id": [2, 3, 4], "home_spread_close": [-3.0, 5.0, 1.0]})
    j = games.merge(lines, on="game_id", how="left", validate="one_to_one")
    assert j.home_spread_close.isna().sum() == 1  # unmatched stays NaN, never guessed
    assert len(j) == 3


def test_orient_lines_flips_reversed_neutral_site_quotes():
    from cbb_edge.market.espn_lines import orient_to_games

    games = pd.DataFrame(
        {
            "game_id": [1, 2, 3, 4],
            "home_espn_id": [10, 20, 30, 40],
            "away_espn_id": [11, 21, 31, 41],
        }
    )
    lines = pd.DataFrame(
        {
            "game_id": [1, 2, 3, 4],
            "pc_home_espn_id": [10, 21, 99, 40],  # 2 reversed, 3 unknown team
            "pc_away_espn_id": [11, 20, 31, 41],
            "home_spread_close": [-5.0, -7.0, -3.0, -6.0],
            "home_spread_open": [-4.0, -6.5, -3.0, -6.0],
            "home_ml_close": [-200.0, -300.0, -150.0, 250.0],  # game 4: sign contradicts spread
            "away_ml_close": [170.0, 250.0, 130.0, -300.0],
            "home_ml_open": [None, -280.0, None, None],
            "away_ml_open": [None, 230.0, None, None],
        }
    )
    d = orient_to_games(lines, games).set_index("game_id")
    assert d.loc[1, "orientation"] == "as_quoted" and d.loc[1, "home_spread_close"] == -5.0
    assert d.loc[2, "orientation"] == "flipped" and d.loc[2, "home_spread_close"] == 7.0
    assert d.loc[2, "home_spread_open"] == 6.5
    assert d.loc[2, "home_ml_close"] == 250.0 and d.loc[2, "away_ml_close"] == -300.0
    assert d.loc[3, "orientation"] == "unknown" and not d.loc[3, "line_usable"]
    assert d.loc[4, "line_suspect"] and not d.loc[4, "line_usable"]
    assert d.loc[1, "line_usable"] and d.loc[2, "line_usable"]
