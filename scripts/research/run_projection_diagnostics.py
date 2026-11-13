"""Offline projection diagnostics (RESEARCH ONLY): writes research/diagnostics/projection_diagnostics.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cbb_edge.research import projection_diagnostics as pd_
from cbb_edge.research import wave1 as w
from cbb_edge.research import wave13 as w13
from cbb_edge.research import wave14 as w14


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projections", required=True, type=Path)
    ap.add_argument("--schedule", required=True, type=Path)
    ap.add_argument("--espn", required=True, type=Path)
    ap.add_argument(
        "--out", type=Path, default=Path("research/diagnostics/projection_diagnostics.json")
    )
    a = ap.parse_args()
    frozen = {v: w.load_frozen(a.projections, v) for v in pd_.VERSIONS}
    finals, orient = w13.load_finals_oriented(a.schedule, frozen[pd_.BASE])
    market, orient_mk = w13.orient_market(w.load_espn_lines(a.espn), frozen[pd_.BASE])
    rows, funnel = pd_.build_games(frozen, finals, market, before=w.parse_ts(w14.PROSPECTIVE_FROM))
    res = {"evidence_class": "EXPLORATORY_HISTORICAL (records frozen before the Wave 14 boundary only)",
           "funnel": funnel, "orientation_finals": orient["status"], "orientation_market": orient_mk,
           **pd_.run(rows)}  # fmt: skip
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("funnel", "n_games", "n_dates", "n_with_market")}))


if __name__ == "__main__":
    main()
