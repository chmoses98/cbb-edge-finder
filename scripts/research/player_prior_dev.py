"""DEV-only comparison of player-prior variants (B11 transfer translation, B12 box prior).

Runs the walk-forward RAPM team features for 2011-2014 with each prior provider variant
and scores the player-derived matchup margin on DEV games 2013-2014 (the first seasons
with an expanding-window prior fit). Score: RMSE of an OLS of actual margin on
[p_margin, L] fitted on the same DEV games (2 parameters; identical for all variants),
overall and for games where either team has played <= 5 games.

Output: research/wave3/player_prior_dev.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players import box_prior, team_prior
from cbb_edge.players.rapm import player_team_features

sys.path.insert(0, str(Path(__file__).parent))
from run_wave2 import rapm_cfg  # noqa: E402

OUT = Path("research/wave3/player_prior_dev.csv")
VARIANTS = {
    "carry_0.2.0": None,
    "B11_translate": dict(kind="rapm", box_update=False, translate=True),
    "B12_box_only": dict(kind="box", box_update=True, translate=True),
    "B12_box_rapm": dict(kind="both", box_update=True, translate=True),
    "B12_box_rapm_noupdate": dict(kind="both", box_update=False, translate=True),
    # post-hoc (after the four above): RAPM start prior + in-season box update
    "B12_rapm_boxupdate": dict(kind="rapm", box_update=True, translate=True),
}


def score(pf: pd.DataFrame, games: pd.DataFrame, states: pd.DataFrame) -> dict[str, float]:
    d = pf[pf["season"].isin([2013, 2014])].merge(
        games[["game_id", "home_score", "away_score", "neutral_site"]], on="game_id"
    )
    d = d.merge(states[["game_id", "mu_tempo", "h_off_tempo", "a_off_tempo"]], on="game_id")
    poss = d["mu_tempo"] + d["h_off_tempo"] + d["a_off_tempo"]
    pm = poss / 100 * ((d["h_p_off"] + d["a_p_def"]) - (d["a_p_off"] + d["h_p_def"]))
    L = (~d["neutral_site"].astype(bool)).astype(float)
    y = (d["home_score"] - d["away_score"]).astype(float)
    ok = pm.notna() & y.notna()
    X = np.column_stack([np.ones(ok.sum()), pm[ok], L[ok]])
    b = np.linalg.lstsq(X, y[ok], rcond=None)[0]
    e = y[ok] - X @ b
    mg = np.minimum(d["h_games_seen_p"], d["a_games_seen_p"])[ok]
    return {
        "n": int(ok.sum()),
        "rmse": float(np.sqrt(np.mean(e**2))),
        "rmse_g0_5": float(np.sqrt(np.mean(e[mg <= 5] ** 2))),
        "rmse_g6p": float(np.sqrt(np.mean(e[mg > 5] ** 2))),
        "slope": float(b[1]),
    }


def main() -> None:
    games, _ = load_pure_silver()
    states = pd.read_parquet(data_dir() / "research" / "wave2" / "states_shot.parquet")
    fin = team_prior.season_final_ratings(states, games)
    fin["net"] = fin["o"] - fin["d"]
    ps = pd.read_parquet(data_dir() / "silver" / "players" / "player_seasons.parquet")
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    pg_min = pg[["season", "game_id", "team_id", "player_id", "min"]]
    rc = rapm_cfg()
    only = sys.argv[1:] or list(VARIANTS)
    rows = []
    for name in only:
        kw = VARIANTS[name]
        prov = None if kw is None else box_prior.PlayerPriorProvider(ps, pg, fin, **kw)
        pf = player_team_features(
            [2011, 2012, 2013, 2014], games, pg_min, rc, verbose=False, prior_provider=prov
        )
        rec = {"variant": name, **score(pf, games, states)}
        print(rec, flush=True)
        rows.append(rec)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows)
    if OUT.exists() and len(only) < len(VARIANTS):
        out = pd.concat([pd.read_csv(OUT), out]).drop_duplicates("variant", keep="last")
    out.to_csv(OUT, index=False)


if __name__ == "__main__":
    main()
