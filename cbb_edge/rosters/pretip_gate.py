"""Pre-tip evidence gate (Wave 9). A prospective observation is CREDITED only when its
whole evidence chain provably existed before tip. Nothing here reconstructs anything:
a game without genuine pre-tip evidence is UNSCORABLE, a game whose evidence fails a
check is INVALID, and both are reported loudly instead of being scored.

Status per settled game (base ``pure-0.5.0`` / P-ROSTER-1 ``pure-0.5.0+roster`` pair):

* ``VALID``       every check below passes -> enters the scoreboard;
* ``INVALID``     a pre-tip record exists but a check fails (reasons listed);
* ``UNSCORABLE``  no pre-tip record for one of the versions (only post-tip records, or
                  none at all): never reconstructed;
* ``PENDING``     not settled yet (not counted anywhere).

Checks (fail closed; "unknown" fails):

1. both records' ``as_of`` < tip;
2. the roster record's truth snapshot stamp < its ``as_of`` and < tip;
3. the truth files (records, teams, proster_state) and official-page files (rows,
   discovery) of that snapshot exist, and their sha256 equal the hashes the record
   stored before tip (``roster.truth_files_sha256``): no replaced snapshot;
4. code SHA recorded on both records; roster-archive commit recorded;
5. each record's file sha256 equals its run manifest entry (``manifests/<stamp>.json``);
6. first-commit time (append-only branch history) of both records, of the truth
   records file and of the official rows file < tip;
7. none of those files was ever modified or deleted after it was added;
8. no second, different record with the same (version, game, as_of);
9. the record's expected rotation equals the archived snapshot's rotation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

VALID, INVALID, UNSCORABLE, PENDING = "VALID", "INVALID", "UNSCORABLE", "PENDING"
REQUIRED_TRUTH = ("truth_records", "truth_teams", "truth_proster_state")
REQUIRED_OFFICIAL = ("official_rows", "official_discovery")


def _ts(x: object) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def manifest_index(root: Path | None) -> dict[str, str]:
    """Record path suffix (relative to the run's output dir) -> sha256, all manifests."""
    out: dict[str, str] = {}
    if root is None or not Path(root).exists():
        return out
    for m in sorted(Path(root).rglob("manifests/*.json")):
        try:
            body = json.loads(m.read_text())
        except ValueError:
            continue
        for rel, sha in (body.get("files") or {}).items():
            out.setdefault(rel, sha)
    return out


def _in_manifest(path: str, sha: str, idx: dict[str, str]) -> bool | None:
    for rel, s in idx.items():
        if path == rel or path.endswith("/" + rel):
            return s == sha
    return None


def git_mutated_paths(root: Path | None) -> set[str] | None:
    """Paths that were modified or deleted after being added (None: no git history)."""
    if root is None or not (Path(root) / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--diff-filter=MD", "--format=", "--name-only",
             "--no-renames"], capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return None
    return {x for x in out.splitlines() if x}


def duplicates(recs: list[dict[str, Any]]) -> set[tuple[str, int, str]]:
    """(version, game, as_of) keys that appear with DIFFERENT content."""
    seen: dict[tuple[str, int, str], set[str]] = {}
    for r in recs:
        k = (r.get("model", {}).get("version"), int(r["game"]["espn_game_id"]),
             str(r.get("prospective", {}).get("as_of")))  # fmt: skip
        seen.setdefault(k, set()).add(r["_sha256"])
    return {k for k, v in seen.items() if len(v) > 1}


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def check_pair(row: pd.Series, *, roster_archive: Path | None, manifests: dict[str, str],
               committed: dict[str, pd.Timestamp] | None,
               committed_roster: dict[str, pd.Timestamp] | None,
               mutated: set[str] | None, mutated_roster: set[str] | None,
               dups: set[tuple[str, int, str]],
               rotation_match: bool | None) -> list[str]:  # fmt: skip
    from cbb_edge.rosters.prospective_score import BASE, ROSTER, evidence_files

    tip = row["tip"]
    why: list[str] = []
    for k in ("base", "roster"):
        if not row[f"{k}_as_of"] < tip:
            why.append(f"{k}_as_of_not_before_tip")
        if not row.get(f"{k}_code_sha"):
            why.append(f"{k}_code_sha_missing")
        m = _in_manifest(row[f"{k}_path"], row[f"{k}_sha256"], manifests)
        if m is None:
            why.append(f"{k}_not_in_manifest")
        elif not m:
            why.append(f"{k}_hash_mismatch_vs_manifest")
        c = (committed or {}).get(row[f"{k}_path"])
        if c is None:
            why.append(f"{k}_commit_time_unknown")
        elif not c < tip:
            why.append(f"{k}_committed_after_tip")
        if mutated is None:
            why.append(f"{k}_history_unavailable")
        elif row[f"{k}_path"] in mutated:
            why.append(f"{k}_archived_file_mutated")
        ver = BASE if k == "base" else ROSTER
        if (ver, int(row["espn_game_id"]), str(row[f"{k}_as_of_raw"])) in dups:
            why.append(f"{k}_duplicate_record_differs")
    stamp = row.get("truth_snapshot")
    if not stamp:
        why.append("truth_snapshot_missing")
    else:
        ts = _ts(stamp)
        if not (ts < row["roster_as_of"] and ts < tip):
            why.append("truth_snapshot_not_before_as_of_and_tip")
    if not row.get("truth_archive_commit"):
        why.append("roster_archive_commit_missing")
    recorded = row.get("truth_files_sha256") or {}
    if not recorded:
        why.append("truth_hashes_not_recorded")
    if roster_archive is None or not stamp:
        why.append("roster_archive_unavailable")
    else:
        files = evidence_files(roster_archive, stamp)
        for k in (*REQUIRED_TRUTH, *REQUIRED_OFFICIAL):
            cur = _sha(files[k])
            if cur is None:
                why.append(f"{k}_missing")
            elif recorded and recorded.get(k) != cur:
                why.append(f"{k}_replaced_after_projection")
        for k in ("truth_records", "official_rows"):
            rel = str(files[k].relative_to(roster_archive))
            c = (committed_roster or {}).get(rel)
            if c is None:
                why.append(f"{k}_commit_time_unknown")
            elif not c < tip:
                why.append(f"{k}_committed_after_tip")
            if mutated_roster is None:
                why.append("roster_history_unavailable")
            elif rel in mutated_roster:
                why.append(f"{k}_archived_file_mutated")
    if rotation_match is False:
        why.append("rotation_differs_from_snapshot")
    return sorted(set(why))


def classify(pre: pd.DataFrame, pg: pd.DataFrame, res: pd.DataFrame,
             expected: pd.DataFrame | None, tg: pd.DataFrame | None,
             **ctx: Any) -> pd.DataFrame:  # fmt: skip
    """One row per settled game we expected to score: status + reasons.

    ``expected``: espn_game_id of every D-I game the experiment should cover (from the
    schedule). Settled games in it without a scored pair are UNSCORABLE (never silently
    dropped); games in ``pg`` are VALID or INVALID."""
    from cbb_edge.rosters.prospective_score import BASE, ROSTER

    rows = []
    settled = set(res["espn_game_id"].astype(int)) if len(res) else set()
    rm: dict[int, bool | None] = {}
    if tg is not None and len(tg) and "rotation_matches_snapshot" in tg:
        for gid, x in tg.groupby("espn_game_id"):
            v = [bool(b) for b in x["rotation_matches_snapshot"] if b is not None and b == b]
            rm[int(gid)] = None if not v else all(v)
    for _, r in pg.iterrows():
        why = check_pair(r, rotation_match=rm.get(int(r["espn_game_id"])), **ctx)
        rows.append({"espn_game_id": int(r["espn_game_id"]), "status": INVALID if why else VALID,
                     "reasons": ";".join(why)})  # fmt: skip
    scored = {x["espn_game_id"] for x in rows}
    have = {v: set(pre.loc[pre["version"] == v, "espn_game_id"]) if len(pre) else set()
            for v in (BASE, ROSTER)}  # fmt: skip
    exp_ids = set(expected["espn_game_id"].astype(int)) if expected is not None else settled
    for gid in sorted((exp_ids & settled) - scored):
        miss = [v for v in (BASE, ROSTER) if gid not in have[v]]
        rows.append({"espn_game_id": gid, "status": UNSCORABLE,
                     "reasons": ";".join(f"no_pre_tip_record:{v}" for v in miss)
                     or "not_paired"})  # fmt: skip
    for gid in sorted(exp_ids - settled - scored):
        rows.append({"espn_game_id": gid, "status": PENDING, "reasons": ""})
    return pd.DataFrame(rows, columns=["espn_game_id", "status", "reasons"])
