"""Live / research parity, layer by layer (Wave 5, Priority 0).

For one game day D of a completed season, ``as_of`` = D's first tip − 1 s (so research
and live use exactly the same information set), and for each frozen model:

1. LIVE features   ``prospective.feature_frame(model, season, as_of)``;
2. RESEARCH features from the research pipeline that produced the artifact's training
   data (run_wave2 / run_wave3 / run_wave4 frames);
3. per-feature differences for every final model input (margin + total specs);
4. margins: artifact applied to LIVE features vs artifact applied to RESEARCH features
   (= pure reconstruction difference) vs the research walk-forward OOS margin
   (differs legitimately: expanding-window coefficients, not the frozen ones).

``team_hca`` is a season-indexed input (shrunk B3 home residuals of the previous three
seasons); the artifact stores it for its target season only, so for a past test season
the research value is injected into the LIVE frame as well (documented).

    python scripts/research/parity_diagnostics.py [day] [version ...]   # day default 2025-12-06
Output: research/wave5/parity_<version>_<day>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.app import prospective

sys.path.insert(0, str(Path(__file__).parent))
import run_wave2 as w2  # noqa: E402
import run_wave3 as w3  # noqa: E402
import run_wave4 as w4  # noqa: E402

OUT = Path("research/wave5")


def research_frame(version: str, ctx: w3.Ctx) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(df, X) of the research pipeline whose features trained ``version``."""
    from cbb_edge.research import blocks

    if version == "pure-0.2.0":
        st = pd.read_parquet(w2.WORK / "states_shot.parquet")
        pf = pd.read_parquet(w2.WORK / "player_features.parquet")
        df = w3.frame(ctx, st, pf)
        X = w4.base_X(df, [])
        X = X.drop(columns=[c for c in blocks.mismatch_block(df).columns if c in X])
        return df, X
    if version == "pure-0.3.0":
        df = w3.frame(
            ctx,
            pd.read_parquet(w3.WORK / "states_b15.parquet"),
            pd.read_parquet(w3.WORK / "pf_b12.parquet"),
        )
        return df, w4.base_X(df, [])
    if version == "pure-0.4.0":
        df = w3.frame(
            ctx,
            pd.read_parquet(w4.WORK / "states_b16b.parquet"),
            pd.read_parquet(w4.WORK / "pf_b19h.parquet"),
        )
        sf = pd.read_parquet(w4.WORK / "shooting_features.parquet")
        return df, w4.base_X(df, [blocks.shooting_block(df, sf)])
    if version == "pure-0.5.0":
        import run_wave5 as w5

        df = w5.b20_frame(ctx)
        comp = json.loads((w5.OUT / "b25_components.json").read_text())["components"]
        return df, w5.b25_X(ctx, df, comp)
    raise SystemExit(version)


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else "2025-12-06"
    versions = sys.argv[2:] or ["pure-0.2.0", "pure-0.3.0", "pure-0.4.0"]
    ctx = w3.Ctx()
    games = ctx.games
    gd = games[games["game_date_et"].astype(str) == day]
    as_of = pd.Timestamp(gd["start_time_utc"].min()) - pd.Timedelta(seconds=1)
    season = int(gd["season"].iloc[0])
    OUT.mkdir(parents=True, exist_ok=True)
    for v in versions:
        model = prospective.load_model(v)
        live = prospective.feature_frame(model, season, as_of)
        live = live[live["game_id"].isin(gd["game_id"])].set_index("game_id")
        df, X = research_frame(v, ctx)
        X.index = df["game_id"].to_numpy()
        ids = live.index.intersection(X.index)
        feats = list(dict.fromkeys(model["margin"]["features"] + model["total"]["features"]))
        R = X.loc[ids]
        L = live.loc[ids].copy()
        if "team_hca" in feats:
            L["team_hca"] = R["team_hca"]  # season-indexed input, see module docstring
        rows = []
        for f in feats:
            a = pd.to_numeric(L[f], errors="coerce").to_numpy(float)
            b = pd.to_numeric(R[f], errors="coerce").to_numpy(float)
            dd = np.abs(a - b)
            rows.append(
                {
                    "feature": f,
                    "max_abs": float(np.nanmax(dd)) if len(dd) else 0.0,
                    "mean_abs": float(np.nanmean(dd)) if len(dd) else 0.0,
                    "nan_live": int(np.isnan(a).sum()),
                    "nan_research": int(np.isnan(b).sum()),
                }
            )
        ft = pd.DataFrame(rows).sort_values("mean_abs", ascending=False)
        m_live = prospective.apply_linear(L, model["margin"])
        m_res = prospective.apply_linear(R, model["margin"])
        t_live = prospective.apply_linear(L, model["total"])
        t_res = prospective.apply_linear(R, model["total"])
        rep = {
            "version": v,
            "day": day,
            "as_of": str(as_of),
            "n_games": len(ids),
            "margin_live_vs_research_features": {
                "mean_abs": float(np.mean(np.abs(m_live - m_res))),
                "max_abs": float(np.max(np.abs(m_live - m_res))),
                "corr": float(np.corrcoef(m_live, m_res)[0, 1]),
            },
            "total_live_vs_research_features": {
                "mean_abs": float(np.mean(np.abs(t_live - t_res))),
                "max_abs": float(np.max(np.abs(t_live - t_res))),
            },
            "worst_features": ft.head(25).to_dict("records"),
        }
        (OUT / f"parity_{v}_{day}.json").write_text(json.dumps(rep, indent=1, default=float))
        print(json.dumps({k: rep[k] for k in rep if k != "worst_features"}, default=float))
        print(ft.head(15).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
