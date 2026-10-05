"""Live / research parity (Wave 5, Priority 0).

The live runner replays only the current season from a season-boundary checkpoint of the
research replay (``cbb_edge.app.checkpoints``). These tests pin that mechanism:

* resuming the team engine, a RAPM chain or the shooting skills from a stored boundary
  state reproduces the continuous multi-season replay EXACTLY (synthetic data, CI);
* the committed checkpoints are content-hashed, pinned, and tampering is detected;
* the committed parity reports (full real-data comparison, produced by
  ``scripts/research/parity_diagnostics.py``) meet the frozen target.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cbb_edge.app import checkpoints
from cbb_edge.backtest.walkforward import EngineConfig, run
from cbb_edge.players import shooting
from cbb_edge.players.rapm import RapmConfig, player_team_features
from tests.synthetic import make_league
from tests.test_players import _world

REPO = Path(__file__).resolve().parents[1]

CHECKPOINT_SHA = {
    ("pure-0.2.0", 2025): "4febe10bfafea25f3ba0deccd6bd401662ff1373520248121d1bba3e98cb2429",
    ("pure-0.2.0", 2026): "7bae1c5cdf63d333fe374c66ebc266e9a516cff5b20a613e03d9040baeb564b6",
    ("pure-0.3.0", 2025): "704880738bc0ed124f3228eb9ea701655dcc88ebf06199ad8a15585bc9015029",
    ("pure-0.3.0", 2026): "05a6387a0933101b6f21276b627bcdb5f28a71092e5180c61048c367c0246128",
    ("pure-0.4.0", 2025): "0dda4f83775187177bea2a5d73b60baa3f3d7fb1f2b7c5a4b90d8aaf10fa225a",
    ("pure-0.4.0", 2026): "eef201a0861b47236552132f682bdf3900a1e48f33f3149147ac20a8fb7a634d",
}


def _two_season_league():
    g1, t1, _ = make_league(season=2020, seed=1, gid_start=1000)
    g2, t2, _ = make_league(season=2021, seed=2, gid_start=5000)
    return pd.concat([g1, g2], ignore_index=True), pd.concat([t1, t2], ignore_index=True)


def test_engine_resume_from_checkpoint_is_exact(monkeypatch, tmp_path):
    games, tg = _two_season_league()
    teams = sorted(set(tg["team_id"]))
    import cbb_edge.data.ids.teams as tm

    monkeypatch.setattr(tm, "_registry", lambda: pd.DataFrame({"team_id": teams}))
    cfg = EngineConfig()
    ends: dict = {}
    full = run(games, tg, [2020, 2021], cfg, verbose=False, end_fits_out=ends)
    p = tmp_path / "engine_end.npz"
    checkpoints.save_engine(ends[2020], teams, p)
    resumed = run(
        games, tg, [2021], cfg, verbose=False, initial_end=checkpoints.load_engine(p, teams)
    )
    a = full[full["season"] == 2021].set_index("game_id").sort_index()
    b = resumed.set_index("game_id").sort_index()
    num = [c for c in a.columns if pd.api.types.is_numeric_dtype(a[c])]
    assert len(a) == len(b) > 0
    np.testing.assert_array_equal(a[num].to_numpy(float), b[num].to_numpy(float))
    cold = run(games, tg, [2021], cfg, verbose=False).set_index("game_id").sort_index()
    assert not np.allclose(a[num].to_numpy(float), cold[num].to_numpy(float))  # non-trivial
    with pytest.raises(ValueError):
        checkpoints.load_engine(p, teams[::-1])


def _two_season_world(tmp_path):
    g1, s1, p1, _, _ = _world(tmp_path, seed=5, season=2020)
    g2, s2, p2, _, _ = _world(tmp_path, seed=6, season=2021)
    for x in (g2, s2, p2):
        x["game_id"] = x["game_id"] + 100000
    s2.to_parquet(tmp_path / "data" / "silver" / "stints" / "stints_2021.parquet")
    return pd.concat([g1, g2], ignore_index=True), pd.concat([p1, p2], ignore_index=True)


def test_rapm_resume_from_checkpoint_is_exact(tmp_path):
    games, pg = _two_season_world(tmp_path)
    cfg = RapmConfig(lam_o=200, lam_d=200)
    ends: dict = {}
    full = player_team_features([2020, 2021], games, pg, cfg, verbose=False, end_ratings=ends)
    p = tmp_path / "rapm_2020.parquet"
    checkpoints.save_rapm(ends[2020], p)
    resumed = player_team_features(
        [2021], games, pg, cfg, verbose=False, initial_prev=checkpoints.load_rapm(p)
    )
    a = full[full["season"] == 2021].set_index("game_id").sort_index()
    b = resumed.set_index("game_id").sort_index()
    num = [c for c in a.columns if pd.api.types.is_numeric_dtype(a[c])]
    assert len(a) == len(b) > 0
    np.testing.assert_allclose(a[num].to_numpy(float), b[num].to_numpy(float), rtol=0, atol=1e-12)
    cold = player_team_features([2021], games, pg, cfg, verbose=False)
    cold = cold.set_index("game_id").sort_index()
    assert not np.allclose(a[num].to_numpy(float), cold[num].to_numpy(float))  # non-trivial


def _shooting_rows(seed=0):
    rng = np.random.default_rng(seed)
    games, rows = [], []
    teams = ["T1", "T2", "T3", "T4"]
    players = {t: [f"{t}p{j}" for j in range(6)] for t in teams}
    gid = 1
    for season in (2020, 2021):
        start = pd.Timestamp(f"{season - 1}-11-10 23:00", tz="UTC")
        for d in range(12):
            for h, a in (
                (teams[d % 4], teams[(d + 1) % 4]),
                (teams[(d + 2) % 4], teams[(d + 3) % 4]),
            ):
                t0 = start + pd.Timedelta(days=d)
                games.append(
                    {
                        "game_id": gid,
                        "season": season,
                        "start_time_utc": t0,
                        "home_team_id": h,
                        "away_team_id": a,
                    }
                )
                for t in (h, a):
                    for q in players[t]:
                        fga, fg3a, fta = rng.integers(2, 12), rng.integers(0, 6), rng.integers(0, 6)
                        fg3a = min(fg3a, fga)
                        rows.append(
                            {
                                "season": season,
                                "game_id": gid,
                                "team_id": t,
                                "player_id": q,
                                "position": ["G", "F", "C"][int(q[-1]) % 3],
                                "available_at": t0 + pd.Timedelta(hours=3),
                                "fga": fga,
                                "fgm": rng.binomial(fga, 0.45),
                                "fg3a": fg3a,
                                "fg3m": rng.binomial(fg3a, 0.33),
                                "fta": fta,
                                "ftm": rng.binomial(fta, 0.7),
                                "min": 20.0,
                            }
                        )
                        rows[-1]["fg3m"] = min(rows[-1]["fg3m"], rows[-1]["fgm"])
                gid += 1
    return pd.DataFrame(games), pd.DataFrame(rows)


def test_shooting_resume_from_checkpoint_is_exact():
    games, pg = _shooting_rows()
    sp = shooting.ShootingPrior(
        kappa={"3": 200.0, "2": 100.0, "ft": 25.0},
        pos_mean={t: {"G": 0.4, "F": 0.45, "C": 0.5} for t in ("3", "2", "ft")},
        b3=0.25,
    )
    x = shooting.player_games(pg)
    full = shooting.live_features(x, games, sp, 2021)
    shooting.team_features(x[x["season"] <= 2020], games, sp)
    prev = {k: v for k, v in shooting.team_features.prev_team.items() if k[1] == 2020}
    resumed = shooting.live_features(
        x[x["season"] == 2021], games, sp, 2021, shooting.career_totals(x, 2020), prev
    )
    a = full.set_index("game_id").sort_index()
    b = resumed.set_index("game_id").sort_index()
    assert len(a) == len(b) > 0
    np.testing.assert_allclose(a.to_numpy(float), b.to_numpy(float), rtol=0, atol=1e-12)
    cold = shooting.live_features(x[x["season"] == 2021], games, sp, 2021)
    cold = cold.set_index("game_id").sort_index().to_numpy(float)
    assert not np.allclose(a.to_numpy(float), cold, equal_nan=True)  # non-trivial


@pytest.mark.parametrize("key", sorted(CHECKPOINT_SHA))
def test_committed_checkpoints_verify_and_are_pinned(key):
    v, b = key
    ck = checkpoints.Checkpoint(v, b)  # verifies every file hash
    assert ck.manifest["sha256"] == CHECKPOINT_SHA[key]
    assert ck.manifest["target_season"] == b + 1
    for rep in ck.manifest["verification"].values():
        d = next(x for k, x in rep.items() if k.startswith("max_abs_diff"))
        assert d <= 1e-4  # checkpoint replay reproduces the cached research replay


def test_checkpoint_tampering_is_detected(monkeypatch, tmp_path):
    src = checkpoints.path_for("pure-0.2.0", 2026)
    dst = tmp_path / "pure-0.2.0" / "boundary_2026"
    shutil.copytree(src, dst)
    monkeypatch.setattr(checkpoints, "ROOT", tmp_path)
    checkpoints.Checkpoint("pure-0.2.0", 2026)
    f = dst / "rapm_base_2026.json"
    f.write_text(f.read_text().replace("}", " }"))
    with pytest.raises(ValueError):
        checkpoints.Checkpoint("pure-0.2.0", 2026)


@pytest.mark.parametrize("version", ["pure-0.2.0", "pure-0.3.0", "pure-0.4.0"])
@pytest.mark.parametrize("day", ["2025-12-06", "2026-02-14"])
def test_recorded_parity_meets_frozen_target(version, day):
    rep = json.loads((REPO / "research" / "wave5" / f"parity_{version}_{day}.json").read_text())
    m = rep["margin_live_vs_research_features"]
    assert rep["n_games"] >= 100
    assert m["mean_abs"] <= 1e-6 and m["max_abs"] <= 1e-6
    assert rep["total_live_vs_research_features"]["max_abs"] <= 1e-6
    assert all(f["max_abs"] <= 1e-6 for f in rep["worst_features"])
