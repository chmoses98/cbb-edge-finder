"""Downstream market-stage benchmark / future_market_alignment / Kalshi / availability."""

from __future__ import annotations

import pandas as pd

from cbb_edge.market import stages


def _rec(gid, version, as_of, margin, wp=0.6, avail=None):
    r = {
        "game": {"espn_game_id": gid, "start_time_utc": "2026-11-20T23:00:00+00:00"},
        "model": {"version": version},
        "prospective": {"as_of": as_of},
        "projection": {"margin": margin, "total": 140.0, "home_win_prob": wp, "margin_sd": 11},
    }
    if avail:
        r["availability"] = avail
    return r


def _snaps():
    rows = []
    for gid, moves in ((1, (-3.0, -4.0, -5.0)), (2, (2.0, 2.0, 1.0))):
        for (h, t), mv in zip(
            (
                ("T-24h", "2026-11-19T23:00Z"),
                ("T-6h", "2026-11-20T17:00Z"),
                ("latest", "2026-11-20T22:50Z"),
            ),
            moves,
            strict=True,
        ):
            rows.append(
                {
                    "game_id": gid,
                    "captured_at": t,
                    "horizon": h,
                    "provider": "x",
                    "spread": mv,
                    "home_favorite": mv < 0,
                    "over_under": 140.0,
                }
            )
    return pd.DataFrame(rows)


def test_lines_orientation_uses_favourite_flag():
    ln = stages.espn_lines(_snaps())
    g1 = ln[ln["game_id"] == 1]
    assert (g1["mkt_margin"] > 0).all()  # home favoured -> positive home margin
    assert (ln[ln["game_id"] == 2]["mkt_margin"] < 0).all()


def test_stage_benchmark_and_alignment():
    recs = [
        _rec(1, "pure-0.3.0", "2026-11-19T22:00:00+00:00", 6.0),
        _rec(2, "pure-0.3.0", "2026-11-19T22:00:00+00:00", -1.0),
    ]
    proj = stages.projection_table(recs)
    lines = stages.espn_lines(_snaps())
    res = pd.DataFrame({"game_id": [1, 2], "margin": [5.0, -2.0]})
    sb = stages.stage_benchmark(proj, lines, res)
    assert set(sb["stage"]) == {"T-24h", "T-6h", "latest"} and (sb["n"] == 2).all()
    fa = stages.future_market_alignment(proj, lines)
    t24 = fa[fa["stage"] == "T-24h"].iloc[0]
    # game 1: PURE 6 vs mkt 3 -> later 5 (agree); game 2: PURE -1 vs -2 -> later -1 (agree)
    assert t24["sign_agreement"] == 1.0


def test_projection_must_precede_line_capture():
    recs = [_rec(1, "v", "2026-11-20T18:00:00+00:00", 6.0)]  # after the T-24h / T-6h lines
    proj = stages.projection_table(recs)
    sb = stages.stage_benchmark(
        proj, stages.espn_lines(_snaps()), pd.DataFrame({"game_id": [1], "margin": [5.0]})
    )
    assert set(sb["stage"]) == {"latest"}


def test_kalshi_table_and_availability_impact():
    recs = [_rec(1, "v", "2026-11-20T12:00:00+00:00", 4.0, wp=0.65)]
    k = pd.DataFrame(
        [
            {
                "captured_at": "2026-11-20T11:00:00+00:00",
                "family": "GAME_WINNER",
                "market": {"ticker": "K1", "yes_bid": 58, "yes_ask": 62},
            },
            {
                "captured_at": "2026-11-20T22:30:00+00:00",
                "family": "GAME_WINNER",
                "market": {"ticker": "K1", "yes_bid": 66, "yes_ask": 68},
            },
        ]
    )
    res = pd.DataFrame({"game_id": [1], "margin": [3.0]})
    t = stages.kalshi_table(recs, k, {"K1": (1, True)}, res)
    row = t.iloc[0]
    assert abs(row["pure_prob_yes"] - 0.65) < 1e-9 and abs(row["kalshi_prob_yes"] - 0.60) < 1e-9
    assert abs(row["kalshi_final_pretip_prob_yes"] - 0.67) < 1e-9 and row["yes_won"] == 1.0
    av = [
        _rec(
            1,
            "v+avail",
            "2026-11-20T18:00:00+00:00",
            2.0,
            avail={
                "margin_base": 4.0,
                "total_base": 141.0,
                "players": [{"player_id": "P1", "d_share": -0.5}],
            },
        )
    ]
    ai = stages.availability_impact(av, stages.espn_lines(_snaps()), res)
    assert ai.iloc[0]["d_margin"] == -2.0 and ai.iloc[0]["minutes_changed"] == 20.0
