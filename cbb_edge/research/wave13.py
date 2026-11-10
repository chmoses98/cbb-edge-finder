"""Wave 13 evaluation helpers: orientation-safe finals and market lines (RESEARCH ONLY).

Results and ESPN lines are mapped onto the PROJECTED teams by canonical team identity
(``cbb_edge.data.ids.orientation``). A game whose identity cannot be verified is excluded and counted
(fail closed); no archived projection or schedule row is rewritten.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cbb_edge.data.ids.orientation import Orientation, check_orientation, to_projection_frame
from cbb_edge.research import wave1 as w

PROSPECTIVE_FROM = "2026-11-10T21:00:00+00:00"  # registration time (WAVE13.md section 1)


def load_finals_oriented(
    schedule_root: Path,
    base: dict[int, dict[str, Any]],
    *,
    season: int = 2027,
    resolve: Callable[[Any], str | None] | None = None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Finals in the PROJECTION's home/away frame, plus an orientation audit.

    ``base``: frozen projections (``wave1.load_frozen``) of one version, carrying canonical team ids.
    Score = last completed observation; ``available_at`` = first completed observation."""
    last: dict[int, dict[str, Any]] = {}
    first_seen: dict[int, Any] = {}
    for path in sorted(schedule_root.glob("rows/**/*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if not (
                    r.get("status_type_completed")
                    and r.get("home_score") is not None
                    and r.get("away_score") is not None
                    and r.get("game_id") is not None
                ):
                    continue
                gid, seen = int(r["game_id"]), w.parse_ts(r.get("observed_at"))
                last[gid] = r
                if gid not in first_seen or (seen and first_seen[gid] and seen < first_seen[gid]):
                    first_seen[gid] = seen
    out: dict[int, dict[str, Any]] = {}
    audit: dict[str, Any] = {"status": Counter(), "excluded": {}, "swapped": []}
    for gid, p in base.items():
        r = last.get(gid)
        if r is None:
            continue
        c = check_orientation(
            p.get("home_tid"), p.get("away_tid"), r.get("home_id"), r.get("away_id"),
            neutral=bool(r.get("neutral_site")), season=season, resolve=resolve,
        )  # fmt: skip
        audit["status"][c.status.value] += 1
        if not c.scorable:
            audit["excluded"][gid] = c.reason
            continue
        if c.status is Orientation.SWAPPED:
            audit["swapped"].append(gid)
        h, a = to_projection_frame(c, int(r["home_score"]), int(r["away_score"]))
        out[gid] = {"home": int(h), "away": int(a), "available_at": first_seen[gid],
                    "orientation": c.status.value}  # fmt: skip
    audit["status"] = dict(audit["status"])
    audit["swapped"].sort()
    return out, audit


def orient_market(
    market: dict[int, dict[str, Any]],
    base: dict[int, dict[str, Any]],
    *,
    season: int = 2027,
    resolve: Callable[[Any], str | None] | None = None,
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    """ESPN lines re-expressed in the projection's frame (``spread`` stays the home spread, so market
    margin = -spread still holds). Unverifiable orientation: the line is dropped, never guessed."""
    out: dict[int, dict[str, Any]] = {}
    cnt: Counter[str] = Counter()
    for gid, m in market.items():
        p = base.get(gid)
        if p is None:
            continue
        c = check_orientation(
            p.get("home_tid"), p.get("away_tid"), m.get("home_espn_id"), m.get("away_espn_id"),
            neutral=bool(m.get("neutral")), season=season, resolve=resolve,
        )  # fmt: skip
        cnt[c.status.value] += 1
        if not c.scorable:
            continue
        spread = m["spread"] if c.status is Orientation.SAME else -m["spread"]
        out[gid] = {**m, "spread": spread, "orientation": c.status.value}
    return out, dict(cnt)
