"""Coefficient part of the live/research gap (Wave 5, Priority 0).

With reconstruction now exact (parity_diagnostics.py), the remaining difference between a
live projection and the research walk-forward OOS prediction of a past game is purely the
coefficients: the frozen artifact was fitted on 2012..2026 (its target season is 2027),
the OOS stack for season s on 2012..s-1. For s = 2027 these are the same fit. This script
applies each artifact to the research features of 2025-26 and compares with the OOS
predictions of the same arm. Output: research/wave5/parity_coefficients.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.app import prospective

sys.path.insert(0, str(Path(__file__).parent))
import parity_diagnostics as pdg  # noqa: E402
import run_wave3 as w3  # noqa: E402
import run_wave4 as w4  # noqa: E402

ARM = {"pure-0.3.0": "B15", "pure-0.4.0": "B20"}


def main() -> None:
    ctx = w3.Ctx()
    pp = pd.read_parquet(w4.WORK / "pure_predictions.parquet").set_index("game_id")
    out = {}
    for v, arm in ARM.items():
        model = prospective.load_model(v)
        df, X = pdg.research_frame(v, ctx)
        X.index = df["game_id"].to_numpy()
        ids = X.index[(df["season"] == 2026).to_numpy()].intersection(pp.index)
        m_art = prospective.apply_linear(X.loc[ids], model["margin"])
        m_oos = pp.loc[ids, f"{arm}_margin"].to_numpy()
        d = m_art - m_oos
        out[v] = {
            "n_games": len(ids),
            "artifact_minus_oos_mean_abs": float(np.mean(np.abs(d))),
            "artifact_minus_oos_max_abs": float(np.max(np.abs(d))),
            "artifact_minus_oos_mean": float(np.mean(d)),
            "corr": float(np.corrcoef(m_art, m_oos)[0, 1]),
            "note": "coefficients only: artifact trained 2012-2026, OOS stack 2012-2025",
        }
        print(v, out[v], flush=True)
    Path("research/wave5/parity_coefficients.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
