"""MARKET_BENCHMARK at multiple stages of the information cycle (downstream only).

Inputs are the append-only archives: PURE projection records (``projections-archive``),
ESPN pre-tip line snapshots (``espn-lines-archive``), Kalshi snapshots
(``kalshi-archive``) and availability captures (``availability-archive``). Nothing here
can feed PURE_BASKETBALL (the PURE packages cannot import ``cbb_edge.market``; CI).

* ``stage_benchmark``  How close was PURE to the market — and to the result — at
  T-24h, T-6h, T-90m, T-30m and latest pre-tip? For each stage it uses the market line
  captured in that stage and the latest PURE record archived at or before that capture.
* ``future_market_alignment``  Was PURE, at stage s, directionally closer to where the
  market went LATER (the latest pre-tip line)? Neutral diagnostic, not an edge claim:
  sign agreement of (PURE_s − M_s) with (M_latest − M_s), correlation, and RMSE of
  PURE_s vs M_latest compared with M_s vs M_latest.
* ``kalshi_table``  PURE probability vs Kalshi implied probability per projection
  snapshot and mapped market, with the later and final pre-tip Kalshi prices and the
  outcome.
* ``availability_impact``  For records that carry an availability overlay: projected
  margin / total change from the status update, minutes changed, the game error, and
  the market move AFTERWARDS (evaluated after the fact only).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

STAGES = ("T-24h", "T-6h", "T-90m", "T-30m", "latest")


def read_jsonl_tree(root: Path, pattern: str = "*.jsonl") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for f in sorted(root.rglob(pattern)):
        opener = gzip.open if f.suffix == ".gz" else open
        with opener(f, "rt") as fh:  # type: ignore[operator]
            rows.extend(json.loads(x) for x in fh if x.strip())
    return pd.DataFrame(rows)


def espn_lines(snaps: pd.DataFrame) -> pd.DataFrame:
    """Home-perspective market margin (= −home spread) and total per snapshot row.
    Orientation uses the home_favorite flag (ESPN's spread sign is not reliable)."""
    if snaps.empty:
        return snaps
    s = snaps.copy()
    mag = pd.to_numeric(s["spread"], errors="coerce").abs()
    fav = s["home_favorite"].map({True: 1.0, False: -1.0})
    s["mkt_margin"] = mag * fav
    s["mkt_total"] = pd.to_numeric(s["over_under"], errors="coerce")
    s["captured_at"] = pd.to_datetime(s["captured_at"], utc=True)
    return s.dropna(subset=["mkt_margin"])[
        ["game_id", "captured_at", "horizon", "provider", "mkt_margin", "mkt_total"]
    ]


def projection_table(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append(
            {
                "game_id": r["game"].get("espn_game_id"),
                "version": r["model"]["version"],
                "as_of": pd.Timestamp(r["prospective"]["as_of"]),
                "margin": r["projection"]["margin"],
                "total": r["projection"]["total"],
                "home_wp": r["projection"]["home_win_prob"],
                "margin_sd": r["projection"].get("margin_sd"),
            }
        )
    p = pd.DataFrame(rows)
    if not p.empty:
        p["as_of"] = pd.to_datetime(p["as_of"], utc=True)
    return p


def _asof_join(proj: pd.DataFrame, lines: pd.DataFrame) -> pd.DataFrame:
    """For each (version, line snapshot): the latest PURE record with as_of <= capture."""
    out = []
    for v, pv in proj.groupby("version"):
        a = lines.sort_values("captured_at")
        b = pv.sort_values("as_of")
        j = pd.merge_asof(
            a, b, left_on="captured_at", right_on="as_of", by="game_id", direction="backward"
        )
        out.append(j.assign(version=v).dropna(subset=["margin"]))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def stage_benchmark(proj: pd.DataFrame, lines: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """RMSE of PURE and of the market line vs the final margin, by version and stage."""
    if proj.empty or lines.empty:
        return pd.DataFrame()
    j = _asof_join(proj, lines.drop_duplicates(["game_id", "horizon"], keep="last"))
    j = j.merge(results[["game_id", "margin"]].rename(columns={"margin": "actual"}), on="game_id")
    rows = []
    for (v, h), x in j.groupby(["version", "horizon"]):
        e_p = x["margin"] - x["actual"]
        e_m = x["mkt_margin"] - x["actual"]
        rows.append(
            {
                "version": v,
                "stage": h,
                "n": len(x),
                "pure_rmse": float(np.sqrt((e_p**2).mean())),
                "market_rmse": float(np.sqrt((e_m**2).mean())),
                "market_gap": float(np.sqrt((e_p**2).mean()) - np.sqrt((e_m**2).mean())),
                "pure_vs_market_rmse": float(
                    np.sqrt(((x["margin"] - x["mkt_margin"]) ** 2).mean())
                ),
            }
        )
    return pd.DataFrame(rows)


def future_market_alignment(
    proj: pd.DataFrame, lines: pd.DataFrame, min_move: float = 0.25
) -> pd.DataFrame:
    if proj.empty or lines.empty:
        return pd.DataFrame()
    last = (
        lines.sort_values("captured_at")
        .groupby("game_id")
        .tail(1)[["game_id", "mkt_margin"]]
        .rename(columns={"mkt_margin": "mkt_latest"})
    )
    j = _asof_join(proj, lines.drop_duplicates(["game_id", "horizon"], keep="last"))
    j = j.merge(last, on="game_id")
    rows = []
    for (v, h), x in j.groupby(["version", "horizon"]):
        if h == "latest":
            continue
        dp = x["margin"] - x["mkt_margin"]  # PURE vs market now
        dm = x["mkt_latest"] - x["mkt_margin"]  # where the market went later
        moved = dm.abs() >= min_move
        rows.append(
            {
                "version": v,
                "stage": h,
                "n": len(x),
                "n_moved": int(moved.sum()),
                "sign_agreement": float((np.sign(dp[moved]) == np.sign(dm[moved])).mean())
                if moved.any()
                else np.nan,
                "corr_pure_gap_with_future_move": float(np.corrcoef(dp, dm)[0, 1])
                if len(x) > 2 and dp.std() > 0 and dm.std() > 0
                else np.nan,
                "rmse_pure_vs_latest_market": float(
                    np.sqrt(((x["margin"] - x["mkt_latest"]) ** 2).mean())
                ),
                "rmse_stage_market_vs_latest": float(np.sqrt((dm**2).mean())),
            }
        )
    return pd.DataFrame(rows)


def kalshi_table(
    records: list[dict[str, Any]],
    kalshi: pd.DataFrame,
    market_to_game: dict[str, tuple[int, bool]],
    results: pd.DataFrame,
) -> pd.DataFrame:
    """One row per (projection record, mapped GAME_WINNER market): PURE probability of
    the YES team winning, Kalshi mid at the latest snapshot <= record as_of, the later
    and final pre-tip mids, and the outcome. ``market_to_game``: ticker -> (game_id,
    yes_is_home)."""
    if kalshi.empty or not records:
        return pd.DataFrame()
    k = kalshi.copy()
    k["ticker"] = k["market"].map(lambda m: m.get("ticker"))
    k["captured_at"] = pd.to_datetime(k["captured_at"], utc=True)
    k["mid"] = k["market"].map(_mid)
    k = k[k["ticker"].isin(market_to_game) & (k["family"] == "GAME_WINNER") & k["mid"].notna()]
    res = results.set_index("game_id")["margin"]
    rows = []
    for r in records:
        gid = r["game"].get("espn_game_id")
        as_of = pd.Timestamp(r["prospective"]["as_of"])
        tip = pd.Timestamp(r["game"]["start_time_utc"])
        for tk, (g, yes_home) in market_to_game.items():
            if g != gid:
                continue
            x = k[k["ticker"] == tk].sort_values("captured_at")
            before = x[x["captured_at"] <= as_of]
            pre = x[x["captured_at"] < tip]
            if before.empty or pre.empty:
                continue
            ph = r["projection"]["home_win_prob"]
            outcome = res.get(gid)
            rows.append(
                {
                    "game_id": gid,
                    "ticker": tk,
                    "version": r["model"]["version"],
                    "as_of": as_of,
                    "pure_prob_yes": ph if yes_home else 1 - ph,
                    "kalshi_prob_yes": before["mid"].iloc[-1] / 100,
                    "kalshi_at": before["captured_at"].iloc[-1],
                    "kalshi_later_prob_yes": x[x["captured_at"] > as_of]["mid"].iloc[0] / 100
                    if (x["captured_at"] > as_of).any()
                    else np.nan,
                    "kalshi_final_pretip_prob_yes": pre["mid"].iloc[-1] / 100,
                    "yes_won": (
                        None
                        if outcome is None or pd.isna(outcome)
                        else float((outcome > 0) == bool(yes_home))
                    ),
                }
            )
    return pd.DataFrame(rows)


def _mid(m: dict[str, Any]) -> float | None:
    b, a = m.get("yes_bid"), m.get("yes_ask")
    if b is None or a is None or not (0 < a <= 100) or b < 0:
        return None
    return (float(b) + float(a)) / 2


def availability_impact(
    records: list[dict[str, Any]], lines: pd.DataFrame, results: pd.DataFrame
) -> pd.DataFrame:
    """Records with an ``availability`` block {margin_base, total_base, players:[...]}:
    projected change from the status update, game error, market move afterwards."""
    rows = []
    for r in records:
        av = r.get("availability")
        if not av:
            continue
        rows.append(
            {
                "game_id": r["game"].get("espn_game_id"),
                "version": r["model"]["version"],
                "as_of": pd.Timestamp(r["prospective"]["as_of"]),
                "d_margin": r["projection"]["margin"] - av["margin_base"],
                "d_total": r["projection"]["total"] - av["total_base"],
                "n_players_changed": len(av.get("players", [])),
                "minutes_changed": float(
                    sum(abs(p.get("d_share", 0)) for p in av.get("players", [])) * 40
                ),
                "margin": r["projection"]["margin"],
                "margin_base": av["margin_base"],
            }
        )
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d["as_of"] = pd.to_datetime(d["as_of"], utc=True)
    d = d.merge(
        results[["game_id", "margin"]].rename(columns={"margin": "actual"}),
        on="game_id",
        how="left",
    )
    d["abs_err_avail"] = (d["margin"] - d["actual"]).abs()
    d["abs_err_base"] = (d["margin_base"] - d["actual"]).abs()
    if not lines.empty:
        ln = lines.sort_values("captured_at")
        after = []
        for _, x in d.iterrows():
            g = ln[ln["game_id"] == x["game_id"]]
            pre = g[g["captured_at"] <= x["as_of"]]
            post = g[g["captured_at"] > x["as_of"]]
            after.append(
                post["mkt_margin"].iloc[-1] - pre["mkt_margin"].iloc[-1]
                if len(pre) and len(post)
                else np.nan
            )
        d["market_move_after"] = after
    return d
