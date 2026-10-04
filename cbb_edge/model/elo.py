"""Points-based Elo: a dynamic, opponent-aware benchmark with no box-score inputs.

Rating R is in points. Pregame expected home margin = R_h - R_a + H * L. After each
game day, R_h += k_eff * (clip(margin) - expected) and R_a -= the same, with
k_eff = k / (1 + games_played / g_half) (fast early, slower later). Between seasons
ratings are regressed: R <- carry * R. Updates are applied only after all of a day's
games are projected (same information discipline as the walk-forward engine).
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd


def elo_projections(
    games: pd.DataFrame,
    seasons: list[int],
    *,
    k: float = 0.22,
    g_half: float = 12.0,
    home: float = 3.2,
    carry: float = 0.72,
    cap: float = 25.0,
) -> pd.DataFrame:
    g = games[
        games.season.isin(seasons)
        & games.home_team_id.notna()
        & games.away_team_id.notna()
        & games.home_is_d1
        & games.away_is_d1
        & ~games.status.isin(["STATUS_CANCELED", "STATUS_POSTPONED"])
    ]
    g = g.sort_values("start_time_utc")
    R: dict[str, float] = defaultdict(float)
    n: dict[str, int] = defaultdict(int)
    out = []
    prev_season = None
    for (season, _day), gd in g.groupby(["season", "game_date_et"], sort=True):
        if prev_season is not None and season != prev_season:
            for t in list(R):
                R[t] *= carry
                n[t] = 0
        prev_season = season
        L = (~gd.neutral_site.astype(bool)).astype(float).to_numpy()
        h, a = gd.home_team_id.to_numpy(), gd.away_team_id.to_numpy()
        exp = np.array([R[x] - R[y] for x, y in zip(h, a, strict=True)]) + home * L
        out.append(pd.DataFrame({"game_id": gd.game_id.to_numpy(), "elo_margin": exp}))
        done = gd.completed.to_numpy() & gd.home_score.notna().to_numpy()
        for i in np.flatnonzero(done):
            m = float(gd.home_score.iloc[i] - gd.away_score.iloc[i])
            err = float(np.clip(m, -cap, cap) - exp[i])
            for t, sign in ((h[i], 1.0), (a[i], -1.0)):
                R[t] += sign * k / (1 + n[t] / g_half) * err
                n[t] += 1
    return pd.concat(out, ignore_index=True)
