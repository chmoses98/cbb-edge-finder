"""Load prospective availability captures as P(plays) overrides (P-AVAIL, PROSPECTIVE_ONLY).

Only explicit reports count (``confidence == 'reported'``): a roster entry with no
injury listing is not evidence of anything. For each (game, player) the latest capture
with ``captured_at <= as_of`` wins. Information strictly before ``as_of`` only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_overrides(
    root: Path, as_of: pd.Timestamp
) -> tuple[dict[tuple[int, str], float], dict[int, str]]:
    rows = []
    for f in sorted((root / "captures").rglob("*.jsonl")) if root.exists() else []:
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        return {}, {}
    d = pd.DataFrame(rows)
    d["captured_at"] = pd.to_datetime(d["captured_at"], utc=True)
    d = d[(d["captured_at"] <= as_of) & d["espn_athlete_id"].notna()]
    d = d.sort_values("captured_at").drop_duplicates(["game_id", "espn_athlete_id"], keep="last")
    rep = d[d["confidence"] == "reported"]
    over = {
        (int(g), f"P{a}"): float(p)
        for g, a, p in zip(rep["game_id"], rep["espn_athlete_id"], rep["p_play"], strict=True)
    }
    when = rep.groupby("game_id")["captured_at"].max().astype(str).to_dict()
    return over, {int(k): v for k, v in when.items()}
