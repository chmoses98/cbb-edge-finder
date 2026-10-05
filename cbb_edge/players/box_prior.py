"""Box-score-informed (SPM) priors and transfer translation for player impact.

Both are fitted on DEV seasons only against a *weak-prior* RAPM (λ small, zero prior
mean), so the targets are not themselves dominated by the priors being learned.

* SPM: ridge regression of weak-prior RAPM offense / defense on per-40 box production,
  true shooting, 3PA rate, usage rate and position, weighted by possessions.
* Translation: next-season weak-prior RAPM regressed on this-season RAPM separately
  for players who stay vs. transfer, with the change in team strength
  (new team − old team, prior-season player-derived team net) for transfers.

Used by ``rapm.player_team_features(..., prior_model=...)``: a player's season prior is
``w_r * carry * RAPM_prev + w_b * SPM(box_prev)`` (returners), the translated prior for
a transfer once he first appears for his new team, and a current-season box update
``SPM(box_to_date)`` blended in with weight ``minutes / (minutes + M)``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge

from cbb_edge.players.rapm import DEF, OFF, IncrementalRapm, RapmConfig
from cbb_edge.players.stints import stints_path

SPM_FEATURES = [
    "pts_40",
    "ast_40",
    "orb_40",
    "drb_40",
    "stl_40",
    "blk_40",
    "tov_40",
    "pf_40",
    "fga_40",
    "fta_40",
    "ts",
    "fg3a_rate",
    "usage_rate",
    "pos_g",
    "pos_c",
]


def box_features(x: pd.DataFrame) -> pd.DataFrame:
    """Per-40 / rate features from player-season (or season-to-date) box sums."""
    m40 = x["minutes"].clip(lower=1) / 40.0
    X = pd.DataFrame(index=x.index)
    for c in ("pts", "ast", "orb", "drb", "stl", "blk", "tov", "pf", "fga", "fta"):
        X[f"{c}_40"] = (x[c] / m40).clip(upper=60)
    X["ts"] = (
        (x["pts"] / (2 * (x["fga"] + 0.475 * x["fta"])).replace(0, np.nan)).fillna(0.5).clip(0, 1)
    )
    X["fg3a_rate"] = (x["fg3a"] / x["fga"].replace(0, np.nan)).fillna(0.3)
    X["usage_rate"] = ((x["fga"] + 0.475 * x["fta"] + x["tov"]) / m40).clip(upper=60)
    pos = x.get("position", pd.Series("", index=x.index)).fillna("").astype(str).str.upper()
    X["pos_g"] = pos.str.startswith("G").astype(float)
    X["pos_c"] = pos.str.startswith("C").astype(float)
    return X


def weak_rapm(season: int, lam: float = 150.0) -> pd.DataFrame:
    st = pd.read_parquet(stints_path(season))
    players = sorted(set(st[OFF + DEF].to_numpy().ravel()))
    cfg = RapmConfig(lam_o=lam, lam_d=lam, new_o=0.0, new_d=0.0)
    inc = IncrementalRapm(players, np.zeros(len(players)), np.zeros(len(players)), cfg)
    inc.add(st)
    inc.solve()
    r = inc.ratings()
    return pd.DataFrame(
        {"player_id": r.players, "season": season, "w_o": r.o, "w_d": r.d, "w_poss": r.poss}
    )


@dataclass
class PriorModel:
    spm_o: dict[str, float] = field(default_factory=dict)
    spm_d: dict[str, float] = field(default_factory=dict)
    spm_o0: float = 0.0
    spm_d0: float = 0.0
    carry_ret: tuple[float, float] = (0.0, 0.7)  # (intercept, slope) offense; defense below
    carry_ret_d: tuple[float, float] = (0.0, 0.7)
    carry_tr: tuple[float, float, float] = (0.0, 0.6, 0.0)  # (c0, slope, gamma*dStrength)
    carry_tr_d: tuple[float, float, float] = (0.0, 0.6, 0.0)
    w_rapm: float = 1.0
    w_box: float = 0.0
    box_update_m: float = 300.0  # minutes for current-season box to get half weight
    fit_seasons: list[int] = field(default_factory=list)

    def spm(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        o = self.spm_o0 + sum(X[c].to_numpy() * v for c, v in self.spm_o.items())
        d = self.spm_d0 + sum(X[c].to_numpy() * v for c, v in self.spm_d.items())
        return np.asarray(o, dtype=float), np.asarray(d, dtype=float)

    def to_dict(self) -> dict:
        return asdict(self)


def fit_prior_model(
    ps: pd.DataFrame, seasons: list[int], team_strength: pd.DataFrame
) -> tuple[PriorModel, dict[str, object]]:
    """Fit SPM + translation on ``seasons`` (DEV). ``team_strength``: team_id, season, net."""
    weak = pd.concat([weak_rapm(s) for s in sorted(set(seasons) | {max(seasons) + 1})])
    d = ps.merge(weak, on=["player_id", "season"], how="inner")
    d = d[d["season"].isin(seasons) & (d["w_poss"] >= 100)]
    X = box_features(d)
    w = d["w_poss"].clip(upper=2500)
    pm = PriorModel(fit_seasons=list(seasons))
    diag: dict[str, object] = {"n_spm": len(d)}
    for side, tgt in (("o", "w_o"), ("d", "w_d")):
        m = Ridge(alpha=50.0).fit(X[SPM_FEATURES], d[tgt], sample_weight=w)
        setattr(pm, f"spm_{side}", dict(zip(SPM_FEATURES, map(float, m.coef_), strict=True)))
        setattr(pm, f"spm_{side}0", float(m.intercept_))
        pred = m.predict(X[SPM_FEATURES])
        diag[f"spm_{side}_r2_w"] = float(
            1
            - np.average((d[tgt] - pred) ** 2, weights=w)
            / np.average((d[tgt] - np.average(d[tgt], weights=w)) ** 2, weights=w)
        )
    # translation: season s weak RAPM -> season s+1 weak RAPM (both observed)
    nxt = weak.rename(columns={"w_o": "n_o", "w_d": "n_d", "w_poss": "n_poss"})
    nxt["season"] = nxt["season"] - 1
    t = d.merge(nxt, on=["player_id", "season"], how="inner")
    t = t[(t["n_poss"] >= 100)]
    ps_next = ps[["player_id", "season", "team_id"]].rename(columns={"team_id": "next_team_id"})
    ps_next["season"] = ps_next["season"] - 1
    t = t.merge(ps_next, on=["player_id", "season"], how="inner")
    ts = team_strength.set_index(["team_id", "season"])["net"]
    t["old_net"] = [ts.get((a, b), np.nan) for a, b in zip(t["team_id"], t["season"], strict=True)]
    t["new_net"] = [
        ts.get((a, b), np.nan) for a, b in zip(t["next_team_id"], t["season"], strict=True)
    ]
    t["dstr"] = (t["new_net"] - t["old_net"]).fillna(0)
    stay = t[t["next_team_id"] == t["team_id"]]
    move = t[t["next_team_id"] != t["team_id"]]
    for side, cur, nx in (("", "w_o", "n_o"), ("_d", "w_d", "n_d")):
        m = LinearRegression().fit(stay[[cur]], stay[nx], sample_weight=stay["n_poss"])
        setattr(pm, f"carry_ret{side}", (float(m.intercept_), float(m.coef_[0])))
        if len(move) > 50:
            m2 = LinearRegression().fit(move[[cur, "dstr"]], move[nx], sample_weight=move["n_poss"])
            setattr(
                pm,
                f"carry_tr{side}",
                (float(m2.intercept_), float(m2.coef_[0]), float(m2.coef_[1])),
            )
    diag.update({"n_stay": len(stay), "n_transfer": len(move)})
    return pm, diag
