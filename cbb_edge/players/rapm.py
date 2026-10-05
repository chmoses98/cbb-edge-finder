"""Walk-forward player impact (prior-anchored ridge RAPM) and player-based team strength.

Model, per stint side (offense perspective), weight = possessions (garbage time
down-weighted):

    100 * pts / poss = mu + eta * loc + sum_{p in offense} o_p + sum_{q in defense} d_q + e

``o_p`` = offensive contribution (pts/100 added on offense), ``d_q`` = defensive
contribution (pts/100 *allowed*; negative is good). Ridge penalty anchors every player
to a prior:

    lam_o * (o_p - prior_o_p)^2 + lam_d * (d_p - prior_d_p)^2

prior = carry * (last season's end-of-season rating) when the player (ESPN athlete id)
has history — this follows transfers between schools automatically — otherwise a
new-player prior (freshman / unmatched). Ratings are re-solved every game day from
stints with ``available_at`` strictly before the day's first tip (incremental normal
equations + warm-started CG), so a rating at time T uses only possessions before T.

Player-based team strength for a game: expected on-court shares s_p (sum 5) from the
team's minutes in its previous games this season (exponentially weighted, missed games
count as 0 — this captures injuries/absences), then team_o = sum s_p o_p and
team_d = sum s_p d_p. Before a team's first game the previous season's roster shares
are used and the row is flagged ``roster_known = 0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from cbb_edge.data.http import data_dir
from cbb_edge.players.stints import stints_path

OFF = [f"o{i}" for i in range(5)]
DEF = [f"d{i}" for i in range(5)]


@dataclass(frozen=True)
class RapmConfig:
    lam_o: float = 2000.0  # prior strength, possessions-equivalent per player
    lam_d: float = 2000.0
    carry: float = 0.7  # share of last season's rating kept
    new_o: float = -0.8  # prior for players with no history (pts/100)
    new_d: float = 0.4
    garbage_weight: float = 0.3
    lam_mu: float = 1e4
    lam_eta: float = 1e4
    minutes_halflife_games: float = 4.0


class PriorProvider(Protocol):
    def start(
        self, season: int, players: list[str], prev: SeasonRapm | None, cfg: RapmConfig
    ) -> tuple[np.ndarray, np.ndarray]: ...

    def day(self, cutoff_ns: int) -> tuple[np.ndarray, np.ndarray] | None: ...


@dataclass
class SeasonRapm:
    players: list[str]
    o: np.ndarray
    d: np.ndarray
    mu: float
    eta: float
    poss: np.ndarray


def _design(
    st: pd.DataFrame, index: dict[str, int], n: int, garbage_weight: float = 0.3
) -> tuple[sp.csr_matrix, np.ndarray, np.ndarray]:
    m = len(st)
    k = 2 + 2 * n
    rows = np.repeat(np.arange(m), 12)
    cols = np.empty((m, 12), dtype=np.int64)
    vals = np.ones((m, 12))
    cols[:, 0] = 0
    loc = np.where(st["neutral"].to_numpy(), 0.0, np.where(st["off_home"].to_numpy(), 1.0, -1.0))
    cols[:, 1] = 1
    vals[:, 1] = loc
    for j, c in enumerate(OFF):
        cols[:, 2 + j] = 2 + st[c].map(index).to_numpy()
    for j, c in enumerate(DEF):
        cols[:, 7 + j] = 2 + n + st[c].map(index).to_numpy()
    X = sp.csr_matrix((vals.ravel(), (rows, cols.ravel())), shape=(m, k))
    poss = st["poss"].to_numpy(dtype=float)
    w = np.clip(poss - (1.0 - garbage_weight) * st["garbage"].to_numpy(dtype=float), 0.5, None)
    y = 100.0 * st["pts"].to_numpy(dtype=float) / poss
    return X, w, y


class IncrementalRapm:
    """Accumulates normal equations as stints become available; solves on demand."""

    def __init__(
        self,
        players: list[str],
        prior_o: np.ndarray,
        prior_d: np.ndarray,
        cfg: RapmConfig,
        mu0: float = 104.0,
        eta0: float = 1.5,
    ):
        self.players = players
        self.index = {p: i for i, p in enumerate(players)}
        self.n = len(players)
        k = 2 + 2 * self.n
        self.A = sp.csr_matrix((k, k))
        self.b = np.zeros(k)
        self.cfg = cfg
        self.prior = np.concatenate([[mu0, eta0], prior_o, prior_d])
        self.diag = np.concatenate(
            [[cfg.lam_mu, cfg.lam_eta], np.full(self.n, cfg.lam_o), np.full(self.n, cfg.lam_d)]
        )
        self.x = self.prior.copy()
        self.poss = np.zeros(self.n)

    def add(self, st: pd.DataFrame) -> None:
        if not len(st):
            return
        X, w, y = _design(st, self.index, self.n, self.cfg.garbage_weight)
        Xw = X.multiply(w[:, None]).tocsr()
        self.A = (self.A + X.T @ Xw).tocsr()
        self.b += Xw.T @ y
        for c in OFF:
            np.add.at(self.poss, st[c].map(self.index).to_numpy(), st["poss"].to_numpy())

    def solve(self) -> np.ndarray:
        M = (self.A + sp.diags(self.diag)).tocsr()
        rhs = self.b + self.diag * self.prior
        x, info = spla.cg(M, rhs, x0=self.x, rtol=1e-8, atol=0.0, maxiter=3000)
        if info != 0:
            x = spla.spsolve(M.tocsc(), rhs)
        self.x = x
        return x

    def ratings(self) -> SeasonRapm:
        n = self.n
        return SeasonRapm(
            self.players,
            self.x[2 : 2 + n].copy(),
            self.x[2 + n :].copy(),
            float(self.x[0]),
            float(self.x[1]),
            self.poss.copy(),
        )


def season_priors(
    players: list[str], prev: SeasonRapm | None, cfg: RapmConfig
) -> tuple[np.ndarray, np.ndarray]:
    po = np.full(len(players), cfg.new_o)
    pd_ = np.full(len(players), cfg.new_d)
    if prev is not None:
        idx = {p: i for i, p in enumerate(prev.players)}
        for i, p in enumerate(players):
            j = idx.get(p)
            if j is not None and prev.poss[j] > 0:
                po[i] = cfg.carry * prev.o[j]
                pd_[i] = cfg.carry * prev.d[j]
    return po, pd_


def minutes_shares(pg_team_games: pd.DataFrame, halflife: float) -> pd.DataFrame:
    """Expected on-court share per player from previous games (EW, missed games = 0).

    ``pg_team_games``: player-game rows (player_id, game_id, start_time_utc, min) for ONE
    team, already restricted to games before the cutoff. Returns player_id, share (sum 5).
    """
    if pg_team_games.empty:
        return pd.DataFrame(columns=["player_id", "share"])
    piv = pg_team_games.pivot_table(
        index="game_id", columns="player_id", values="min", aggfunc="sum", fill_value=0.0
    )
    order = pg_team_games.drop_duplicates("game_id").set_index("game_id")["start_time_utc"]
    piv = piv.loc[order.sort_values().index]
    tot = piv.sum(axis=1).replace(0, np.nan)
    share = piv.div(tot / 5.0, axis=0).clip(upper=1.0)
    k = np.arange(len(share))[::-1]
    w = 0.5 ** (k / halflife)
    s = share.mul(w, axis=0).sum(axis=0) / w.sum()
    s = s[s > 0]
    s = s * (5.0 / s.sum())
    return s.rename("share").reset_index()


def _ns(x: pd.Series) -> np.ndarray:
    """UTC epoch nanoseconds (explicit unit: pandas may store us resolution)."""
    return pd.to_datetime(x, utc=True).dt.as_unit("ns").astype("int64").to_numpy()


def _ns_scalar(t: pd.Timestamp) -> int:
    return int(pd.Timestamp(t).tz_convert("UTC").as_unit("ns").value)


class TeamShares:
    """Exponentially weighted on-court shares for every prefix of a team's season.

    ``shares(m)`` = EW average over the team's first ``m`` games (missed games count 0),
    normalized to sum 5. Computed once per team-season by recursion, so querying it for
    any cutoff is O(players).
    """

    def __init__(self, x: pd.DataFrame, halflife: float):
        piv = x.pivot_table(
            index="game_id", columns="player_id", values="min", aggfunc="sum", fill_value=0.0
        )
        meta = x.drop_duplicates("game_id").set_index("game_id")[["start_time_utc", "available_at"]]
        meta = meta.loc[piv.index].sort_values("start_time_utc")
        piv = piv.loc[meta.index]
        tot = piv.sum(axis=1).replace(0, np.nan)
        S = piv.div(tot / 5.0, axis=0).clip(upper=1.0).fillna(0.0).to_numpy()
        self.players = np.array(piv.columns)
        self.available = _ns(meta["available_at"])
        decay = 0.5 ** (1.0 / halflife)
        k = len(S)
        self.E = np.zeros((k + 1, S.shape[1]))
        num = np.zeros(S.shape[1])
        den = 0.0
        for i in range(k):
            num = decay * num + S[i]
            den = decay * den + 1.0
            self.E[i + 1] = num / den

    def n_available(self, cutoff: pd.Timestamp) -> int:
        return int((self.available < _ns_scalar(cutoff)).sum())

    def shares(self, m: int) -> tuple[np.ndarray, np.ndarray]:
        e = self.E[m]
        keep = e > 0
        s = e[keep]
        return self.players[keep], s * (5.0 / s.sum()) if s.sum() > 0 else s


def _prev_shares(prev_pg: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    out = {}
    for t, x in prev_pg.groupby("team_id"):
        m = x.groupby("player_id")["min"].sum()
        m = m[m > 0]
        tot = m.sum()
        if tot > 0:
            out[t] = (m.index.to_numpy(), (m / tot * 5.0).clip(upper=1.0).to_numpy())
    return out


def player_team_features(
    seasons: list[int],
    games: pd.DataFrame,
    pg: pd.DataFrame,
    cfg: RapmConfig | None = None,
    verbose: bool = True,
    save: bool = False,
    prior_provider: PriorProvider | None = None,
    update_ratings: bool = True,
    end_ratings: dict[int, SeasonRapm] | None = None,
) -> pd.DataFrame:
    """Walk-forward player-based team ratings for every D-I game in ``seasons``.

    ``prior_provider`` (optional, e.g. ``box_prior.PlayerPriorProvider``) replaces the
    season-start carry priors and may update player priors day by day from information
    available before each day's first tip. ``None`` = the pure-0.2.0 behaviour.
    ``update_ratings=False`` keeps every player at his season-start prior (no in-season
    RAPM updates; minutes shares still follow the observed rotation): roster
    composition without in-season performance, for the B10r team prior.
    ``end_ratings`` (optional dict) collects each season's end-of-season ratings.

    The first season seeds player priors and is still emitted (with weak priors).
    Returns one row per game: h/a player offense, defense, roster_known flags, n players.
    """
    cfg = cfg or RapmConfig()
    prev: SeasonRapm | None = None
    out = []
    pg = pg[pg["min"].fillna(0) > 0]
    gmeta = games[["game_id", "start_time_utc", "available_at"]]
    for season in seasons:
        p = stints_path(season)
        if p.exists():
            st = pd.read_parquet(p).sort_values("available_at", kind="stable")
        elif prev is not None:
            # no possession data yet (e.g. live season): player priors + ESPN minutes only
            st = pd.DataFrame(
                columns=[
                    "game_id",
                    "available_at",
                    "neutral",
                    "off_home",
                    *OFF,
                    *DEF,
                    "poss",
                    "pts",
                    "garbage",
                    "season",
                ]
            )
            st["available_at"] = pd.to_datetime(st["available_at"], utc=True)
        else:
            continue
        st_avail = _ns(st["available_at"])
        gs = games[
            (games["season"] == season)
            & games["home_team_id"].notna()
            & games["away_team_id"].notna()
            & games["home_is_d1"]
            & games["away_is_d1"]
            & ~games["status"].isin(["STATUS_CANCELED", "STATUS_POSTPONED"])
        ]
        pgs = pg[pg["season"] == season].merge(gmeta, on="game_id", how="inner")
        players = set(st[OFF + DEF].to_numpy().ravel()) | set(pgs["player_id"])
        if prev is not None:
            # carry every previously rated player so pre-season rosters (and live seasons
            # without possession data yet) still map to their priors
            players |= set(prev.players)
        players = sorted(players)
        if prior_provider is not None:
            po, pd_ = prior_provider.start(season, players, prev, cfg)
        else:
            po, pd_ = season_priors(players, prev, cfg)
        inc = IncrementalRapm(
            players, po, pd_, cfg, prev.mu if prev else 104.0, prev.eta if prev else 1.5
        )
        team_sh = {t: TeamShares(x, cfg.minutes_halflife_games) for t, x in pgs.groupby("team_id")}
        prev_sh = _prev_shares(pg[pg["season"] == season - 1])
        added = 0
        for _day, gd in gs.sort_values("start_time_utc").groupby("game_date_et", sort=True):
            cutoff = gd["start_time_utc"].min()
            new_end = int(np.searchsorted(st_avail, _ns_scalar(cutoff), side="left"))
            changed = False
            if new_end > added and update_ratings:
                inc.add(st.iloc[added:new_end])
                added = new_end
                changed = True
            if prior_provider is not None:
                upd = prior_provider.day(_ns_scalar(cutoff))
                if upd is not None:
                    inc.prior[2 : 2 + inc.n] = upd[0]
                    inc.prior[2 + inc.n :] = upd[1]
                    changed = True
            if changed:
                inc.solve()
            n = inc.n
            o_all, d_all = inc.x[2 : 2 + n], inc.x[2 + n :]
            rows = []
            for g in gd.itertuples(index=False):
                rec = {
                    "game_id": g.game_id,
                    "season": season,
                    "rapm_mu": float(inc.x[0]),
                    "rapm_eta": float(inc.x[1]),
                    "rapm_info_poss": float(inc.poss.sum()),
                }
                for side, team in (("h", g.home_team_id), ("a", g.away_team_id)):
                    ts = team_sh.get(team)
                    m = ts.n_available(cutoff) if ts is not None else 0
                    if m > 0:
                        pids, s = ts.shares(m)
                    else:
                        pids, s = prev_sh.get(team, (np.array([]), np.array([])))
                    idx = np.array([inc.index.get(x, -1) for x in pids], dtype=int)
                    oo = (
                        np.where(idx >= 0, o_all[np.clip(idx, 0, None)], cfg.new_o)
                        if len(idx)
                        else np.array([])
                    )
                    dd = (
                        np.where(idx >= 0, d_all[np.clip(idx, 0, None)], cfg.new_d)
                        if len(idx)
                        else np.array([])
                    )
                    if len(s):
                        rec[f"{side}_p_off"] = float((s * oo).sum())
                        rec[f"{side}_p_def"] = float((s * dd).sum())
                        rec[f"{side}_p_n"] = int((s > 0.25).sum())
                        rec[f"{side}_p_top5_share"] = float(np.sort(s)[::-1][:5].sum() / 5)
                    else:
                        rec[f"{side}_p_off"] = 5 * cfg.new_o
                        rec[f"{side}_p_def"] = 5 * cfg.new_d
                        rec[f"{side}_p_n"] = 0
                        rec[f"{side}_p_top5_share"] = np.nan
                    rec[f"{side}_roster_known"] = int(m > 0)
                    rec[f"{side}_games_seen_p"] = m
                rows.append(rec)
            out.append(pd.DataFrame(rows))
        if added < len(st):
            inc.add(st.iloc[added:])
            inc.solve()
        prev = inc.ratings()
        if end_ratings is not None:
            end_ratings[season] = prev
        if save:
            save_end_of_season(prev, season)
        if verbose:
            print(
                f"  rapm {season}: players={len(players)} mu={prev.mu:.1f} eta={prev.eta:.2f}",
                flush=True,
            )
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def save_end_of_season(prev: SeasonRapm, season: int) -> None:
    path = data_dir() / "silver" / "players" / f"rapm_end_{season}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"player_id": prev.players, "o": prev.o, "d": prev.d, "poss": prev.poss}
    ).to_parquet(path, index=False)
