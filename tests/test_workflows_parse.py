"""Every GitHub Actions workflow must parse as YAML and declare its triggers.

A workflow with a YAML syntax error (for example an unquoted step name containing ': ') loads in an editor but
GitHub rejects it: it is listed under its file path, cannot be dispatched, and fails instantly on every push.
That happened to kalshi-candles.yml; this test makes it a CI failure instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses_and_declares_triggers_and_jobs(path: Path):
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), path
    triggers = doc.get(True, doc.get("on"))  # PyYAML reads the bare key `on` as boolean True
    assert triggers, f"{path.name}: no triggers"
    assert doc.get("name"), f"{path.name}: missing name"
    jobs = doc.get("jobs") or {}
    assert jobs, f"{path.name}: no jobs"
    for job_id, job in jobs.items():
        assert job.get("runs-on"), f"{path.name}:{job_id} missing runs-on"
        for i, step in enumerate(job.get("steps") or []):
            assert ("run" in step) or ("uses" in step), (
                f"{path.name}:{job_id} step {i} has no run/uses"
            )
            if "name" in step:
                assert isinstance(step["name"], str), (
                    f"{path.name}:{job_id} step {i} name is not a string"
                )


def test_production_workflows_can_be_dispatched():
    for name in (
        "kalshi-candles",
        "fee-schedule-probe",
        "period-scores",
        "market-research",
        "kalshi-capture",
    ):
        p = Path(f".github/workflows/{name}.yml")
        if not p.exists():
            continue  # a stacked PR may not contain it yet
        doc = yaml.safe_load(p.read_text())
        triggers = doc.get(True, doc.get("on"))
        assert "workflow_dispatch" in triggers, f"{name} cannot be dispatched"


def _step(workflow: str, prefix: str) -> dict:
    doc = yaml.safe_load(Path(f".github/workflows/{workflow}.yml").read_text())
    steps = [s for j in doc["jobs"].values() for s in j.get("steps") or []]
    return next(s for s in steps if str(s.get("name", "")).startswith(prefix))


def test_projection_catchup_ticks_still_observe_game_states():
    """Finals must be archived on catch-up ticks that skip projecting (no `due` gate), but never on
    PR runs; projecting and appending projections stay gated on `due`."""
    obs = _step("prospective-projections", "Observe game states")
    assert "steps.decide.outputs.due" not in obs["if"]
    assert "!cancelled()" in obs["if"] and "github.event_name != 'pull_request'" in obs["if"]
    assert "schedule_state observe" in obs["run"] and "projections-archive" not in obs["run"]
    for prefix in ("Refresh free inputs and project", "Append to projections-archive"):
        assert (
            "steps.decide.outputs.due == 'true'" in _step("prospective-projections", prefix)["if"]
        )


def test_ci_cancels_superseded_pr_runs_only():
    doc = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    c = doc["concurrency"]
    assert "pull_request.number" in c["group"] and "github.run_id" in c["group"]
    assert c["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    regrade = doc["jobs"]["wave14-regrade"]
    assert regrade["permissions"] == {"contents": "read", "actions": "read"}
    # Regrade on manual dispatch, Wave 14 PRs and main pushes (merges) only; push is main-only.
    assert "workflow_dispatch" in regrade["if"] and "github.event_name == 'push'" in regrade["if"]
    assert "contains(github.head_ref, 'wave-14')" in regrade["if"]
    assert doc[True]["push"] == {"branches": ["main"]}  # YAML 1.1 parses the `on` key as True
    assert "schedule" not in doc[True]
    run = next(s["run"] for s in regrade["steps"] if "run_wave14.py" in s.get("run", ""))
    assert "--recheck-outcomes" in run
