"""Prospective scorecards (Wave 6): weekly model monitor, game-1 rotation accuracy,
P-ROSTER-1 metrics. Everything here reads archived records AFTER the games; nothing
can change an archived projection (records are append-only and read-only here).

* ``model_monitor``     every archived version (incl. ``+roster`` / ``+avail``): margin
                        RMSE / MAE, total RMSE, log loss, calibration slope, market gap
                        (downstream benchmark only), by games-seen slice, using each
                        version's latest pregame record per game.
* ``rotation_scorecard`` for each team's first game: the archived P-ROSTER state at
                        T-7d / T-72h / T-24h / T-6h / latest pregame vs actual minutes:
                        top-5 / top-8 identification, minutes MAE, starters, rotation
                        precision / recall (>= 10 minutes).
* ``proster_metrics``   preregistered P-ROSTER-1 questions (WAVE6.md): game-1 and games
                        2-3 RMSE base vs +roster, market gap, roster confidence vs |error|.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

OFFSETS = {"T-7d": pd.Timedelta(days=7), "T-72h": pd.Timedelta(hours=72),
           "T-24h": pd.Timedelta(hours=24), "T-6h": pd.Timedelta(hours=6),
           "latest": pd.Timedelta(0)}  # fmt: skip
GS_SLICES = {"game_1": (0, 0), "games_2_3": (1, 2), "games_4_6": (3, 5), "games_7_10": (6, 9),
             "games_11_plus": (10, 999)}  # fmt: skip
CONF_RANK = {"CONFIRMED": 2, "LIKELY": 1, "CONFLICTED": 0, "STALE": 0, "UNKNOWN": 0}


def latest_pregame(recs: list[dict]) -> pd.DataFrame:
    rows = []
    for r in recs:
        g, p = r.get("game", {}), r.get("projection", {})
        tip = pd.Timestamp(g.get("start_time_utc"))
        asof = pd.Timestamp(r.get("prospective", {}).get("as_of"))
        if asof >= tip:
            continue
        f = r.get("freshness", {})
        rows.append({
            "version": r.get("model", {}).get("version"), "espn_game_id": g.get("espn_game_id"),
            "as_of": asof, "tip": tip, "margin": p.get("margin"), "total": p.get("total"),
            "home_wp": p.get("home_win_prob"),
            "gs": min(f.get("home_games_seen", 99), f.get("away_games_seen", 99)),
            "roster_conf": min(
                CONF_RANK.get((r.get("roster", {}).get("sides", {}).get(s, {}) or {}).get(
                    "roster_confidence", "UNKNOWN"), 0) for s in ("home", "away")
            ) if "roster" in r else None,
        })  # fmt: skip
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    return d.sort_values("as_of").groupby(["version", "espn_game_id"]).tail(1)


def _metrics(x: pd.DataFrame) -> dict:
    if x.empty:
        return {"n": 0}
    e = x["result_margin"] - x["margin"]
    q = x["home_wp"].clip(1e-4, 1 - 1e-4)
    y = (x["result_margin"] > 0).astype(float)
    out = {
        "n": int(len(x)),
        "margin_rmse": float(np.sqrt((e**2).mean())),
        "margin_mae": float(e.abs().mean()),
        "total_rmse": float(np.sqrt(((x["result_total"] - x["total"]) ** 2).mean()))
        if "result_total" in x
        else None,
        "log_loss": float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean()),
        "calibration_slope": float(np.polyfit(x["margin"], x["result_margin"], 1)[0])
        if len(x) > 2 and x["margin"].std() > 0
        else None,
    }
    if "mkt_margin" in x and x["mkt_margin"].notna().sum() > 2:
        m = x[x["mkt_margin"].notna()]
        out["market_gap"] = float(
            np.sqrt(((m["result_margin"] - m["margin"]) ** 2).mean())
            - np.sqrt(((m["result_margin"] - m["mkt_margin"]) ** 2).mean())
        )
        out["n_market"] = int(len(m))
    return out


def model_monitor(recs: list[dict], res: pd.DataFrame, mkt: pd.DataFrame | None = None) -> dict:
    """``res``: espn_game_id, result_margin, result_total. ``mkt``: espn_game_id,
    mkt_margin (closing home margin implied by the line; benchmark only)."""
    d = latest_pregame(recs)
    if d.empty or res.empty:
        return {}
    d = d.merge(res, on="espn_game_id", how="inner")
    if mkt is not None and len(mkt):
        d = d.merge(mkt, on="espn_game_id", how="left")
    out = {}
    for v, x in d.groupby("version"):
        out[v] = {"all": _metrics(x)}
        for k, (lo, hi) in GS_SLICES.items():
            out[v][k] = _metrics(x[x["gs"].between(lo, hi)])
    return out


def proster_metrics(recs: list[dict], res: pd.DataFrame, mkt: pd.DataFrame | None = None) -> dict:
    """Preregistered P-ROSTER-1 prospective questions on games with both versions."""
    d = latest_pregame(recs)
    if d.empty or res.empty:
        return {}
    d = d.merge(res, on="espn_game_id", how="inner")
    if mkt is not None and len(mkt):
        d = d.merge(mkt, on="espn_game_id", how="left")
    ro = d[d["version"].str.endswith("+roster", na=False)]
    out = {}
    for v, x in ro.groupby("version"):
        base = d[
            (d["version"] == v.replace("+roster", "")) & d["espn_game_id"].isin(x["espn_game_id"])
        ]
        rep = {}
        for k, (lo, hi) in (("game_1", (0, 0)), ("games_2_3", (1, 2))):
            xa, xb = x[x["gs"].between(lo, hi)], base[base["gs"].between(lo, hi)]
            rep[k] = {"roster": _metrics(xa), "base": _metrics(xb)}
        err = (x["result_margin"] - x["margin"]).abs()
        ok = x["roster_conf"].notna()
        rep["confidence_vs_abs_error_spearman"] = (
            float(pd.Series(x.loc[ok, "roster_conf"]).corr(err[ok], method="spearman"))
            if ok.sum() > 10
            else None
        )
        out[v] = rep
    return out


def _states(roster_archive: Path) -> list[tuple[pd.Timestamp, list[dict]]]:
    out = []
    for f in sorted((roster_archive / "truth").rglob("*_proster_state.json")):
        ts = pd.Timestamp(f.name.split("_")[0])
        ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
        out.append((ts, json.loads(f.read_text())))
    return out


def rotation_scorecard(
    roster_archive: Path, first_games: pd.DataFrame, box: pd.DataFrame
) -> pd.DataFrame:
    """``first_games``: team_id, espn_game_id, tip (each team's first game).
    ``box``: espn_game_id, team_id, player_id, minutes, starter (actual)."""
    states = _states(roster_archive)
    rows = []
    for g in first_games.itertuples(index=False):
        act = box[(box["espn_game_id"] == g.espn_game_id) & (box["team_id"] == g.team_id)]
        if act.empty:
            continue
        a_min = act.set_index("player_id")["minutes"].astype(float)
        a5 = set(a_min.nlargest(5).index)
        a8 = set(a_min.nlargest(8).index)
        a_rot = set(a_min[a_min >= 10].index)
        starters = set(act.loc[act["starter"].astype(bool), "player_id"])
        for lab, off in OFFSETS.items():
            cut = g.tip - off
            snap = [s for s in states if s[0] < cut]
            if not snap:
                continue
            ts, st = snap[-1]
            team = next((t for t in st if t["team_id"] == g.team_id), None)
            if team is None or not team.get("expected_rotation"):
                continue
            pr = pd.Series({r["player_id"]: 40 * r["share"] for r in team["expected_rotation"]})
            p5, p8 = set(pr.nlargest(5).index), set(pr.nlargest(8).index)
            p_rot = set(pr[pr >= 10].index)
            idx = a_min.index.union(pr.index)
            mae = float((a_min.reindex(idx).fillna(0) - pr.reindex(idx).fillna(0)).abs().mean())
            rows.append({
                "team_id": g.team_id, "espn_game_id": g.espn_game_id, "snapshot": lab,
                "snapshot_ts": ts.isoformat(), "roster_confidence": team.get("roster_confidence"),
                "top5": len(a5 & p5) / 5, "top8": len(a8 & p8) / 8, "minutes_mae": mae,
                "starters": len(starters & p5) / 5 if len(starters) == 5 else np.nan,
                "rotation_precision": len(a_rot & p_rot) / len(p_rot) if p_rot else np.nan,
                "rotation_recall": len(a_rot & p_rot) / len(a_rot) if a_rot else np.nan,
            })  # fmt: skip
    return pd.DataFrame(rows)


def _rotation_metrics(
    shares: pd.Series, listed: set, actual: pd.Series, hist: pd.DataFrame
) -> dict:
    s = shares[shares > 0]
    false = s[~s.index.isin(listed)]
    h = hist.reindex(false.index)
    in_rot = set(s.index)
    tot = float(actual.sum())
    return {
        "n_rotation": int(len(s)),
        "false_players": int(len(false)),
        "false_minutes": float(40 * false.sum()),
        "false_usage": float((false * h["usage_share"].fillna(0.0)).sum()),
        "false_value": float((false * h["rapm_net"].fillna(0.0)).sum()),
        "omitted_minutes_share": float(actual[~actual.index.isin(in_rot)].sum() / tot)
        if tot > 0
        else np.nan,
    }


def false_inclusion(
    roster_archive: Path,
    first_games: pd.DataFrame,
    box5: pd.DataFrame,
    history: pd.DataFrame,
    season: int,
) -> pd.DataFrame:
    """Departed-player false inclusion (preregistered, research/hypotheses/WAVE7.md 7).

    ``first_games``: team_id, espn_game_id, tip. ``box5``: every box-score row (played
    or DNP) of each team's first five games: espn_game_id, team_id, player_id, minutes.
    ``history``: models/rosters/history_2026.parquet. A rotation player is FALSE if he
    is listed in none of the team's first five box scores. BASE = last season's full
    minute shares (what pure-0.5.0 uses at game 1); ROSTER = the archived P-ROSTER-1
    expected rotation at each offset."""
    states = _states(roster_archive)
    last = history[history["role_season"] == season - 1]
    hist = history.drop_duplicates("player_id").set_index("player_id")
    rows = []
    for g in first_games.itertuples(index=False):
        listed = set(box5.loc[box5["team_id"] == g.team_id, "player_id"])
        if not listed:
            continue
        act = box5[(box5["espn_game_id"] == g.espn_game_id) & (box5["team_id"] == g.team_id)]
        actual = act.set_index("player_id")["minutes"].astype(float)
        base = last[last["role_team"] == g.team_id].set_index("player_id")["min_share"]
        rows.append({"team_id": g.team_id, "espn_game_id": g.espn_game_id, "rotation": "BASE",
                     "snapshot": None, **_rotation_metrics(base, listed, actual, hist)})  # fmt: skip
        for lab, off in OFFSETS.items():
            snap = [s for s in states if s[0] < g.tip - off]
            if not snap:
                continue
            ts, st = snap[-1]
            team = next((t for t in st if t["team_id"] == g.team_id), None)
            if team is None or not team.get("expected_rotation"):
                continue
            sh = pd.Series({r["player_id"]: r["share"] for r in team["expected_rotation"]})
            rows.append({"team_id": g.team_id, "espn_game_id": g.espn_game_id,
                         "rotation": "ROSTER", "snapshot": lab, "snapshot_ts": ts.isoformat(),
                         "roster_confidence": team.get("roster_confidence"),
                         **_rotation_metrics(sh, listed, actual, hist)})  # fmt: skip
    return pd.DataFrame(rows)
