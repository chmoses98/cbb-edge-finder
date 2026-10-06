"""Wave 9: West Florida enters the team universe for 2026-27 only; history unchanged."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cbb_edge.app import checkpoints
from cbb_edge.backtest.walkforward import EngineConfig, run
from cbb_edge.data.ids import teams as T
from cbb_edge.data.silver.build import d1_membership
from tests.synthetic import make_league

REPO = Path(__file__).resolve().parents[1]


def test_west_florida_has_a_stable_id_mapped_only_from_2026_27():
    T.clear_caches()
    reg = T._registry().set_index("team_id")
    assert reg.loc["T0374", "espn_team_id"] == 2697
    assert reg.loc["T0374", "espn_display_name"] == "West Florida Argonauts"
    assert reg.loc["T0374", "first_d1_season"] == 2027
    assert T.canonical_from_espn_in(2697, 2027) == "T0374"
    for s in (2006, 2011, 2022, 2026):  # seasons it appeared as a D-II opponent
        assert T.canonical_from_espn_in(2697, s) is None
    assert T.canonical_from_espn_in(2598, 2010) == "T0293"  # others never gated
    assert T.resolve("West Florida", "espn") == "T0374"
    # ids are never renumbered: the new id is appended after every existing one
    ids = sorted(reg.index)
    assert ids[-1] == "T0374" and len(ids) == len(set(ids))


def test_saint_francis_stays_historical_and_inactive():
    T.clear_caches()
    reg = T._registry().set_index("team_id")
    assert reg.loc["T0293", "espn_team_id"] == 2598 and reg.loc["T0293", "last_d1_season"] == 2026
    m = T.authoritative_members(2027)
    assert m is not None and len(m) == 365 and 2697 in m and 2598 not in m
    for s in range(2006, 2027):
        assert T.authoritative_members(s) is None  # history keeps the games-count rule
    from cbb_edge.availability.capture import current_d1_teams

    cur = current_d1_teams()
    assert 2697 in cur and 2598 not in cur


def test_d1_membership_unchanged_without_authoritative_list():
    sched = pd.DataFrame({"status": ["STATUS_FINAL"] * 40, "home_espn_id": [1] * 20 + [2] * 20,
                          "away_espn_id": [2] * 20 + [3] * 20})  # fmt: skip
    assert d1_membership(sched) == {1, 2, 3}
    assert d1_membership(sched, {9}) == {1, 2, 3, 9}  # partial schedule fallback
    assert d1_membership(sched, {9}, frozenset({1, 7})) == {1, 7}  # authoritative


def test_checkpoint_accepts_only_entering_teams(tmp_path, monkeypatch):
    g1, t1, _ = make_league(season=2020, seed=1, gid_start=1000)
    g2, t2, _ = make_league(season=2021, seed=2, gid_start=5000)
    games, tg = pd.concat([g1, g2], ignore_index=True), pd.concat([t1, t2], ignore_index=True)
    teams = sorted(set(tg["team_id"]))
    monkeypatch.setattr(T, "_registry", lambda: pd.DataFrame({"team_id": teams}))
    cfg = EngineConfig()
    ends: dict = {}
    run(games, tg, [2020], cfg, verbose=False, end_fits_out=ends)
    p = tmp_path / "engine_end.npz"
    checkpoints.save_engine(ends[2020], teams, p)
    base = run(games, tg, [2021], cfg, verbose=False,
               initial_end=checkpoints.load_engine(p, teams))  # fmt: skip
    # the registry grows by one entering team with no games yet
    grown = sorted([*teams, "TZZZZ"])
    monkeypatch.setattr(T, "_registry", lambda: pd.DataFrame({"team_id": grown}))
    with pytest.raises(ValueError):
        checkpoints.load_engine(p, grown)  # not declared as entering
    end = checkpoints.load_engine(p, grown, entering={"TZZZZ"})
    assert end.team_ids == teams
    res = run(games, tg, [2021], cfg, verbose=False, initial_end=end)
    a, b = base.set_index("game_id").sort_index(), res.set_index("game_id").sort_index()
    num = [c for c in a.columns if pd.api.types.is_numeric_dtype(a[c])]
    assert len(a) == len(b) > 0
    # existing teams' states: equal up to the iterative solver's tolerance (a larger
    # system; real-data pre-season projections were byte-identical, WAVE9 report)
    np.testing.assert_allclose(a[num].to_numpy(float), b[num].to_numpy(float), atol=1e-6)
    with pytest.raises(ValueError):
        checkpoints.load_engine(p, grown[1:], entering={"TZZZZ"})  # a team dropped


def test_committed_checkpoints_load_with_the_grown_registry():
    T.clear_caches()
    ids = sorted(T._registry()["team_id"])
    for v in ("pure-0.2.0", "pure-0.5.0"):
        ck = checkpoints.Checkpoint(v, 2026)
        end = ck.engine(ids)
        assert "T0374" not in end.team_ids and len(end.team_ids) == len(ids) - 1
