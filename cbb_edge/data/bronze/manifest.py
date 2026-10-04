"""Bronze manifests: committed, append-only records of every raw file we hold.

The raw files themselves live in the gitignored data lake; the manifest (small JSONL,
committed under ``manifests/bronze/``) is the reproducibility contract: URL, retrieval
time, sha256, bytes and schema version for every file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cbb_edge.data.http import data_dir, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "manifests" / "bronze"


def manifest_path(source: str) -> Path:
    return MANIFEST_DIR / f"{source}.jsonl"


def load_manifest(source: str) -> dict[str, dict[str, Any]]:
    """Return manifest entries keyed by ``local_path`` (latest entry wins)."""
    path = manifest_path(source)
    out: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                out[rec["local_path"]] = rec
    return out


def record(meta: dict[str, Any], **extra: Any) -> None:
    """Append ``meta`` (from ``FetchResult.meta``) to the source manifest if new."""
    source = meta["source"]
    existing = load_manifest(source)
    prev = existing.get(meta["local_path"])
    if prev and prev.get("sha256") == meta["sha256"]:
        return
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    rec = {**meta, **extra}
    with manifest_path(source).open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def verify(source: str) -> list[str]:
    """Verify local files against the manifest. Returns a list of problems."""
    problems = []
    for rel, rec in load_manifest(source).items():
        p = data_dir() / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif sha256_file(p) != rec["sha256"]:
            problems.append(f"checksum mismatch: {rel}")
    return problems
