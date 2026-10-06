"""Wave 8 prospective scorer + season-aware membership (synthetic fixtures, offline)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.rosters import membership
from cbb_edge.rosters import prospective_score as ps

REPO = Path(__file__).resolve().parents[1]
STAMP = "20261101T120000Z"


def _rec(version, gid, as_of, margin, gs=(0, 0), roster=None, tip="2026-11-03T00:00:00+00:00",
         home="T1", away="T2"):  # fmt: skip
    r = {
        "game": {"espn_game_id": gid, "game_id": f"G{gid}", "season": 2027,
                 "start_time_utc": tip, "site": "home"},
        "home": {"team_id": home}, "away": {"team_id": away},
        "projection": {"margin": margin, "total": 140.0, "home_win_prob": 0.6, "margin_sd": 11},
        "model": {"version": version},
        "freshness": {"home_games_seen": gs[0], "away_games_seen": gs[1]},
        "ratings": {"home": {"adj_off": 110, "adj_def": 100}, "away": {"adj_off": 105, "adj_def": 104}},
        "prospective": {"as_of": as_of, "code_version": "0.x", "code_sha": "abc"},
    }  # fmt: skip
    if roster is not None:
        r["roster"] = roster
    return r


def _roster(base, a, b, rot_home=None):
    side = {"roster_confidence": "CONFIRMED", "overlay_applied": True,
            "continuity_correction_applied": True, "truth_cont": 0.4,
            "expected_returning_share": 0.5, "tr_prev": 0.3, "first_d1": 2.0,
            "proj_min_returning": 80.0, "expected_rotation": rot_home or []}  # fmt: skip
    return {"truth_snapshot": STAMP, "spec_sha256": "s", "margin_base": base,
            "adjustment_a_input_substitution": a, "adjustment_b_continuity": b,
            "sides": {"home": side, "away": dict(side, expected_rotation=[])}}  # fmt: skip


def _archive(tmp: Path, rotation=None) -> Path:
    d = tmp / "truth" / "2026" / "11" / "01"
    d.mkdir(parents=True)
    pd.DataFrame([{"player_id": "P1", "team_id": "T1", "status": "CONFIRMED"}]).to_json(
        d / f"{STAMP}_records.jsonl", orient="records", lines=True
    )
    (d / f"{STAMP}_teams.json").write_text(json.dumps([{"team_id": "T1", "fresh_groups": ["a"]}]))
    rot = rotation or [{"player_id": f"P{i}", "share": 0.2, "class": "transfer" if i < 2 else
                        "returning"} for i in range(10)]  # fmt: skip
    (d / f"{STAMP}_proster_state.json").write_text(json.dumps(
        [{"team_id": "T1", "roster_confidence": "CONFIRMED", "expected_rotation": rot}]))  # fmt: skip
    return tmp


def test_scored_record_is_latest_strictly_before_tip_and_paired():
    recs = [
        _rec(ps.BASE, 1, "2026-11-01T14:00:00+00:00", 3.0),
        _rec(ps.BASE, 1, "2026-11-02T21:00:00+00:00", 4.0),
        _rec(ps.BASE, 1, "2026-11-03T00:00:00+00:00", 99.0),  # at tip: never scored
        _rec(ps.ROSTER, 1, "2026-11-02T21:00:00+00:00", 6.0, roster=_roster(4.0, 1.5, 0.5)),
        _rec(ps.INCUMBENT, 1, "2026-11-02T21:00:00+00:00", 2.0),
        _rec(ps.BASE, 2, "2026-11-02T21:00:00+00:00", 1.0),  # no roster record: unpaired
    ]
    for i, r in enumerate(recs):
        r["_path"], r["_sha256"] = f"r{i}.json", f"h{i}"
    res = pd.DataFrame({"espn_game_id": [1, 2], "result_margin": [10.0, -3.0],
                        "result_total": [150.0, 130.0]})  # fmt: skip
    pg = ps.paired_games(ps.pregame(recs), res)
    assert list(pg["espn_game_id"]) == [1]
    g = pg.iloc[0]
    assert g["base_margin"] == 4.0 and g["roster_margin"] == 6.0 and g["incumbent_margin"] == 2.0
    assert g["base_err"] == 6.0 and g["roster_err"] == 4.0  # actual - projected
    assert g["d_abs"] == -2.0 and g["d_sq"] == 16 - 36
    # frozen component split: (a)-only = base + adj_a; (b) = the rest
    assert g["a_only_err"] == 10.0 - 5.5 and np.isclose(g["d_abs_from_b"], -0.5)
    assert g["same_run"] and g["margin_base_consistent"] and g["min_gs"] == 0


def test_score_summary_slices_and_dashboard_show_n(tmp_path):
    arch = _archive(tmp_path / "ra")
    recs = []
    rng = np.random.default_rng(0)
    for gid in range(1, 31):
        m = float(rng.normal(0, 5))
        gs = (0, 0) if gid <= 20 else (1, 2)
        asof = "2026-11-02T21:00:00+00:00"
        recs += [_rec(ps.BASE, gid, asof, m, gs),
                 _rec(ps.ROSTER, gid, asof, m + 1, gs, roster=_roster(m, 0.6, 0.4 + gid / 10))]  # fmt: skip
    for i, r in enumerate(recs):
        r["_path"], r["_sha256"] = f"r{i}.json", f"h{i}"
    res = pd.DataFrame({"espn_game_id": range(1, 31), "result_margin": rng.normal(1, 10, 30),
                        "result_total": 140.0})  # fmt: skip
    frames, s = ps.score(recs, res, roster_archive=arch, d1_teams={"T1", "T2"}, enforce_gate=False)
    assert s["settled_paired_games"] == 30
    assert s["primary"]["game_1"]["N"] == 20 and s["primary"]["games_2_3"]["N"] == 10
    # every fixture game is on one day: a day-clustered interval needs >= 10 days
    assert s["primary"]["game_1"]["paired_abs_change_ci90_day_bootstrap"] is None
    assert s["primary"]["games_2_3"]["paired_abs_change_ci90_day_bootstrap"] is None  # n < 20
    assert sum(t["N"] for t in s["diagnostic_game1_adj_b_buckets"].values()) == 20
    assert set(s["diagnostic_team_game_number"]) == {"team_game_1", "team_game_2", "team_game_3"}
    assert s["integrity"]["truth_evidence_complete"] == 30
    tg = frames["team_games"]
    assert (
        tg["opponent_d1"].all()
        and (tg.loc[tg["team_id"] == "T1", "n_transfer_expected"] == 2).all()
    )
    md = ps.dashboard(s, "x")
    assert "game 1 N = 20" in md and "| game_1 | **20** |" in md
    head = md.split("## HEADLINE")[1].split("##")[0]
    assert "| **20** |" in head and "departed-player" in head
    assert md.index("HEADLINE") < md.index("Game 2 and Game 3, separately")
    # deterministic: identical inputs -> byte-identical outputs
    ps.write(tmp_path / "o1", frames, s, "x")
    frames2, s2 = ps.score(
        recs, res, roster_archive=arch, d1_teams={"T1", "T2"}, enforce_gate=False
    )
    ps.write(tmp_path / "o2", frames2, s2, "x")
    for f in (tmp_path / "o1").iterdir():
        assert f.read_bytes() == (tmp_path / "o2" / f.name).read_bytes(), f.name


def test_no_results_writes_empty_scoreboard(tmp_path):
    frames, s = ps.score([], pd.DataFrame(columns=["espn_game_id", "result_margin"]))
    assert s["settled_paired_games"] == 0 and "note" in s
    ps.write(tmp_path, frames, s, "x")
    md = (tmp_path / "dashboard.md").read_text()
    assert "game 1 N = 0" in md and "NO DATA" in md


def test_rotation_in_record_must_match_snapshot(tmp_path):
    rot = [{"player_id": f"P{i}", "share": 0.2, "class": "returning"} for i in range(10)]
    arch = _archive(tmp_path, rot)
    ok = sorted(rot, key=lambda e: -e["share"])[:8]
    recs = [_rec(ps.BASE, 1, "2026-11-02T21:00:00+00:00", 1.0),
            _rec(ps.ROSTER, 1, "2026-11-02T21:00:00+00:00", 1.0, roster=_roster(1.0, 0, 0, ok))]  # fmt: skip
    for i, r in enumerate(recs):
        r["_path"], r["_sha256"] = f"r{i}.json", f"h{i}"
    res = pd.DataFrame({"espn_game_id": [1], "result_margin": [2.0], "result_total": [140.0]})
    pg = ps.paired_games(ps.pregame(recs), res, roster_archive=arch)
    tg = ps.team_games(pg, arch)
    assert bool(tg.set_index("side").loc["home", "rotation_matches_snapshot"])
    assert (
        pg.iloc[0]["truth_records_sha256"]
        == hashlib.sha256(next(arch.rglob("*_records.jsonl")).read_bytes()).hexdigest()
    )
    recs[1]["roster"]["sides"]["home"]["expected_rotation"] = [{"player_id": "X", "share": 1.0}]
    tg2 = ps.team_games(ps.paired_games(ps.pregame(recs), res, roster_archive=arch), arch)
    assert not tg2.set_index("side").loc["home", "rotation_matches_snapshot"]


def test_load_records_hashes_every_file(tmp_path):
    p = tmp_path / "pure-0.5.0" / "2027" / "2026-11-03" / "G1" / "a.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_rec(ps.BASE, 1, "2026-11-02T21:00:00+00:00", 1.0)))
    (tmp_path / "other.json").write_text(json.dumps({"game": {"season": 2026}}))
    got = ps.load_records(tmp_path, 2027)
    assert len(got) == 1 and got[0]["_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()


def test_scorer_never_imports_market_or_changes_frozen_versions():
    src = (REPO / "cbb_edge" / "rosters" / "prospective_score.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("cbb_edge.market")
    assert ps.VERSIONS == {"base": "pure-0.5.0", "roster": "pure-0.5.0+roster",
                           "incumbent": "pure-0.2.0"}  # fmt: skip
    assert ps.PRIMARY_SLICES == {"game_1": (0, 0), "games_2_3": (1, 2)}  # WAVE7.md 7


# ------------------------------------------------------------------------ membership
def test_membership_keeps_history_and_marks_2026_27_changes():
    t = membership.table()
    sf = t[t["team_id"] == "T0293"]  # Saint Francis (PA)
    assert sf["season"].min() == 2006 and sf["season"].max() == 2026 and len(sf) == 21
    assert not membership.is_member("T0293", 2027) and membership.is_member("T0293", 2026)
    uwf = membership.members(2027)
    uwf = uwf[uwf["school"] == "University of West Florida"].iloc[0]
    assert uwf["team_id"] == "T0374" and uwf["espn_team_id"] == 2697  # Wave 9
    assert uwf["status"] == "MEMBER"
    assert (
        not (membership.table()["team_id"] == "T0374")
        .loc[lambda s: s]
        .index.isin(membership.table().index[membership.table()["season"] < 2027])
        .any()
    )  # never backfilled
    assert len(membership.members(2027)) == 365 and len(membership.members(2026)) == 365
    tr = membership.transitions()["2026->2027"]
    assert {"espn_team_id": 2598, "change": "left"} in tr
    assert {"espn_team_id": 2697, "change": "entered"} in tr


def test_membership_history_matches_team_registry_counts():
    t = membership.table()
    reg = pd.read_csv(REPO / "cbb_edge" / "data" / "ids" / "teams.csv")
    h = t[(t["season"] <= 2026) & t["team_id"].notna()].groupby("team_id")["season"].count()
    for r in reg.itertuples(index=False):
        expect = r.n_d1_seasons - (1 if r.last_d1_season == 2027 else 0)
        assert h.get(r.team_id, 0) == expect, r.team_id
    assert t[t["season"] <= 2026]["team_id"].notna().all()  # history: every row has an id


def test_membership_directory_rows_mirror_universe():
    u = pd.read_csv(
        REPO / "models" / "rosters" / "ncaa_d1_mbb_universe.csv", dtype={"team_id": str}
    )
    m = membership.members(2027)
    assert sorted(m["ncaa_org_id"].astype(int)) == sorted(u["ncaa_org_id"].astype(int))
    assert set(m["team_id"].dropna()) == set(u["team_id"].dropna())


def test_git_first_commit_times_reads_when_each_file_was_added(tmp_path):
    import subprocess

    def git(*a, env=None):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, env=env)

    import os

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    for i, when in enumerate(("2026-11-01T10:00:00+00:00", "2026-11-02T10:00:00+00:00")):
        (tmp_path / f"f{i}.json").write_text("{}")
        git("add", "-A")
        env = dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
        git("commit", "-q", "-m", str(i), env=env)
    t = ps.git_first_commit_times(tmp_path)
    assert t["f0.json"] == pd.Timestamp("2026-11-01T10:00:00Z")
    assert t["f1.json"] == pd.Timestamp("2026-11-02T10:00:00Z")
    assert ps.git_first_commit_times(tmp_path / "nope") == {}


def test_dashboard_excludes_non_members_from_confidence():
    from cbb_edge.rosters import dashboard

    teams = pd.DataFrame({"team_id": ["T1", "T0293"], "roster_confidence": ["CONFIRMED", "STALE"],
                          "confidence_reason": ["x", "no_fresh_majority"]})  # fmt: skip
    reg = {"teams": [{"team_id": "T1", "status": "VERIFIED", "exception": None, "school": "a"}]}
    sc = dashboard.scorecard(reg, [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), teams, 2,
                             members={"T1"})  # fmt: skip
    assert sc["confidence"]["STALE"] == 0 and sc["not_d1_this_season"] == ["T0293"]
    assert "T0293" not in sc["unresolved_teams"]
    assert "Not D-I this season" in dashboard.markdown(sc, "s")


def test_full_path_with_box_scores_and_overlay_confidence(tmp_path):
    arch = _archive(tmp_path / "ra")
    tip = "2026-11-03T00:00:00+00:00"
    recs = [_rec(ps.BASE, 1, "2026-11-02T21:00:00+00:00", 2.0, tip=tip),
            _rec(ps.ROSTER, 1, "2026-11-02T21:00:00+00:00", 3.0, tip=tip,
                 roster=_roster(2.0, 0.5, 0.5))]  # fmt: skip
    for i, r in enumerate(recs):
        r["_path"], r["_sha256"] = f"r{i}.json", f"h{i}"
    res = pd.DataFrame({"espn_game_id": [1], "result_margin": [5.0], "result_total": [140.0]})
    games = pd.DataFrame({"espn_game_id": [1], "home_team_id": ["T1"], "away_team_id": ["T2"],
                          "tip": [pd.Timestamp(tip)]})  # fmt: skip
    box = pd.DataFrame({"espn_game_id": 1, "team_id": "T1",
                        "player_id": [f"P{i}" for i in range(8)] + ["X1"],
                        "minutes": [30, 30, 30, 30, 30, 20, 15, 15.0, 0.0],
                        "starter": [True] * 5 + [False] * 4})  # fmt: skip
    frames, s = ps.score(
        recs, res, roster_archive=arch, box=box, games=games, d1_teams={"T1"}, enforce_gate=False
    )
    assert len(frames["false_inclusion_realized"]) and len(frames["rotation_validation"])
    rv = frames["rotation_validation"].iloc[0]
    assert np.isclose(rv["predicted_minutes_on_non_players"], 16.0)  # P8, P9 never played
    assert "game_1 / CONFIRMED" in s["primary_by_overlay_confidence"]
    assert "latest" in s["intermediate_rotation"] and "BASE" in s["intermediate_rotation"]
    assert not frames["team_games"].set_index("side").loc["home", "opponent_d1"]  # T2 not D-I
    assert "Intermediate" in ps.dashboard(s, "x")


def test_interval_only_with_20_games_on_10_days_and_tiny_samples_flagged():
    import numpy as np

    rng = np.random.default_rng(1)
    d = rng.normal(0, 1, 40)
    assert ps._boot_ci(d, np.repeat(np.arange(4), 10)) is None  # 4 days
    assert ps._boot_ci(d[:19], np.arange(19)) is None  # 19 games
    assert ps._boot_ci(d, np.repeat(np.arange(10), 4)) is not None
    s = {"headline": {"game_1": {"N": 5}}, "gate": {"counts": {"VALID": 5}}}
    assert "INSUFFICIENT SAMPLE (N = 5 < 20)" in ps.dashboard(s, "x")
    assert "SYNTHETIC" in ps.dashboard(s, "x", banner="SYNTHETIC DRY RUN")
