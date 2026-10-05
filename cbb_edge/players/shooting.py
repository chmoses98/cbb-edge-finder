"""Heavily shrunk player shooting skill -> team expected shooting (B17).

Player skill per shot type (3P, FT, 2P) is a beta-binomial posterior mean:

    skill = (makes + κ·m) / (attempts + κ)

using all of the player's earlier D-I attempts (previous seasons on any team plus this
season's games that tipped before T; transfers keep their history). The prior mean m is
the DEV position mean (G / F / C); for 3P it also has a term in the player's FT skill
(FT% is a proxy for shooting touch): m3 = pos_mean3 + b·(ftskill − pos_meanFT).
κ (per type) and b are fitted on DEV seasons (2008–2014, careers from 2006) by
maximizing the next-game binomial log-likelihood, over a fixed grid.

The team expectation for game T weights players by their EW share (half-life 4 games,
missed games = 0) of the team's attempts of that type in its earlier games this season.
Before the team's first game it falls back to last season's attempt shares.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from cbb_edge.players.availability_model import _pos

TYPES = {"3": ("fg3m", "fg3a"), "ft": ("ftm", "fta"), "2": ("fg2m", "fg2a")}
KAPPA_GRID = (25.0, 50.0, 100.0, 200.0, 400.0, 800.0)
B_GRID = (0.0, 0.25, 0.5, 0.75)
HALFLIFE = 4.0


def player_games(pg: pd.DataFrame) -> pd.DataFrame:
    x = pg[
        [
            "season",
            "game_id",
            "team_id",
            "player_id",
            "position",
            "available_at",
            "fgm",
            "fga",
            "fg3m",
            "fg3a",
            "ftm",
            "fta",
            "min",
        ]
    ].copy()
    for c in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "min"):
        x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0.0)
    x = x[x["min"] > 0]
    x["fg2m"] = (x["fgm"] - x["fg3m"]).clip(lower=0)
    x["fg2a"] = (x["fga"] - x["fg3a"]).clip(lower=0)
    x["pos"] = x["position"].map(_pos)
    x["t"] = pd.to_datetime(x["available_at"], utc=True).astype("int64")
    return x.sort_values(["player_id", "t"]).reset_index(drop=True)


def career_before(x: pd.DataFrame) -> pd.DataFrame:
    """Per player-game: career makes / attempts strictly before this game."""
    g = x.groupby("player_id")
    out = x[["player_id", "game_id", "season", "team_id", "pos", "t"]].copy()
    for _, (mk, at) in TYPES.items():
        out[f"cm_{mk}"] = g[mk].cumsum() - x[mk]
        out[f"ca_{at}"] = g[at].cumsum() - x[at]
        out[mk] = x[mk]
        out[at] = x[at]
    return out


@dataclass
class ShootingPrior:
    kappa: dict[str, float] = field(default_factory=dict)
    pos_mean: dict[str, dict[str, float]] = field(default_factory=dict)  # type -> pos -> m
    b3: float = 0.0
    fit: dict[str, object] = field(default_factory=dict)

    def skill(
        self,
        typ: str,
        cm: np.ndarray,
        ca: np.ndarray,
        pos: np.ndarray,
        ftskill: np.ndarray | None = None,
    ) -> np.ndarray:
        m = np.array([self.pos_mean[typ].get(p, self.pos_mean[typ]["F"]) for p in pos])
        if typ == "3" and ftskill is not None:
            mft = np.array([self.pos_mean["ft"].get(p, self.pos_mean["ft"]["F"]) for p in pos])
            m = np.clip(m + self.b3 * (ftskill - mft), 0.05, 0.6)
        k = self.kappa[typ]
        return (cm + k * m) / (ca + k)


def _ll(mk: np.ndarray, at: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(np.sum(mk * np.log(p) + (at - mk) * np.log(1 - p)))


def fit_prior(cb: pd.DataFrame, fit_seasons: list[int]) -> ShootingPrior:
    """Grid-fit κ per type and b (3P on FT skill) on games of ``fit_seasons``."""
    sp = ShootingPrior()
    hist = cb[cb["season"] <= max(fit_seasons)]
    for typ, (mk, at) in TYPES.items():
        tot = hist.groupby("pos")[[mk, at]].sum()
        sp.pos_mean[typ] = (tot[mk] / tot[at]).to_dict()
        sp.pos_mean[typ].setdefault("F", float(tot[mk].sum() / tot[at].sum()))
    ev = cb[cb["season"].isin(fit_seasons)]
    pos = ev["pos"].to_numpy()
    res = {}
    for typ, (mk, at) in TYPES.items():
        best = None
        for k in KAPPA_GRID:
            sp.kappa[typ] = k
            p = sp.skill(typ, ev[f"cm_{mk}"].to_numpy(), ev[f"ca_{at}"].to_numpy(), pos)
            ll = _ll(ev[mk].to_numpy(), ev[at].to_numpy(), p)
            res[f"{typ}|k={k}"] = ll
            if best is None or ll > best[1]:
                best = (k, ll)
        sp.kappa[typ] = best[0]
    ft = sp.skill("ft", ev["cm_ftm"].to_numpy(), ev["ca_fta"].to_numpy(), pos)
    best_b = None
    for b in B_GRID:
        sp.b3 = b
        p = sp.skill("3", ev["cm_fg3m"].to_numpy(), ev["ca_fg3a"].to_numpy(), pos, ft)
        ll = _ll(ev["fg3m"].to_numpy(), ev["fg3a"].to_numpy(), p)
        res[f"b3={b}"] = ll
        if best_b is None or ll > best_b[1]:
            best_b = (b, ll)
    sp.b3 = best_b[0]
    sp.fit = {"seasons": fit_seasons, "loglik": res}
    return sp


def team_features(x: pd.DataFrame, games: pd.DataFrame, sp: ShootingPrior) -> pd.DataFrame:
    """Per game: h/a expected 3P%, FT%, 2P% from player skills (info before tip).

    A player's skill before game i = his posterior AFTER his most recent earlier game
    (any team, any season), i.e. only completed games enter.
    """
    cb = career_before(x)
    pos = cb["pos"].to_numpy()
    post: dict[str, np.ndarray] = {}
    ft_post = sp.skill(
        "ft", (cb["cm_ftm"] + cb["ftm"]).to_numpy(), (cb["ca_fta"] + cb["fta"]).to_numpy(), pos
    )
    post["ft"] = ft_post
    post["3"] = sp.skill(
        "3",
        (cb["cm_fg3m"] + cb["fg3m"]).to_numpy(),
        (cb["ca_fg3a"] + cb["fg3a"]).to_numpy(),
        pos,
        ft_post,
    )
    post["2"] = sp.skill(
        "2", (cb["cm_fg2m"] + cb["fg2m"]).to_numpy(), (cb["ca_fg2a"] + cb["fg2a"]).to_numpy(), pos
    )
    for t in TYPES:
        cb[f"post_{t}"] = post[t]
    meta = games.set_index("game_id")["start_time_utc"]
    decay = 0.5 ** (1.0 / HALFLIFE)
    recs = []
    prev_team: dict[tuple[str, int], dict[str, float]] = {}
    for (s, team), y in cb.groupby(["season", "team_id"], sort=True):
        gids = meta.reindex(y["game_id"].unique()).sort_values().index.to_numpy()
        pl = np.array(sorted(y["player_id"].unique()))
        gidx = {g: i for i, g in enumerate(gids)}
        pidx = {q: i for i, q in enumerate(pl)}
        k, n = len(gids), len(pl)
        r = y["game_id"].map(gidx).to_numpy()
        c = y["player_id"].map(pidx).to_numpy()
        feats: dict[str, np.ndarray] = {}
        for typ, (_, at) in TYPES.items():
            A = np.zeros((k, n))
            P = np.full((k, n), np.nan)
            A[r, c] = y[at].to_numpy()
            P[r, c] = y[f"post_{typ}"].to_numpy()
            before = pd.DataFrame(P).ffill().shift(1).to_numpy()  # posterior before row i
            out = np.full(k, np.nan)
            ew = np.zeros(n)
            for i in range(k):
                ok = (ew > 0) & np.isfinite(before[i])
                if ok.any():
                    out[i] = float((ew[ok] * before[i][ok]).sum() / ew[ok].sum())
                tot = A[i].sum()
                ew = decay * ew + (A[i] / tot if tot > 0 else 0.0)
            if not np.isfinite(out[0]):
                out[0] = prev_team.get((team, s - 1), {}).get(typ, np.nan)
            feats[typ] = out
            prev_team.setdefault((team, s), {})[typ] = (
                float(np.nanmean(out[-5:])) if np.isfinite(out).any() else np.nan
            )
        recs.append(
            pd.DataFrame(
                {"game_id": gids, "team_id": team, **{f"sk{t}": v for t, v in feats.items()}}
            )
        )
    tf = pd.concat(recs, ignore_index=True)
    g = games[["game_id", "home_team_id", "away_team_id"]]
    h = tf.rename(columns={"team_id": "home_team_id", **{f"sk{t}": f"h_sk{t}" for t in TYPES}})
    a = tf.rename(columns={"team_id": "away_team_id", **{f"sk{t}": f"a_sk{t}" for t in TYPES}})
    out = g.merge(h, on=["game_id", "home_team_id"], how="left").merge(
        a, on=["game_id", "away_team_id"], how="left"
    )
    return out.drop(columns=["home_team_id", "away_team_id"])
