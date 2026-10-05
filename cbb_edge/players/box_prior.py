"""Box-score-informed player priors (SPM) and transfer translation (B11 / B12).

Everything is fitted walk-forward: the model used for season ``s`` is fitted only on
player-season pairs whose *later* season is < s (expanding window). Nothing is tuned on
validation seasons; the fixed choices are documented constants (ridge alpha, weak-RAPM
λ, minimum possessions, in-season box half-weight minutes).

Targets are next-observed-season *weak-prior* RAPM (λ=100, zero prior mean), so they are
not dominated by the priors being learned. Predictors, from the player's previous
observed season (s-1, or s-2 for pre-2021 sit-out transfers):

* ``rapm``  – end-of-season walk-forward RAPM (what the engine actually carries);
* ``spm``   – box-score SPM: ridge of weak RAPM on per-40 box, TS%, 3PA rate and listed
              position (fitted on the same expanding window);
* ``dstr``  – transfers only: new team − old team end-of-season engine net rating
              (both from the previous season, known preseason).

Variants (``kind``): ``rapm`` (RAPM carry), ``box`` (SPM only), ``both`` (weights from
data). Only relative quantities are fitted (see ``fit_prior_model``); the overall carry
scale is the DEV-tuned wave-2 value. Transfers get their own regression (+ dstr), applied from the moment the
player first appears for his new team — never before (historically his destination is
not known preseason). During the season the prior is blended with SPM of the player's
season-to-date box line, weight ``m / (m + BOX_HALF_MINUTES)``.

New players with no D-I history keep the generic newcomer prior (no recruiting data is
used — none is available free in a leakage-safe form).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge

from cbb_edge.data.http import data_dir
from cbb_edge.players.rapm import (
    DEF,
    OFF,
    IncrementalRapm,
    RapmConfig,
    SeasonRapm,
    _ns,
    season_priors,
)
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
    "pos_g",
    "pos_c",
]
BOX_COLS = ["pts", "ast", "orb", "drb", "stl", "blk", "tov", "pf", "fga", "fg3a", "fta"]
BOX_HALF_MINUTES = 400.0
WEAK_LAMBDA = 100.0
MIN_POSS = 300.0


def box_features(x: pd.DataFrame) -> pd.DataFrame:
    """Per-40 / rate features from player box sums (needs ``minutes`` + BOX_COLS)."""
    m40 = x["minutes"].clip(lower=1) / 40.0
    X = pd.DataFrame(index=x.index)
    for c in ("pts", "ast", "orb", "drb", "stl", "blk", "tov", "pf", "fga", "fta"):
        X[f"{c}_40"] = (x[c] / m40).clip(upper=60)
    att = 2 * (x["fga"] + 0.475 * x["fta"])
    X["ts"] = (x["pts"] / att.replace(0, np.nan)).fillna(0.5).clip(0, 1)
    X["fg3a_rate"] = (x["fg3a"] / x["fga"].replace(0, np.nan)).fillna(0.3)
    pos = (
        x["position"].fillna("").astype(str).str.upper()
        if "position" in x
        else pd.Series("", index=x.index)
    )
    X["pos_g"] = pos.str.startswith("G").astype(float)
    X["pos_c"] = pos.str.startswith("C").astype(float)
    return X


def weak_rapm(season: int, lam: float = WEAK_LAMBDA) -> pd.DataFrame:
    p = data_dir() / "silver" / "players" / f"rapm_weak_{season}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    st = pd.read_parquet(stints_path(season))
    players = sorted(set(st[OFF + DEF].to_numpy().ravel()))
    cfg = RapmConfig(lam_o=lam, lam_d=lam, new_o=0.0, new_d=0.0)
    z = np.zeros(len(players))
    inc = IncrementalRapm(players, z, z.copy(), cfg)
    inc.add(st)
    inc.solve()
    r = inc.ratings()
    out = pd.DataFrame(
        {"player_id": r.players, "season": season, "w_o": r.o, "w_d": r.d, "w_poss": r.poss}
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p, index=False)
    return out


@dataclass
class PriorModel:
    kind: str
    spm_o: list[float] = field(default_factory=list)  # [intercept, *coef] (SPM_FEATURES)
    spm_d: list[float] = field(default_factory=list)
    ret_o: list[float] = field(default_factory=list)  # [c0, c_rapm, c_spm]
    ret_d: list[float] = field(default_factory=list)
    tr_o: list[float] = field(default_factory=list)  # [c0, c_rapm, c_spm, c_dstr]
    tr_d: list[float] = field(default_factory=list)
    n_ret: int = 0
    n_tr: int = 0
    last_pair_season: int = 0

    def spm(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        A = X[SPM_FEATURES].to_numpy(dtype=float)
        return (
            self.spm_o[0] + A @ np.asarray(self.spm_o[1:]),
            self.spm_d[0] + A @ np.asarray(self.spm_d[1:]),
        )


def pair_table(ps: pd.DataFrame, team_net: pd.DataFrame, last_season: int) -> pd.DataFrame:
    """Player-season pairs (season s -> next observed season s' <= last_season) with the
    weak-RAPM target, walk-forward RAPM predictor, box features and team change."""
    x = ps[ps["next_season"].notna() & (ps["next_season"] <= last_season)]
    x = x[(x["next_season"] - x["season"] <= 2) & x["rapm_o"].notna()]
    x = x.assign(next_season=x["next_season"].astype(int))
    seasons = sorted(set(x["season"].astype(int)) | set(x["next_season"]))
    seasons = [s for s in seasons if stints_path(s).exists()]
    if not seasons:
        return x.iloc[0:0]
    weak = pd.concat([weak_rapm(s) for s in seasons])
    cur = weak.rename(columns={"w_o": "c_o", "w_d": "c_d", "w_poss": "c_poss"})
    nxt = weak.rename(
        columns={"season": "next_season", "w_o": "n_o", "w_d": "n_d", "w_poss": "n_poss"}
    )
    x = x.merge(cur, on=["player_id", "season"], how="inner")
    x = x.merge(nxt, on=["player_id", "next_season"], how="inner")
    x = x[(x["n_poss"] >= MIN_POSS) & (x["c_poss"] >= MIN_POSS)].reset_index(drop=True)
    net = team_net.set_index(["team_id", "season"])["net"]
    old = net.reindex(pd.MultiIndex.from_arrays([x["team_id"], x["season"]])).to_numpy()
    new = net.reindex(pd.MultiIndex.from_arrays([x["next_team"], x["next_season"] - 1])).to_numpy()
    return x.assign(dstr=np.nan_to_num(new - old), transfer=x["next_team"] != x["team_id"])


def fit_prior_model(
    pairs: pd.DataFrame, kind: str, last_season: int, carry: float = 0.95
) -> PriorModel:
    """SPM + carry / translation coefficients.

    Next-season targets are only observed for players who played enough next season,
    which selects "survivors" and biases any intercept (and the absolute slope) upward.
    So only RELATIVE quantities are taken from the data, through the origin:

    * RAPM vs SPM weights (``both``): next ~ b_r*rapm + b_s*spm, normalized to sum 1;
    * transfer persistence: k = slope(transfers) / slope(returners) of next ~ combined
      predictor, and the team-change effect g = slope(dstr) / slope(returners);

    while the overall scale is the DEV-tuned wave-2 carry (0.95) and players without
    history keep the DEV-tuned newcomer constants.
    """
    pm = PriorModel(kind=kind, last_pair_season=last_season)
    X = box_features(pairs)
    w = pairs["c_poss"].clip(upper=3000)
    for side, tgt in (("o", "c_o"), ("d", "c_d")):
        m = Ridge(alpha=50.0).fit(X[SPM_FEATURES], pairs[tgt], sample_weight=w)
        setattr(pm, f"spm_{side}", [float(m.intercept_), *map(float, m.coef_)])
    so, sd = pm.spm(X)
    d = pairs.assign(spm_o=so, spm_d=sd)
    wn = d["n_poss"].clip(upper=3000)
    ret = d[~d["transfer"]]
    tr = d[d["transfer"]]
    pm.n_ret, pm.n_tr = len(ret), len(tr)
    for side, r, s_, tgt in (("o", "rapm_o", "spm_o", "n_o"), ("d", "rapm_d", "spm_d", "n_d")):
        if kind == "rapm":
            wr, ws = 1.0, 0.0
        elif kind == "box":
            wr, ws = 0.0, 1.0
        else:
            b = (
                LinearRegression(fit_intercept=False)
                .fit(ret[[r, s_]], ret[tgt], sample_weight=wn[ret.index])
                .coef_
            )
            b = np.clip(b, 0.0, None)
            wr, ws = (b / b.sum()) if b.sum() > 0 else (1.0, 0.0)
        comb_ret = wr * ret[r] + ws * ret[s_]
        b_ret = float(
            LinearRegression(fit_intercept=False)
            .fit(comb_ret.to_frame(), ret[tgt], sample_weight=wn[ret.index])
            .coef_[0]
        )
        k, g = 1.0, 0.0
        if len(tr) >= 60 and b_ret > 0:
            comb_tr = wr * tr[r] + ws * tr[s_]
            bt = (
                LinearRegression(fit_intercept=False)
                .fit(
                    pd.DataFrame({"c": comb_tr, "dstr": tr["dstr"]}),
                    tr[tgt],
                    sample_weight=wn[tr.index],
                )
                .coef_
            )
            k, g = float(np.clip(bt[0] / b_ret, 0.0, 1.5)), float(bt[1] / b_ret)
        setattr(pm, f"ret_{side}", [0.0, carry * wr, carry * ws])
        setattr(pm, f"tr_{side}", [0.0, carry * k * wr, carry * k * ws, carry * g])
    return pm


class PlayerPriorProvider:
    """Walk-forward player prior provider for ``rapm.player_team_features``.

    ``start`` gives season-start priors from each player's previous observed season;
    ``day`` gives updated priors from information available before a cutoff: transfer
    translation once the player has appeared for a new team, and the in-season SPM blend.
    """

    def __init__(
        self,
        ps: pd.DataFrame,
        pg: pd.DataFrame,
        team_net: pd.DataFrame,
        kind: str = "both",
        box_update: bool = True,
        translate: bool = True,
        half_minutes: float = BOX_HALF_MINUTES,
        carry: float = 0.95,
    ):
        self.carry = carry
        self.ps = ps
        self.pg = pg
        self.kind = kind
        self.box_update = box_update
        self.translate = translate
        self.half = half_minutes
        self.team_net_df = team_net
        self.team_net = team_net.set_index(["team_id", "season"])["net"].to_dict()
        self.models: dict[int, PriorModel] = {}
        self.ends: dict[int, SeasonRapm] = {}

    def model(self, season: int) -> PriorModel | None:
        if season not in self.models:
            pairs = pair_table(self.ps, self.team_net_df, season - 1)
            self.models[season] = (
                fit_prior_model(pairs, self.kind, season - 1, self.carry)
                if len(pairs) >= 1000
                else None
            )
        return self.models[season]

    def _history(self, season: int, players: list[str]) -> pd.DataFrame:
        h = self.ps[(self.ps["season"] < season) & (self.ps["season"] >= season - 2)]
        h = h.sort_values("season").drop_duplicates("player_id", keep="last")
        h = h.set_index("player_id").reindex(players)
        ro = np.full(len(players), np.nan)
        rd = np.full(len(players), np.nan)
        hs = h["season"].to_numpy()
        for s in (season - 2, season - 1):
            r = self.ends.get(s)
            if r is None:
                continue
            idx = {p: i for i, p in enumerate(r.players)}
            for i, p in enumerate(players):
                j = idx.get(p)
                if j is not None and r.poss[j] > 0 and hs[i] == s:
                    ro[i], rd[i] = r.o[j], r.d[j]
        return h.assign(rapm_o_run=ro, rapm_d_run=rd)

    def start(
        self, season: int, players: list[str], prev: SeasonRapm | None, cfg: RapmConfig
    ) -> tuple[np.ndarray, np.ndarray]:
        n = len(players)
        po, pd_ = np.full(n, cfg.new_o), np.full(n, cfg.new_d)
        if prev is not None:
            self.ends[season - 1] = prev
        pm = self.model(season)
        self._pm = None
        if pm is None:  # no earlier pairs to fit on: plain carry priors, no updates
            return season_priors(players, prev, cfg)
        h = self._history(season, players)
        have = np.where(h["season"].notna().to_numpy())[0]
        self._players, self._hist, self._pm, self._season = players, h, pm, season
        self._hv = None
        if len(have):
            hh = h.iloc[have]
            X = box_features(hh[["minutes", *BOX_COLS]].fillna(0).assign(position=hh["position"]))
            so, sd = pm.spm(X)
            ro = np.where(np.isfinite(hh["rapm_o_run"]), hh["rapm_o_run"], so)
            rd = np.where(np.isfinite(hh["rapm_d_run"]), hh["rapm_d_run"], sd)
            po[have] = pm.ret_o[0] + pm.ret_o[1] * ro + pm.ret_o[2] * so
            pd_[have] = pm.ret_d[0] + pm.ret_d[1] * rd + pm.ret_d[2] * sd
            self._hv = {
                "idx": have,
                "ro": ro,
                "rd": rd,
                "so": so,
                "sd": sd,
                "team": hh["team_id"].to_numpy(),
                "season": hh["season"].to_numpy().astype(int),
            }
        self._base = (po.copy(), pd_.copy())
        x = self.pg[(self.pg["season"] == season) & self.pg["player_id"].isin(set(players))]
        x = x.assign(t=_ns(x["available_at"])).sort_values("t", kind="stable")
        self._x, self._t, self._ptr = x, x["t"].to_numpy(), 0
        self._cum = pd.DataFrame(
            0.0, index=pd.Index(players, name="player_id"), columns=["minutes", *BOX_COLS]
        )
        self._pos = pd.Series("", index=self._cum.index, dtype=object)
        first = x.drop_duplicates("player_id")
        self._first = dict(
            zip(first["player_id"], zip(first["t"], first["team_id"], strict=True), strict=True)
        )
        return po, pd_

    def day(self, cutoff_ns: int) -> tuple[np.ndarray, np.ndarray] | None:
        if self._pm is None:
            return None
        end = int(np.searchsorted(self._t, cutoff_ns, side="left"))
        if end <= self._ptr:
            return None
        new = self._x.iloc[self._ptr : end]
        self._ptr = end
        add = new.groupby("player_id")[["min", *BOX_COLS]].sum().rename(columns={"min": "minutes"})
        self._cum.loc[add.index, add.columns] += add.to_numpy()
        pos = new.drop_duplicates("player_id", keep="last").set_index("player_id")["position"]
        self._pos.loc[pos.index] = pos.fillna("").astype(str).to_numpy()
        po, pd_ = self._base[0].copy(), self._base[1].copy()
        pm = self._pm
        if self.translate and self._hv is not None:
            hv = self._hv
            for k, i in enumerate(hv["idx"]):
                f = self._first.get(self._players[i])
                if f is None or f[0] >= cutoff_ns or f[1] == hv["team"][k]:
                    continue
                ds = self.team_net.get((f[1], self._season - 1), np.nan) - self.team_net.get(
                    (hv["team"][k], hv["season"][k]), np.nan
                )
                ds = float(ds) if np.isfinite(ds) else 0.0
                po[i] = pm.tr_o[0] + pm.tr_o[1] * hv["ro"][k] + pm.tr_o[2] * hv["so"][k]
                po[i] += pm.tr_o[3] * ds
                pd_[i] = pm.tr_d[0] + pm.tr_d[1] * hv["rd"][k] + pm.tr_d[2] * hv["sd"][k]
                pd_[i] += pm.tr_d[3] * ds
        if self.box_update:
            m = self._cum["minutes"].to_numpy()
            on = m > 0
            if on.any():
                X = box_features(self._cum[on].assign(position=self._pos[on]))
                so, sd = pm.spm(X)
                w = m[on] / (m[on] + self.half)
                po[on] = (1 - w) * po[on] + w * so
                pd_[on] = (1 - w) * pd_[on] + w * sd
        return po, pd_
