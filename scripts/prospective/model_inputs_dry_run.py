"""Real-data dry run + point-in-time verification of the ``model_inputs`` export (read-only).

    CBB_DATA_DIR=<lake built like refresh_and_project.py> python scripts/prospective/model_inputs_dry_run.py \
        --as-of 2026-11-05T23:06:44.762463Z --version pure-0.2.0 --out research/wave13/model_inputs_dry_run.json

Checks, all against the PRODUCTION projection code on a locally rebuilt free-input lake:
  1. every exported games/possessions-seen value equals an independent recomputation from the raw
     silver team-games available before ``as_of``;
  2. the exported pace / efficiency noise equals an independent (loop) recomputation;
  3. the exported efficiency / tempo equal the same run's ``ratings`` block;
  4. FUTURE-ROW PERTURBATION: every team-game row with ``available_at >= as_of`` is scaled
     (possessions x1.6, ppp x0.5, box counts x1.6) in a copy of the lake; the whole ``model_inputs``
     block AND the projection must be bit-identical (nothing after ``as_of`` may leak in).
Nothing is written to an archive; the perturbed lake is a temp directory of symlinks.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd


def project(version: str, asof: pd.Timestamp) -> list[dict]:
    from cbb_edge.app import prospective as P

    return P.project_window(2027, asof, 30.0, P.load_model(version))


def independent_checks(recs: list[dict], tg: pd.DataFrame, asof: pd.Timestamp) -> dict:
    cur = tg[(tg.season == 2027) & (tg.available_at < asof) & tg.team_is_d1 & tg.opp_is_d1
             & tg.team_id.notna() & tg.opp_id.notna()]  # fmt: skip
    seen = cur.groupby("team_id").agg(n=("game_id", "nunique"), poss=("poss", "sum"))
    bad = []
    for r in recs:
        for side in ("home", "away"):
            tid, mi = r[side]["team_id"], r["model_inputs"][side]
            n, p = int(seen.n.get(tid, 0)), float(seen.poss.get(tid, 0.0))
            if mi["games_seen"] != n or abs((mi["possessions_seen"] or 0) - p) > 1e-6:
                bad.append([r["game"]["espn_game_id"], side, tid])
    allc = tg[(tg.season == 2027) & (tg.available_at < asof)].dropna(
        subset=["tempo", "ppp", "poss", "team_id"]
    )
    by: dict[str, list] = {}
    for t, tem, ppp, poss in zip(allc.team_id, allc.tempo, allc.ppp, allc.poss, strict=True):
        by.setdefault(t, []).append((tem, ppp * 100, poss))
    ss_t = ss_e = dof = 0.0
    for rows in by.values():
        if len(rows) < 2:
            continue
        mt, me = sum(x[0] for x in rows) / len(rows), sum(x[1] for x in rows) / len(rows)
        for tem, e, poss in rows:
            ss_t += (tem - mt) ** 2
            ss_e += ((e - me) * math.sqrt(poss)) ** 2
        dof += len(rows) - 1
    nz = recs[0]["model_inputs"]["noise"]
    ind = {"tempo_game_sd": math.sqrt(ss_t / dof), "eff_unit_sd": math.sqrt(ss_e / dof)}
    same_run = 0.0
    for r in recs:
        for side in ("home", "away"):
            mi, rt = r["model_inputs"][side], r["ratings"][side]
            same_run = max(same_run, abs(mi["efficiency"]["adj_off"] - rt["adj_off"]),
                           abs(mi["efficiency"]["adj_def"] - rt["adj_def"]),
                           abs(mi["expected_tempo"] - rt["adj_tempo"]))  # fmt: skip
    return {
        "records": len(recs),
        "seen_mismatches_vs_independent": bad,
        "noise_export": {
            k: nz.get(k) for k in ("tempo_game_sd", "eff_unit_sd", "n_rows", "n_teams")
        },
        "noise_independent": ind,
        "noise_max_abs_diff": max(
            abs(nz["tempo_game_sd"] - ind["tempo_game_sd"]),
            abs(nz["eff_unit_sd"] - ind["eff_unit_sd"]),
        ),  # fmt: skip
        "same_run_ratings_max_abs_diff": same_run,
    }


def perturbed_lake(lake: Path, asof: pd.Timestamp) -> tuple[Path, int]:
    tmp = Path(tempfile.mkdtemp(prefix="lake_pert_"))
    for d in ("_cost", "bronze", "ids"):
        if (lake / d).exists():
            (tmp / d).symlink_to(lake / d)
    (tmp / "silver").mkdir()
    for f in (lake / "silver").iterdir():
        if f.name != "team_games.parquet":
            (tmp / "silver" / f.name).symlink_to(f)
    tg = pd.read_parquet(lake / "silver" / "team_games.parquet")
    fut = tg.available_at >= asof
    for c in (
        "poss",
        "tempo",
        "pts",
        "opp_pts",
        "fga",
        "opp_fga",
        "tov",
        "opp_tov",
        "fta",
        "opp_fta",
    ):
        tg.loc[fut, c] = tg.loc[fut, c] * 1.6
    for c in ("ppp", "opp_ppp"):
        tg.loc[fut, c] = tg.loc[fut, c] * 0.5
    tg.to_parquet(tmp / "silver" / "team_games.parquet", index=False)
    return tmp, int(fut.sum())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--version", default="pure-0.2.0")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--skip-perturbation", action="store_true")
    a = ap.parse_args()
    asof = pd.Timestamp(a.as_of)
    lake = Path(os.environ["CBB_DATA_DIR"])
    recs = project(a.version, asof)
    tg = pd.read_parquet(lake / "silver" / "team_games.parquet")
    res: dict = {"as_of": asof.isoformat(), "version": a.version,
                 "checks": independent_checks(recs, tg, asof)}  # fmt: skip
    if not a.skip_perturbation:
        tmp, n_fut = perturbed_lake(lake, asof)
        try:
            os.environ["CBB_DATA_DIR"] = str(tmp)
            pert = project(a.version, asof)
        finally:
            os.environ["CBB_DATA_DIR"] = str(lake)
            shutil.rmtree(tmp, ignore_errors=True)
        pm = {r["game"]["espn_game_id"]: r for r in pert}
        res["future_row_perturbation"] = {
            "future_rows_perturbed": n_fut,
            "records": len(recs),
            "model_inputs_changed": sum(r["model_inputs"] != pm[r["game"]["espn_game_id"]]["model_inputs"] for r in recs),
            "projections_changed": sum(r["projection"] != pm[r["game"]["espn_game_id"]]["projection"] for r in recs),
        }  # fmt: skip
    ck = res["checks"]
    res["pass"] = (not ck["seen_mismatches_vs_independent"] and ck["noise_max_abs_diff"] < 1e-6
                   and ck["same_run_ratings_max_abs_diff"] < 1e-9
                   and (a.skip_perturbation or (res["future_row_perturbation"]["model_inputs_changed"] == 0
                                                and res["future_row_perturbation"]["projections_changed"] == 0)))  # fmt: skip
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    print(json.dumps(res, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
