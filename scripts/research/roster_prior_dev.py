"""Estimate roster-continuity prior coefficients on DEV seasons only (2008-2014).

Model (per stat, team i, season s):
    a_s,i = (c0 + c1 * share_s,i) * a_{s-1},i + e
where a = full-season opponent-adjusted rating (weak prior) and share = fraction of the
team's previous-season minutes played by players who appear for it in season s.
Writes research/baseline/roster_prior_dev.json. Validation/holdout seasons untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.backtest.walkforward import d1_rows, returning_share
from cbb_edge.data.ids.teams import _registry
from cbb_edge.ratings.adjusted import STATS, fit_stat

DEV = list(range(2007, 2015))
OUT = Path("research/baseline/roster_prior_dev.json")


def season_ratings(tg: pd.DataFrame, team_ids: list[str]) -> dict[str, np.ndarray]:
    idx = {t: i for i, t in enumerate(team_ids)}
    n = len(team_ids)
    out = {}
    for name in ("eff", "efg", "to", "orb", "ftr", "tempo"):
        spec = STATS[name]
        mu0 = float(np.nanmean(tg[spec.value_col]) * spec.scale)
        f = fit_stat(tg, spec, idx, np.zeros(n), np.zeros(n), 30.0, mu0, 0.0)
        out[name + "_off"] = f.off
        out[name + "_def"] = f.deff
    return out


def main() -> None:
    tg = pd.read_parquet("data/silver/team_games.parquet")
    pg = pd.read_parquet(
        "data/silver/player_games.parquet", columns=["season", "team_id", "player_id", "min"]
    )
    pg = pg[pg.team_id.notna() & pg["min"].fillna(0).gt(0)]
    team_ids = sorted(_registry().team_id)
    rat = {s: season_ratings(d1_rows(tg[tg.season == s]), team_ids) for s in [2006, *DEV]}
    rows = []
    for s in DEV:
        share = returning_share(pg[pg.season == s - 1], pg[pg.season == s], team_ids)
        for k in rat[s]:
            cur, prev = rat[s][k], rat[s - 1][k]
            ok = np.isfinite(share) & (np.abs(prev) > 0) & (np.abs(cur) > 0)
            for c, p, sh in zip(cur[ok], prev[ok], share[ok], strict=True):
                rows.append({"season": s, "stat": k, "cur": c, "prev": p, "share": sh})
    d = pd.DataFrame(rows)
    res = {}
    for k, g in d.groupby("stat"):
        X = np.column_stack([g.prev, g.prev * g.share])
        c, *_ = np.linalg.lstsq(X, g.cur, rcond=None)
        simple = float(np.linalg.lstsq(g.prev.to_numpy()[:, None], g.cur, rcond=None)[0][0])
        res[k] = {
            "c0": float(c[0]),
            "c1": float(c[1]),
            "simple_rho": simple,
            "n": len(g),
            "mean_share": float(g.share.mean()),
        }
    eff = [res["eff_off"], res["eff_def"]]
    res["pooled_eff"] = {
        "c0": float(np.mean([e["c0"] for e in eff])),
        "c1": float(np.mean([e["c1"] for e in eff])),
    }
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
