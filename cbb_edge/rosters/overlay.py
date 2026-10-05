"""P-ROSTER-1: PROSPECTIVE_ONLY roster-truth overlay on pure-0.5.0 (WAVE6.md).

``pure-0.5.0+roster`` = the frozen pure-0.5.0 projection plus two recorded components.

(a) **Input substitution.** Before a team's first game, the frozen player block uses
    last season's full minute shares, players who left included. The overlay replaces
    them with the expected rotation over the roster-truth players (CONFIRMED / LIKELY):
    a HistGradientBoosting minutes model retrained at run time from
    ``models/rosters/rotation_train.parquet``. The frozen artifact is then re-applied
    unchanged.
(b) **Continuity correction.** ``models/overlays/p-roster-1.json`` (hash-pinned). It is
    a function of (truth − expected) returning share, the incoming transfers' previous
    minute share and the number of first-D-I players expected to play, each × 1 / (1 + gs / 3),
    home minus away, for games seen ≤ 10.

Teams whose roster confidence is STALE or UNKNOWN get no overlay (adjustment 0, flagged).
(b) applies only to CONFIRMED rosters (an official source or two independent source
groups agree): single-feed ESPN rosters were shown to be stale in content.
No market data is read. Base records are never modified; overlay records are archived
as their own version.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
ROSTERS = REPO / "models" / "rosters"
SPEC = REPO / "models" / "overlays" / "p-roster-1.json"
TRUSTED = ("CONFIRMED", "LIKELY", "CONFLICTED")
PLAYER_OK = ("CONFIRMED", "LIKELY")
ROT_FEATURES = [
    "prev_min_share", "prev_start_rate", "prev_usage", "prev_net", "d1_seasons",
    "pos_g", "pos_c", "transfer", "origin_net", "first_d1", "depth_same_pos",
    "team_prev_net",
]  # fmt: skip
APPEAR_SHARE = 0.10  # expected share at which a first-D-I player counts as "playing"


def load_spec() -> dict[str, Any]:
    spec = json.loads(SPEC.read_text())
    sha = spec.pop("sha256")
    if hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest() != sha:
        raise ValueError("p-roster-1.json was modified")
    spec["sha256"] = sha
    return spec


def latest_truth(
    archive: Path, as_of: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame, str] | None:
    """Most recent roster-truth snapshot captured strictly before ``as_of``."""
    best = None
    for f in sorted((archive / "truth").rglob("*_records.jsonl")):
        stamp = f.name.split("_")[0]
        ts = (
            pd.Timestamp(stamp).tz_localize("UTC")
            if pd.Timestamp(stamp).tz is None
            else pd.Timestamp(stamp)
        )
        if ts < as_of:
            best = (f, stamp)
    if best is None:
        return None
    f, stamp = best
    recs = pd.read_json(f, lines=True)
    teams = pd.read_json(f.with_name(f"{stamp}_teams.json"))
    return recs, teams, stamp


@lru_cache(maxsize=1)
def _rotation_model():
    from sklearn.ensemble import HistGradientBoostingRegressor

    tr = pd.read_parquet(ROSTERS / "rotation_train.parquet")
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=200, learning_rate=0.05,
                                      random_state=0)  # fmt: skip
    m.fit(tr[ROT_FEATURES], tr["target"])
    return m


def rotation_features(recs: pd.DataFrame, season: int) -> pd.DataFrame:
    from cbb_edge.players.availability_model import _pos

    h = pd.read_parquet(ROSTERS / "history_2026.parquet")
    tn = pd.read_parquet(ROSTERS / "team_net_2026.parquet").set_index("team_id")["team_net"]
    x = recs[recs["status"].isin(PLAYER_OK) & recs["player_id"].notna()][
        ["team_id", "player_id", "classification", "position"]
    ].merge(h, on="player_id", how="left")
    hist = x["role_season"].notna()
    out = x[["team_id", "player_id", "classification"]].copy()
    out["first_d1"] = (~hist).astype(float)
    out["prev_min_share"] = np.where(hist, x["min_share"].fillna(0), 0.0)
    out["prev_start_rate"] = np.where(hist, x["start_rate"].fillna(0), 0.0)
    out["prev_usage"] = np.where(hist, x["usage_share"].fillna(0), 0.0)
    out["prev_net"] = np.where(hist, x["rapm_net"].fillna(-2.0), -2.0)
    out["d1_seasons"] = np.where(hist, x["seasons_prior"].fillna(0) + 1, 0.0)
    out["transfer"] = (hist & (x["role_team"] != x["team_id"])).astype(float)
    # position: last D-I season (history) when known, else the roster listing
    pos = x["position_y"].where(hist, x["position_x"]).map(_pos)
    out["pos_g"] = (pos == "G").astype(float)
    out["pos_c"] = (pos == "C").astype(float)
    out["origin_net"] = np.where(out["transfer"] > 0, x["team_net"].fillna(0.0), 0.0)
    out["team_prev_net"] = out["team_id"].map(tn).fillna(0.0)
    key = np.select([out["pos_g"] > 0, out["pos_c"] > 0], ["G", "C"], "F")
    tot = out.groupby([out["team_id"], key])["prev_min_share"].transform("sum")
    out["depth_same_pos"] = tot - out["prev_min_share"]
    out["role_team"] = x["role_team"].to_numpy()
    out["role_season"] = x["role_season"].to_numpy()
    out["season"] = season
    return out


def expected_rotation(recs: pd.DataFrame, season: int) -> pd.DataFrame:
    r = rotation_features(recs, season)
    if r.empty:
        return r.assign(share=[])
    raw = np.clip(_rotation_model().predict(r[ROT_FEATURES]), 0.0, 1.0)
    r["share_raw"] = raw
    tot = r.groupby("team_id")["share_raw"].transform("sum")
    r["share"] = (5 * r["share_raw"] / tot.replace(0, np.nan)).clip(upper=1.0).fillna(0.0)
    return r


def continuity(rot: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per team: truth returning share of last season's minutes, incoming transfers'
    previous minute share, first-D-I players expected to play, projected minute splits."""
    h = pd.read_parquet(ROSTERS / "history_2026.parquet")
    last = h[h["role_season"] == season - 1]
    prev_tot = last.groupby("role_team")["min_share"].sum()
    out = []
    for team, x in rot.groupby("team_id"):
        on = set(x["player_id"])
        mine = last[last["role_team"] == team]
        ret = float(mine.loc[mine["player_id"].isin(on), "min_share"].sum())
        tot = float(prev_tot.get(team, 0.0))
        trn = x[(x["transfer"] > 0) & (x["role_season"] == season - 1)]
        m = x["share"] * 40.0
        out.append(
            {
                "team_id": team,
                "truth_cont": ret / tot if tot > 0 else np.nan,
                "tr_prev": float(trn["prev_min_share"].sum()),
                "first_d1": float(((x["first_d1"] > 0) & (x["share"] >= APPEAR_SHARE)).sum()),
                "proj_min_returning": float(
                    m[x["classification"].isin(["returning", "returning_after_gap"])].sum()
                ),
                "proj_min_transfer": float(m[x["classification"] == "transfer"].sum()),
                "proj_min_unseen": float(m[x["classification"] == "first_d1"].sum()),
            }
        )
    return pd.DataFrame(out)


def roster_overlay(
    season: int,
    as_of: pd.Timestamp,
    model: dict[str, Any],
    base: list[dict[str, Any]],
    archive: Path,
    horizon_h: float = 30.0,
) -> list[dict[str, Any]]:
    """Records of version ``<version>+roster`` for the base window (PROSPECTIVE_ONLY)."""
    from cbb_edge.app import checkpoints
    from cbb_edge.app.prospective import project_window

    if not base:
        return []
    tr = latest_truth(archive, as_of)
    if tr is None:
        return []
    recs, teams, stamp = tr
    spec = load_spec()
    conf = teams.set_index("team_id")["roster_confidence"].to_dict()
    rot = expected_rotation(recs, season)
    cont = continuity(rot, season).set_index("team_id")
    ck = checkpoints.Checkpoint(model["version"], season - 1)
    pre = ck.preseason().set_index("team_id")["ret_min"]
    trusted = {t for t, c in conf.items() if c in TRUSTED}
    shares = {
        (t, season): (x["player_id"].to_numpy(), x["share"].to_numpy())
        for t, x in rot.groupby("team_id")
        if t in trusted and x["share"].sum() > 0
    }
    sub = {r["game"]["espn_game_id"]: r for r in project_window(season, as_of, horizon_h,
                                                                  model=model,
                                                                  preseason_shares=shares)}  # fmt: skip
    b = spec["component_b"]
    coef = dict(zip(b["features"], b["coef"], strict=True))
    a_, b_ = model["wp_logit"]
    out = []
    for r0 in base:
        gid = r0["game"]["espn_game_id"]
        rs = sub.get(gid)
        if rs is None:
            continue
        side_terms, side_info = {}, {}
        for side in ("home", "away"):
            t = r0[side]["team_id"]
            gs = int(r0["freshness"]["home_games_seen" if side == "home" else "away_games_seen"])
            d = 1.0 / (1.0 + gs / 3.0)
            # (b) needs CONFIRMED rosters: the 2026-10-05 audit showed single-feed ESPN
            # rosters implying 82% continuity vs a 42% historical norm (stale content)
            ok_a = t in trusted and t in cont.index
            ok = ok_a and conf.get(t) == "CONFIRMED" and gs <= b["applies_games_seen_max"]
            c = cont.loc[t] if t in cont.index else None
            exp_ret = float(pre.get(t, np.nan))
            if ok and np.isfinite(c["truth_cont"]) and np.isfinite(exp_ret):
                f = {"dcont": (c["truth_cont"] - exp_ret) * d, "tr_prev": c["tr_prev"] * d,
                     "first_d1": c["first_d1"] * d}  # fmt: skip
            else:
                f = {k: 0.0 for k in coef}
            side_terms[side] = f
            top = rot[rot["team_id"] == t].nlargest(8, "share") if t in trusted else rot.iloc[0:0]
            side_info[side] = {
                "team_id": t,
                "roster_confidence": conf.get(t, "UNKNOWN"),
                "games_seen": gs,
                "overlay_applied": bool(ok_a),
                "continuity_correction_applied": bool(ok),
                "expected_returning_share": exp_ret if np.isfinite(exp_ret) else None,
                **(
                    {k: float(c[k]) if np.isfinite(c[k]) else None for k in cont.columns}
                    if c is not None
                    else {}
                ),  # fmt: skip
                "expected_rotation": [
                    {
                        "player_id": p,
                        "share": round(float(s), 4),
                        "minutes": round(40 * float(s), 1),
                        "class": cl,
                    }
                    for p, s, cl in zip(
                        top["player_id"], top["share"], top["classification"], strict=True
                    )
                ],  # fmt: skip
                "player_block_off": rs["ratings"][side].get("player_off")
                if "ratings" in rs
                else None,
            }
        adj_b = float(sum(coef[k] * (side_terms["home"][k] - side_terms["away"][k]) for k in coef))
        if any(side_info[s]["overlay_applied"] for s in side_info):
            adj_b += 0.0  # intercept not applied: a constant is not roster information
        m_base, t_base = r0["projection"]["margin"], r0["projection"]["total"]
        m_a, t_a = rs["projection"]["margin"], rs["projection"]["total"]
        adj_a = m_a - m_base if any(si["games_seen"] == 0 and si["overlay_applied"]
                                    for si in side_info.values()) else 0.0  # fmt: skip
        margin = m_base + adj_a + adj_b
        total = t_a if adj_a != 0.0 else t_base
        rec = json.loads(json.dumps(r0))
        rec["model"]["version"] = f"{model['version']}+roster"
        p = rec["projection"]
        p["margin"], p["total"] = margin, total
        p["home_score"], p["away_score"] = (total + margin) / 2, (total - margin) / 2
        p["home_win_prob"] = float(1 / (1 + np.exp(-(a_ + b_ * margin))))
        rec["roster"] = {
            "component": "P-ROSTER-1 (PROSPECTIVE_ONLY)",
            "spec_sha256": spec["sha256"],
            "truth_snapshot": stamp,
            "margin_base": m_base,
            "total_base": t_base,
            "adjustment_a_input_substitution": adj_a,
            "adjustment_b_continuity": adj_b,
            "adjustment_total": adj_a + adj_b,
            "uncertainty_margin_sd": p.get("margin_sd"),
            "sides": side_info,
        }
        out.append(rec)
    return out
