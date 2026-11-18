"""Player-aggregate roster overlay ``pro-ch-v1`` on production pure-0.2.0 (RESEARCH_ONLY).

Steps (after the data steps of run_possession_challenger.py, incl. ``prod`` warmup 2022-2025):

    python scripts/research/run_player_roster_overlay.py build     # player states, rosters, aggregates
    python scripts/research/run_player_roster_overlay.py select    # dev: fit 2022-24, validate 2025
    python scripts/research/run_player_roster_overlay.py freeze    # refit 2022-25 -> frozen JSON
    python scripts/research/run_player_roster_overlay.py holdout   # scored once (same 6,390 games)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.research import player_roster_overlay as po

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_possession_challenger as rpc  # noqa: E402

OUT = rpc.REPO / "research" / "player_roster_overlay"
WORK = Path("/tmp/cbb_work/pro")
FROZEN = OUT / "frozen_params.json"
TRAIN, VALID = [2022, 2023, 2024], [2025]
LAMS = (0.01, 0.1, 0.3, 1.0)
WP_LOGIT = json.loads((rpc.REPO / "models" / "pure" / "pure-0.2.0.json").read_text())["wp_logit"]


def cmd_build() -> None:
    g, _ = rpc._silver()
    from cbb_edge.data.http import data_dir

    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    d = po._clean(pg[pg.season >= 2012])
    st = po.player_state(d)
    ros = po.team_rosters(d, st, po.pedigree(d, g), list(range(2021, 2028)))
    WORK.mkdir(parents=True, exist_ok=True)
    po.game_frame(po.aggregates(ros), g).to_parquet(WORK / "gf.parquet")


def dev_frame() -> pd.DataFrame:
    gf = pd.read_parquet(WORK / "gf.parquet")
    p = pd.concat(
        [
            pd.read_parquet(rpc.WORK / f"prod_{s}_warmup.parquet").drop(columns="season")
            for s in TRAIN + VALID
        ]
    )
    return gf.merge(p, on="game_id")


def fit(d: pd.DataFrame, lam: float) -> dict:
    ym = (d.home_score - d.away_score - d.p_margin).to_numpy(float)
    yt = (d.home_score + d.away_score - d.p_total).to_numpy(float)
    models = {}
    for b in ("0-3", "4-10", "11+"):
        m = (d.bucket == b).to_numpy()
        models[b] = {
            "margin": po.fit_ridge(d.loc[m, list(po.D_COLS)].to_numpy(float), ym[m], lam),
            "total": po.fit_ridge(d.loc[m, list(po.S_COLS)].to_numpy(float), yt[m], lam),
            "n": int(m.sum()),
        }
    return models


def apply(d: pd.DataFrame, models: dict) -> pd.DataFrame:
    out = d.copy()
    out["x_margin"], out["x_total"] = out.p_margin.astype(float), out.p_total.astype(float)
    for b, mm in models.items():
        m = (out.bucket == b).to_numpy()
        if m.any():
            out.loc[m, "x_margin"] += po.predict(
                mm["margin"], out.loc[m, list(po.D_COLS)].to_numpy(float)
            )
            out.loc[m, "x_total"] += po.predict(
                mm["total"], out.loc[m, list(po.S_COLS)].to_numpy(float)
            )
    a, b = WP_LOGIT
    out["x_wp"] = 1 / (1 + np.exp(-(a + b * out.x_margin)))
    return out


def cmd_select() -> None:
    d = dev_frame()
    tr, va = d[d.season.isin(TRAIN)], d[d.season.isin(VALID)]
    rows = []
    for lam in LAMS:
        x = apply(va, fit(tr, lam))
        for b in ("0-3", "4-10", "11+", "all"):
            s = x if b == "all" else x[x.bucket == b]
            mf_p, mf_x = rpc.metrics_frame(s, "p"), rpc.metrics_frame(s, "x")
            rows.append(
                {
                    "lam": lam,
                    "bucket": b,
                    "n": len(s),
                    **(mf_x.mean() - mf_p.mean()).round(4).to_dict(),
                }
            )
    print(pd.DataFrame(rows).to_string())


def cmd_freeze(lam: float) -> None:
    d = dev_frame()
    models = fit(d[d.season.isin(TRAIN + VALID)], lam)
    fz = {
        "id": "pro-ch-v1",
        "status": "RESEARCH_ONLY",
        "frozen_before_holdout": True,
        "lam": lam,
        "selected_on": {"train": TRAIN, "validate": VALID},
        "fit_seasons": TRAIN + VALID,
        "profile": {
            "hl_rate_games": po.HL_RATE,
            "hl_minutes_games": po.HL_MIN,
            "prior_minutes": po.PRIOR_MIN,
        },
        "features_margin": list(po.D_COLS),
        "features_total": list(po.S_COLS),
        "wp_link": "production pure-0.2.0 wp_logit on overlaid margin",
        "game0": "ORACLE roster (players listed in the game's box; only earlier history used)",
        "models": models,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(fz, indent=1) + "\n")
    print({b: m["n"] for b, m in models.items()})


def cmd_holdout(archive_root: Path) -> None:
    fz = json.loads(FROZEN.read_text())
    gf = pd.read_parquet(WORK / "gf.parquet")
    h = rpc.holdout_frame(archive_root)[["game_id", "p_margin", "p_total", "p_wp"]]
    d = apply(gf.merge(h, on="game_id"), fz["models"])
    res = {"frozen": fz["id"], "n_total": int(len(d)), "slices": {}}
    for name, m in {
        "all": d.season > 0,
        "k0-3": d.bucket == "0-3",
        "k0_oracle_roster": d.kmin == 0,
        "k1-3_pregame_safe": d.kmin.between(1, 3),
        "k4-10": d.bucket == "4-10",
        "k11+": d.bucket == "11+",
        "2025-26": d.season == 2026,
        "2026-27_to_date": d.season == 2027,
    }.items():
        res["slices"][name] = rpc.paired(d[m], "p", "x")
    (OUT / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    for k, v in res["slices"].items():
        print(
            k,
            v["n"],
            {
                m: (round(v[m]["diff"], 4), [round(c, 4) for c in v[m]["ci95"]])
                for m in ("margin_mae", "total_mae", "brier", "logloss")
            },
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "select", "freeze", "holdout"])
    ap.add_argument("--lam", type=float, default=0.01)
    ap.add_argument("--archive", default="/tmp/cbb_work/archive")
    a = ap.parse_args()
    {"build": cmd_build, "select": cmd_select}.get(a.cmd, lambda: None)()
    if a.cmd == "freeze":
        cmd_freeze(a.lam)
    elif a.cmd == "holdout":
        cmd_holdout(Path(a.archive))


if __name__ == "__main__":
    main()
