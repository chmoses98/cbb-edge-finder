"""Player-level possession model (Wave 5: B21 shot quality, B22 possession components,
B24 interactions). Preregistered in research/hypotheses/WAVE5.md.

Every quantity is a heavily shrunk player rate built from the player's career (all
teams, transfers included) strictly before the game, and aggregated to the team with
weights that use only earlier games:

* w_p = EWMA (half-life 4 games) of the player's minute share in the team's earlier
  games this season. Before game 1 the weights are last season's final weights of the
  team's players times P(return) (``preseason.return_probabilities``), plus a vacancy
  pseudo-player at the unseen-player prior for the rest.
* Player value before game i = his posterior after his latest earlier game for this
  team this season, else his career posterior through the previous season, else the
  positional prior.

Nothing here reads market data, and no player identity is matched fuzzily.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from cbb_edge.players.availability_model import _pos

HALFLIFE = 4.0
ZONES = ("rim", "j2", "t3")
PTS = {"rim": 2.0, "j2": 2.0, "t3": 3.0}
POSITIONS = ("G", "F", "C")

# (numerator, denominator, kind) per player rate. kind: b = beta-binomial proportion,
# p = gamma-Poisson rate. Denominators are opportunity counts (WAVE5.md, B21 / B22).
RATES: dict[str, tuple[str, str, str]] = {
    "k_rim": ("rim_m", "rim_a", "b"),
    "k_j2": ("j2_m", "j2_a", "b"),
    "k_t3": ("t3_m", "t3_a", "b"),
    "k_ft": ("ftm", "fta", "b"),
    "s_rim": ("rim_a", "pbp_fga", "b"),
    "s_j2": ("j2_a", "pbp_fga", "b"),
    "s_t3": ("t3_a", "pbp_fga", "b"),
    "f": ("fta", "fga", "p"),
    "a": ("ast_m", "pbp_fgm", "b"),
    "u": ("use", "min", "p"),
    "to": ("tov", "use", "b"),
    "astr": ("ast", "ast_opp", "b"),
    "orb": ("orb", "orb_opp", "b"),
    "drb": ("drb", "drb_opp", "b"),
    "stl": ("stl", "stl_opp", "b"),
    "blk": ("blk", "blk_opp", "b"),
    "pf": ("pf", "min", "p"),
}
GROUPS = {  # rates sharing one shrinkage constant
    "s": ("s_rim", "s_j2", "s_t3"),
}
FIXED_KAPPA = {"u": 100.0, "a": 50.0}  # tau_u = 100 minutes, tau_ast = 50 makes (WAVE5.md)
# preregistered grids (WAVE5.md): finishing skill, FT rate, B22 possession components
SKILL_GRID = (25.0, 50.0, 100.0, 200.0, 400.0, 800.0)
SELECT_GRID = (20.0, 50.0, 100.0, 200.0)
B22_GRID = (50.0, 100.0, 200.0, 400.0, 800.0)
GRID = {
    **{r: SKILL_GRID for r in ("k_rim", "k_j2", "k_t3", "k_ft")},
    "f": SELECT_GRID,
    **{r: B22_GRID for r in ("to", "astr", "orb", "drb", "stl", "blk", "pf")},
}


@dataclass
class PlayerPrior:
    kappa: dict[str, float] = field(default_factory=dict)
    pos_mean: dict[str, dict[str, float]] = field(default_factory=dict)  # rate -> pos -> m
    fit: dict[str, object] = field(default_factory=dict)

    def mean(self, rate: str, pos: np.ndarray) -> np.ndarray:
        m = self.pos_mean[rate]
        return np.array([m.get(p, m["F"]) for p in pos])

    def value(self, rate: str, num: np.ndarray, den: np.ndarray, pos: np.ndarray) -> np.ndarray:
        k = self.kappa[rate]
        return (num + k * self.mean(rate, pos)) / (den + k)

    def unseen(self, rate: str, mix: dict[str, float]) -> float:
        return float(sum(w * self.pos_mean[rate][p] for p, w in mix.items()))


# ------------------------------------------------------------------ player rows ------
def player_rows(pg: pd.DataFrame, tg: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """Box + PBP shot counts + opportunity denominators per player-game (min > 0)."""
    x = pg[
        [
            "season", "game_id", "team_id", "player_id", "position", "available_at",
            "min", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "orb", "drb", "ast",
            "stl", "blk", "tov", "pf",
        ]
    ].copy()  # fmt: skip
    for c in x.columns[6:]:
        x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0.0)
    x = x[(x["min"] > 0) & x["team_id"].notna()]
    t = tg[
        [
            "game_id", "team_id", "minutes", "fgm", "fga", "opp_fgm", "opp_fga",
            "opp_fg3a", "poss",
        ]
    ].rename(columns={"fgm": "t_fgm", "fga": "t_fga", "poss": "t_poss"})  # fmt: skip
    x = x.merge(t, on=["game_id", "team_id"], how="left")
    on = (x["min"] / x["minutes"].where(x["minutes"] > 0, 40.0)).clip(0, 1)
    x["use"] = x["fga"] + 0.44 * x["fta"] + x["tov"]
    x["ast_opp"] = (on * x["t_fgm"] - x["fgm"]).clip(lower=0)
    x["orb_opp"] = on * (x["t_fga"] - x["t_fgm"])
    x["drb_opp"] = on * (x["opp_fga"] - x["opp_fgm"])
    x["stl_opp"] = on * x["t_poss"]
    x["blk_opp"] = on * (x["opp_fga"] - x["opp_fg3a"])
    sh = shots.drop(columns=["season", "team_id", "fta", "ftm"], errors="ignore")  # box FT
    x = x.merge(sh, on=["game_id", "player_id"], how="left")
    x["has_pbp"] = x["rim_a"].notna()
    for c in sh.columns:
        if c not in ("game_id", "player_id"):
            x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0.0).astype(float)
    x["pbp_fga"] = x["rim_a"] + x["j2_a"] + x["t3_a"]
    x["pbp_fgm"] = x["rim_m"] + x["j2_m"] + x["t3_m"]
    num = [c for c in x.columns if c.endswith("_opp")] + ["t_poss"]
    x[num] = x[num].fillna(0.0)
    x["pos"] = x["position"].map(_pos)
    x["t"] = pd.to_datetime(x["available_at"], utc=True).astype("int64")
    return x.sort_values(["player_id", "t"]).reset_index(drop=True)


def _counts() -> list[str]:
    return sorted({c for n, d, _ in RATES.values() for c in (n, d)})


def career(x: pd.DataFrame, offset: pd.DataFrame | None = None) -> pd.DataFrame:
    """Career sums strictly before (``cb_<c>``) and through (``ca_<c>``) each row.

    ``offset`` (checkpoint): per player_id career count totals from seasons before
    ``x`` (columns = the count names), added to every row."""
    g = x.groupby("player_id")
    out = x[["player_id", "game_id", "season", "team_id", "pos", "t", "min"]].copy()
    off = offset.set_index("player_id") if offset is not None else None
    for c in _counts():
        cs = g[c].cumsum()
        if off is not None:
            cs = cs + x["player_id"].map(off[c]).fillna(0.0).to_numpy()
        out[f"ca_{c}"] = cs
        out[f"cb_{c}"] = cs - x[c]
        out[c] = x[c]
    return out


def career_totals(x: pd.DataFrame, through_season: int) -> pd.DataFrame:
    """Career count totals per player through ``through_season`` (checkpoint)."""
    return x[x["season"] <= through_season].groupby("player_id")[_counts()].sum().reset_index()


# ------------------------------------------------------------------ DEV fit ----------
def _ll(kind: str, num: np.ndarray, den: np.ndarray, p: np.ndarray) -> float:
    if kind == "b":
        p = np.clip(p, 1e-4, 1 - 1e-4)
        return float(np.sum(num * np.log(p) + (den - num) * np.log(1 - p)))
    lam = np.clip(p * den, 1e-6, None)  # Poisson, constant terms dropped
    return float(np.sum(num * np.log(lam) - lam))


def fit_prior(
    cb: pd.DataFrame,
    dev_seasons: list[int],
    mean_seasons: list[int],
    group_grid: tuple[float, ...] = SELECT_GRID,
) -> PlayerPrior:
    """Positional means pooled over ``mean_seasons``; each kappa by next-game predictive
    log-likelihood on ``dev_seasons`` rows (posterior BEFORE the game)."""
    m = cb[cb["season"].isin(mean_seasons)]
    pos_mean: dict[str, dict[str, float]] = {}
    for r, (n, d, _) in RATES.items():
        gsum = m.groupby("pos")[[n, d]].sum()
        pos_mean[r] = {p: float(gsum.loc[p, n] / gsum.loc[p, d]) for p in gsum.index}
        for p in POSITIONS:
            pos_mean[r].setdefault(p, float(gsum[n].sum() / gsum[d].sum()))
    pr = PlayerPrior(kappa={}, pos_mean=pos_mean, fit={})
    dv = cb[cb["season"].isin(dev_seasons)]
    pos = dv["pos"].to_numpy()
    grouped = {r for rs in GROUPS.values() for r in rs}
    for r, (n, d, kind) in RATES.items():
        if r in FIXED_KAPPA:
            pr.kappa[r] = FIXED_KAPPA[r]
            continue
        if r in grouped:
            continue
        lls = {}
        for k in GRID[r]:
            pr.kappa[r] = k
            p = pr.value(r, dv[f"cb_{n}"].to_numpy(), dv[f"cb_{d}"].to_numpy(), pos)
            lls[k] = _ll(kind, dv[n].to_numpy(), dv[d].to_numpy(), p)
        pr.kappa[r] = max(lls, key=lambda k: lls[k])
        pr.fit[r] = {str(k): v for k, v in lls.items()}
    for gname, rs in GROUPS.items():  # multinomial zone selection, one tau
        lls = {}
        for k in group_grid:
            tot = 0.0
            for r in rs:
                pr.kappa[r] = k
            ps = {
                r: pr.value(
                    r, dv[f"cb_{RATES[r][0]}"].to_numpy(), dv[f"cb_{RATES[r][1]}"].to_numpy(), pos
                )
                for r in rs
            }
            z = sum(ps.values())
            for r in rs:
                tot += float(
                    np.sum(dv[RATES[r][0]].to_numpy() * np.log(np.clip(ps[r] / z, 1e-4, 1)))
                )
            lls[k] = tot
        best = max(lls, key=lambda k: lls[k])
        for r in rs:
            pr.kappa[r] = best
        pr.fit[gname] = {str(k): v for k, v in lls.items()}
    return pr


def posteriors(cb: pd.DataFrame, pr: PlayerPrior, through: bool = True) -> pd.DataFrame:
    """Posterior rates per row: after the game (``through``) or before it."""
    pref = "ca_" if through else "cb_"
    pos = cb["pos"].to_numpy()
    out = pd.DataFrame(index=cb.index)
    for r, (n, d, _) in RATES.items():
        out[r] = pr.value(r, cb[pref + n].to_numpy(), cb[pref + d].to_numpy(), pos)
    z = out[["s_rim", "s_j2", "s_t3"]].sum(axis=1)
    for r in ("s_rim", "s_j2", "s_t3"):
        out[r] = out[r] / z
    return out


# ------------------------------------------------------------------ team aggregation -
TEAM_OUT = (
    "x_rim", "x_j2", "x_t3", "xk_rim", "xk_j2", "xk_t3", "xk_ft", "x_ftr", "x_ast",
    "x_to", "x_astr", "x_orb", "x_drb", "x_stl", "x_blk", "x_pf",
    "i_spacing", "i_handler", "i_rimprot", "i_orbsize", "i_hhi",
)  # fmt: skip


def _aggregate(W: np.ndarray, V: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Team expectations for each row of W (weights) given player values V (same shape)."""
    w = W / np.where(W.sum(1, keepdims=True) > 0, W.sum(1, keepdims=True), 1.0)
    wu = w * V["u"]
    su = wu.sum(1)
    su = np.where(su > 0, su, np.nan)
    out: dict[str, np.ndarray] = {}
    mix = {z: (wu * V[f"s_{z}"]).sum(1) / su for z in ZONES}
    for z in ZONES:
        out[f"x_{z}"] = mix[z]
        a = wu * V[f"s_{z}"]
        out[f"xk_{z}"] = (a * V[f"k_{z}"]).sum(1) / np.where(a.sum(1) > 0, a.sum(1), np.nan)
    a = wu * V["f"]
    out["xk_ft"] = (a * V["k_ft"]).sum(1) / np.where(a.sum(1) > 0, a.sum(1), np.nan)
    out["x_ftr"] = a.sum(1) / su
    out["x_ast"] = (wu * V["a"]).sum(1) / su
    out["x_to"] = (wu * V["to"]).sum(1) / su
    for r in ("astr", "orb", "drb", "stl", "blk"):
        out[f"x_{r}"] = 5.0 * (w * V[r]).sum(1)
    out["x_pf"] = 5.0 * 40.0 * (w * V["pf"]).sum(1)
    shooter = (V["k_t3"] >= 0.35) & (V["s_t3"] >= 0.30)
    out["i_spacing"] = (w * shooter).sum(1)
    out["i_handler"] = np.maximum(0.0, 1.0 - 5.0 * (w * (V["astr"] >= 0.20)).sum(1))
    # top-5 by expected minutes among players WITH weight only (a zero-weight column is
    # a player not yet seen with the team; he must never enter these features)
    order = np.argsort(-w, axis=1, kind="stable")[:, :5]
    rows = np.arange(w.shape[0])[:, None]
    pos_w = w[rows, order] > 0
    blk5 = np.where(pos_w, V["blk"][rows, order], -np.inf)
    out["i_rimprot"] = np.where(pos_w.any(1), blk5.max(1) if blk5.size else 0.0, 0.0)
    orb5 = np.sort(np.where(pos_w, V["orb"][rows, order], -np.inf), axis=1)
    out["i_orbsize"] = np.where(np.isfinite(orb5[:, -2:]), orb5[:, -2:], 0.0).sum(1)
    sh = wu / su[:, None]
    out["i_hhi"] = np.nansum(sh**2, axis=1)
    return out


def team_profiles(
    x: pd.DataFrame,
    pr: PlayerPrior,
    games: pd.DataFrame,
    p_ret: dict[tuple[str, str, int], float] | None = None,
    offset: pd.DataFrame | None = None,
    end_val_init: dict[tuple[str, int], np.ndarray] | None = None,
    end_w_init: dict[tuple[str, int], dict[str, float]] | None = None,
    pos_mix: dict[str, float] | None = None,
    extra_teams: list[tuple[int, str]] | None = None,
) -> pd.DataFrame:
    """Pregame expected team profile per (game, team) from player histories (< tip).

    ``p_ret[(player_id, team_id, season)]`` = P(player of team in season-1 returns),
    used only for the game-1 weights. Also sets ``team_profiles.next_state`` (state after
    all completed games, for upcoming games) — prospective use.

    Checkpoint (live replays only the current season): ``offset`` = career counts before
    ``x``, ``end_val_init`` = end-of-season posteriors of earlier seasons,
    ``end_w_init`` = final EWMA weights of earlier seasons, ``pos_mix`` = the unseen-
    player position mix (default: the first five seasons of ``x``). ``extra_teams``
    (season, team) without completed games get their preseason (game-1) state in
    ``next_state``."""
    cb = career(x, offset)
    after = posteriors(cb, pr, through=True)
    rates = list(RATES)
    if pos_mix is None:
        mx = x[x["season"] < x["season"].min() + 5]["pos"].value_counts(normalize=True)
        pos_mix = {p: float(mx.get(p, 0.0)) for p in POSITIONS}
    mix = pos_mix
    team_profiles.pos_mix = mix  # type: ignore[attr-defined]
    unseen = np.array([pr.unseen(r, mix) for r in rates])
    meta = games.set_index("game_id")["start_time_utc"]
    decay = 0.5 ** (1.0 / HALFLIFE)
    # career posterior through each player's season (for next season's preseason value)
    last = (
        cb.assign(**{f"A_{r}": after[r] for r in rates})
        .groupby(["player_id", "season"], sort=True)
        .tail(1)
    )
    end_val = dict(end_val_init or {})
    end_val |= {
        (p, s): v
        for p, s, v in zip(
            last["player_id"],
            last["season"],
            last[[f"A_{r}" for r in rates]].to_numpy(),
            strict=True,
        )
    }
    recs, nxt = [], {}
    end_w: dict[tuple[str, int], dict[str, float]] = dict(end_w_init or {})
    cbr = pd.concat([cb, after.add_prefix("A_")], axis=1)
    groups = list(cbr.groupby(["season", "team_id"], sort=True))
    seen = {k for k, _ in groups}
    groups += [((s_, t_), cbr.iloc[0:0]) for s_, t_ in extra_teams or [] if (s_, t_) not in seen]
    for (s, team), y in groups:
        gids = meta.reindex(y["game_id"].unique()).sort_values().index.to_numpy()
        cur = sorted(y["player_id"].unique())
        prevw = end_w.get((team, s - 1), {})
        cand = [p for p in prevw if p not in set(cur)]
        pl = cur + cand + ["__vacancy__"]
        n, k = len(pl), len(gids)
        pidx = {q: i for i, q in enumerate(pl)}
        gidx = {g: i for i, g in enumerate(gids)}
        r_ = y["game_id"].map(gidx).to_numpy(dtype=int)
        c_ = y["player_id"].map(pidx).to_numpy(dtype=int)
        S = np.zeros((k, n))
        mins = y["min"].to_numpy()
        S[r_, c_] = mins
        S = S / np.where(S.sum(1, keepdims=True) > 0, S.sum(1, keepdims=True), 1.0)
        # preseason value of each player = career posterior through his latest season < s
        pre = np.tile(unseen, (n, 1))
        for q, i in pidx.items():
            v = None
            for ss in (s - 1, s - 2, s - 3):
                v = end_val.get((q, ss))
                if v is not None:
                    break
            if v is not None:
                pre[i] = v
        # initial weights: last season's final weights x P(return) + vacancy
        w0 = np.zeros(n)
        tot = sum(prevw.values())
        if tot > 0:
            for q, wq in prevw.items():
                pr_ = (p_ret or {}).get((q, team, s), 0.6)
                w0[pidx[q]] = wq / tot * pr_
        w0[pidx["__vacancy__"]] = max(0.0, 1.0 - w0.sum())
        W = np.zeros((k, n))
        ew = w0.copy()
        for i in range(k):
            W[i] = ew
            ew = decay * ew + S[i]
        V: dict[str, np.ndarray] = {}
        A = np.full((k, n, len(rates)), np.nan)
        A[r_, c_] = y[[f"A_{r}" for r in rates]].to_numpy()
        for j, r in enumerate(rates):
            P = pd.DataFrame(A[:, :, j]).ffill().shift(1).to_numpy()
            V[r] = np.where(np.isfinite(P), P, pre[:, j][None, :])
        agg = _aggregate(W, V)
        recs.append(pd.DataFrame({"game_id": gids, "team_id": team, "season": s, **agg}))
        # state after all completed games (upcoming games)
        Vn = {}
        for j, r in enumerate(rates):
            P = pd.DataFrame(A[:, :, j]).ffill().to_numpy()[-1] if k else np.full(n, np.nan)
            Vn[r] = np.where(np.isfinite(P), P, pre[:, j])[None, :]
        nxt[(s, team)] = {kk: float(v[0]) for kk, v in _aggregate(ew[None, :], Vn).items()}
        end_w[(team, s)] = {q: float(ew[i]) for q, i in pidx.items() if q in set(cur)}
    team_profiles.end_values = end_val  # type: ignore[attr-defined]
    team_profiles.next_state = nxt  # type: ignore[attr-defined]
    team_profiles.end_weights = end_w  # type: ignore[attr-defined]
    return pd.concat(recs, ignore_index=True)


# ------------------------------------------------------------------ actuals ----------
def team_actuals(shots: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    """Realised per team-game shot mix / finishing (PBP) + box components."""
    s = shots.groupby(["game_id", "team_id"], as_index=False)[
        ["rim_a", "rim_m", "j2_a", "j2_m", "t3_a", "t3_m", "ast_m"]
    ].sum()
    s["pbp_fga"] = s["rim_a"] + s["j2_a"] + s["t3_a"]
    t = tg[
        [
            "game_id", "team_id", "opp_id", "season", "start_time_utc", "fga", "fgm", "fta",
            "tov", "orb", "drb", "stl", "blk", "pf", "opp_fga", "opp_fgm", "opp_fg3a",
            "poss", "pts", "efg", "to_rate", "ftr", "orb_rate", "fg2_pct", "fg3_pct", "ppp",
        ]
    ]  # fmt: skip
    out = t.merge(s, on=["game_id", "team_id"], how="left")
    keep = ("game_id", "team_id", "opp_id", "start_time_utc", "season")
    num = [c for c in out.columns if c not in keep]
    out[num] = out[num].apply(pd.to_numeric, errors="coerce").astype(float)
    return out


DEF_TERMS = ("rim", "t3", "ftr", "rimpct")


def _def_contrib(act: pd.DataFrame, prof: pd.DataFrame) -> pd.DataFrame:
    """Per (game, offence) contribution to the DEFENDER's allowed excess. Games without
    PBP (or without the offence's expectation) contribute zero (numerator and
    denominator), so every game of the defender still gets its pregame running state."""
    a = act.merge(
        prof[["game_id", "team_id", "x_rim", "x_t3", "x_ftr", "xk_rim"]],
        on=["game_id", "team_id"],
        how="left",
    )
    hasx = a["x_rim"].notna()
    ok = hasx & (a["pbp_fga"].fillna(0) > 0)
    okf = hasx & (a["fga"].fillna(0) > 0)
    z = 0.0
    a["n_rim"] = np.where(ok, a["rim_a"] - a["x_rim"] * a["pbp_fga"], z)
    a["d_rim"] = np.where(ok, a["pbp_fga"], z)
    a["n_t3"] = np.where(ok, a["t3_a"] - a["x_t3"] * a["pbp_fga"], z)
    a["d_t3"] = a["d_rim"]
    a["n_rimpct"] = np.where(ok, a["rim_m"] - a["xk_rim"] * a["rim_a"], z)
    a["d_rimpct"] = np.where(ok, a["rim_a"], z)
    a["n_ftr"] = np.where(okf, a["fta"] - a["x_ftr"] * a["fga"], z)
    a["d_ftr"] = np.where(okf, a["fga"], z)
    a = a.rename(columns={"team_id": "off_id", "opp_id": "def_id"})
    a = a[a["def_id"].notna()]
    return a.sort_values(["start_time_utc", "game_id"]).reset_index(drop=True)


def defense_excess(act: pd.DataFrame, prof: pd.DataFrame, k_def: float) -> pd.DataFrame:
    """Per (game, defending team): shrunk season-to-date allowed excess of opponents'
    rim / 3PA share, FT rate and rim FG% over the opponents' own player-based
    expectations, from the defender's EARLIER games only (n / (n + k_def))."""
    a = _def_contrib(act, prof)
    g = a.groupby(["season", "def_id"])
    out = a[["game_id", "def_id", "season", "start_time_utc"]].copy()
    for t in DEF_TERMS:
        num = g[f"n_{t}"].cumsum() - a[f"n_{t}"]
        den = g[f"d_{t}"].cumsum() - a[f"d_{t}"]
        out[f"def_{t}"] = num / (den + k_def)
    # same-day games must not see each other: use the state before the day's first game
    out["day"] = (
        pd.to_datetime(out["start_time_utc"], utc=True).dt.tz_convert("America/New_York").dt.date
    )
    cols = [f"def_{t}" for t in DEF_TERMS]
    out[cols] = out.groupby(["def_id", "day"])[cols].transform("first")
    return out.drop(columns=["day", "start_time_utc"])


def defense_next(act: pd.DataFrame, prof: pd.DataFrame, k_def: float) -> pd.DataFrame:
    """State after ALL completed games (prospective: upcoming games)."""
    a = _def_contrib(act, prof)
    g = a.groupby(["season", "def_id"])[[f"{x}_{t}" for t in DEF_TERMS for x in "nd"]].sum()
    out = pd.DataFrame(index=g.index)
    for t in DEF_TERMS:
        out[f"def_{t}"] = g[f"n_{t}"] / (g[f"d_{t}"] + k_def)
    return out.reset_index()


def league_running(
    act: pd.DataFrame,
    games: pd.DataFrame,
    prev_full: dict[int, tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """League rim / 3PA share over all PBP games on days BEFORE each scheduled game day
    of the season; before any such day: the previous season's full-season mean
    (``prev_full[season - 1]`` overrides / supplies it, e.g. from a checkpoint)."""
    a = act[act["pbp_fga"].fillna(0) > 0][["game_id", "rim_a", "t3_a", "pbp_fga"]]
    a = a.merge(games[["game_id", "season", "game_date_et"]], on="game_id")
    d = a.groupby(["season", "game_date_et"])[["rim_a", "t3_a", "pbp_fga"]].sum()
    days = games[["season", "game_date_et"]].drop_duplicates()
    d = days.merge(d.reset_index(), on=["season", "game_date_et"], how="left").fillna(
        {"rim_a": 0.0, "t3_a": 0.0, "pbp_fga": 0.0}
    )
    d = d.sort_values(["season", "game_date_et"]).reset_index(drop=True)
    g = d.groupby("season")
    for c in ("rim_a", "t3_a", "pbp_fga"):
        d[f"c_{c}"] = g[c].cumsum() - d[c]
    full = d.groupby("season")[["rim_a", "t3_a", "pbp_fga"]].sum()
    fm = {
        int(s): (r.rim_a / r.pbp_fga, r.t3_a / r.pbp_fga)
        for s, r in full.iterrows()
        if r.pbp_fga > 0
    }
    fm.update(prev_full or {})
    ok = d["c_pbp_fga"] > 0
    den = d["c_pbp_fga"].where(ok, 1.0)
    for i, (c, n) in enumerate((("lg_rim", "c_rim_a"), ("lg_t3", "c_t3_a"))):
        fb = d["season"].map(lambda s, i=i: fm.get(int(s) - 1, (np.nan, np.nan))[i])
        d[c] = np.where(ok, d[n] / den, fb)
    return d[["season", "game_date_et", "lg_rim", "lg_t3"]]
