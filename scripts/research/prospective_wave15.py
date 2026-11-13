"""Wave 15 margin-calibration challengers: regrade from the immutable archives (read-only).

Run by the CI regrade job after Wave 14 has verified freeze provenance; also runnable locally:

    python scripts/research/prospective_wave15.py --projections <projections-archive> \
        --schedule <schedule-archive> --provenance research/wave14/freeze_provenance.json \
        --out research/wave15 --report research/reports/WAVE15_MARGIN_CALIBRATION.md --exploratory
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cbb_edge.research import challenger_eval as ce
from cbb_edge.research import wave1 as w
from cbb_edge.research import wave13 as w13
from cbb_edge.research import wave14 as w14
from cbb_edge.research import wave15 as w15

EXPLORATORY_BEFORE = w14.PROSPECTIVE_FROM  # historical development set: records before Wave 14


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projections", required=True, type=Path)
    ap.add_argument("--schedule", required=True, type=Path)
    ap.add_argument("--provenance", type=Path, default=Path("research/wave14/freeze_provenance.json"))  # fmt: skip
    ap.add_argument("--out", type=Path, default=Path("research/wave15"))
    ap.add_argument("--report", type=Path, help="markdown report path (optional)")
    ap.add_argument("--exploratory", action="store_true", help="also write the historical (exploratory) analysis")  # fmt: skip
    ap.add_argument("--now", help="analysis time override (ISO); default: current UTC time")
    a = ap.parse_args()
    now = w.parse_ts(a.now) if a.now else datetime.now(UTC)
    assert now is not None
    frozen = {v: w.load_frozen(a.projections, v) for v in w15.VERSIONS}
    finals, orient = w13.load_finals_oriented(a.schedule, frozen[w15.BASE])
    prov = json.loads(a.provenance.read_text()) if a.provenance.exists() else {}
    pushed = ce.pushed_by(frozen, w15.VERSIONS, w14.record_manifests(a.projections), prov)
    rows, funnel = w15.build_rows(frozen, finals, pushed=pushed)
    res: dict[str, Any] = {
        "wave": 15,
        "status_note": "RESEARCH_ONLY; nothing promoted; prospective verdicts only at the registered analysis time",
        "analysis_time": now.isoformat(),
        "window": {
            "prospective_from": ce.PROSPECTIVE_FROM,
            "last_et_date": ce.LAST_ET_DATE,
            "analysis_not_before": ce.ANALYSIS_NOT_BEFORE,
        },  # fmt: skip
        "provenance_file": str(a.provenance),
        "provenance_verified_manifests": sorted(k for k in prov if not k.startswith("_")),
        "orientation_audit": {k: orient[k] for k in ("status", "excluded")},
        "eligibility_funnel": funnel,
        "verdicts": w15.verdicts(rows, now=now),
        "summary_eligible": ce.summarize(rows, w15.FORECASTERS),
        "calibration_eligible": ce.calibration(rows, w15.FORECASTERS) if rows else {},
        "descriptive_contrasts_NOT_VERDICT": w15.descriptive(rows),
        "eligible_games": [
            {
                k: r[k]
                for k in (
                    "game_id",
                    "date",
                    "tip",
                    "as_of",
                    "y_margin",
                    "n_train",
                    "stretch_s",
                    "hsd_c",
                )
            }  # fmt: skip
            for r in rows
        ],
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "wave15_results.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n")  # fmt: skip
    exp = None
    if a.exploratory:
        cut = w.parse_ts(EXPLORATORY_BEFORE)
        erows, efunnel = w15.build_rows(frozen, finals, pushed=None, select="exploratory", exploratory_before=cut)  # fmt: skip
        exp = {
            "label": "EXPLORATORY_HISTORICAL - development data, NOT evidence; never pooled with prospective rows",
            "records_before": EXPLORATORY_BEFORE,
            "funnel": efunnel,
            "n_dates": len({r["date"] for r in erows}),
            "summary": ce.summarize(erows, w15.FORECASTERS),
            "calibration": ce.calibration(erows, w15.FORECASTERS) if erows else {},
            "contrasts_90pct_date_clustered": w15.descriptive(erows),
            "last_fit": {"stretch_s": erows[-1]["stretch_s"], "hsd_c": erows[-1]["hsd_c"]}
            if erows
            else None,  # fmt: skip
        }
        (a.out / "wave15_exploratory_historical.json").write_text(json.dumps(exp, indent=1, sort_keys=True, default=str) + "\n")  # fmt: skip
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(render(res, exp))
    print("wave15", {k: v["status"] for k, v in res["verdicts"].items()}, funnel)


def _f(x: float) -> str:
    return f"{x:+.4f}"


def _summary_table(s: dict[str, dict[str, float]]) -> list[str]:
    out = ["| forecaster | n | margin MAE | margin bias | log loss | Brier | margin NLL | 80% cover | z-SD |",
           "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for k, v in s.items():
        out.append(f"| {k} | {v['n']:.0f} | {v['margin_mae']:.3f} | {v['margin_bias']:+.3f} | {v['logloss']:.4f} | "
                   f"{v['brier']:.4f} | {v['margin_nll']:.4f} | {v['coverage80']:.3f} | {v['z_sd']:.3f} |")  # fmt: skip
    return out


def render(r: dict[str, Any], exp: dict[str, Any] | None) -> str:
    L = ["# Wave 15 - margin calibration challengers (A1 margin stretch, A2 heteroscedastic SD)", "",
         "Generated by `scripts/research/prospective_wave15.py`; protocol `research/hypotheses/WAVE15.md`. "
         "RESEARCH_ONLY: nothing is promoted and no production model, default or prediction is changed.", "",
         "## Prospective (confirmatory) status", "",
         f"Window: record `as_of` >= {r['window']['prospective_from']}, tips on ET dates <= {r['window']['last_et_date']}; "
         f"single analysis at/after {r['window']['analysis_not_before']}. Analysis time of this file: {r['analysis_time']}.", "",
         "| test | status | games | dates |", "|---|---|---|---|"]  # fmt: skip
    for k, v in r["verdicts"].items():
        L.append(f"| {k} | **{v['status']}** | {v['n_games']} | {v['n_dates']} |")
    L += ["", f"Eligibility funnel: {r['eligibility_funnel']}", ""]
    if r["summary_eligible"]:
        L += _summary_table(r["summary_eligible"]) + [""]
    L += ["Before the registered analysis time the only status is COLLECTING; prospective numbers above are descriptive.", ""]  # fmt: skip
    if exp:
        L += ["## Exploratory historical development (NOT evidence)", "",
              f"{exp['label']}. Records with `as_of` before {exp['records_before']} (the Wave 14 boundary); "
              f"walk-forward fits; {exp['n_dates']} ET dates. Funnel: {exp['funnel']}.", ""]  # fmt: skip
        L += _summary_table(exp["summary"]) + [
            "",
            "| contrast | diff | 90% date-clustered interval |",
            "|---|---|---|",
        ]
        for k, v in exp["contrasts_90pct_date_clustered"].items():
            L.append(f"| {k} | {_f(v['diff'])} | [{_f(v['lo_guard'])}, {_f(v['hi_guard'])}] |")
        L += ["", f"Last walk-forward fit: {exp['last_fit']}", ""]
        for k, v in exp["calibration"].items():
            L.append(f"- {k}: |margin| bands {v['abs_margin_bands']}")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
