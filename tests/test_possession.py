"""Wave 5 player possession model: leakage, checkpoint resume, prospective state."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.features import pbp_shots
from cbb_edge.players import possession as pos


def _league(seed=0, seasons=(2020, 2021), n_days=10):
    rng = np.random.default_rng(seed)
    teams = ["T1", "T2", "T3", "T4"]
    roster = {t: [f"{t}p{j}" for j in range(7)] for t in teams}
    games, rows = [], []
    gid = 1
    for s in seasons:
        start = pd.Timestamp(f"{s - 1}-11-10 23:00", tz="UTC")
        for d in range(n_days):
            for h, a in (
                (teams[d % 4], teams[(d + 1) % 4]),
                (teams[(d + 2) % 4], teams[(d + 3) % 4]),
            ):
                t0 = start + pd.Timedelta(days=d)
                games.append({"game_id": gid, "season": s, "start_time_utc": t0,
                              "home_team_id": h, "away_team_id": a})  # fmt: skip
                for t in (h, a):
                    for q in roster[t][: 5 + (d % 3)]:
                        r = {"season": s, "game_id": gid, "team_id": t, "player_id": q,
                             "pos": ["G", "F", "C"][int(q[-1]) % 3],
                             "t": int((t0 + pd.Timedelta(hours=3)).value),
                             "min": float(rng.integers(8, 36))}  # fmt: skip
                        for c in pos._counts():
                            r[c] = float(rng.integers(0, 6))
                        rows.append(r)
                gid += 1
    x = pd.DataFrame(rows).sort_values(["player_id", "t"]).reset_index(drop=True)
    return pd.DataFrame(games), x


def _prior() -> pos.PlayerPrior:
    return pos.PlayerPrior(
        kappa={r: 50.0 for r in pos.RATES},
        pos_mean={r: {p: 0.3 for p in pos.POSITIONS} for r in pos.RATES},
    )


def test_profiles_ignore_future_games():
    games, x = _league()
    pr = _prior()
    full = pos.team_profiles(x, pr, games)
    cut = games["start_time_utc"].sort_values().iloc[len(games) * 3 // 4]
    part = pos.team_profiles(x[x["t"] < cut.value], pr, games)
    st = games.set_index("game_id")["start_time_utc"]
    f = full[full["game_id"].map(st) < cut]
    m = f.merge(part, on=["game_id", "team_id", "season"], suffixes=("", "_p"))
    assert len(m) == len(f) > 0
    for c in pos.TEAM_OUT:
        np.testing.assert_allclose(m[c], m[f"{c}_p"], rtol=0, atol=1e-12)


def test_profiles_resume_from_checkpoint_exactly():
    games, x = _league(seed=1)
    pr = _prior()
    pret = {(q, t, 2021): 0.7 for q, t in zip(x["player_id"], x["team_id"], strict=True)}
    full = pos.team_profiles(x, pr, games, pret)
    ev = pos.team_profiles.end_values
    ew = pos.team_profiles.end_weights
    mix = pos.team_profiles.pos_mix
    cur = x[x["season"] == 2021]
    res = pos.team_profiles(
        cur,
        pr,
        games,
        pret,
        offset=pos.career_totals(x, 2020),
        end_val_init={k: v for k, v in ev.items() if k[1] <= 2020},
        end_w_init={k: v for k, v in ew.items() if k[1] <= 2020},
        pos_mix=mix,
    )
    a = full[full["season"] == 2021].sort_values(["game_id", "team_id"]).reset_index(drop=True)
    b = res.sort_values(["game_id", "team_id"]).reset_index(drop=True)
    assert len(a) == len(b) > 0
    for c in pos.TEAM_OUT:
        np.testing.assert_allclose(a[c], b[c], rtol=0, atol=1e-12)


def test_next_state_equals_next_game_value():
    games, x = _league(seed=2)
    pr = _prior()
    full = pos.team_profiles(x, pr, games)
    st = games.set_index("game_id")["start_time_utc"]
    last = games[games["season"] == 2021].sort_values("start_time_utc").iloc[-1]
    cut = last["start_time_utc"]
    part = pos.team_profiles(x[x["t"] < cut.value], pr, games)
    del part
    nxt = pos.team_profiles.next_state
    row = full[(full["game_id"] == last["game_id"])].set_index("team_id")
    for team in (last["home_team_id"], last["away_team_id"]):
        for c in pos.TEAM_OUT:
            assert abs(nxt[(2021, team)][c] - row.loc[team, c]) < 1e-12
    assert st.max() == cut


def test_zero_weight_players_never_enter_top5_features():
    w = np.array([[1.0, 0.0, 0.0, 0.0, 0.0, 0.0]])
    V = {r: np.full((1, 6), 0.3) for r in pos.RATES}
    V["blk"] = np.array([[0.01, 0.9, 0.9, 0.9, 0.9, 0.9]])  # future players: huge blocks
    V["orb"] = np.array([[0.02, 0.9, 0.9, 0.9, 0.9, 0.9]])
    out = pos._aggregate(w, V)
    assert out["i_rimprot"][0] == 0.01
    assert out["i_orbsize"][0] == 0.02


def test_zone_classification_is_format_robust():
    t = pd.DataFrame(
        {
            "type_text": ["Three Point Jump Shot", "JumpShot", "LayUpShot", "JumpShot",
                          "DunkShot", "MadeFreeThrow", "Free Throw 1 of 1", "TipShot"],
            "text": ["A made Three Point Jumper.", "B makes 25-foot three point jumper",
                     "C missed Layup.", "D makes 12-foot jumper", "E makes dunk (F assists)",
                     "G made Free Throw.", "H missed Free Throw.", "I made Tip Shot."],
            "scoring_play": [True, True, False, True, True, True, False, True],
            "shooting_play": [True] * 8,
            "score_value": [3, 3, 0, 2, 2, 1, 0, 2],
            "athlete_id_1": [1, 2, 3, 4, 5, 6, 7, 8],
            "athlete_id_2": [np.nan, np.nan, np.nan, np.nan, 9, np.nan, np.nan, np.nan],
        }
    )  # fmt: skip
    s = pbp_shots.classify(t)
    assert s["zone"].tolist() == ["t3", "t3", "rim", "j2", "rim", "ft", "ft", "rim"]
    assert s["ast"].tolist() == [False, False, False, False, True, False, False, False]


def test_defense_excess_uses_only_earlier_games():
    act = pd.DataFrame(
        {
            "game_id": [1, 2, 3],
            "team_id": ["A", "B", "C"],
            "opp_id": ["D", "D", "D"],
            "season": 2020,
            "start_time_utc": pd.to_datetime(["2019-11-10", "2019-11-12", "2019-11-14"], utc=True),
            "pbp_fga": [60.0, 60.0, 60.0],
            "rim_a": [30.0, 0.0, 99.0],
            "rim_m": [15.0, 0.0, 50.0],
            "t3_a": [10.0, 20.0, 0.0],
            "fta": [10.0, 10.0, 10.0],
            "fga": [60.0, 60.0, 60.0],
        }
    )
    prof = pd.DataFrame(
        {
            "game_id": [1, 2, 3],
            "team_id": ["A", "B", "C"],
            "x_rim": 0.3,
            "x_t3": 0.3,
            "x_ftr": 0.3,
            "xk_rim": 0.6,
        }  # fmt: skip
    )
    de = pos.defense_excess(act, prof, 100.0).set_index("game_id")
    assert de.loc[1, "def_rim"] == 0.0  # first game: nothing earlier
    assert abs(de.loc[2, "def_rim"] - (30 - 18) / (60 + 100)) < 1e-12
    act2 = act.copy()
    act2.loc[2, "rim_a"] = 0.0  # changing game 3 must not move games 1-2
    de2 = pos.defense_excess(act2, prof, 100.0).set_index("game_id")
    assert de.loc[[1, 2]].equals(de2.loc[[1, 2]])
