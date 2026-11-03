"""Kalshi discovery/taxonomy/capture tests (network mocked; read-only)."""

from __future__ import annotations

import gzip
import json
from unittest import mock

from cbb_edge.kalshi import capture, taxonomy


def test_cbb_series_detection():
    assert taxonomy.is_cbb_series(
        {"ticker": "KXNCAAMBGAME", "title": "Men's college basketball game"}
    )
    assert taxonomy.is_cbb_series({"ticker": "KXMARMAD", "title": "March Madness champion"})
    assert not taxonomy.is_cbb_series(
        {"ticker": "KXNCAAWBGAME", "title": "Women's college basketball"}
    )
    assert not taxonomy.is_cbb_series({"ticker": "KXNBAGAME", "title": "NBA game"})
    # look-alikes observed in the live series list
    for t in (
        "KXNCAABBGAME",
        "KXNCAABASEBALL",
        "KXTEAMSINNCAABBWS",
        "KXWMARMAD",
        "KXNCAAWBSPREAD",
        "KXWMARMADROUND",
        "KXNCAAMLAXGAME",
        "KXNCAAMSOCCERGAME",
        "KXNCAAMWRESTLING125",
    ):
        assert not taxonomy.is_cbb_series({"ticker": t, "title": ""}), t
    for t in (
        "KXNCAAMBGAME",
        "KXNCAAMBSPREAD",
        "KXNCAAMBTOTAL",
        "KXNCAAMB1HSPREAD",
        "KXMARMADSEED",
        "KXMAKEMARMAD",
        "KXNCAABGAME",
    ):
        assert taxonomy.is_cbb_series({"ticker": t, "title": ""}), t
    assert not taxonomy.is_cbb_series({"ticker": "KXNCAAMX", "title": "NCAA Men's Wrestling"})
    assert taxonomy.is_cbb_series(
        {"ticker": "KXNCAAMACC", "title": "ACC men's basketball champion"}
    )


def test_family_classification():
    s = {"ticker": "KXNCAAMBSPREAD"}
    assert taxonomy.classify_market(s, {"title": "Duke wins by over 5.5 points?"}) == "SPREAD"
    assert (
        taxonomy.classify_market({"ticker": "KXNCAAMBTOTAL"}, {"title": "Total points"}) == "TOTAL"
    )
    assert (
        taxonomy.classify_market({"ticker": "KXNCAAMBGAME"}, {"title": "Duke at UNC Winner?"})
        == "GAME_WINNER"
    )
    assert (
        taxonomy.classify_market(
            {"ticker": "KXMARMAD"}, {"title": "Who will win the national championship?"}
        )
        == "FUTURES_CHAMPION"
    )


def test_yes_mid_both_price_styles():
    assert taxonomy.yes_mid_cents({"yes_bid": 40, "yes_ask": 44}) == 42
    assert taxonomy.yes_mid_cents({"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44"}) == 42
    assert taxonomy.yes_mid_cents({"yes_bid": 0, "yes_ask": 0, "last_price": 37}) == 37


def test_capture_writes_immutable_snapshot(tmp_path):
    series = {
        "series": [
            {"ticker": "KXNCAAMBGAME", "title": "College Basketball Game"},
            {"ticker": "KXNBAGAME", "title": "Pro Basketball"},
        ]
    }
    mk = {
        "ticker": "KXNCAAMBGAME-26NOV04DUKEUNC-DUKE",
        "event_ticker": "KXNCAAMBGAME-26NOV04DUKEUNC",
        "title": "Duke at UNC Winner?",
        "status": "active",
        "yes_bid": 55,
        "yes_ask": 57,
        "close_time": "2026-11-05T02:00:00Z",
    }

    def fake_get(path, params=None):
        if path == "/series":
            return series
        if path == "/events":
            return {
                "events": [{"event_ticker": mk["event_ticker"], "title": "Duke at North Carolina"}],
                "cursor": "",
            }
        if path == "/markets":
            if params.get("status") == "open":
                return {"markets": [mk], "cursor": ""}
            return {"markets": [], "cursor": ""}
        raise AssertionError(path)

    with mock.patch.object(capture, "_get", side_effect=fake_get):
        summary = capture.capture(tmp_path)
    assert summary["n_series"] == 1 and summary["n_markets"] == 1
    assert summary["by_family"] == {"GAME_WINNER": 1}
    rows = [json.loads(x) for x in gzip.open(summary["file"], "rt")]
    assert rows[0]["market"]["ticker"] == mk["ticker"]
    assert rows[0]["schema_version"] == capture.SCHEMA_VERSION
    assert rows[0]["event"]["title"] == "Duke at North Carolina"
    assert summary["events_enriched"] == 1
    assert summary["markets_enriched"] == 1


def test_capture_goes_through_cost_policy():
    """Kalshi requests use the registered free source through the chokepoint."""
    with mock.patch.object(capture, "fetch") as f:
        f.return_value = mock.Mock(json=lambda: {"series": []})
        capture.discover_series()
    assert f.call_args.args[0] == "kalshi_public"


def test_event_ticker_and_title_parsing():
    from datetime import date

    from cbb_edge.kalshi import mapping

    assert mapping.event_date("KXNCAAMBGAME-26NOV04DUKEUNC") == date(2026, 11, 4)
    assert mapping.event_date("garbage") is None
    assert mapping.title_teams("Duke at North Carolina Winner?") == ("Duke", "North Carolina")
    assert mapping.title_teams("Kansas vs. Kentucky") == ("Kansas", "Kentucky")


def test_market_maps_to_unique_canonical_game():
    from datetime import date

    import pandas as pd

    from cbb_edge.data.ids import teams
    from cbb_edge.kalshi import mapping

    duke = teams.resolve("Duke", "espn")
    unc = teams.resolve("North Carolina", "espn")
    games = pd.DataFrame(
        {
            "game_id": [1, 2],
            "game_date_et": [date(2026, 11, 4), date(2026, 12, 4)],
            "home_team_id": [unc, duke],
            "away_team_id": [duke, unc],
        }
    )
    m = {"event_ticker": "KXNCAAMBGAME-26NOV04DUKEUNC", "title": "Duke at North Carolina Winner?"}
    assert mapping.map_market(m, games) == (1, "ok")
    bad = {"event_ticker": "KXNCAAMBGAME-26NOV04XXXYYY", "title": "Dook at Nort Carolina Winner?"}
    assert mapping.map_market(bad, games) == (None, "teams_unresolved")


def test_contract_title_can_be_a_single_team_when_event_identifies_matchup():
    from datetime import date

    import pandas as pd

    from cbb_edge.data.ids import teams
    from cbb_edge.kalshi import mapping

    duke = teams.resolve("Duke", "espn")
    unc = teams.resolve("North Carolina", "espn")
    games = pd.DataFrame(
        {
            "game_id": [11],
            "game_date_et": [date(2026, 11, 4)],
            "home_team_id": [unc],
            "away_team_id": [duke],
        }
    )
    market = {
        "event_ticker": "KXNCAAMBGAME-26NOV04DUKEUNC",
        "title": "Will Duke win?",
    }
    assert mapping.map_market(market, games, {"title": "Duke at North Carolina"}) == (11, "ok")
    # The old snapshot has no event object, but an exact code pair still resolves.
    assert mapping.map_market(market, games) == (11, "ok")
    assert (
        mapping.map_market(
            {"event_ticker": "KXNCAAMBGAME-26NOV04XXXYYY", "title": "Will X win?"},
            games,
        )[0]
        is None
    )
    assert mapping.event_date("KXNCAAMBGAME-26NOV44DUKEUNC") is None


def test_same_teams_two_games_same_date_is_never_guessed():
    from datetime import date

    import pandas as pd

    from cbb_edge.data.ids import teams
    from cbb_edge.kalshi import mapping

    duke = teams.resolve("Duke", "espn")
    unc = teams.resolve("North Carolina", "espn")
    games = pd.DataFrame(
        {
            "game_id": [11, 12],
            "game_date_et": [date(2026, 11, 4)] * 2,
            "home_team_id": [unc, unc],
            "away_team_id": [duke, duke],
        }
    )
    market = {
        "event_ticker": "KXNCAAMBGAME-26NOV04DUKEUNC",
        "title": "Will Duke win?",
    }
    assert mapping.map_market(market, games, {"title": "Duke at North Carolina"}) == (
        None,
        "ambiguous_game",
    )


def test_panel_backfill_prioritizes_current_prices_and_preserves_old_backlog(tmp_path):
    """Current odds must be joined first even with a month of old captures waiting."""
    from cbb_edge.kalshi.history import pending_snapshots

    root = tmp_path / "archive"
    out = tmp_path / "panel"
    directory = root / "snapshots" / "2026" / "11" / "02"
    directory.mkdir(parents=True)
    stamps = ("001000", "121000", "225000")
    for stamp in stamps:
        (directory / f"kalshi_cbb_20261102T{stamp}Z.jsonl.gz").touch()

    remaining = pending_snapshots(root, out)
    assert [p.name for p in remaining] == [
        "kalshi_cbb_20261102T225000Z.jsonl.gz",
        "kalshi_cbb_20261102T121000Z.jsonl.gz",
        "kalshi_cbb_20261102T001000Z.jsonl.gz",
    ]
    newest = out / "panels" / "2026" / "11" / "02"
    newest.mkdir(parents=True)
    (newest / "kalshi_cbb_20261102T225000Z.panel.jsonl.gz").touch()
    assert [p.name for p in pending_snapshots(root, out)] == [
        "kalshi_cbb_20261102T121000Z.jsonl.gz",
        "kalshi_cbb_20261102T001000Z.jsonl.gz",
    ]
    assert len(pending_snapshots(root, out)[:1]) == 1
