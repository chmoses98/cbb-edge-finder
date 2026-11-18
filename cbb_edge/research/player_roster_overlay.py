"""Player-aggregate roster overlay ``pro-ch-v1`` on top of production (RESEARCH_ONLY).

Pattern follows the NBA Phase 14 player-aggregate model. For every team-game:

* **profile** of each player: per-minute box rates from all of his EARLIER games (prior seasons and
  prior schools included; the ESPN athlete id follows transfers), exponentially decayed by games
  played, shrunk toward a replacement-level prior (previous seasons' low-minute players); plus a
  *pedigree*: the net points per game of the team he played most minutes for last season;
* **roster** (pregame-safe, team-game number >= 1): every player listed in the team's earlier box
  scores this season (DNP rows included); projected minutes = decayed mean of his minutes over the
  team's games since he first appeared (0 when absent / DNP);
* **game 0 has no pregame roster source in history**: the ORACLE-ROSTER variant uses the players listed
  in that game's box (only their earlier history and last-season minutes, never this game's stats);
* **team aggregate** = minute-share x profile, scaled to 200 minutes.

The overlay is a ridge on production's residual (production forecast as offset), fitted per
team-game-number bucket on seasons before the holdout.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import lfilter

RATE_STATS = ("pts", "fga", "fta", "fg3a", "orb", "drb", "ast", "stl", "blk", "tov", "pf")
HL_RATE = 40.0  # games
HL_MIN = 4.0  # games
PRIOR_MIN = 150.0  # minutes of replacement-level prior
REPL_CAREER_MIN = 200.0
BUCKETS = ((0, 3), (4, 10), (11, 99))
FEATS = tuple([f"x_{s}" for s in RATE_STATS] + ["x_prior", "x_ped", "x_new"])


def _clean(pg: pd.DataFrame) -> pd.DataFrame:
    d = pg[pg.team_id.notna() & pg.athlete_espn_id.notna()].copy()
    d["min"] = pd.to_numeric(d["min"], errors="coerce").fillna(0.0)
    for s in RATE_STATS:
        d[s] = pd.to_numeric(d[s], errors="coerce").fillna(0.0)
    d["pid"] = d.athlete_espn_id.astype("int64")
    d["date"] = pd.to_datetime(d.game_date_et)
    d["played"] = (d["min"] > 0).astype(float)
    return (
        d.drop_duplicates(["game_id", "pid"])
        .sort_values(["pid", "date", "game_id"])
        .reset_index(drop=True)
    )


def player_state(d: pd.DataFrame) -> pd.DataFrame:
    """Per player-row: decayed rate state built from games STRICTLY before the row."""
    lam = 0.5 ** (1 / HL_RATE)
    cm = d.groupby("pid")["min"].cumsum() - d["min"]
    pl = d[d.played > 0]
    low = pl[cm[pl.index] < REPL_CAREER_MIN].groupby("season")[["min", *RATE_STATS]].sum()
    prior = low[list(RATE_STATS)].div(low["min"], axis=0)
    prior.index = prior.index + 1  # season s uses season s-1 replacement level
    first = int(d.season.min())
    allp = pl.groupby("season")[["min", *RATE_STATS]].sum()
    prior.loc[first] = allp[list(RATE_STATS)].div(allp["min"], axis=0).loc[first]
    prior = prior.sort_index()
    pidv = d.pid.to_numpy()
    bounds = np.flatnonzero(np.r_[True, pidv[1:] != pidv[:-1], True])
    mins, played = d["min"].to_numpy(), d.played.to_numpy()
    sv = {s: d[s].to_numpy() for s in RATE_STATS}
    dm = np.zeros(len(d))
    num = {s: np.zeros(len(d)) for s in RATE_STATS}
    for a, b in zip(bounds[:-1], bounds[1:], strict=True):
        idx = np.flatnonzero(played[a:b] > 0)
        if not len(idx):
            continue
        pos = np.searchsorted(idx, np.arange(b - a), side="left") - 1  # last played game before row
        ok = pos >= 0
        cum = lfilter([1.0], [1.0, -lam], mins[a:b][idx])
        dm[a:b][ok] = cum[pos[ok]]
        for s in RATE_STATS:
            num[s][a:b][ok] = lfilter([1.0], [1.0, -lam], sv[s][a:b][idx])[pos[ok]]
    out = d[["game_id", "pid", "team_id", "season", "date", "min", "played"]].copy()
    out["w_prior"] = PRIOR_MIN / (PRIOR_MIN + dm)
    pr = prior.reindex(d.season).to_numpy()
    for j, s in enumerate(RATE_STATS):
        out[f"r_{s}"] = (num[s] + PRIOR_MIN * pr[:, j]) / (dm + PRIOR_MIN)
    return out


def pedigree(d: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """(pid, season) -> last season's main team's net points per game and minutes per game."""
    g = games[games.completed.astype(bool) & games.home_score.notna()]
    rows = pd.concat(
        [
            pd.DataFrame(
                {"season": g.season, "team_id": g.home_team_id, "net": g.home_score - g.away_score}
            ),
            pd.DataFrame(
                {"season": g.season, "team_id": g.away_team_id, "net": g.away_score - g.home_score}
            ),
        ]
    ).dropna()
    tnet = rows.groupby(["season", "team_id"]).net.mean().rename("tnet").reset_index()
    pm = (
        d[d.played > 0]
        .groupby(["pid", "season", "team_id"], as_index=False)
        .agg(m=("min", "sum"), n=("min", "size"))
    )
    main = (
        pm.sort_values("m")
        .groupby(["pid", "season"])
        .tail(1)
        .merge(tnet, on=["season", "team_id"], how="left")
    )
    tot = pm.groupby(["pid", "season"], as_index=False).agg(m=("m", "sum"), n=("n", "sum"))
    main = main[["pid", "season", "tnet"]].merge(tot, on=["pid", "season"])
    main["mpg_prev"] = main.m / main.n
    main["season"] = main.season + 1  # available for the NEXT season only
    return main[["pid", "season", "tnet", "mpg_prev"]]


def team_rosters(
    d: pd.DataFrame, st: pd.DataFrame, ped: pd.DataFrame, seasons: list[int]
) -> pd.DataFrame:
    """Pregame candidate rows per (team-game, player) with profile and projected minutes.

    Team-game number k >= 1: players listed for this team in its earlier games this season.
    k == 0: ORACLE roster (players listed in this game's box) with last-season minutes per game.
    """
    st = st.merge(ped, on=["pid", "season"], how="left")
    lam = 0.5 ** (1 / HL_MIN)
    d = d[d.season.isin(seasons)]
    out = []
    for (s, t), rows in d.groupby(["season", "team_id"], sort=False):
        tg = rows[["game_id", "date"]].drop_duplicates("game_id").sort_values(["date", "game_id"])
        gidx = {g: i for i, g in enumerate(tg.game_id)}
        players = rows.pid.unique()
        pix = {p: j for j, p in enumerate(players)}
        M = np.full((len(tg), len(players)), np.nan)  # minutes (0 if listed DNP), NaN if not listed
        M[rows.game_id.map(gidx).to_numpy(), rows.pid.map(pix).to_numpy()] = rows["min"].to_numpy()
        listed = ~np.isnan(M)
        first = np.where(listed.any(0), listed.argmax(0), len(tg))
        Mz = np.nan_to_num(M)
        # decayed mean of minutes over team games since first appearance, strictly before game i
        num = np.zeros_like(Mz)
        den = np.zeros_like(Mz)
        for i in range(1, len(tg)):
            act = (first < i).astype(float)
            num[i] = lam * num[i - 1] + Mz[i - 1] * act
            den[i] = lam * den[i - 1] + act * (first <= i - 1)
        for i, r in enumerate(tg.itertuples()):
            if i == 0:
                sel = np.flatnonzero(listed[0])
                mproj = np.full(len(sel), np.nan)
            else:
                sel = np.flatnonzero(first < i)
                mproj = num[i, sel] / np.maximum(den[i, sel], 1e-9)
            out.append(
                pd.DataFrame(
                    {
                        "game_id": r.game_id,
                        "team_id": t,
                        "season": s,
                        "k": i,
                        "date": r.date,
                        "pid": players[sel],
                        "m_proj": mproj,
                    }
                )
            )
    ros = pd.concat(out, ignore_index=True)
    # pre-game profile at the game date: last state row with date < game date, else (no history) prior
    cols = ["pid", "date", "w_prior", *[f"r_{x}" for x in RATE_STATS]]
    nxt = st[cols].copy()  # state rows hold pre-game values for their own date
    ros = ros.sort_values("date")
    nxt = nxt.sort_values("date")
    m = pd.merge_asof(ros, nxt, on="date", by="pid", direction="forward", allow_exact_matches=True)
    # forward match gives the first row on/after the game date whose state uses only games before it;
    # guard: that state must not include this game -> it is by construction (strictly-before state).
    return m.merge(
        st[["pid", "season", "tnet", "mpg_prev"]].drop_duplicates(["pid", "season"]),
        on=["pid", "season"],
        how="left",
    )


def aggregates(ros: pd.DataFrame, prior_rates: pd.Series | None = None) -> pd.DataFrame:
    r = ros.copy()
    r["m_proj"] = r.m_proj.fillna(r.mpg_prev).fillna(8.0)
    r.loc[r.k == 0, "m_proj"] = r.loc[r.k == 0, "mpg_prev"].fillna(8.0)
    for s in RATE_STATS:  # no later state row at all: league-free fallback to team-game mean below
        r[f"r_{s}"] = r[f"r_{s}"].fillna(r.groupby("season")[f"r_{s}"].transform("median"))
    r["w_prior"] = r.w_prior.fillna(1.0)
    r["new"] = r.mpg_prev.isna().astype(float)
    w = r.m_proj.to_numpy()
    x = pd.DataFrame({"game_id": r.game_id, "team_id": r.team_id, "k": r.k, "w": w})
    for s in RATE_STATS:
        x[f"x_{s}"] = w * r[f"r_{s}"].to_numpy() * 40
    x["x_prior"] = w * r.w_prior.to_numpy()
    x["x_new"] = w * r.new.to_numpy()
    x["x_ped"] = w * r.tnet.fillna(-8.0).to_numpy()
    g = x.groupby(["game_id", "team_id"], as_index=False).agg(
        {"k": "first", "w": "sum", **{f: "sum" for f in FEATS}}
    )
    for f in FEATS:
        g[f] = g[f] / g.w.clip(lower=1e-9)
    return g


def game_frame(agg: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    g = games[
        [
            "game_id",
            "season",
            "home_team_id",
            "away_team_id",
            "neutral_site",
            "home_score",
            "away_score",
        ]
    ]
    h = agg.add_prefix("h_").rename(columns={"h_game_id": "game_id", "h_team_id": "home_team_id"})
    a = agg.add_prefix("a_").rename(columns={"a_game_id": "game_id", "a_team_id": "away_team_id"})
    df = g.merge(h, on=["game_id", "home_team_id"]).merge(a, on=["game_id", "away_team_id"])
    for f in FEATS:
        df[f"d_{f}"] = df[f"h_{f}"] - df[f"a_{f}"]
        df[f"s_{f}"] = df[f"h_{f}"] + df[f"a_{f}"]
    df["kmin"] = np.minimum(df.h_k, df.a_k)
    df["bucket"] = np.select([df.kmin <= 3, df.kmin <= 10], ["0-3", "4-10"], "11+")
    return df


D_COLS = tuple(f"d_{f}" for f in FEATS)
S_COLS = tuple(f"s_{f}" for f in FEATS)


def fit_ridge(X: np.ndarray, y: np.ndarray, lam: float) -> dict:
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    beta = np.linalg.solve(Z.T @ Z + lam * len(y) * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return {"mu": mu.tolist(), "sd": sd.tolist(), "beta": beta.tolist(), "b0": float(y.mean())}


def predict(m: dict, X: np.ndarray) -> np.ndarray:
    return ((X - np.array(m["mu"])) / np.array(m["sd"])) @ np.array(m["beta"]) + m["b0"]
