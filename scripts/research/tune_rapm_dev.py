"""Tune RAPM hyperparameters on DEV seasons only (2012-2014; 2011 seeds priors).

Objective: DEV margin RMSE of the player-only projection
    margin = poss_hat/100 * [(off_h + def_a) - (off_a + def_h) + 2*eta*L]   (def = pts allowed)
with poss_hat from the (walk-forward) team engine. Validation/holdout untouched.
Output: research/wave2/rapm_dev_tuning.csv
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.model.arms import attach_games, matchup_features
from cbb_edge.players.rapm import RapmConfig, player_team_features

OUT = Path("research/wave2/rapm_dev_tuning.csv")


def main() -> None:
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min"],
    )
    st = pd.read_parquet(data_dir() / "research" / "states_adjusted.parquet")
    base = attach_games(st[st.season.between(2012, 2014)], g)
    base["poss_hat"] = matchup_features(base)["poss"]
    rows = []
    for lam, carry, new in itertools.product(
        (800.0, 2000.0, 5000.0), (0.5, 0.8), ((-0.8, 0.4), (0.0, 0.0))
    ):
        cfg = RapmConfig(lam_o=lam, lam_d=lam, carry=carry, new_o=new[0], new_d=new[1])
        f = player_team_features([2011, 2012, 2013, 2014], g, pg, cfg, verbose=False)
        d = base.merge(f, on=["game_id", "season"], how="inner")
        d = d[d.margin.notna()]
        # d = points ALLOWED per 100 (positive = bad defense)
        m = (
            d.poss_hat
            / 100
            * ((d.h_p_off + d.a_p_def) - (d.a_p_off + d.h_p_def) + 2 * d.rapm_eta * d.L)
        )
        e = m - d.margin
        rows.append(
            {
                "lam": lam,
                "carry": carry,
                "new_o": new[0],
                "new_d": new[1],
                "rmse": float(np.sqrt((e**2).mean())),
                "mae": float(e.abs().mean()),
                "bias": float(e.mean()),
                "n": len(d),
            }
        )
        print(rows[-1], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values("rmse").to_csv(OUT, index=False)


if __name__ == "__main__":
    main()
