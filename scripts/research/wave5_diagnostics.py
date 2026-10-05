"""Wave-5 diagnostics (preregistered in research/hypotheses/WAVE5.md; NOT eligible,
never used to tune anything). Reads the Wave-5 OOS predictions and pure silver tables.

    python scripts/research/wave5_diagnostics.py [section ...]
    sections: components decomposition first_game uncertainty scale totals

Writes research/wave5/diagnostics_<section>.json (+ csv tables). No market data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

from cbb_edge.data.http import data_dir
from cbb_edge.model.arms import matchup_features

sys.path.insert(0, str(Path(__file__).parent))
import run_wave3 as w3  # noqa: E402
import run_wave5 as w5  # noqa: E402

OUT = w5.OUT
VALID = list(range(2015, 2025))
HIST = [2025, 2026]
GS_BUCKETS = [(-1, 0, "0"), (1, 4, "1-4"), (5, 9, "5-9"), (10, 19, "10-19"), (20, 99, "20+")]


def _rmse(e) -> float:
    e = np.asarray(e, float)
    return float(np.sqrt(np.nanmean(e**2)))


def _metrics(pred: pd.Series, act: pd.Series, gs: pd.Series | None = None) -> dict:
    ok = pred.notna() & act.notna() & np.isfinite(pred) & np.isfinite(act)
    p, a = pred[ok].astype(float), act[ok].astype(float)
    e = a - p
    slope = float(np.polyfit(p, a, 1)[0]) if p.std() > 0 else float("nan")
    out = {
        "n": int(ok.sum()),
        "mae": float(e.abs().mean()),
        "rmse": _rmse(e),
        "bias_actual_minus_pred": float(e.mean()),
        "calibration_slope": slope,
        "corr": float(np.corrcoef(p, a)[0, 1]),
    }
    if gs is not None:
        g = gs[ok]
        out["rmse_by_games_seen"] = {
            lab: _rmse(e[(g >= lo) & (g <= hi)]) for lo, hi, lab in GS_BUCKETS
        }
    return out


class Data:
    def __init__(self) -> None:
        self.ctx = w3.Ctx()
        self.df = w5.b20_frame(self.ctx)
        self.pf = w5.load_possession(self.df)
        pp = pd.read_parquet(w5.WORK / "pure_predictions.parquet")
        self.pp = pp.set_index("game_id").loc[self.df["game_id"]].reset_index()
        self.mf = matchup_features(self.df)
        self.act = pd.read_parquet(w5.WORK / "team_actuals.parquet")

    def sides(self) -> pd.DataFrame:
        """One row per (game, offence side) with expectations and actuals."""
        df, pf, mf, pp = self.df, self.pf, self.mf, self.pp
        rows = []
        for side, o, d, team, opp in (
            ("h", "h", "a", "home_team_id", "away_team_id"),
            ("a", "a", "h", "away_team_id", "home_team_id"),
        ):
            r = pd.DataFrame(
                {
                    "game_id": df["game_id"],
                    "season": df["season"],
                    "side": side,
                    "team_id": df[team],
                    "opp_id": df[opp],
                    "games_seen": df[f"{o}_games_seen"],
                    "month": pd.to_datetime(df["start_time_utc"], utc=True).dt.month,
                    "poss_hat": mf["poss"],
                    "eff_hat": mf[f"eff_{side}"],
                    "efg_hat": mf.get(f"efg_{side}"),
                    "to_hat": mf.get(f"to_{side}"),
                    "orb_hat": mf.get(f"orb_{side}"),
                    "ftr_hat": mf.get(f"ftr_{side}"),
                    "fg2_hat": df["mu_fg2"] + df[f"{o}_off_fg2"] + df[f"{d}_def_fg2"]
                    + (1 if side == "h" else -1) * df["eta_fg2"] * df["L"],
                    "fg3_hat": df["mu_fg3"] + df[f"{o}_off_fg3"] + df[f"{d}_def_fg3"]
                    + (1 if side == "h" else -1) * df["eta_fg3"] * df["L"],
                    "fg3a_rate_hat": df["mu_fg3a_rate"] + df[f"{o}_off_fg3a_rate"]
                    + df[f"{d}_def_fg3a_rate"],
                    "p_mix_rim": None,
                    "B20_pts": (pp["B20_total"] + (1 if side == "h" else -1) * pp["B20_margin"]) / 2,
                    "B25_pts": (pp["B25_total"] + (1 if side == "h" else -1) * pp["B25_margin"]) / 2,
                }
            )  # fmt: skip
            m = {
                z: (pf[f"{o}_x_{z}"] + (pf[f"{d}_def_{z}"] if z != "j2" else 0)).clip(0.02, 0.9)
                for z in ("rim", "t3", "j2")
            }
            zs = m["rim"] + m["t3"] + m["j2"]
            for z in m:
                r[f"p_mix_{z}"] = (m[z] / zs).to_numpy()
            k_rim = pf[f"{o}_xk_rim"] + pf[f"{d}_def_rimpct"]
            r["p_pps"] = (
                2 * r["p_mix_rim"] * k_rim + 2 * r["p_mix_j2"] * pf[f"{o}_xk_j2"]
                + 3 * r["p_mix_t3"] * pf[f"{o}_xk_t3"]
            ).to_numpy()  # fmt: skip
            r["p_fg2"] = (
                (r["p_mix_rim"] * k_rim + r["p_mix_j2"] * pf[f"{o}_xk_j2"])
                / (r["p_mix_rim"] + r["p_mix_j2"])
            ).to_numpy()
            r["p_fg3"] = pf[f"{o}_xk_t3"].to_numpy()
            r["p_to"] = (pf[f"{o}_x_to"] + 0 * pf[f"{d}_x_stl"]).to_numpy()
            r["p_orb"] = pf[f"{o}_x_orb"].to_numpy()
            r["p_ftr"] = (pf[f"{o}_x_ftr"] + pf[f"{d}_def_ftr"]).to_numpy()
            rows.append(r)
        s = pd.concat(rows, ignore_index=True)
        a = self.act.rename(columns={"team_id": "team_id"})
        s = s.merge(
            a[
                [
                    "game_id", "team_id", "poss", "pts", "efg", "to_rate", "ftr", "orb_rate",
                    "fg2_pct", "fg3_pct", "ppp", "pbp_fga", "rim_a", "t3_a", "j2_a", "fga",
                ]
            ],
            on=["game_id", "team_id"],
            how="left",
        )  # fmt: skip
        tg = self.ctx.tg[["game_id", "team_id", "fg3a"]]
        return s.merge(tg, on=["game_id", "team_id"], how="left")


# ------------------------------------------------------------------ components -------
def components(D: Data) -> dict:
    s = D.sides()
    s["act_rim"] = s["rim_a"] / s["pbp_fga"].where(s["pbp_fga"] > 0)
    s["act_t3"] = s["t3_a"] / s["pbp_fga"].where(s["pbp_fga"] > 0)
    s["act_3par"] = s["fg3a"] / s["fga"].where(s["fga"] > 0)
    # team-level baseline for the PBP shot mix: own season-to-date share, shrunk to the
    # league (n / (n + 200) FGA), information before the game
    s = s.sort_values(["season", "team_id", "game_id"])
    t = D.act.sort_values("start_time_utc").copy()
    g = t.groupby(["season", "team_id"])
    pb = t[t["pbp_fga"] > 0].groupby("season")
    for z in ("rim", "t3"):
        num = g[f"{z}_a"].cumsum() - t[f"{z}_a"].fillna(0)
        den = g["pbp_fga"].cumsum() - t["pbp_fga"].fillna(0)
        # league anchor: PREVIOUS season's share (known before the season)
        lg = t["season"].map((pb[f"{z}_a"].sum() / pb["pbp_fga"].sum()).shift(1))
        t[f"team_{z}"] = (num.fillna(0) + 200 * lg) / (den.fillna(0) + 200)
    s = s.merge(
        t[["game_id", "team_id", "team_rim", "team_t3"]], on=["game_id", "team_id"], how="left"
    )
    rep: dict = {"note": "validation 2015-2024 unless stated; actuals from silver team_games / PBP"}
    for split, seasons in (("validation", VALID), ("2025_26", [2026])):
        x = s[s["season"].isin(seasons)]
        gs = x["games_seen"]
        r = {
            "possessions_engine": _metrics(x["poss_hat"], x["poss"], gs),
            "ppp_engine": _metrics(x["eff_hat"] / 100, x["ppp"], gs),
            "points_B20": _metrics(x["B20_pts"], x["pts"], gs),
            "points_B25": _metrics(x["B25_pts"], x["pts"], gs),
            "efg_engine": _metrics(x["efg_hat"] / 100, x["efg"], gs),
            "efg_player_xpps_over_2": _metrics(x["p_pps"] / 2, x["efg"], gs),
            "fg2_engine": _metrics(x["fg2_hat"] / 100, x["fg2_pct"], gs),
            "fg2_player": _metrics(x["p_fg2"], x["fg2_pct"], gs),
            "fg3_engine": _metrics(x["fg3_hat"] / 100, x["fg3_pct"], gs),
            "fg3_player": _metrics(x["p_fg3"], x["fg3_pct"], gs),
            "three_pa_rate_engine": _metrics(x["fg3a_rate_hat"] / 100, x["act_3par"], gs),
            "three_pa_share_player": _metrics(x["p_mix_t3"], x["act_t3"], gs),
            "three_pa_share_team_baseline": _metrics(x["team_t3"], x["act_t3"], gs),
            "rim_share_player": _metrics(x["p_mix_rim"], x["act_rim"], gs),
            "rim_share_team_baseline": _metrics(x["team_rim"], x["act_rim"], gs),
            "to_rate_engine": _metrics(x["to_hat"] / 100, x["to_rate"], gs),
            "to_rate_player": _metrics(x["p_to"], x["to_rate"], gs),
            "orb_rate_engine": _metrics(x["orb_hat"] / 100, x["orb_rate"], gs),
            "orb_rate_player": _metrics(x["p_orb"], x["orb_rate"], gs),
            "ft_rate_engine": _metrics(x["ftr_hat"] / 100, x["ftr"], gs),
            "ft_rate_player": _metrics(x["p_ftr"], x["ftr"], gs),
        }
        rep[split] = r
    return rep


# ------------------------------------------------------------------ decomposition ----
def decomposition(D: Data) -> dict:
    """Points error of B25 per offence side, regressed on the component errors
    (possessions, eFG, TO, ORB, FT rate): coefficient x error variance share."""
    s = D.sides()
    s = s[s["season"].isin(VALID)].dropna(
        subset=["pts", "poss", "efg", "to_rate", "orb_rate", "ftr", "efg_hat"]
    )
    y = s["pts"] - s["B25_pts"]
    Xc = pd.DataFrame(
        {
            "pace": (s["poss"] - s["poss_hat"]) * s["eff_hat"] / 100,
            "shot_making": s["efg"] - s["efg_hat"] / 100,
            "turnovers": s["to_rate"] - s["to_hat"] / 100,
            "off_rebounds": s["orb_rate"] - s["orb_hat"] / 100,
            "free_throws": s["ftr"] - s["ftr_hat"] / 100,
        }
    )
    A = np.column_stack([np.ones(len(Xc)), Xc.to_numpy()])
    beta, *_ = np.linalg.lstsq(A, y.to_numpy(), rcond=None)
    contrib = Xc.to_numpy() * beta[1:]
    var = contrib.var(axis=0)
    cov = np.cov(np.column_stack([contrib, y]).T)[:-1, -1]
    out = {
        "target": "team points error, B25 OOS, validation 2015-2024, per offence side",
        "n_side_games": len(y),
        "points_error_sd": float(y.std()),
        "r2": float(1 - np.var(y - A @ beta) / np.var(y)),
        "components": {
            c: {
                "coef": float(beta[i + 1]),
                "contrib_sd": float(np.sqrt(var[i])),
                "share_of_error_variance": float(cov[i] / np.var(y)),
            }
            for i, c in enumerate(Xc.columns)
        },
    }
    # home/away offence and defence: home-side errors are home offence = away defence
    for side in ("h", "a"):
        e = (s["pts"] - s["B25_pts"])[s["side"] == side]
        out[f"{'home' if side == 'h' else 'away'}_offence_points_error"] = {
            "rmse": _rmse(e),
            "bias_actual_minus_pred": float(e.mean()),
        }
    return out


# ------------------------------------------------------------------ first game -------
def _team_season_table(D: Data) -> pd.DataFrame:
    ps = D.ctx.ps
    pre = D.ctx.pre()
    g = ps.groupby(["team_id", "season"])
    tab = pd.DataFrame(
        {
            "transfer_in_n": g["transfer_in"].sum(),
            "transfer_in_min_share": g.apply(
                lambda x: (
                    (x["min_share"] * x["transfer_in"]).sum() / max(x["min_share"].sum(), 1e-9)
                ),
                include_groups=False,
            ),
            "newcomers_n": g.apply(
                lambda x: int((x["seasons_prior"].fillna(0) == 0).sum()), include_groups=False
            ),
            "rotation_prior_d1_share": g.apply(
                lambda x: (
                    float((x.loc[x["min_share"] >= 0.25, "seasons_prior"].fillna(0) > 0).mean())
                    if (x["min_share"] >= 0.25).any()
                    else np.nan
                ),
                include_groups=False,
            ),
        }
    ).reset_index()
    tab = tab.merge(pre[["team_id", "season", "ret_min", "ret_impact", "pre_net"]], how="left")
    fin = D.ctx.finals9.assign(prev_net=lambda f: f["o"] - f["d"])[
        ["team_id", "season", "prev_net"]
    ]
    fin = fin.assign(season=fin["season"] + 1)
    tab = tab.merge(fin, on=["team_id", "season"], how="left")
    act = D.act.groupby(["team_id", "season"]).agg(
        n_games=("game_id", "size"), n_pbp=("pbp_fga", lambda v: int((v.fillna(0) > 0).sum()))
    )
    cov = (act["n_pbp"] / act["n_games"]).rename("pbp_cov").reset_index()
    cov = cov.assign(season=cov["season"] + 1)
    return tab.merge(cov, on=["team_id", "season"], how="left")


def first_game(D: Data) -> dict:
    df, pp = D.df, D.pp
    tab = _team_season_table(D)
    rows = []
    for side, team, gs in (
        ("h", "home_team_id", "h_games_seen"),
        ("a", "away_team_id", "a_games_seen"),
    ):
        sgn = 1.0 if side == "h" else -1.0
        r = pd.DataFrame(
            {
                "game_id": df["game_id"],
                "season": df["season"],
                "team_id": df[team],
                "games_seen": df[gs],
                "conf": df["conference_game"],
                "e20": sgn * (df["margin"] - pp["B20_margin"]),
                "e25": sgn * (df["margin"] - pp["B25_margin"]),
            }
        )
        rows.append(r)
    t = pd.concat(rows, ignore_index=True)
    t = t[t["season"].isin(VALID)].merge(tab, on=["team_id", "season"], how="left")
    first = t[t["games_seen"] == 0]
    rep = {
        "n_first_games": len(first),
        "rmse_first_B20": _rmse(first["e20"]),
        "rmse_first_B25": _rmse(first["e25"]),
        "rmse_games_seen_ge10_B25": _rmse(t.loc[t["games_seen"] >= 10, "e25"]),
        "by_factor": {},
        "note": "returning coach: unavailable (no free timestamped coach source in the lake)",
    }
    for f in (
        "ret_min", "ret_impact", "transfer_in_n", "transfer_in_min_share", "newcomers_n",
        "rotation_prior_d1_share", "prev_net", "pbp_cov",
    ):  # fmt: skip
        x = first.dropna(subset=[f])
        if x[f].nunique() < 3:
            continue
        q = pd.qcut(x[f].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
        rep["by_factor"][f] = {
            str(k): {
                "n": len(v),
                "mean_value": float(v[f].mean()),
                "rmse_B20": _rmse(v["e20"]),
                "rmse_B25": _rmse(v["e25"]),
                "mean_err_B25": float(v["e25"].mean()),
            }
            for k, v in x.groupby(q, observed=True)
        }
    return rep


# ------------------------------------------------------------------ uncertainty ------
def uncertainty(D: Data) -> dict:
    """Preregistered equal-weight index (not fitted); does it predict |error| in games
    1-5? Uses each season's realised roster composition (from 2026-27 on, the
    preseason roster archive supplies it before tip)."""
    tab = _team_season_table(D)
    comp = pd.DataFrame(
        {
            "a": 1 - tab["ret_min"],
            "b": tab["transfer_in_min_share"],
            "c": tab["newcomers_n"],
            "d": 1 - tab["rotation_prior_d1_share"],
            "e": 1 - tab["pbp_cov"].fillna(0),
        }
    )
    z = (comp - comp.mean()) / comp.std()
    tab["u_index"] = z.mean(axis=1)
    df, pp = D.df, D.pp
    rows = []
    for side, team, gs in (
        ("h", "home_team_id", "h_games_seen"),
        ("a", "away_team_id", "a_games_seen"),
    ):
        sgn = 1.0 if side == "h" else -1.0
        rows.append(
            pd.DataFrame(
                {
                    "season": df["season"],
                    "team_id": df[team],
                    "games_seen": df[gs],
                    "abs_e25": (sgn * (df["margin"] - pp["B25_margin"])).abs(),
                }
            )
        )
    t = pd.concat(rows, ignore_index=True)
    t = t[t["season"].isin(VALID) & t["games_seen"].between(0, 4)].merge(
        tab[["team_id", "season", "u_index"]], on=["team_id", "season"], how="left"
    )
    t = t.dropna(subset=["u_index"])
    rho, p = spearmanr(t["u_index"], t["abs_e25"])
    dec = pd.qcut(t["u_index"].rank(method="first"), 10, labels=False)
    later = pd.concat(rows, ignore_index=True)
    later = later[later["season"].isin(VALID) & (later["games_seen"] >= 10)]
    return {
        "n_team_games_1_5": len(t),
        "spearman_rho_abs_error": float(rho),
        "p_value": float(p),
        "abs_error_by_decile": {
            int(k): float(v) for k, v in t.groupby(dec)["abs_e25"].mean().items()
        },
        "rmse_by_decile": {int(k): _rmse(v["abs_e25"]) for k, v in t.groupby(dec)},
        "reference_abs_error_games_seen_ge10": float(later["abs_e25"].mean()),
        "use": "variance only (an interval-width input), never the mean",
    }


# ------------------------------------------------------------------ impact scale -----
def scale(D: Data) -> dict:
    """Player-impact scale from repeated absence stretches (no market data)."""
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min"],
    )
    pg = pg[pg["team_id"].notna() & pg["season"].between(2012, 2026) & (pg["min"].fillna(0) > 0)]
    ps = D.ctx.ps
    reg = ps[(ps["min_share"] >= 0.4) & ps["rapm_net"].notna() & (ps["rapm_poss"] > 1500)]
    reg = reg[["player_id", "team_id", "season", "rapm_net", "min_share", "minutes", "games"]]
    df = D.df
    st = df.set_index("game_id")
    tgames = pd.concat(
        [
            df[["game_id", "season", "home_team_id", "start_time_utc"]].rename(
                columns={"home_team_id": "team_id"}
            ),
            df[["game_id", "season", "away_team_id", "start_time_utc"]].rename(
                columns={"away_team_id": "team_id"}
            ),
        ]
    ).sort_values("start_time_utc")
    played = set(zip(pg["game_id"], pg["player_id"], strict=True))
    out = []
    for (team, s), gl in tgames.groupby(["team_id", "season"]):
        rr = reg[(reg["team_id"] == team) & (reg["season"] == s)]
        if rr.empty:
            continue
        gids = gl["game_id"].to_numpy()
        for r in rr.itertuples(index=False):
            pres = np.array([(g, r.player_id) in played for g in gids])
            if pres.sum() < 5:
                continue
            first = np.argmax(pres)
            i = first
            while i < len(gids):
                if not pres[i]:
                    j = i
                    while j < len(gids) and not pres[j]:
                        j += 1
                    if j - i >= 3 and i > first:
                        out.append((team, s, r.player_id, r.rapm_net, r.minutes / max(r.games, 1),
                                    gids[i - 1], gids[i:j]))  # fmt: skip
                    i = j
                else:
                    i += 1
    rows = []
    for team, s, pid, net, mpg, g0, stretch in out:
        b = st.loc[g0]
        side0 = "h" if b["home_team_id"] == team else "a"
        t_net0 = b[f"{side0}_off_eff"] - b[f"{side0}_def_eff"]
        for g in stretch:
            x = st.loc[g]
            side = "h" if x["home_team_id"] == team else "a"
            o = "a" if side == "h" else "h"
            sg = 1.0 if side == "h" else -1.0
            poss = x["mu_tempo"] + x["h_off_tempo"] + x["a_off_tempo"]
            opp_net = x[f"{o}_off_eff"] - x[f"{o}_def_eff"]
            exp = poss / 100 * (t_net0 - opp_net) + sg * x["eta_eff"] * x["L"] * poss / 100 * 2
            act = sg * x["margin"]
            rows.append(
                {
                    "team": team,
                    "season": s,
                    "player": pid,
                    "stretch": f"{team}|{s}|{pid}|{g0}",
                    "pred_drop": -net * (mpg / 40.0) * poss / 100,
                    "actual_change": act - exp,
                }
            )
    t = pd.DataFrame(rows)
    sm = t.groupby("stretch").agg(
        pred=("pred_drop", "mean"), act=("actual_change", "mean"), n=("pred_drop", "size")
    )
    w = sm["n"].to_numpy(float)
    X = np.column_stack([np.ones(len(sm)), sm["pred"]])
    W = np.diag(w)
    beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ sm["act"].to_numpy())
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(1000):
        i = rng.integers(0, len(sm), len(sm))
        Xi, yi, wi = X[i], sm["act"].to_numpy()[i], w[i]
        boots.append(np.linalg.solve(Xi.T @ (wi[:, None] * Xi), Xi.T @ (wi * yi))[1])
    # persistence and transfers (season s vs s+1 net rating)
    a = ps[ps["rapm_poss"] > 1000][["player_id", "season", "team_id", "rapm_net"]]
    b = a.assign(season=a["season"] - 1)
    m = a.merge(b, on=["player_id", "season"], suffixes=("", "_next"))
    tr = m[m["team_id"] != m["team_id_next"]]
    stay = m[m["team_id"] == m["team_id_next"]]
    return {
        "absence_stretches": int(len(sm)),
        "stretch_games": int(sm["n"].sum()),
        "slope_actual_on_predicted": float(beta[1]),
        "slope_ci90": [float(np.quantile(boots, 0.05)), float(np.quantile(boots, 0.95))],
        "intercept": float(beta[0]),
        "interpretation": "slope ~ 1: ratings correctly scaled; > 1: compressed; < 1: inflated",
        "persistence_same_team": {
            "n": len(stay),
            "corr": float(np.corrcoef(stay["rapm_net"], stay["rapm_net_next"])[0, 1]),
            "slope": float(np.polyfit(stay["rapm_net"], stay["rapm_net_next"], 1)[0]),
        },
        "transfers": {
            "n": len(tr),
            "corr": float(np.corrcoef(tr["rapm_net"], tr["rapm_net_next"])[0, 1]),
            "slope": float(np.polyfit(tr["rapm_net"], tr["rapm_net_next"], 1)[0]),
        },
        "lineup_rapm": "ratings ARE lineup (stint) RAPM; split-sample check not run (report)",
        "no_market": "no sportsbook move is used anywhere in this calibration",
    }


# ------------------------------------------------------------------ totals -----------
def totals(D: Data) -> dict:
    """Regulation x OT mixture vs single Normal for the total (B25 OOS means)."""
    df, pp = D.df, D.pp
    pg = pd.read_parquet(data_dir() / "silver" / "pbp_game.parquet")
    x = df[["game_id", "season", "total", "margin"]].merge(
        pg.drop(columns=["season"]), on="game_id", how="inner"
    )
    x["mt"] = pp.set_index("game_id").loc[x["game_id"], "B25_total"].to_numpy()
    x["mm"] = pp.set_index("game_id").loc[x["game_id"], "B25_margin"].to_numpy()
    x["poss_hat"] = D.mf.set_axis(df["game_id"]).loc[x["game_id"], "poss"].to_numpy()
    x["reg_total"] = x["reg_home"] + x["reg_away"]
    x["reg_margin"] = x["reg_home"] - x["reg_away"]
    x["ot"] = x["n_periods"] > 2
    x["ot_pts"] = x["ot_home"].fillna(0) + x["ot_away"].fillna(0)
    x = x.dropna(subset=["mt", "mm", "reg_total"])
    res = []
    for s in range(2017, 2025):
        tr = x[(x["season"] < s) & (x["season"] >= 2015)]
        te = x[x["season"] == s].copy()
        if tr.empty or te.empty:
            continue
        sig_tot = float((tr["total"] - tr["mt"]).std())
        sig_rm = float((tr["reg_margin"] - tr["mm"]).std())
        otn = tr[tr["ot"]]
        n_ot = tr.loc[tr["ot"], "n_periods"] - 2
        q_more = float((n_ot > 1).sum() / max(n_ot.sum(), 1))  # P(another OT | an OT)
        per_ot = (otn["ot_pts"] / n_ot).astype(float)
        ot_ratio = float((per_ot / otn["mt"]).mean())
        sig_ot = float((per_ot - ot_ratio * otn["mt"]).std())
        # regulation mean / sd: mu_reg = a + b * mt, sd = c + d * poss_hat (in-window)
        A = np.column_stack([np.ones(len(tr)), tr["mt"]])
        ab = np.linalg.lstsq(A, tr["reg_total"], rcond=None)[0]
        r = tr["reg_total"] - A @ ab
        B = np.column_stack([np.ones(len(tr)), tr["poss_hat"]])
        cd = np.linalg.lstsq(B, np.abs(r) * np.sqrt(np.pi / 2), rcond=None)[0]
        te["mu_reg"] = ab[0] + ab[1] * te["mt"]
        te["sd_reg"] = np.maximum(cd[0] + cd[1] * te["poss_hat"], 5.0)
        te["p_ot"] = norm.cdf((0.5 - te["mm"]) / sig_rm) - norm.cdf((-0.5 - te["mm"]) / sig_rm)
        te["sig_tot"] = sig_tot
        te["q_more"], te["ot_ratio"], te["sig_ot"] = q_more, ot_ratio, sig_ot
        res.append(te)
    t = pd.concat(res, ignore_index=True)
    rng = np.random.default_rng(0)
    S = 400
    y = t["total"].to_numpy(float)
    # mixture samples
    reg = rng.normal(t["mu_reg"].to_numpy()[:, None], t["sd_reg"].to_numpy()[:, None], (len(t), S))
    k = np.zeros((len(t), S))
    alive = rng.random((len(t), S)) < t["p_ot"].to_numpy()[:, None]
    while alive.any():
        k += alive
        alive = alive & (rng.random((len(t), S)) < t["q_more"].to_numpy()[:, None])
    ot = (
        rng.normal(0, 1, (len(t), S)) * t["sig_ot"].to_numpy()[:, None] * np.sqrt(k)
        + k * (t["ot_ratio"].to_numpy() * t["mt"].to_numpy())[:, None]
    )
    mix = reg + ot
    single = rng.normal(t["mt"].to_numpy()[:, None], t["sig_tot"].to_numpy()[:, None], (len(t), S))

    def crps(samp: np.ndarray) -> np.ndarray:
        a = np.abs(samp - y[:, None]).mean(1)
        ss = np.sort(samp, axis=1)
        i = np.arange(1, S + 1)
        b = ((2 * i - S - 1) * ss).sum(1) / (S * S)
        return a - b

    def logscore(samp: np.ndarray) -> np.ndarray:  # P(total = y) via +-0.5 window, KDE-free
        p = ((samp > y[:, None] - 1.5) & (samp <= y[:, None] + 1.5)).mean(1) / 3
        return -np.log(np.clip(p, 1e-4, None))

    def cover(samp: np.ndarray, lvl: float, m: np.ndarray | None = None) -> float:
        yy = y if m is None else y[m]
        lo, hi = np.quantile(samp, [(1 - lvl) / 2, (1 + lvl) / 2], axis=1)
        return float(((yy >= lo) & (yy <= hi)).mean())

    def pit(samp: np.ndarray) -> list[float]:
        u = (samp < y[:, None]).mean(1)
        return np.histogram(u, bins=10, range=(0, 1))[0].astype(float).tolist()

    sub = {
        "all": np.ones(len(t), bool),
        "mismatch_abs_margin_gt15": np.abs(t["mm"].to_numpy()) > 15,
        "fast_top_decile": t["poss_hat"].to_numpy() >= np.quantile(t["poss_hat"], 0.9),
        "close_abs_margin_lt3": np.abs(t["mm"].to_numpy()) < 3,
    }
    out = {"evaluated_seasons": "2017-2024 (parameters fitted on 2015..s-1)", "n": len(t)}
    for nm, samp in (("single_normal", single), ("regulation_ot_mixture", mix)):
        c, ls = crps(samp), logscore(samp)
        out[nm] = {
            g: {
                "n": int(m.sum()),
                "crps": float(c[m].mean()),
                "log_score": float(ls[m].mean()),
                "cover80": cover(samp[m], 0.8, m) if m.any() else None,
            }
            for g, m in sub.items()
        }
        out[nm]["coverage"] = {str(lv): cover(samp, lv) for lv in (0.5, 0.8, 0.95)}
        q95, q05 = np.quantile(samp, 0.95, axis=1), np.quantile(samp, 0.05, axis=1)
        out[nm]["tail"] = {"P(y>q95)": float((y > q95).mean()), "P(y<q05)": float((y < q05).mean())}
        out[nm]["pit_hist_10"] = pit(samp)
    out["ot_rate_actual"] = float(t["ot"].mean())
    out["ot_rate_predicted_mean"] = float(t["p_ot"].mean())
    hi = t["p_ot"] >= t["p_ot"].quantile(0.9)
    out["ot_calibration_top_decile"] = {
        "pred": float(t.loc[hi, "p_ot"].mean()),
        "actual": float(t.loc[hi, "ot"].mean()),
    }
    return out


SECTIONS = {
    "components": components,
    "decomposition": decomposition,
    "first_game": first_game,
    "uncertainty": uncertainty,
    "scale": scale,
    "totals": totals,
}


def main() -> None:
    want = sys.argv[1:] or list(SECTIONS)
    D = Data()
    for s in want:
        rep = SECTIONS[s](D)
        (OUT / f"diagnostics_{s}.json").write_text(json.dumps(rep, indent=1, default=float))
        print(s, json.dumps(rep, default=float)[:1500], flush=True)


if __name__ == "__main__":
    main()
