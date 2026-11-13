"""Wave 14 evaluation coverage (markdown) from run_wave14 outputs; deterministic, read-only.

Usage: python scripts/research/wave14_coverage.py RESULTS.json PROVENANCE.json [> COVERAGE.md]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def coverage(res: dict[str, Any], prov: dict[str, Any]) -> str:
    f, v = res["eligibility_funnel"], res["verdict"]
    pend = res.get("pending_finals_diagnostic") or {}
    s = res.get("summary_eligible") or {}
    ns = {k: int(x["n"]) for k, x in s.items()}
    per_date = Counter(g["date"] for g in res.get("eligible_games") or [])
    verified = sorted(k for k in prov if not k.startswith("_"))
    unverified = prov.get("_unverified") or {}
    post = res["post_boundary_records"]["games"]
    graded = f.get("eligible", 0)
    lines = [
        "## Wave 14 evaluation coverage",
        "",
        f"- Status: **{v['status']}** ({v['n_games']} games on {v['n_dates']} dates; floor "
        f"{v['floor']['games']} / {v['floor']['dates']}).",
        f"- Post-boundary games: {post}; graded {graded} ({100 * graded / post:.0f}%)."
        if post
        else "- Post-boundary games: 0.",
        f"- Every forecaster graded on the identical {graded} games: "
        f"{'yes' if set(ns.values()) <= {graded} and len(ns) == 5 else 'NO ' + str(ns)}.",
        f"- Freeze provenance: {len(verified)} manifest(s) verified, {len(unverified)} unverified "
        f"(evidence fetched {prov.get('_evidence_fetched_at')}, archive head "
        f"{str(prov.get('_archive_head'))[:7]}).",
        "",
        "| funnel stage | games |",
        "|---|---|",
        *[f"| {k} | {n} |" for k, n in sorted(f.items())],
        "",
        "| graded ET date | games |",
        "|---|---|",
        *[f"| {d} | {n} |" for d, n in sorted(per_date.items())],
        "",
        f"Awaiting finals (schedule archive last written {pend.get('schedule_archive_last_observed_at')}): "
        f"{pend.get('classes', {})}; needs attention: {len(pend.get('needs_attention') or [])}.",
    ]
    for k, r in sorted(unverified.items()):
        lines.append(f"- UNVERIFIED {k}: {r.get('reason')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    res = json.loads(Path(sys.argv[1]).read_text())
    prov = json.loads(Path(sys.argv[2]).read_text())
    sys.stdout.write(coverage(res, prov))


if __name__ == "__main__":
    main()
