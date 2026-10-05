"""Player/lineup layer: RAPM recovery, walk-forward leakage, minutes shares."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cbb_edge.players import rapm
from cbb_edge.players.rapm import IncrementalRapm, RapmConfig, TeamShares, player_team_features


def _world(tmp_path, seed=0, n_teams=6, n_days=24, season=2020):
    rng = np.random.default_rng(seed)
    teams = [f"T{i + 1:04d}" for i in range(n_teams)]
    roster = {t: [f"P{1000 * (i + 1) + j}" for j in range(8)] for i, t in enumerate(teams)}
    o_true = {p: rng.normal(0, 3) for t in teams for p in roster[t]}
    d_true = {p: rng.normal(0, 3) for t in teams for p in roster[t]}
    start = pd.Timestamp(f"{season - 1}-11-10 23:00", tz="UTC")
    games, stints, pgs = [], [], []
    gid = 1
    for day in range(n_days):
        order = rng.permutation(n_teams)
        for k in range(0, n_teams - 1, 2):
            h, a = teams[order[k]], teams[order[k + 1]]
            t0 = start + pd.Timedelta(days=day)
            games.append(
                {
                    "game_id": gid,
                    "season": season,
                    "start_time_utc": t0,
                    "available_at": t0 + pd.Timedelta(hours=3),
                    "game_date_et": t0.tz_convert("America/New_York").date(),
                    "home_team_id": h,
                    "away_team_id": a,
                    "home_is_d1": True,
                    "away_is_d1": True,
                    "status": "STATUS_FINAL",
                }
            )
            mins = {p: 0.0 for p in roster[h] + roster[a]}
            for _ in range(10):
                hp = sorted(rng.choice(roster[h], 5, replace=False))
                ap = sorted(rng.choice(roster[a], 5, replace=False))
                for off, de, home in ((hp, ap, True), (ap, hp, False)):
                    rate = 1.0 + (sum(o_true[p] for p in off) + sum(d_true[q] for q in de)) / 100
                    poss = 8
                    pts = rng.poisson(max(rate, 0.2) * poss)
                    row = {
                        "game_id": gid,
                        "available_at": t0 + pd.Timedelta(hours=3),
                        "neutral": False,
                        "off_home": home,
                        "poss": poss,
                        "pts": pts,
                        "garbage": 0,
                        "season": season,
                    }
                    row.update({f"o{i}": off[i] for i in range(5)})
                    row.update({f"d{i}": de[i] for i in range(5)})
                    stints.append(row)
                for p in hp + ap:
                    mins[p] += 4.0
            for t in (h, a):
                for p in roster[t]:
                    pgs.append(
                        {
                            "season": season,
                            "game_id": gid,
                            "team_id": t,
                            "player_id": p,
                            "min": mins[p],
                        }
                    )
            gid += 1
    games = pd.DataFrame(games)
    st = pd.DataFrame(stints)
    p = tmp_path / "data" / "silver" / "stints"
    p.mkdir(parents=True, exist_ok=True)
    st.to_parquet(p / f"stints_{season}.parquet")
    return games, st, pd.DataFrame(pgs), o_true, d_true


def test_rapm_recovers_player_effects(tmp_path):
    games, st, pg, o_true, d_true = _world(tmp_path, n_days=80)
    players = sorted(o_true)
    cfg = RapmConfig(lam_o=50, lam_d=50, new_o=0, new_d=0)
    inc = IncrementalRapm(players, np.zeros(len(players)), np.zeros(len(players)), cfg, 100, 0)
    inc.add(st)
    inc.solve()
    r = inc.ratings()
    est = np.array(r.o)
    tru = np.array([o_true[p] for p in r.players])
    assert np.corrcoef(est, tru)[0, 1] > 0.5


def test_player_features_have_no_future_leakage(tmp_path):
    games, st, pg, _, _ = _world(tmp_path, seed=3)
    cfg = RapmConfig(lam_o=200, lam_d=200)
    f1 = player_team_features([2020], games, pg, cfg, verbose=False)
    cut = games["start_time_utc"].sort_values().iloc[len(games) // 2]
    future = games.loc[games.start_time_utc >= cut, "game_id"]
    st2 = st.copy()
    st2.loc[st2.game_id.isin(future), "pts"] *= 5
    st2.to_parquet(rapm.stints_path(2020))
    pg2 = pg.copy()
    pg2.loc[pg2.game_id.isin(future), "min"] = np.random.default_rng(1).uniform(
        0, 40, pg2.game_id.isin(future).sum()
    )
    f2 = player_team_features([2020], games, pg2, cfg, verbose=False)
    past = games.loc[games.start_time_utc < cut, "game_id"]
    a = f1.set_index("game_id").loc[past].sort_index()
    b = f2.set_index("game_id").loc[past].sort_index()
    pd.testing.assert_frame_equal(a, b)
    later = games.loc[games.start_time_utc > cut + pd.Timedelta(days=1), "game_id"]
    assert not np.allclose(
        f1.set_index("game_id").loc[later, "h_p_off"], f2.set_index("game_id").loc[later, "h_p_off"]
    )


def test_first_game_uses_no_current_season_minutes(tmp_path):
    games, st, pg, _, _ = _world(tmp_path, seed=5)
    f = player_team_features([2020], games, pg, RapmConfig(), verbose=False)
    first = games.sort_values("start_time_utc").iloc[0]["game_id"]
    row = f.set_index("game_id").loc[first]
    assert row["h_roster_known"] == 0 and row["h_games_seen_p"] == 0


def test_team_shares_ewma_and_missed_games():
    t0 = pd.Timestamp("2020-01-01", tz="UTC")
    rows = []
    for k in range(4):
        for p, m in (("A", 40.0), ("B", 40.0 if k < 3 else 0.0), ("C", 0.0 if k < 3 else 40.0)):
            rows.append(
                {
                    "game_id": k,
                    "player_id": p,
                    "min": m,
                    "start_time_utc": t0 + pd.Timedelta(days=k),
                    "available_at": t0 + pd.Timedelta(days=k, hours=3),
                }
            )
    ts = TeamShares(pd.DataFrame(rows), halflife=1.0)
    pids, s = ts.shares(4)
    sh = dict(zip(pids, s, strict=True))
    assert abs(sum(s) - 5.0) < 1e-9
    assert sh["C"] > 0 and sh["B"] > sh["C"] * 0.5  # B missed only the latest game
    assert ts.n_available(t0 + pd.Timedelta(days=2)) == 2  # games 0,1 available before cutoff
    assert ts.n_available(t0 + pd.Timedelta(days=1, hours=3)) == 1  # strict inequality
