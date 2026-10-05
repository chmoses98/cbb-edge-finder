"""Preseason roster-state features and player-derived team priors (leakage-safe).

For season ``s`` everything here uses ONLY data from seasons < s:

* ``return_probabilities`` – P(player returns to the same team) for every player of
  season s-1, from a logistic model fitted on seasons < s-1 (whose outcomes are known
  before season s). Features: experience (observed seasons), on-court share, start rate,
  usage, player impact, era (transfer-portal seasons).
* ``preseason_team_features`` – expected returning production per team (minutes,
  usage, starts, assists, rebounds, stocks, player impact, top-1 / top-3 impact, number
  of returning rotation players, departed production) and a player-derived preseason
  offense / defense: expected returners' carried impact + vacated minutes filled at the
  empirical newcomer level (minutes-weighted impact of first-season-with-team players in
  earlier seasons — freshmen and transfers alike, because historically we cannot know
  preseason which newcomers arrive).

Realized returns (hindsight) are available through ``realized=True`` for research
diagnostics only; predictive arms never use them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from cbb_edge.data.http import data_dir

PORTAL_ERA = 2021  # one-time transfer exception era


def load_player_seasons() -> pd.DataFrame:
    return pd.read_parquet(data_dir() / "silver" / "players" / "player_seasons.parquet")


def _return_X(x: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=x.index)
    sp = x["seasons_prior"].clip(upper=4)
    for k in range(5):
        X[f"exp{k}"] = (sp == k).astype(float)
    X["min_share"] = x["min_share"].clip(0, 1)
    X["start_rate"] = x["start_rate"].fillna(0)
    X["usage"] = x["usage_share"].fillna(0)
    X["net"] = x.get("rapm_net", pd.Series(0.0, index=x.index)).fillna(0).clip(-15, 15)
    X["portal"] = (x["season"] + 1 >= PORTAL_ERA).astype(float)
    X["portal_x_net"] = X["portal"] * X["net"]
    X["portal_x_min"] = X["portal"] * X["min_share"]
    return X


def return_probabilities(ps: pd.DataFrame, season: int) -> pd.Series:
    """P(return) for players of season-1, fitted on rows with season <= season-2."""
    prev = ps[ps["season"] == season - 1]
    train = ps[(ps["season"] <= season - 2) & (ps["season"] >= 2007)]
    if len(train) < 2000:
        return pd.Series(0.6, index=prev.index)
    m = LogisticRegression(C=1.0, max_iter=2000).fit(
        _return_X(train), train["returns_next"].astype(int)
    )
    return pd.Series(m.predict_proba(_return_X(prev))[:, 1], index=prev.index)


def newcomer_level(ps: pd.DataFrame, season: int, carry: float) -> tuple[float, float]:
    """Minutes-weighted end-of-season impact of newcomers (first season with the team) in
    seasons < season, expressed per on-court unit — the fill-in value for vacated minutes."""
    x = ps[(ps["season"] < season) & ~ps["returning"] & ps["rapm_o"].notna()]
    if x.empty:
        return (-0.8, 0.4)
    w = x["min_share"].clip(lower=0)
    return (float(np.average(x["rapm_o"], weights=w)), float(np.average(x["rapm_d"], weights=w)))


def preseason_team_features(
    ps: pd.DataFrame, season: int, carry: float = 0.95, realized: bool = False
) -> pd.DataFrame:
    prev = ps[ps["season"] == season - 1].copy()
    if prev.empty:
        return pd.DataFrame()
    if realized:
        prev["p_ret"] = prev["returns_next"].astype(float)
    else:
        prev["p_ret"] = return_probabilities(ps, season)
    no, nd = newcomer_level(ps, season, carry)
    prev["po"] = carry * prev["rapm_o"].fillna(no)
    prev["pd"] = carry * prev["rapm_d"].fillna(nd)
    prev["pnet"] = prev["po"] - prev["pd"]
    tot = prev.groupby("team_id")[["ast", "orb", "drb", "stl", "blk", "pts"]].transform("sum")
    for c in ("ast", "orb", "drb", "stl", "blk", "pts"):
        prev[f"{c}_sh"] = prev[c] / tot[c].replace(0, np.nan)
    p = prev["p_ret"]
    prev["e_min"] = p * prev["min_share"]
    rows = []
    for team, x in prev.groupby("team_id"):
        e_min = float(x["e_min"].sum())
        vac = max(5.0 - e_min, 0.0)
        ord_net = x.sort_values("pnet", ascending=False)
        top = ord_net[ord_net["min_share"] >= 0.25]
        rec = {
            "team_id": team,
            "season": season,
            "ret_min": e_min / 5.0,
            "ret_usage": float((x["p_ret"] * x["usage_share"]).sum()),
            "ret_starts": float((x["p_ret"] * x["start_rate"].fillna(0)).sum()) / 5.0,
            "ret_rot_n": float(x.loc[x["min_share"] >= 0.25, "p_ret"].sum()),
            "pre_o": float((x["e_min"] * x["po"]).sum() + vac * carry * no),
            "pre_d": float((x["e_min"] * x["pd"]).sum() + vac * carry * nd),
            "ret_impact": float((x["e_min"] * x["pnet"]).sum()),
            "lost_impact": float(((1 - x["p_ret"]) * x["min_share"] * x["pnet"]).sum()),
            "ret_top1": float((top["p_ret"] * top["pnet"]).head(1).sum()),
            "ret_top3": float((top["p_ret"] * top["pnet"]).head(3).sum()),
            "prev_top3": float(top["pnet"].head(3).sum()),
        }
        for c in ("ast", "orb", "drb", "stl", "blk", "pts"):
            rec[f"ret_{c}"] = float((x["p_ret"] * x[f"{c}_sh"]).sum())
        rec["pre_net"] = rec["pre_o"] - rec["pre_d"]
        rows.append(rec)
    return pd.DataFrame(rows)


def all_seasons(
    ps: pd.DataFrame, seasons: list[int], realized: bool = False, carry: float = 0.95
) -> pd.DataFrame:
    return pd.concat(
        [preseason_team_features(ps, s, carry, realized) for s in seasons], ignore_index=True
    )
