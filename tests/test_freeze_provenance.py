"""Automated freeze provenance (fail closed) and the pending-final diagnostic."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cbb_edge.research import freeze_provenance as fp
from cbb_edge.research import wave14 as w14

CODE = "a" * 40
COMMIT_AT = "2026-11-12T21:14:37+00:00"
SINCE = datetime(2026, 11, 11, 22, tzinfo=UTC)


def _git(root: Path, *a: str, when: str = COMMIT_AT) -> str:
    env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when,
           "GIT_AUTHOR_NAME": "bot", "GIT_AUTHOR_EMAIL": "b@x", "GIT_COMMITTER_NAME": "bot",
           "GIT_COMMITTER_EMAIL": "b@x"}  # fmt: skip
    return subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True, env=env).stdout.strip()  # fmt: skip


def _archive(tmp_path: Path, stem: str = "20261112T211053Z", as_of: str = "2026-11-12T21:10:53+00:00") -> Path:  # fmt: skip
    root = tmp_path / "arch"
    (root / "projections" / "manifests").mkdir(parents=True)
    _git(root, "init", "-q")
    (root / "README.md").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init", when="2026-11-11T10:00:00+00:00")
    rec = "pure-0.5.0/2027/2026-11-12/G1/r.json"
    (root / "projections" / rec).parent.mkdir(parents=True)
    (root / "projections" / rec).write_text('{"x": 1}\n')
    h = hashlib.sha256((root / "projections" / rec).read_bytes()).hexdigest()
    m = {"as_of": as_of, "code_sha": CODE, "files": {rec: h}}
    (root / "projections" / "manifests" / f"{stem}.json").write_text(json.dumps(m))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "prospective projections")
    return root


def job(jid=1, head=CODE, st="2026-11-12T21:14:34Z", ct="2026-11-12T21:14:39Z", step="success", concl="success", wf=fp.WORKFLOW):  # fmt: skip
    return {"job_id": jid, "run_id": 10 + jid, "workflow_name": wf, "head_sha": head, "conclusion": concl,
            "append_step": {"conclusion": step, "started_at": st, "completed_at": ct}}  # fmt: skip


def test_verified_with_server_step_time_as_upper_bound(tmp_path):
    root = _archive(tmp_path)
    r = fp.verify_manifest(root, "20261112T211053Z", [job()])
    assert r["verified"] and r["pushed_by"] == "2026-11-12T21:14:39+00:00"
    assert r["actions_job"] == 1 and r["archive_commit"] == _git(root, "rev-parse", "HEAD")
    out = fp.build(root, {"jobs": [job()]}, SINCE)
    assert out["20261112T211053Z"]["pushed_by"] == r["pushed_by"] and out["_unverified"] == {}


@pytest.mark.parametrize(
    "jobs,reason",
    [
        ([], "0_matching_actions_jobs"),
        ([job(head="b" * 40)], "0_matching_actions_jobs"),  # different code than the manifest
        ([job(step="skipped")], "0_matching_actions_jobs"),
        ([job(concl="failure")], "0_matching_actions_jobs"),
        ([job(wf="ops-watch")], "0_matching_actions_jobs"),
        ([job(st="2026-11-12T22:00:00Z", ct="2026-11-12T22:00:05Z")], "0_matching_actions_jobs"),
        ([job(st="2026-11-12T21:00:00Z")], "0_matching_actions_jobs"),  # step began before as_of
        ([job(1), job(2)], "2_matching_actions_jobs"),  # ambiguous -> fail closed
    ],
)
def test_unverifiable_evidence_fails_closed(tmp_path, jobs, reason):
    root = _archive(tmp_path)
    r = fp.verify_manifest(root, "20261112T211053Z", jobs)
    assert r == {**r, "verified": False, "reason": reason}
    out = fp.build(root, {"jobs": jobs}, SINCE)
    assert "20261112T211053Z" not in out and "20261112T211053Z" in out["_unverified"]


def test_record_changed_after_commit_fails_closed(tmp_path):
    root = _archive(tmp_path)
    rec = root / "projections/pure-0.5.0/2027/2026-11-12/G1/r.json"
    rec.write_text('{"x": 2}\n')
    _git(root, "commit", "-qam", "mutate", when="2026-11-12T23:00:00+00:00")
    assert fp.verify_manifest(root, "20261112T211053Z", [job()])["reason"] == "record_absent_or_changed_after_commit"  # fmt: skip


def test_uncommitted_hash_mismatch_fails_closed(tmp_path):
    root = _archive(tmp_path)
    (root / "projections/pure-0.5.0/2027/2026-11-12/G1/r.json").write_text('{"x": 3}\n')
    assert fp.verify_manifest(root, "20261112T211053Z", [job()])["reason"] == "record_hash_mismatch_at_head"  # fmt: skip


def test_not_a_git_checkout_verifies_nothing(tmp_path):
    root = _archive(tmp_path)
    plain = tmp_path / "plain"
    subprocess.run(["cp", "-r", str(root), str(plain)], check=True)
    subprocess.run(["rm", "-rf", str(plain / ".git")], check=True)
    out = fp.build(plain, {"jobs": [job()]}, SINCE)
    assert out["_unverified"]["20261112T211053Z"]["reason"] == "projections_root_not_a_git_checkout"


def test_pre_boundary_manifests_are_not_checked(tmp_path):
    root = _archive(tmp_path, stem="20261111T212246Z", as_of="2026-11-11T21:22:46+00:00")
    assert fp.build(root, {"jobs": []}, SINCE)["_unverified"] == {}


def test_generated_provenance_feeds_wave14_exclusion(tmp_path):
    """End to end: only a verified manifest makes a game gradable."""
    root = _archive(tmp_path)
    rm = {(v, 1, "2026-11-12T21:10:53+00:00"): "20261112T211053Z" for v in w14.VERSIONS}
    as_of = datetime(2026, 11, 12, 21, 10, 53, tzinfo=UTC)
    frozen = {v: {1: {"as_of": as_of}} for v in w14.VERSIONS}
    ok = w14.freeze_pushed_at(frozen, rm, fp.build(root, {"jobs": [job()]}, SINCE))
    bad = w14.freeze_pushed_at(frozen, rm, fp.build(root, {"jobs": []}, SINCE))
    assert ok[1]["pushed_by"] == datetime(2026, 11, 12, 21, 14, 39, tzinfo=UTC)
    assert bad[1] == {"pushed_by": None, "reason": "manifest_push_time_unverified"}


def test_trim_and_merge_evidence_keep_only_needed_fields():
    raw = {"id": 5, "run_id": 9, "run_attempt": 1, "workflow_name": fp.WORKFLOW, "head_sha": CODE,
           "conclusion": "success", "runner_name": "x",
           "steps": [{"name": "Set up job", "conclusion": "success"},
                     {"name": fp.APPEND_STEP, "conclusion": "success", "number": 13,
                      "started_at": "s", "completed_at": "c"}]}  # fmt: skip
    t = fp.trim_job(raw)
    assert t["append_step"] == {"conclusion": "success", "started_at": "s", "completed_at": "c"}
    assert "runner_name" not in t
    assert [j["job_id"] for j in fp.merge_evidence({"jobs": [job(7), job(5)]}, [t])] == [5, 7]


def test_committed_provenance_is_reproducible_from_committed_evidence():
    """The committed freeze_provenance.json must be exactly what the generator yields (no hand edits)."""
    here = Path(__file__).parents[1] / "research/wave14"
    prov = json.loads((here / "freeze_provenance.json").read_text())
    ev = json.loads((here / "provenance_evidence.json").read_text())
    assert prov["_note"] == fp.NOTE and prov["_evidence_fetched_at"] == ev["fetched_at"]
    ids = {j["job_id"] for j in ev["jobs"]}
    for k, v in prov.items():
        if not k.startswith("_"):
            assert v["actions_job"] in ids and v["pushed_by"] >= v["committer_date"]


# ------------------------------------------------------------------ pending finals diagnostic
def test_pending_finals_classifies_lag_future_and_attention(tmp_path):
    t = datetime(2026, 11, 12, 23, tzinfo=UTC)
    rows = tmp_path / "rows/2026/11/13"
    rows.mkdir(parents=True)
    cap = t + timedelta(hours=1)  # last archive write: 1 h after the 23:00Z tip
    obs = [{"game_id": 1, "observed_at": cap.isoformat(), "status_type_name": "STATUS_IN_PROGRESS"},
           {"game_id": 3, "observed_at": cap.isoformat(), "status_type_name": "STATUS_POSTPONED"}]  # fmt: skip
    (rows / "a.jsonl").write_text("\n".join(json.dumps(o) for o in obs) + "\n")
    b = w14.PROSPECTIVE_FROM
    base = {
        1: {"as_of": t - timedelta(hours=2), "tip": t},  # tipped 1 h before last write: lag
        2: {"as_of": t - timedelta(hours=2), "tip": t + timedelta(hours=5)},  # future
        3: {"as_of": t - timedelta(hours=9), "tip": t - timedelta(hours=6)},  # should be final
        4: {"as_of": t - timedelta(hours=2), "tip": t - timedelta(hours=6)},  # has a final
        5: {"as_of": datetime(2026, 11, 10, tzinfo=UTC), "tip": t},  # before the boundary
    }
    d = w14.pending_finals(base, {4: {}}, tmp_path, prospective_from=b)
    assert d["classes"] == {"capture_lag": 1, "tip_after_last_capture": 1, "no_final_after_expected_end": 1}  # fmt: skip
    assert d["needs_attention"] == [{"game_id": 3, "tip": str(base[3]["tip"]), "last_status": "STATUS_POSTPONED"}]  # fmt: skip
