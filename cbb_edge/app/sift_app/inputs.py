"""Read-only loaders over the archive checkouts the publisher translates.

Every function here only READS: projection records and run manifests
(``projections-archive``), roster truth (``roster-archive``), the prospective scoreboard
(``prospective-scores``), schedule observations / ESPN rows (``schedule-archive``) and the
read-only Kalshi capture (``kalshi-archive``). Nothing is fitted, projected or rewritten.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .selection import ts


def git_head(root: Path | None) -> str | None:
    """The commit a checkout is at (provenance only)."""
    if root is None or not (Path(root) / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True)  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def _stamp_ts(stamp: str) -> pd.Timestamp:
    return ts(pd.Timestamp(stamp))


# ------------------------------------------------------------------ projections archive
def load_records(root: Path | None, season: int) -> list[dict[str, Any]]:
    """Every archived projection record of ``season`` with its archive path and sha256
    (the same reading as ``rosters.prospective_score.load_records``)."""
    out: list[dict[str, Any]] = []
    if root is None or not Path(root).exists():
        return out
    for f in sorted(Path(root).rglob("*.json")):
        if "manifests" in f.parts or ".git" in f.parts:
            continue
        b = f.read_bytes()
        try:
            r = json.loads(b)
        except ValueError:
            continue
        if not isinstance(r, dict) or (r.get("game") or {}).get("season") != season:
            continue
        r["_path"] = str(f.relative_to(root))
        r["_sha256"] = hashlib.sha256(b).hexdigest()
        out.append(r)
    return out


def load_manifests(root: Path | None) -> list[dict[str, Any]]:
    """Run manifests (one per prospective run, written even when no game is in the window:
    the pipeline's heartbeat), oldest first."""
    out = []
    if root is None or not Path(root).exists():
        return out
    for m in sorted(Path(root).rglob("manifests/*.json")):
        try:
            body = json.loads(m.read_text())
        except ValueError:
            continue
        if body.get("as_of"):
            out.append({"stamp": m.stem, "as_of": body["as_of"], "code_sha": body.get("code_sha"),
                        "roster_archive_commit": body.get("roster_archive_commit"),
                        "records": len(body.get("files") or {})})  # fmt: skip
    return sorted(out, key=lambda x: ts(x["as_of"]))


# ------------------------------------------------------------------ roster truth
@dataclass
class Truth:
    stamp: str
    teams: pd.DataFrame  # one row per team: roster_confidence, counts, reason
    proster: dict[str, dict[str, Any]]  # team_id -> P-ROSTER state (continuity, rotation)
    names: dict[str, dict[str, Any]]  # player_id -> identity row (name, class, last team)
    sanity: dict[str, dict[str, Any]]  # team_id -> rotation sanity row
    audit: dict[str, dict[str, Any]] = field(default_factory=dict)  # team_id -> continuity audit
    audit_stamp: str | None = None

    @property
    def as_of(self) -> pd.Timestamp:
        return _stamp_ts(self.stamp)


def truth_stamps(root: Path | None) -> list[str]:
    if root is None or not (Path(root) / "truth").exists():
        return []
    return sorted({f.name.split("_")[0] for f in (Path(root) / "truth").rglob("*_teams.json")})


def _day(root: Path, stamp: str) -> Path:
    return Path(root) / "truth" / stamp[:4] / stamp[4:6] / stamp[6:8]


def _jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def load_truth(root: Path | None, now: pd.Timestamp, stamp: str | None = None) -> Truth | None:
    """The newest roster-truth snapshot captured at or before ``now`` (or exactly ``stamp``)."""
    stamps = [s for s in truth_stamps(root) if _stamp_ts(s) <= now]
    if stamp is not None:
        stamps = [s for s in stamps if s == stamp]
    if not stamps:
        return None
    s = stamps[-1]
    d = _day(Path(root), s)  # type: ignore[arg-type]
    teams = pd.DataFrame(json.loads((d / f"{s}_teams.json").read_text()))
    pst = d / f"{s}_proster_state.json"
    proster = {x["team_id"]: x for x in json.loads(pst.read_text())} if pst.exists() else {}
    names = {}
    for r in _jsonl(d / f"{s}_records.jsonl"):
        if r.get("player_id"):
            names[r["player_id"]] = {k: r.get(k) for k in (
                "name", "team_id", "classification", "last_team", "last_season", "position",
                "status", "class_labels", "d1_seasons")}  # fmt: skip
    sanity = {r["team_id"]: r for r in _jsonl(d / f"{s}_rotation_sanity.jsonl")}
    audit, audit_stamp = {}, None
    for a in sorted((Path(root) / "truth").rglob("*_continuity_audit.json"), key=lambda p: p.name):  # type: ignore[arg-type]
        st = a.name.split("_")[0]
        if st <= s:
            audit_stamp = st
            body = json.loads(a.read_text())
            audit = {"_summary": {k: v for k, v in body.items() if k not in ("large", "all")}}
            for row in body.get("all", []):
                audit[row["team_id"]] = row
    return Truth(s, teams, proster, names, sanity, audit, audit_stamp)


# ------------------------------------------------------------------ prospective scoreboard
@dataclass
class Scoreboard:
    stamp: str
    path: str
    summary: dict[str, Any]
    gate: dict[int, dict[str, str]]  # espn_game_id -> {status, reasons}


def load_scoreboard(root: Path | None) -> Scoreboard | None:
    if root is None or not (Path(root) / "LATEST").exists():
        return None
    rel = (Path(root) / "LATEST").read_text().strip()
    d = Path(root) / rel
    if not (d / "summary.json").exists():
        return None
    summary = json.loads((d / "summary.json").read_text())
    gate: dict[int, dict[str, str]] = {}
    g = d / "integrity_gate.csv"
    if g.exists():
        for r in pd.read_csv(g, dtype={"reasons": str}).fillna("").to_dict("records"):
            gate[int(r["espn_game_id"])] = {
                "status": str(r["status"]),
                "reasons": str(r["reasons"]),
            }
    return Scoreboard(Path(rel).name, rel, summary, gate)


# ------------------------------------------------------------------ Kalshi capture
@dataclass
class KalshiCapture:
    captured_at: str
    file: str
    markets: list[dict[str, Any]]  # raw kalshi-snapshot-v1 rows
    summary: dict[str, Any]


def load_kalshi(root: Path | None, now: pd.Timestamp) -> KalshiCapture | None:
    if root is None or not (Path(root) / "snapshots").exists():
        return None
    files = sorted((Path(root) / "snapshots").rglob("kalshi_cbb_*.jsonl.gz"))
    files = [f for f in files if _stamp_ts(f.name.split("_")[-1].split(".")[0]) <= now]
    if not files:
        return None
    f = files[-1]
    rows = [json.loads(x) for x in gzip.decompress(f.read_bytes()).decode().splitlines() if x]
    sp = f.with_name(f.name.replace(".jsonl.gz", ".summary.json"))
    summary = json.loads(sp.read_text()) if sp.exists() else {}
    cap = summary.get("captured_at") or (rows[0]["captured_at"] if rows else None)
    return KalshiCapture(cap, str(f.relative_to(root)), rows, summary)


# ------------------------------------------------------------------ schedule observations
def latest_schedule_observation(root: Path | None) -> str | None:
    """Newest observation stamp in the schedule archive (rows/ or obs/)."""
    if root is None or not Path(root).exists():
        return None
    stamps = [f.name.split("_")[0] for f in Path(root).rglob("*.jsonl") if "_" in f.name]
    stamps = [s for s in stamps if len(s) == 16 and s.endswith("Z")]
    return max(stamps) if stamps else None


def stamp_iso(stamp: str | None) -> str | None:
    return None if not stamp else _stamp_ts(stamp).isoformat()
