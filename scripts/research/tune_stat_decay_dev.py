"""Per-component prior decay (stabilization) on DEV seasons only.

For each opponent-adjusted stat separately, vary its prior strength λ (in observation
units; the shared PR #1 scale is multiplier 1.0) and measure the ONE-STEP-AHEAD error of
that component: predicted home-offense value (mu + off_home + def_away + eta*L) vs the
actual team-game value, weighted by the stat's observation weight. DEV 2008-2014
(2006-2007 warm-up). Also reports error by min(games seen) so the decay curve is
visible. Output: research/wave3/stat_decay_dev.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.backtest.config import tuned_config
from cbb_edge.backtest.walkforward import run
from cbb_edge.features.shot_profile import enrich_team_games
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.ratings.adjusted import BASE_STATS, SHOT_STATS, STATS

DEV = list(range(2006, 2015))
OUT = Path("research/wave3/stat_decay_dev.csv")
MULTS = (0.25, 0.5, 1.0, 2.0, 4.0)


def main() -> None:
    games, tg = load_pure_silver()
    tg = enrich_team_games(tg)
    home = tg.merge(games[["game_id", "home_espn_id"]], on="game_id")
    home = home[home["team_espn_id"] == home["home_espn_id"]].drop_duplicates("game_id")
    rows = []
    base = tuned_config()
    for stat in BASE_STATS + SHOT_STATS:
        spec = STATS[stat]
        for mult in MULTS:
            lam = dict(base.lam)
            lam[stat] = base.lam[stat] * mult
            cfg = tuned_config(stats=(stat,), lam=lam)
            st = run(games, tg, DEV, cfg, verbose=False)
            st = st[st["season"] >= 2008].merge(games[["game_id", "neutral_site"]], on="game_id")
            L = (~st["neutral_site"].astype(bool)).astype(float)
            if spec.pace:
                pred = st[f"mu_{stat}"] + st[f"h_off_{stat}"] + st[f"a_off_{stat}"]
            else:
                pred = (
                    st[f"mu_{stat}"]
                    + st[f"h_off_{stat}"]
                    + st[f"a_def_{stat}"]
                    + st[f"eta_{stat}"] * L
                )
            d = st.assign(pred=pred).merge(home, on="game_id")
            y = d[spec.value_col].astype(float) * spec.scale
            w = (
                np.ones(len(d))
                if spec.weight_col is None
                else d[spec.weight_col].astype(float).to_numpy()
            )
            ok = np.isfinite(y) & np.isfinite(w) & (w > 0) & d["pred"].notna()
            e = (d["pred"] - y)[ok]
            ww = w[ok.to_numpy()]
            mg = np.minimum(d["h_games_seen"], d["a_games_seen"])[ok]
            rec = {
                "stat": stat,
                "mult": mult,
                "lam": lam[stat],
                "wrmse": float(np.sqrt(np.average(e**2, weights=ww))),
                "n": int(ok.sum()),
            }
            for lo, hi in ((0, 1), (1, 4), (4, 8), (8, 15), (15, 99)):
                m = ((mg >= lo) & (mg < hi)).to_numpy()
                if m.any():
                    rec[f"wrmse_g{lo}_{hi}"] = float(np.sqrt(np.average(e[m] ** 2, weights=ww[m])))
            rows.append(rec)
            print(rec, flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)


if __name__ == "__main__":
    main()
