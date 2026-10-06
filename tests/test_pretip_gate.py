"""Wave 9: the pre-tip evidence gate and the failure states (synthetic fixtures, CI)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pandas as pd

from cbb_edge.rosters import pretip_gate as G
from cbb_edge.rosters import prospective_score as ps

STAMP = "20261101T120000Z"
TIP = "2026-11-03T00:00:00+00:00"
ASOF = "2026-11-02T21:00:00+00:00"
CONF = ["CONFIRMED", "LIKELY", "CONFLICTED", "STALE", "UNKNOWN"]
ROT = [{"player_id": f"P{i}", "share": 0.2, "class": "returning"} for i in range(10)]


def git(repo: Path, *a: str, when: str = "2026-11-01T13:00:00+00:00") -> None:
    env = dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)


def init(repo: Path) -> Path:
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    return repo


def roster_archive(tmp: Path, stamp: str = STAMP, when: str = "2026-11-01T13:00:00+00:00",
                   teams: tuple[str, ...] = ("T1", "T2")) -> Path:  # fmt: skip
    ra = tmp / "ra" if not (tmp / "ra").exists() else tmp / "ra"
    if not ra.exists():
        init(ra)
    d = ra / "truth" / stamp[:4] / stamp[4:6] / stamp[6:8]
    o = ra / "official" / stamp[:4] / stamp[4:6] / stamp[6:8]
    d.mkdir(parents=True, exist_ok=True)
    o.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"player_id": "P1", "team_id": t, "status": "CONFIRMED"} for t in teams]
                 ).to_json(d / f"{stamp}_records.jsonl", orient="records", lines=True)  # fmt: skip
    (d / f"{stamp}_teams.json").write_text(json.dumps([{"team_id": t} for t in teams]))
    (d / f"{stamp}_proster_state.json").write_text(json.dumps(
        [{"team_id": t, "roster_confidence": "CONFIRMED", "expected_rotation": ROT} for t in teams]))  # fmt: skip
    (d / f"{stamp}_freshness.jsonl").write_text("")
    (d / f"{stamp}_conflicts.jsonl").write_text("")
    (o / f"{stamp}_rows.jsonl").write_text('{"team_id": "T1"}\n')
    (o / f"{stamp}_pages.jsonl").write_text('{"team_id": "T1"}\n')
    (o / f"{stamp}_discovery.json").write_text("{}")
    git(ra, "add", "-A")
    git(ra, "commit", "-q", "-m", f"truth {stamp}", when=when)
    return ra


def hashes(ra: Path, stamp: str) -> dict[str, str | None]:
    return {k: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
            for k, p in ps.evidence_files(ra, stamp).items()}  # fmt: skip


def rec(version: str, gid: int, home: str, away: str, margin: float, ra: Path, *,
        asof: str = ASOF, tip: str = TIP, stamp: str = STAMP, conf: str = "CONFIRMED",
        code_sha: str | None = "abc") -> dict:  # fmt: skip
    r = {
        "game": {"espn_game_id": gid, "game_id": f"G{gid}", "season": 2027,
                 "start_time_utc": tip, "site": "home"},
        "home": {"team_id": home}, "away": {"team_id": away},
        "projection": {"margin": margin, "total": 140.0, "home_win_prob": 0.6},
        "model": {"version": version},
        "freshness": {"home_games_seen": 0, "away_games_seen": 0},
        "prospective": {"as_of": asof, "code_sha": code_sha},
    }  # fmt: skip
    if version == ps.ROSTER:
        top = sorted(ROT, key=lambda e: -e["share"])[:8]
        side = {"roster_confidence": conf, "overlay_applied": True, "expected_rotation": top}
        r["roster"] = {"truth_snapshot": stamp, "truth_archive_commit": "c0ffee",
                       "truth_files_sha256": hashes(ra, stamp), "margin_base": margin - 1,
                       "adjustment_a_input_substitution": 0.6,
                       "adjustment_b_continuity": 0.4,
                       "sides": {"home": dict(side, team_id=home),
                                 "away": dict(side, team_id=away)}}  # fmt: skip
    return r


def archive(tmp: Path, records: list[dict], when: str = "2026-11-02T21:06:00+00:00",
            name: str = "pa") -> Path:  # fmt: skip
    pa = tmp / name
    if not pa.exists():
        init(pa)
    files = {}
    for r in records:
        v = r["model"]["version"].replace("+", "_")
        stamp = r["prospective"]["as_of"].replace(":", "").replace("+0000", "Z")
        rel = (
            f"{v}/2027/{r['game']['start_time_utc'][:10]}/G{r['game']['espn_game_id']}/{stamp}.json"
        )
        p = pa / "projections" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(r, sort_keys=True)
        p.write_text(blob)
        files[rel] = hashlib.sha256(blob.encode()).hexdigest()
    m = pa / "projections" / "manifests" / f"{when.replace(':', '')}.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"files": files}))
    git(pa, "add", "-A")
    git(pa, "commit", "-q", "-m", "projections", when=when)
    return pa


def score(pa: Path, ra: Path, res: pd.DataFrame, expected: list[int] | None = None,
          games: pd.DataFrame | None = None) -> tuple[dict, dict]:  # fmt: skip
    recs = ps.load_records(pa, 2027)
    exp = pd.DataFrame({"espn_game_id": expected if expected is not None else res["espn_game_id"]})
    return ps.score(recs, res, roster_archive=ra, games=games,
                    committed=ps.git_first_commit_times(pa),
                    committed_roster=ps.git_first_commit_times(ra), projections_root=pa,
                    expected=exp)  # fmt: skip


def results(*gids: int) -> pd.DataFrame:
    return pd.DataFrame({"espn_game_id": list(gids), "result_margin": [5.0] * len(gids),
                         "result_total": [140.0] * len(gids)})  # fmt: skip


def status(frames: dict, gid: int) -> tuple[str, str]:
    g = frames["integrity_gate"].set_index("espn_game_id")
    return g.loc[gid, "status"], g.loc[gid, "reasons"]


def test_complete_evidence_chain_is_valid_and_scored(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, [rec(ps.BASE, 1, "T1", "T2", 2.0, ra),
                            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)])  # fmt: skip
    frames, s = score(pa, ra, results(1))
    assert status(frames, 1) == ("VALID", "")
    assert s["primary"]["game_1"]["N"] == 1 and s["gate"]["counts"] == {"VALID": 1}


def test_failure_states_are_loud_and_never_scored(tmp_path):
    ra = roster_archive(tmp_path)
    late = "20261103T060000Z"  # a truth snapshot captured AFTER tip
    roster_archive(tmp_path, late, when="2026-11-03T06:30:00+00:00")
    recs = [
        rec(ps.BASE, 1, "T1", "T2", 2.0, ra), rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra, stamp=late),
        rec(ps.BASE, 2, "T1", "T2", 2.0, ra, code_sha=None), rec(ps.ROSTER, 2, "T1", "T2", 3.0, ra),
        rec(ps.BASE, 3, "T1", "T2", 2.0, ra),  # P-ROSTER-1 record only after tip
        rec(ps.ROSTER, 3, "T1", "T2", 3.0, ra, asof="2026-11-03T00:30:00+00:00"),
    ]  # fmt: skip
    pa = archive(tmp_path, recs)
    frames, s = score(pa, ra, results(1, 2, 3))
    st1, why1 = status(frames, 1)
    assert st1 == "INVALID" and "truth_snapshot_not_before_as_of_and_tip" in why1
    st2, why2 = status(frames, 2)
    assert st2 == "INVALID" and "base_code_sha_missing" in why2
    assert status(frames, 3) == ("UNSCORABLE", f"no_pre_tip_record:{ps.ROSTER}")
    assert "primary" not in s  # nothing credited


def test_replaced_snapshot_mutated_record_and_late_commit_fail(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, [rec(ps.BASE, 1, "T1", "T2", 2.0, ra),
                            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)])  # fmt: skip
    # a post-tip refresh silently rewrites the scored truth snapshot
    p = ps.evidence_files(ra, STAMP)["truth_proster_state"]
    p.write_text(json.dumps([{"team_id": "T1", "expected_rotation": []}]))
    git(ra, "add", "-A")
    git(ra, "commit", "-q", "-m", "rewrite", when="2026-11-03T05:00:00+00:00")
    # and somebody edits an archived projection after tip
    f = next(x for x in (pa / "projections").rglob("*.json") if "manifests" not in x.parts
             and "roster" in str(x))  # fmt: skip
    body = json.loads(f.read_text())
    body["projection"]["margin"] = 9.0
    f.write_text(json.dumps(body, sort_keys=True))
    git(pa, "add", "-A")
    git(pa, "commit", "-q", "-m", "edit", when="2026-11-03T05:00:00+00:00")
    frames, _ = score(pa, ra, results(1))
    st, why = status(frames, 1)
    assert st == "INVALID"
    for r in (
        "truth_proster_state_replaced_after_projection",
        "roster_hash_mismatch_vs_manifest",
        "roster_archived_file_mutated",
        "truth_proster_state_replaced_after_projection",
    ):
        assert r in why, why


def test_projection_pushed_after_tip_is_invalid(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, [rec(ps.BASE, 1, "T1", "T2", 2.0, ra),
                            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)],
                 when="2026-11-03T02:00:00+00:00")  # stamped pre-tip, pushed post-tip  # fmt: skip
    frames, _ = score(pa, ra, results(1))
    st, why = status(frames, 1)
    assert (
        st == "INVALID"
        and "base_committed_after_tip" in why
        and "roster_committed_after_tip" in why
    )


def test_duplicate_record_with_different_content_is_invalid(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, [rec(ps.BASE, 1, "T1", "T2", 2.0, ra),
                            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)])  # fmt: skip
    d = pa / "projections" / "copy"  # same (version, game, as_of), different content
    d.mkdir()
    r = rec(ps.BASE, 1, "T1", "T2", 7.0, ra)
    (d / "dup.json").write_text(json.dumps(r, sort_keys=True))
    git(pa, "add", "-A")
    git(pa, "commit", "-q", "-m", "dup", when="2026-11-02T22:00:00+00:00")
    frames, _ = score(pa, ra, results(1))
    assert "base_duplicate_record_differs" in status(frames, 1)[1]


def test_every_confidence_class_scores_and_rescheduled_tip_is_respected(tmp_path):
    ra = roster_archive(tmp_path)
    recs = []
    for i, c in enumerate(CONF, start=1):
        recs += [
            rec(ps.BASE, i, "T1", "T2", 1.0, ra),
            rec(ps.ROSTER, i, "T1", "T2", 2.0, ra, conf=c),
        ]
    pa = archive(tmp_path, recs)
    frames, s = score(pa, ra, results(1, 2, 3, 4, 5))
    assert set(frames["integrity_gate"]["status"]) == {"VALID"}
    assert {k.split(" / ")[1] for k in s["primary_by_overlay_confidence"]} == set(CONF)
    # game 5 really tipped EARLIER than its records said (moved up): records made after
    # the real tip are not pre-tip evidence -> UNSCORABLE, not reconstructed
    games = pd.DataFrame({"espn_game_id": [1, 2, 3, 4, 5], "home_team_id": "T1",
                          "away_team_id": "T2",
                          "tip": [pd.Timestamp(TIP)] * 4 + [pd.Timestamp("2026-11-02T18:00:00Z")]})  # fmt: skip
    frames, _ = score(pa, ra, results(1, 2, 3, 4, 5), games=games)
    assert status(frames, 5)[0] == "UNSCORABLE"


def test_unsettled_and_out_of_scope_games(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, [rec(ps.BASE, 1, "T1", "T2", 2.0, ra),
                            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)])  # fmt: skip
    # game 1 tipped but has no result yet (postponed / result missing): PENDING;
    # game 9 (a non-D-I opponent) is not in the expected set at all
    frames, s = score(pa, ra, results(), expected=[1])
    assert status(frames, 1) == ("PENDING", "")
    assert 9 not in set(frames["integrity_gate"]["espn_game_id"])
    assert s["settled_paired_games"] == 0


def test_gate_fails_closed_without_history(tmp_path):
    ra = roster_archive(tmp_path)
    pa = archive(tmp_path, [rec(ps.BASE, 1, "T1", "T2", 2.0, ra),
                            rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)])  # fmt: skip
    recs = ps.load_records(pa, 2027)
    frames, _ = ps.score(recs, results(1), roster_archive=ra, projections_root=pa,
                         expected=pd.DataFrame({"espn_game_id": [1]}))  # no commit times  # fmt: skip
    st, why = status(frames, 1)
    assert st == "INVALID" and "base_commit_time_unknown" in why
    assert G.manifest_index(None) == {} and G.git_mutated_paths(tmp_path / "x") is None


def test_manifest_lookup_is_exact_with_the_incumbent_legacy_layout(tmp_path):
    """Regression (found by the Wave 9 dry run): pure-0.2.0 records live at the archive
    root (no version folder), so their path is a suffix of every other version's path
    for the same game and run. The manifest must be matched on exact paths."""
    ra = roster_archive(tmp_path)
    recs = [rec(ps.BASE, 1, "T1", "T2", 2.0, ra), rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra),
            rec(ps.INCUMBENT, 1, "T1", "T2", 1.0, ra)]  # fmt: skip
    pa = archive(tmp_path, recs)
    # move the incumbent to the legacy layout and rewrite the manifest accordingly
    inc = next((pa / "projections" / "pure-0.2.0").rglob("*.json"))
    rel_new = inc.relative_to(pa / "projections" / "pure-0.2.0")
    dst = pa / "projections" / rel_new
    dst.parent.mkdir(parents=True, exist_ok=True)
    inc.rename(dst)
    m = next((pa / "projections" / "manifests").glob("*.json"))
    body = json.loads(m.read_text())
    body["files"] = {(str(rel_new) if k.startswith("pure-0.2.0/") else k): v
                     for k, v in body["files"].items()}  # fmt: skip
    m.write_text(json.dumps(body))
    git(pa, "add", "-A")
    git(pa, "commit", "-q", "-m", "legacy layout", when="2026-11-02T21:07:00+00:00")
    idx = G.manifest_index(pa)
    assert str(Path("projections") / rel_new) in idx
    frames, _ = score(pa, ra, results(1))
    assert "hash_mismatch" not in status(frames, 1)[1]
