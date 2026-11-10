"""Wave 1 (2026-11-10): reproduce, diagnose and walk-forward-correct the PURE scoring-level error.

RESEARCH ONLY. Nothing here places, sizes, recommends or authorises a trade, and nothing edits a
frozen projection: every input is read from the immutable archives and every output is a new file.

Pieces
------
* loaders (frozen projections, verified finals with an *availability* time, ESPN pre-tip lines);
* ``decompose``  - exact possession x efficiency decomposition of total / margin errors;
* ``segment``    - error summaries by team game number, pace, spread size, opponent quality, ...;
* ``metrics`` / ``paired_bootstrap`` - the scoring rules used to compare versions on IDENTICAL games.

The walk-forward challenger itself lives in ``cbb_edge.model.level_adapt`` (pure functions).
"""

from __future__ import annotations

import glob
import json
import math
import random
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BASE_VERSION = "pure-0.5.0"
INCUMBENT = "pure-0.2.0"
ROSTER_VERSION = "pure-0.5.0_roster"
#: version -> directory (relative to the projections-archive root) holding <date>/<game>/<as_of>.json
VERSION_DIRS = {
    "pure-0.2.0": "projections/2027",
    "pure-0.3.0": "projections/pure-0.3.0/2027",
    "pure-0.4.0": "projections/pure-0.4.0/2027",
    "pure-0.5.0": "projections/pure-0.5.0/2027",
    "pure-0.5.0_roster": "projections/pure-0.5.0_roster/2027",
}
#: scoring window requested for Wave 1: ET dates through 2026-11-09 (EST = UTC-5 after Nov 1)
CUTOFF_TIP_UTC = "2026-11-10T05:00:00+00:00"


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------------- loaders
def load_frozen(root: Path, version: str) -> dict[int, dict[str, Any]]:
    """Latest FROZEN projection per game whose information cutoff (``as_of``) precedes the tip.

    Records are immutable archive files; we only read them. ``as_of`` (not file generation time) is
    the information cutoff, which is also the rule the prospective scoreboard uses, so counts and
    errors reconcile with it."""
    best: dict[int, dict[str, Any]] = {}
    pattern = str(root / VERSION_DIRS[version] / "*" / "*" / "*.json")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as fh:
            r = json.load(fh)
        g = r.get("game") or {}
        gid, tip = g.get("espn_game_id"), parse_ts(g.get("start_time_utc"))
        as_of = parse_ts((r.get("prospective") or {}).get("as_of"))
        p = r.get("projection") or {}
        if gid is None or tip is None or as_of is None:
            continue
        if not as_of < tip or p.get("margin") is None or p.get("total") is None:
            continue
        cur = best.get(int(gid))
        if cur is None or as_of > cur["as_of"]:
            fr = r.get("freshness") or {}
            best[int(gid)] = {
                "game_id": int(gid), "tip": tip, "as_of": as_of, "site": g.get("site"),
                "home_name": (r.get("home") or {}).get("name"),
                "away_name": (r.get("away") or {}).get("name"),
                "home_conf": (r.get("home") or {}).get("conference"),
                "away_conf": (r.get("away") or {}).get("conference"),
                "margin": float(p["margin"]), "total": float(p["total"]),
                "margin_sd": float(p["margin_sd"]), "total_sd": float(p["total_sd"]),
                "home_score": float(p["home_score"]), "away_score": float(p["away_score"]),
                "poss": float(p["possessions"]), "home_ppp": float(p["home_ppp"]),
                "away_ppp": float(p["away_ppp"]), "home_wp": float(p["home_win_prob"]),
                "home_games_seen": fr.get("home_games_seen"),
                "away_games_seen": fr.get("away_games_seen"),
                "home_tempo": ((r.get("ratings") or {}).get("home") or {}).get("adj_tempo"),
                "away_tempo": ((r.get("ratings") or {}).get("away") or {}).get("adj_tempo"),
                "home_adj_o": ((r.get("ratings") or {}).get("home") or {}).get("adj_off"),
                "home_adj_d": ((r.get("ratings") or {}).get("home") or {}).get("adj_def"),
                "away_adj_o": ((r.get("ratings") or {}).get("away") or {}).get("adj_off"),
                "away_adj_d": ((r.get("ratings") or {}).get("away") or {}).get("adj_def"),
                "roster": r.get("roster"),
                "sha": (r.get("prospective") or {}).get("model_sha256"),
            }  # fmt: skip
    return best


def load_finals(schedule_root: Path) -> dict[int, dict[str, Any]]:
    """Verified finals. ``available_at`` (first archive observation already showing the game as
    completed) - not the tip - is when a result may enter a walk-forward fit."""
    out: dict[int, dict[str, Any]] = {}
    for path in sorted(schedule_root.glob("rows/**/*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if not (
                    r.get("status_type_completed")
                    and r.get("home_score") is not None
                    and r.get("away_score") is not None
                    and r.get("game_id") is not None
                ):
                    continue
                gid, seen = int(r["game_id"]), parse_ts(r.get("observed_at"))
                first = out[gid]["available_at"] if gid in out else seen
                # score = LAST verified completed observation (ESPN corrects finals); availability
                # = FIRST completed observation (when a walk-forward fit could first have seen it)
                out[gid] = {
                    "home": int(r["home_score"]), "away": int(r["away_score"]),
                    "available_at": min(first, seen) if first and seen else (first or seen),
                    "periods": r.get("status_period"), "neutral": bool(r.get("neutral_site")),
                }  # fmt: skip
    return out


def load_espn_lines(espn_root: Path) -> dict[int, dict[str, Any]]:
    """Last pre-tip free ESPN line per game (BENCHMARK ONLY; never a PURE input).

    ``spread`` is the HOME spread (negative = home favourite) so market margin = -spread."""
    best: dict[int, dict[str, Any]] = {}
    for path in sorted(glob.glob(str(espn_root / "snapshots" / "**" / "*.jsonl"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                cap, tip = parse_ts(r.get("captured_at")), parse_ts(r.get("tip_utc"))
                if cap is None or tip is None or cap >= tip:
                    continue
                if r.get("spread") is None or r.get("over_under") is None:
                    continue
                gid = int(r["game_id"])
                cur = best.get(gid)
                if cur is None or cap > cur["captured_at"]:
                    best[gid] = {
                        "captured_at": cap, "spread": float(r["spread"]),
                        "total": float(r["over_under"]), "provider": r.get("provider"),
                        "minutes_to_tip": r.get("minutes_to_tip"),
                    }  # fmt: skip
    return best


def load_team_box_actuals(team_box_parquet: Path) -> dict[int, dict[str, float]]:
    """Realized possessions / points per possession per game from the free ESPN team box score.

    POSTGAME DATA: used only to *score* errors, never as a model input."""
    import pandas as pd

    from cbb_edge.features.possessions import team_possessions

    df = pd.read_parquet(team_box_parquet)
    out: dict[int, dict[str, float]] = {}
    for gid, g in df.groupby("game_id"):
        if len(g) != 2:
            continue
        home = g[g["team_home_away"] == "home"]
        away = g[g["team_home_away"] == "away"]
        if len(home) != 1 or len(away) != 1:
            continue
        h, a = home.iloc[0], away.iloc[0]
        try:
            ph = team_possessions(
                float(h["field_goals_attempted"]), float(h["offensive_rebounds"]),
                float(h["turnovers"]), float(h["free_throws_attempted"]),
            )  # fmt: skip
            pa = team_possessions(
                float(a["field_goals_attempted"]), float(a["offensive_rebounds"]),
                float(a["turnovers"]), float(a["free_throws_attempted"]),
            )  # fmt: skip
        except (TypeError, ValueError, KeyError):
            continue
        poss = (ph + pa) / 2.0
        if not poss or poss != poss or poss < 30:
            continue
        out[int(gid)] = {"poss": poss, "home_pts": float(h["team_score"]),
                         "away_pts": float(a["team_score"])}  # fmt: skip
    return out


# --------------------------------------------------------------------------------- assembly
def eligible_games(
    frozen: dict[str, dict[int, dict[str, Any]]],
    finals: dict[int, dict[str, Any]],
    *,
    cutoff_tip: str = CUTOFF_TIP_UTC,
) -> list[int]:
    """Games with a frozen pregame projection from EVERY version and a verified final, tipping
    before ``cutoff_tip``. Ordered by tip time."""
    cut = parse_ts(cutoff_tip)
    ids = set(finals)
    for per in frozen.values():
        ids &= set(per)
    base = frozen[BASE_VERSION]
    keep = [g for g in ids if base[g]["tip"] < cut]  # type: ignore[operator]
    return sorted(keep, key=lambda g: (base[g]["tip"], g))


def errors(proj: dict[str, Any], final: dict[str, Any]) -> dict[str, float]:
    h, a = final["home"], final["away"]
    return {
        "margin_err": (h - a) - proj["margin"],
        "total_err": (h + a) - proj["total"],
    }


# --------------------------------------------------------------------------------- decomposition
def decompose(proj: dict[str, Any], act: dict[str, float]) -> dict[str, float]:
    """Exact (sequential) decomposition. With ``score = poss x ppp`` for both teams:

    total_err  = pace_term + eff_term, pace = (poss_a - poss_p) * (hppp_p + appp_p),
                 eff = poss_a * [(hppp_a - hppp_p) + (appp_a - appp_p)]
    margin_err = pace_m + off_h - off_a with the same split on the difference of the two ppps.
    The home team's *defensive* efficiency error is the away team's ppp error (and vice versa)."""
    pp = proj["poss"]
    hp, ap = proj["home_ppp"], proj["away_ppp"]
    pa = act["poss"]
    ha, aa = act["home_pts"] / pa, act["away_pts"] / pa
    d_poss, d_h, d_a = pa - pp, ha - hp, aa - ap
    return {
        "poss_err": d_poss,
        "home_ppp_err": d_h,  # home offence == away defence
        "away_ppp_err": d_a,  # away offence == home defence
        "total_pace_term": d_poss * (hp + ap),
        "total_eff_term": pa * (d_h + d_a),
        "margin_pace_term": d_poss * (hp - ap),
        "margin_eff_term": pa * (d_h - d_a),
        "total_err_check": (act["home_pts"] + act["away_pts"]) - proj["total"],
    }


# --------------------------------------------------------------------------------- statistics
def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def point_metrics(rows: Iterable[dict[str, float]]) -> dict[str, float]:
    """Margin/total MAE, RMSE, bias; winner Brier/log loss, from rows with
    margin_err, total_err, p_home (prob) and y_home (0/1)."""
    rows = list(rows)
    me = [r["margin_err"] for r in rows]
    te = [r["total_err"] for r in rows]
    out: dict[str, float] = {"n": float(len(rows))}
    if not rows:
        return out
    out.update(
        margin_mae=mean([abs(x) for x in me]), margin_rmse=math.sqrt(mean([x * x for x in me])),
        margin_bias=mean(me),
        total_mae=mean([abs(x) for x in te]), total_rmse=math.sqrt(mean([x * x for x in te])),
        total_bias=mean(te),
    )  # fmt: skip
    sc = [r for r in rows if r.get("p_home") is not None]
    if sc:
        out["brier"] = mean([brier(r["p_home"], int(r["y_home"])) for r in sc])
        out["logloss"] = mean([logloss(r["p_home"], int(r["y_home"])) for r in sc])
    return out


def paired_bootstrap(
    a: Sequence[float], b: Sequence[float], *, reps: int = 4000, seed: int = 20261110
) -> dict[str, float]:
    """Mean of (a - b) over identical games with a 90% percentile bootstrap interval (games are the
    resampling unit). Negative = a is lower (better for loss-type quantities)."""
    n = len(a)
    d = [x - y for x, y in zip(a, b, strict=True)]
    if n == 0:
        return {"n": 0.0, "diff": float("nan"), "lo": float("nan"), "hi": float("nan")}
    rng = random.Random(seed)
    means = sorted(mean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(reps))
    return {
        "n": float(n), "diff": mean(d),
        "lo": means[int(0.05 * reps)], "hi": means[int(0.95 * reps) - 1],
    }  # fmt: skip


def bucket(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str | None]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        k = key(r)
        if k is not None:
            out.setdefault(k, []).append(r)
    return out


def tercile_labels(values: Sequence[float]) -> tuple[float, float]:
    s = sorted(values)
    return s[len(s) // 3], s[(2 * len(s)) // 3]


def et_date(tip: datetime) -> str:
    """Tip's Eastern calendar date (EST, UTC-5; all Wave 1 games are after the Nov 1 change)."""
    return (tip - timedelta(hours=5)).date().isoformat()
