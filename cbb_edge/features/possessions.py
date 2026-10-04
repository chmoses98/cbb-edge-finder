"""Possession estimates and (raw) Four Factors.

Possessions (per team, college convention):

    poss = FGA - ORB + TOV + 0.475 * FTA

The game possession count is the mean of both teams' estimates (they should be equal in
truth; averaging removes rebounding/FT bookkeeping noise). Tempo is normalized to 40
minutes: ``tempo = poss * 40 / (40 + 5 * n_ot)``.

Four Factors (Dean Oliver), offense perspective:

    eFG%  = (FGM + 0.5 * 3PM) / FGA
    TO%   = TOV / poss
    ORB%  = ORB / (ORB + opp DRB)
    FTR   = FTA / FGA

plus shot-profile rates: 2P%, 3P%, 3PA rate (3PA/FGA), FT%.

These are RAW per-game numbers. Predictive features use the opponent-adjusted
versions produced by ``cbb_edge.ratings.adjusted``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FTA_COEF = 0.475


def team_possessions(
    fga: float | np.ndarray | pd.Series,
    orb: float | np.ndarray | pd.Series,
    tov: float | np.ndarray | pd.Series,
    fta: float | np.ndarray | pd.Series,
) -> float | np.ndarray | pd.Series:
    return fga - orb + tov + FTA_COEF * fta


def game_possessions(tg: pd.DataFrame) -> pd.Series:
    own = team_possessions(tg["fga"], tg["orb"], tg["tov"], tg["fta"])
    opp = team_possessions(tg["opp_fga"], tg["opp_orb"], tg["opp_tov"], tg["opp_fta"])
    return (own + opp) / 2.0


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a.astype(float).div(b.astype(float).where(b > 0))


def add_possessions_and_factors(tg: pd.DataFrame) -> pd.DataFrame:
    tg = tg.copy()
    tg["poss"] = game_possessions(tg)
    n_ot = tg["n_ot"] if "n_ot" in tg else 0
    tg["minutes"] = 40 + 5 * n_ot
    tg["tempo"] = tg["poss"] * 40.0 / tg["minutes"]
    tg["ppp"] = _safe_div(tg["pts"], tg["poss"])
    tg["opp_ppp"] = _safe_div(tg["opp_pts"], tg["poss"])
    for pre in ("", "opp_"):
        fga, fgm = tg[f"{pre}fga"], tg[f"{pre}fgm"]
        fg3a, fg3m = tg[f"{pre}fg3a"], tg[f"{pre}fg3m"]
        tg[f"{pre}efg"] = _safe_div(fgm + 0.5 * fg3m, fga)
        tg[f"{pre}to_rate"] = _safe_div(tg[f"{pre}tov"], tg["poss"])
        tg[f"{pre}ftr"] = _safe_div(tg[f"{pre}fta"], fga)
        tg[f"{pre}fg2a"] = fga - fg3a
        tg[f"{pre}fg2_pct"] = _safe_div(fgm - fg3m, fga - fg3a)
        tg[f"{pre}fg3_pct"] = _safe_div(fg3m, fg3a)
        tg[f"{pre}fg3a_rate"] = _safe_div(fg3a, fga)
        tg[f"{pre}ft_pct"] = _safe_div(tg[f"{pre}ftm"], tg[f"{pre}fta"])
    tg["orb_rate"] = _safe_div(tg["orb"], tg["orb"] + tg["opp_drb"])
    tg["opp_orb_rate"] = _safe_div(tg["opp_orb"], tg["opp_orb"] + tg["drb"])
    tg["orb_chances"] = tg["orb"] + tg["opp_drb"]
    # Box-score sanity: flag implausible rows rather than silently using them.
    tg["box_ok"] = (
        tg["poss"].between(45, 110)
        & tg["fga"].gt(20)
        & tg["opp_fga"].gt(20)
        & tg["ppp"].between(0.3, 1.9)
        & tg["opp_ppp"].between(0.3, 1.9)
    )
    return tg
