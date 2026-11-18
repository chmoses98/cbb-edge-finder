"""Possession challenger vs frozen production pure-0.2.0 (RESEARCH_ONLY).

Reproduce (data never committed; CBB_DATA_DIR points at a scratch lake):

    export CBB_DATA_DIR=/tmp/cbb_work/data OMP_NUM_THREADS=1
    # bronze: vault archives CBB/espn_team_box_schedules + espn_player_box_pbp_early_seasons
    # (schedules/team_box/player_box), plus free sportsdataverse ncaa_mbb_possessions /
    # ncaa_mbb_lineups 2017-2026; then silver build, stints, shot profile (see results md).
    python scripts/research/run_possession_challenger.py prod  --season 2026 --mode checkpoint
    python scripts/research/run_possession_challenger.py prod  --season 2025 --mode warmup
    python scripts/research/run_possession_challenger.py raw
    python scripts/research/run_possession_challenger.py freeze    # dev only -> frozen JSON
    python scripts/research/run_possession_challenger.py holdout   # scored once

Holdout = 2025-26 (season 2026, production reproduced walk-forward from its frozen
boundary-2025 checkpoint) + 2026-27 to date (season 2027, archived pre-tip production records).
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from cbb_edge.research import possession_challenger as pc

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "research" / "possession_challenger"
WORK = Path("/tmp/cbb_work/pc")
FROZEN = OUT / "frozen_params.json"
RESULTS = OUT / "results.json"
PARAMS = pc.Params(tau_days=120.0, lam_eff=400.0, rho_eff=0.95, lam_tempo=3.0)  # dev-tuned 2015-24
DEV_BLEND = [2024, 2025]  # production (warmup reconstruction) available, never holdout
HOLDOUT = [2026, 2027]


def _silver() -> tuple[pd.DataFrame, pd.DataFrame]:
    from cbb_edge.data.http import data_dir

    s = data_dir() / "silver"
    return pd.read_parquet(s / "games.parquet"), pd.read_parquet(s / "team_games.parquet")


def cmd_prod(season: int, mode: str) -> None:
    """Walk-forward production pure-0.2.0 forecasts for every game of ``season``."""
    from cbb_edge.app.prospective import apply_linear, feature_frame, load_model

    m = load_model("pure-0.2.0")
    df = feature_frame(m, season, pd.Timestamp(f"{season}-05-01T00:00:00Z"), reconstruction=mode)
    df["p_margin"] = apply_linear(df, m["margin"])
    df["p_total"] = apply_linear(df, m["total"])
    a, b = m["wp_logit"]
    df["p_wp"] = 1 / (1 + np.exp(-(a + b * df.p_margin)))
    WORK.mkdir(parents=True, exist_ok=True)
    df[["game_id", "season", "p_margin", "p_total", "p_wp"]].to_parquet(
        WORK / f"prod_{season}_{mode}.parquet"
    )


def archived_production(root: Path) -> pd.DataFrame:
    """Latest pre-tip pure-0.2.0 incumbent record per game from the projections archive."""
    rows = []
    for f in glob.glob(str(root / "projections" / "2027" / "*" / "*" / "*.json")):
        d = json.loads(Path(f).read_text())
        if d.get("model", {}).get("version") != "pure-0.2.0":
            continue
        pr, pp = d["projection"], d.get("prospective", {})
        rows.append(
            dict(
                game_id=d["game"]["espn_game_id"],
                as_of=pp.get("as_of"),
                start=d["game"]["start_time_utc"],
                p_margin=pr["margin"],
                p_total=pr["total"],
                p_wp=pr["home_win_prob"],
                home=d["home"]["team_id"],
            )
        )
    a = pd.DataFrame(rows)
    a["as_of"], a["start"] = pd.to_datetime(a.as_of, utc=True), pd.to_datetime(a.start, utc=True)
    return a[a.as_of < a.start].sort_values("as_of").groupby("game_id").tail(1)


def cmd_raw() -> None:
    g, tg = _silver()
    raw = pc.raw_walk_forward(g, tg, list(range(2006, 2028)), PARAMS)
    WORK.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(WORK / "raw.parquet")


def challenger(raw: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    f, _ = pc.forecasts(raw, seasons, PARAMS)
    return f


def blend(df: pd.DataFrame, fz: dict) -> pd.DataFrame:
    out = df.copy()
    wm, wt = fz["blend"]["w_margin"], fz["blend"]["w_total"]
    out["x_margin"] = (1 - wm) * out.p_margin + wm * out.c_margin
    out["x_total"] = (1 - wt) * out.p_total + wt * out.c_total
    a, b = fz["blend"]["wp_probit"]
    out["x_wp"] = np.clip(norm.cdf(a + b * out.x_margin), 1e-4, 1 - 1e-4)
    return out


def cmd_freeze() -> None:
    raw = pd.read_parquet(WORK / "raw.parquet")
    c = challenger(raw, DEV_BLEND)
    p = pd.concat([pd.read_parquet(WORK / f"prod_{s}_warmup.parquet") for s in DEV_BLEND])
    d = c.merge(p.drop(columns="season"), on="game_id")
    ym, yt = d.home_score - d.away_score, d.home_score + d.away_score
    # least-squares blend weight on dev only, clipped to [0, 1]
    wm = float(
        np.clip(
            np.dot(d.c_margin - d.p_margin, ym - d.p_margin)
            / np.sum((d.c_margin - d.p_margin) ** 2),
            0,
            1,
        )
    )
    wt = float(
        np.clip(
            np.dot(d.c_total - d.p_total, yt - d.p_total) / np.sum((d.c_total - d.p_total) ** 2),
            0,
            1,
        )
    )
    xm = (1 - wm) * d.p_margin + wm * d.c_margin
    from sklearn.linear_model import LogisticRegression

    lr = LogisticRegression(C=1e6).fit(xm.to_numpy()[:, None], (ym > 0).to_numpy())
    # convert logit fit to probit scale (a, b) via 1.702 approximation is avoided: fit probit directly
    from scipy.optimize import minimize

    y = (ym > 0).to_numpy(float)

    def nll(t: np.ndarray) -> float:
        q = np.clip(norm.cdf(t[0] + t[1] * xm.to_numpy()), 1e-9, 1 - 1e-9)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))

    ab = minimize(nll, np.array([0.0, 1 / 11.0]), method="Nelder-Mead").x
    fz = {
        "id": "poss-ch-v1",
        "status": "RESEARCH_ONLY",
        "frozen_before_holdout": True,
        "standalone_params": PARAMS.to_dict(),
        "standalone_tuning_seasons": "2015-2024 (calibration layer refit each season on the 6 prior seasons)",
        "blend": {
            "w_margin": wm,
            "w_total": wt,
            "wp_probit": [float(ab[0]), float(ab[1])],
            "fit_seasons": DEV_BLEND,
            "n_games": int(len(d)),
            "production_source": "pure-0.2.0 feature_frame(reconstruction='warmup')",
        },
        "logit_reference": [float(lr.intercept_[0]), float(lr.coef_[0][0])],
        "holdout": "season 2026 (checkpoint reproduction) + season 2027 to date (archived pre-tip records)",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(fz, indent=1) + "\n")
    print(json.dumps(fz, indent=1))


def metrics_frame(d: pd.DataFrame, pre: str) -> pd.DataFrame:
    ym, yt = d.home_score - d.away_score, d.home_score + d.away_score
    yw = (ym > 0).astype(float)
    q = d[f"{pre}_wp"].clip(1e-6, 1 - 1e-6)
    hp, ap = (
        (d[f"{pre}_total"] + d[f"{pre}_margin"]) / 2,
        (d[f"{pre}_total"] - d[f"{pre}_margin"]) / 2,
    )
    return pd.DataFrame(
        {
            "margin_mae": (d[f"{pre}_margin"] - ym).abs(),
            "total_mae": (d[f"{pre}_total"] - yt).abs(),
            "team_total_mae": ((hp - d.home_score).abs() + (ap - d.away_score).abs()) / 2,
            "brier": (q - yw) ** 2,
            "logloss": -(yw * np.log(q) + (1 - yw) * np.log(1 - q)),
        }
    )


def calib_slope(q: np.ndarray, y: np.ndarray) -> float:
    from sklearn.linear_model import LogisticRegression

    z = np.log(q / (1 - q))
    return float(LogisticRegression(C=1e6).fit(z[:, None], y).coef_[0][0])


def paired(d: pd.DataFrame, a: str, b: str, n_boot: int = 2000, seed: int = 7) -> dict:
    """Paired differences b - a per game; bootstrap resamples games (each game one cluster)."""
    ma, mb = metrics_frame(d, a), metrics_frame(d, b)
    diff = (mb - ma).to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (n_boot, len(d)))
    boots = np.stack([diff[i].mean(0) for i in idx])
    y = (d.home_score > d.away_score).to_numpy(float)
    out = {}
    for j, k in enumerate(ma.columns):
        lo, hi = np.percentile(boots[:, j], [2.5, 97.5])
        out[k] = {
            a: float(ma[k].mean()),
            b: float(mb[k].mean()),
            "diff": float(diff[:, j].mean()),
            "ci95": [float(lo), float(hi)],
        }
    out["calibration_slope"] = {
        a: calib_slope(d[f"{a}_wp"].clip(1e-6, 1 - 1e-6).to_numpy(), y),
        b: calib_slope(d[f"{b}_wp"].clip(1e-6, 1 - 1e-6).to_numpy(), y),
    }
    out["n"] = int(len(d))
    return out


def holdout_frame(archive_root: Path) -> pd.DataFrame:
    g, _ = _silver()
    raw = pd.read_parquet(WORK / "raw.parquet")
    c = challenger(raw, HOLDOUT)
    p26 = pd.read_parquet(WORK / "prod_2026_checkpoint.parquet").drop(columns="season")
    a27 = archived_production(archive_root)
    a27 = a27.merge(g[["game_id", "home_team_id"]], on="game_id")
    swap = a27.home != a27.home_team_id  # neutral-site orientation: flip to schedule order
    a27.loc[swap, "p_margin"] *= -1
    a27.loc[swap, "p_wp"] = 1 - a27.loc[swap, "p_wp"]
    p = pd.concat([p26, a27[["game_id", "p_margin", "p_total", "p_wp"]]])
    return c.merge(p, on="game_id")


def cmd_holdout(archive_root: Path) -> None:
    fz = json.loads(FROZEN.read_text())
    d = blend(holdout_frame(archive_root), fz)
    res = {"frozen": fz["id"], "holdout": fz["holdout"], "by_slice": {}}
    for name, m in {
        "all": d.season.isin(HOLDOUT),
        "2025-26": d.season == 2026,
        "2026-27_to_date": d.season == 2027,
    }.items():
        dd = d[m]
        res["by_slice"][name] = {
            "blend_vs_production": paired(dd, "p", "x"),
            "standalone_vs_production": paired(dd, "p", "c"),
        }
    RESULTS.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res["by_slice"]["all"], indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prod", "raw", "freeze", "holdout"])
    ap.add_argument("--season", type=int)
    ap.add_argument("--mode", default="checkpoint")
    ap.add_argument("--archive", default="/tmp/cbb_work/archive")
    a = ap.parse_args()
    if a.cmd == "prod":
        cmd_prod(a.season, a.mode)
    elif a.cmd == "raw":
        cmd_raw()
    elif a.cmd == "freeze":
        cmd_freeze()
    else:
        cmd_holdout(Path(a.archive))


if __name__ == "__main__":
    main()
