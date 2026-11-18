"""Phase 15 CBB pipeline: walk-forward ratings -> frozen layers -> holdout scoring at Kalshi strikes -> matrix rows.

python research/phase15/cbb_p15_run.py --derived /home/user/p15work/cbb/derived --work /home/user/p15work/cbb/work \
    --kalshi /home/user/p15work/kalshi/CBB/CBB --out /home/user/sift-alpha/research/phase15/matrix/CBB.json
Stages are cached in --work (wf_raw.parquet, frozen_cfg.json); delete them to recompute.
"""
from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import cbb_p15_eval as EV  # noqa: E402
import cbb_p15_kalshi as KX  # noqa: E402
import cbb_p15_model as M  # noqa: E402

E = EV.E
LAM, TAU = 8.0, 90.0          # chosen on DEV 2010-2019 (grid lam {3,8,20} x tau {90,inf}, margin+total MSE)
_G: dict = {}


def _wf_job(args):
    v, S = args
    cfg = M.Cfg(variant=v, coef=_G["co"], lam_prior=LAM, lam_tempo=LAM, tau=TAU)
    p = M.walk_forward(_G["games"], _G["finals"], cfg, [S], st=_G["st"], pret=_G["pret"])
    p["variant"] = v
    return p


def prepare(derived: Path):
    games = pd.read_parquet(derived / "cbb_games.parquet")
    pm = pd.read_parquet(derived / "cbb_player_minutes.parquet")
    finals = M.season_finals(games)
    st = M.player_tables(pm)
    pret = M.return_rates(st, range(2008, 2022))
    stt = {"st": st, "_pm": pm}
    co = M.fit_prior_coefs(games, finals, stt, pret, range(2008, 2023))
    return games, pm, finals, stt, pret, co


def walk_all(work: Path, games, finals, stt, pret, co):
    f = work / "wf_raw.parquet"
    if f.exists():
        return pd.read_parquet(f)
    _G.update(games=games, finals=finals, st=stt, pret=pret, co=co)
    jobs = [(v, s) for s in range(2027, 2007, -1) for v in ("full", "base")]
    with Pool(4) as pool:
        res = pool.map(_wf_job, jobs, chunksize=1)
    out = pd.concat(res)
    out.to_parquet(f)
    return out


def fg_table(games, raw, variant):
    ctx = M.context_features(games)
    d = raw[raw.variant == variant].merge(games, on=["game_id", "season"]).merge(ctx, on="game_id")
    return d[d.home_d1 & d.away_d1].reset_index(drop=True)


def pmfs(F, n):
    return {g: EV.GamePMF(m, sm, t, stt, r, n) for g, m, sm, t, stt, r in
            zip(F.game_id, F.mu_m, F.sd_m, F.mu_t, F.sd_t, F.rho, strict=False)}


def window_rows(pa, pb, outcomes, kind, centers, half_width, step):
    """Common strike ladder for both forecasters: half-point strikes in a window around the mean of the two models'
    forecasts (Kalshi lists strikes around the expected value; series p10-p90 in the universe file)."""
    rows = []
    for g, c in centers.items():
        y = outcomes[g]
        for k in E.strike_window(c, half_width, step):
            for side in (("home", "away") if kind in ("spread", "team_total") else (None,)):
                if kind == "spread":
                    yy = (y[0] - y[1] if side == "home" else y[1] - y[0]) > k
                elif kind == "team_total":
                    yy = (y[0] if side == "home" else y[1]) > k
                else:
                    yy = (y[0] + y[1]) > k
                rows.append((g, EV.contract_p(pa[g], kind, side, k), EV.contract_p(pb[g], kind, side, k), float(yy)))
    return pd.DataFrame(rows, columns=["game_id", "pa", "pb", "y"])


def winner_rows(pa, pb, outcomes, three_way=False):
    rows = []
    for g, y in outcomes.items():
        sides = ("home", "away", "tie") if three_way else ("home",)
        for s in sides:
            yy = {"home": y[0] > y[1], "away": y[1] > y[0], "tie": y[0] == y[1]}[s]
            rows.append((g, EV.contract_p(pa[g], "winner", s, None), EV.contract_p(pb[g], "winner", s, None), float(yy)))
    return pd.DataFrame(rows, columns=["game_id", "pa", "pb", "y"])


def kalshi_rows(mt, series, kind, pa, pb):
    q = mt[(mt.series.isin(series)) & mt.game_id.isin(pa.keys()) & mt.game_id.isin(pb.keys())]
    if kind != "total":
        q = q[q.side.notna()]
    rows = [(g, EV.contract_p(pa[g], kind, s, k), EV.contract_p(pb[g], kind, s, k), float(r))
            for g, s, k, r in zip(q.game_id, q.side, q.strike, q.result, strict=False)]
    return pd.DataFrame(rows, columns=["game_id", "pa", "pb", "y"])


def score(R, la="model", lb="baseline"):
    if not len(R):
        return None
    return EV.summarize(R.pa, R.pb, R.y, R.game_id.values, la, lb)


def dist_metrics(Fa, Fb, outcomes, kind):
    ga = Fa.set_index("game_id")
    gb = Fb.set_index("game_id")
    ids = [g for g in ga.index if g in gb.index and g in outcomes]
    y = np.array([(outcomes[g][0] - outcomes[g][1]) if kind == "margin" else sum(outcomes[g]) for g in ids])
    col, sdc = ("mu_m", "sd_m") if kind == "margin" else ("mu_t", "sd_t")
    ca = E.crps_normal(ga.loc[ids, col].values, ga.loc[ids, sdc].values, y)
    cb = E.crps_normal(gb.loc[ids, col].values, gb.loc[ids, sdc].values, y)
    ea, eb = np.abs(y - ga.loc[ids, col].values), np.abs(y - gb.loc[ids, col].values)
    cl = np.array(ids)
    return {"n": len(ids), "crps": E.cluster_ci(ca, cl), "crps_baseline": round(float(cb.mean()), 4),
            "d_crps": E.paired_delta(ca, cb, cl), "mae": E.cluster_ci(ea, cl), "mae_baseline": round(float(eb.mean()), 4),
            "d_mae": E.paired_delta(ea, eb, cl), "bias_y_minus_mu": round(float((y - ga.loc[ids, col].values).mean()), 3),
            "z_sd": round(float(np.std((y - ga.loc[ids, col].values) / ga.loc[ids, sdc].values)), 3)}


# ----------------------------------------------------------------------------------------------- production replay
def production_fg(work: Path, games: pd.DataFrame, sched_names: pd.DataFrame, version: str = "pure-0.2.0"):
    """Last pre-tip archived record per game (projections-archive branch, extracted to prod_2027.parquet).  Orientation
    verified by team display name; swapped records are flipped, unverifiable ones dropped."""
    P = pd.read_parquet(work / "prod_2027.parquet")
    P = P[P.version == version].merge(sched_names, on="game_id", how="inner")
    same = (P.home_name == P.h_name) & (P.away_name == P.a_name)
    swap = (P.home_name == P.a_name) & (P.away_name == P.h_name)
    P = P[same | swap].copy()
    sgn = np.where(swap[same | swap], -1.0, 1.0)
    return pd.DataFrame({"game_id": P.game_id.astype(np.int64).values, "mu_m": sgn * P.margin.values, "sd_m": P.margin_sd.values,
                         "mu_t": P.total.values, "sd_t": P.total_sd.values, "rho": 0.0}), int(swap.sum())


# ----------------------------------------------------------------------------------------------- forecasts
def forecasts(games, raw, halves, PAR, seasons):
    """Final FG (full + base), 1H and 2H (model + proportional baseline) forecast frames for D-I v D-I games of
    `seasons`.  Uses only frozen parameters PAR and date-strict inputs."""
    out = {}
    for v in ("full", "base"):
        d = fg_table(games, raw, v)
        d = d[d.season.isin(seasons)]
        out["fg_" + v] = EV.apply_fg(d, v, PAR["fg_" + v])
    d = fg_table(games, raw, "full")
    d = d[d.season.isin(seasons)].reset_index(drop=True)
    F = out["fg_full"].set_index("game_id").loc[d.game_id].reset_index()
    sh = EV.team_share_lookup(games[games.season.isin(set(seasons) | {min(seasons) - 1})], halves, PAR["s1"])
    pd_ = d[["game_id", "neutral"]].merge(F, on="game_id").merge(sh, on="game_id")
    for half, share in (("1h", PAR["s1"]), ("2h", 1 - PAR["s1"])):
        out[half + "_model"] = EV.apply_period(pd_, PAR["s1"], half, PAR[half])
        out[half + "_prop"] = EV.proportional(pd_, share, PAR["fg_full"]["rho"])
    return out


def fit_params(games, raw, halves):
    PAR = {}
    for v in ("full", "base"):
        d = fg_table(games, raw, v)
        PAR["fg_" + v] = EV.fit_fg(d[d.season.isin(EV.FG_TRAIN)], v)
    tr = halves[halves.season.isin(EV.P_TRAIN)].merge(games[["game_id", "home_pts", "away_pts"]], on="game_id")
    PAR["s1"] = float((tr.home_1h + tr.away_1h).sum() / (tr.home_pts + tr.away_pts).sum())
    d = fg_table(games, raw, "full")
    d = d[d.season.isin(EV.P_TRAIN)]
    F = EV.apply_fg(d, "full", PAR["fg_full"]).merge(d[["game_id", "neutral"]], on="game_id")
    sh = EV.team_share_lookup(games[games.season.isin([min(EV.P_TRAIN) - 1] + EV.P_TRAIN)], halves, PAR["s1"])
    F = F.merge(sh, on="game_id").merge(halves, on="game_id")
    for half, (hc, ac) in (("1h", ("home_1h", "away_1h")), ("2h", ("home_2hot", "away_2hot"))):
        F["y_m"], F["y_t"] = F[hc] - F[ac], F[hc] + F[ac]
        PAR[half] = EV.fit_period(F, PAR["s1"], half)
    return PAR


# ----------------------------------------------------------------------------------------------- truncation test
def truncation_check(games, pm, pret, co, raw, halves, PAR, dates):
    """For each date d: rebuild every input from data truncated to games dated < d (games ON d keep only their schedule
    identity; scores, possessions and linescores are overwritten with garbage, later games and player boxes dropped),
    recompute season finals, walk-forward, context and period features, and compare the final forecasts for the games
    on d with the full-data run.  Identical = no look-ahead."""
    out = []
    full = None
    for d in dates:
        d = pd.Timestamp(d)
        S = int(games.loc[games.date == d, "season"].iloc[0])
        g = games[games.date <= d].copy()
        on = g.date == d
        g.loc[on, ["home_pts", "away_pts"]] = 999
        g.loc[on, "poss"] = 1.0
        hv = halves[halves.game_id.isin(g.game_id[~on])]
        hv = pd.concat([hv, halves[halves.game_id.isin(g.game_id[on])].assign(home_1h=500, away_1h=0)])
        p = pm[pm.date < d]
        st = {"st": M.player_tables(p), "_pm": p}
        fin = M.season_finals(g[g.season < S])
        rt = []
        for v in ("full", "base"):
            cfg = M.Cfg(variant=v, coef=co, lam_prior=LAM, lam_tempo=LAM, tau=TAU)
            rt.append(M.walk_forward(g, fin, cfg, [S], st=st, pret=pret, dates_by_season={S: [d]}).assign(variant=v))
        rt = pd.concat(rt)
        ft = forecasts(g, rt, hv, PAR, [S])
        if full is None or S not in full[1]:
            full = (forecasts(games, raw, halves, PAR, [S]), [S])
        for k, fr in ft.items():
            ref = full[0][k].set_index("game_id").loc[fr.game_id]
            cols = ["mu_m", "mu_t", "sd_m", "sd_t"]
            diff = float(np.max(np.abs(ref[cols].values - fr[cols].values))) if len(fr) else float("nan")
            out.append({"date": str(d.date()), "forecast": k, "games": len(fr), "max_abs_diff": diff})
    return out


# ----------------------------------------------------------------------------------------------- main
FAMILIES = {  # family -> (segment, kind, kalshi series, window (half_width, step) or None for winner)
    "winner_FG": ("FG", "winner", ["KXNCAAMBGAME"], None),
    "spread_FG": ("FG", "spread", ["KXNCAAMBSPREAD"], (12, 2)),
    "total_FG": ("FG", "total", ["KXNCAAMBTOTAL"], (20, 4)),
    "team_total_FG": ("FG", "team_total", ["KXNCAAMBTEAMTOTAL"], (12, 3)),
    "winner_1H": ("1H", "winner", ["KXNCAAMB1HWINNER", "KXNCAAMB1H"], None),
    "spread_1H": ("1H", "spread", ["KXNCAAMB1HSPREAD"], (8, 2)),
    "total_1H": ("1H", "total", ["KXNCAAMB1HTOTAL"], (12, 3)),
    "winner_2H": ("2H", "winner", ["KXNCAAMB2H"], None),
    "spread_2H": ("2H", "spread", ["KXNCAAMB2HSPREAD"], (8, 2)),
    "total_2H": ("2H", "total", ["KXNCAAMB2HTOTAL"], (12, 3)),
}


def family_rows(fam, pa, pb, Fa, Fb, outcomes, mt, ids):
    seg, kind, series, win = FAMILIES[fam]
    ids = [g for g in ids if g in pa and g in pb and g in outcomes]
    oc = {g: outcomes[g] for g in ids}
    if kind == "winner":
        W = winner_rows(pa, pb, oc, three_way=seg != "FG")
    else:
        fa, fb = Fa.set_index("game_id"), Fb.set_index("game_id")
        if kind == "spread":
            c = (fa.loc[ids, "mu_m"] + fb.loc[ids, "mu_m"]) / 2
        elif kind == "total":
            c = (fa.loc[ids, "mu_t"] + fb.loc[ids, "mu_t"]) / 2
        else:
            c = (fa.loc[ids, "mu_t"] + fb.loc[ids, "mu_t"]) / 4   # ladder around the mean team score
        W = window_rows(pa, pb, oc, kind, c.to_dict(), *win)
    K = kalshi_rows(mt[mt.game_id.isin(ids)], series, kind, pa, pb)
    return W, K


def verdict(s_win, s_k, n_games, gain_ci, min_games=150):
    s = s_k if (s_k and s_k["n_games"] >= min_games) else s_win
    if s is None or n_games < min_games:
        return "ABSTAIN"
    ok = 0.85 <= s["slope"] <= 1.15
    if not ok:
        return "ABSTAIN" if not (0.75 <= s["slope"] <= 1.25) else "USABLE"
    return "RELIABLE" if gain_ci is not None and gain_ci[1] < 0 else "USABLE"


def apply_caps(rows):
    """Conservative verdict caps, added after the first scoring pass (they can only lower a verdict): (1) FG rows cannot be RELIABLE when the production
    incumbent beats this model on the paired 2026-27 comparison (margin CRPS CI above 0) - a stronger forecaster exists;
    (2) 2H rows are capped at USABLE: Kalshi lists 16 2H events, too few to check settlement-level calibration."""
    prod = [r for r in rows if r["family"] == "spread_FG" and r["segment"].endswith("vs production")]
    fg_cap = bool(prod and prod[0]["metrics"]["dist"] and prod[0]["metrics"]["dist"]["d_crps"][1][0] > 0)
    for r in rows:
        seg = r["segment"].split(" |")[0]
        if r["verdict"] == "RELIABLE" and ((seg == "FG" and fg_cap) or seg == "2H"):
            r["verdict"] = "USABLE"
            r["notes"] += ("; capped: production pure-0.2.0 beats this model on 2026-27 margins" if seg == "FG"
                           else "; capped: only 16 Kalshi 2H events")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--derived", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--kalshi", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    games, pm, finals, stt, pret, co = prepare(a.derived)
    raw = walk_all(a.work, games, finals, stt, pret, co)
    halves = pd.read_parquet(a.derived / "cbb_halftime_scores.parquet")
    PAR = fit_params(games, raw, halves)
    res = {"frozen": {"lam_prior": LAM, "tau": TAU, "prior_coefs": co, "p_return": pret, **PAR}}
    res["truncation_test"] = truncation_check(games, pm, pret, co, raw, halves, PAR,
                                              ["2025-11-14", "2026-01-17", "2026-03-07", "2026-11-12"])
    print("truncation", res["truncation_test"], flush=True)
    mk = KX.load_markets(a.kalshi)
    mt = KX.match_events(mk, games[games.season >= 2026])
    res["kalshi_match"] = KX.match_report(mk, mt)
    sc = pd.read_parquet(a.raw / "espn_team_box_schedules/schedules/mbb_schedule_2027.parquet",
                         columns=["game_id", "home_display_name", "away_display_name"])
    sc = sc.rename(columns={"home_display_name": "h_name", "away_display_name": "a_name"}).astype({"game_id": np.int64})
    prod, n_swapped = production_fg(a.work, games, sc)
    res["production"] = {"version": "pure-0.2.0 (incumbent)", "games": len(prod), "orientation_swapped": n_swapped}
    F = forecasts(games, raw, halves, PAR, HOLD_SEASONS)
    g = games.set_index("game_id")
    hv = halves.set_index("game_id")
    out_fg = {gid: (int(g.at[gid, "home_pts"]), int(g.at[gid, "away_pts"])) for gid in F["fg_full"].game_id}
    out_h = {"1H": {gid: (int(r.home_1h), int(r.away_1h)) for gid, r in hv.iterrows()},
             "2H": {gid: (int(r.home_2hot), int(r.away_2hot)) for gid, r in hv.iterrows()}}
    ctx = M.context_features(games).set_index("game_id")
    nmin = np.minimum(ctx.n_before_h, ctx.n_before_a)
    season = g.season
    P = {}
    for key, n in (("fg_full", 200), ("fg_base", 200), ("1h_model", 120), ("1h_prop", 120), ("2h_model", 140), ("2h_prop", 140)):
        P[key] = pmfs(F[key], n)
        print("pmf", key, flush=True)
    P["prod"] = pmfs(prod, 200)
    F["prod"] = prod
    pairs = {"FG": ("fg_full", "fg_base", out_fg), "1H": ("1h_model", "1h_prop", out_h["1H"]), "2H": ("2h_model", "2h_prop", out_h["2H"])}
    rows = []
    for fam, (seg, kind, _series, _win) in FAMILIES.items():
        ka, kb, oc = pairs[seg]
        comps = [("2025-26", 2026, ka, kb, None), ("2025-26 early (<10 team games)", 2026, ka, kb, "early"),
                 ("2025-26 Jan-Apr (>=10 team games)", 2026, ka, kb, "late"), ("2026-27 to date", 2027, ka, kb, None)]
        if seg == "FG":
            comps.append(("2026-27 to date vs production", 2027, "fg_full", "prod", None))
        for label, S, A, B, sl in comps:
            ids = [i for i in F[A].game_id if season.get(i) == S]
            if sl == "early":
                ids = [i for i in ids if nmin.get(i, 99) < EV.EARLY]
            elif sl == "late":
                ids = [i for i in ids if nmin.get(i, 0) >= EV.EARLY]
            W, K = family_rows(fam, P[A], P[B], F[A], F[B], oc, mt, ids)
            sw, sk = score(W), score(K)
            n_games = len(set(W.game_id)) if len(W) else 0
            dm = None
            if kind in ("spread", "total"):
                dm = dist_metrics(F[A][F[A].game_id.isin(ids)], F[B][F[B].game_id.isin(ids)], oc,
                                  "margin" if kind == "spread" else "total")
            gain = (sk if (sk and sk["n_games"] >= 150) else sw or {}).get("d_logloss", [None, None])[1]
            v = verdict(sw, sk, n_games, gain)
            base_name = {"fg_base": "p15-eff-base (simple opp-adj efficiency, constant-regressed prior)",
                         "prod": "production pure-0.2.0 (archived pre-tip records)",
                         "1h_prop": "proportional split of p15-eff-full FG forecast (mean x s, SD x sqrt s)",
                         "2h_prop": "proportional split of p15-eff-full FG forecast (mean x (1-s), SD x sqrt(1-s))"}[B]
            metrics = {"window_strikes": sw, "kalshi_strikes": sk, "dist": dm}
            rows.append(E.matrix_row("CBB", fam, f"{seg} | {label}", "p15-eff-full" if seg == "FG" else f"p15-{seg.lower()}-fitted",
                                     base_name, n_games, metrics, v,
                                     ["opp-adj efficiency+tempo walk-forward", "roster-continuity/transfer prior",
                                      "team HCA + rest"] + ([f"{seg} share tendencies, fitted to {seg} outcomes"] if seg != "FG" else []),
                                     notes="window = common half-point ladder around mean of both forecasts; kalshi = actual "
                                           "settled Kalshi strikes matched by ticker (result field as outcome)"))
            print(fam, label, n_games, v, sw and (sw["logloss"], sw["d_logloss"], sw["slope"]),
                  sk and (sk["n_games"], sk["logloss"], sk["d_logloss"], sk["slope"]), flush=True)
    E.write_rows(apply_caps(rows), a.out)
    (a.work / "cbb_p15_results.json").write_text(json.dumps(res, indent=1, default=float))


HOLD_SEASONS = EV.HOLD

if __name__ == "__main__":
    main()
