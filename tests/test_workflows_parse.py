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
