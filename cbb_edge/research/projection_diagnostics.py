"""Offline projection-weakness diagnostics across the five frozen model versions (RESEARCH ONLY).

Reads frozen pre-tip records (``wave1.load_frozen``), orientation-verified finals and the last pre-tip
ESPN line (benchmark only, never an input). Nothing is fitted for production and nothing is promoted.
Records frozen at/after the Wave 14 boundary are kept OUT of every statistic here (the frozen Wave 14
evaluation owns them); only their count is reported. All numbers are EXPLORATORY_HISTORICAL.

Every per-version statistic is computed on the identical game set (all five versions frozen pre-tip
with a verified final). Intervals: 90% percentile bootstrap resampling whole ET dates (clusters).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from cbb_edge.research import wave1 as w

VERSIONS = ("pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0", "pure-0.5.0_roster")
BASE = "pure-0.5.0"
MARKET = "market"
REPS, SEED = 1000, 20261113
Z80 = 1.2815515655446004


def build_games(
    frozen: dict[str, dict[int, dict[str, Any]]],
    finals: dict[int, dict[str, Any]],
    market: dict[int, dict[str, Any]],
    *,
    before: Any,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Identical-game rows: every version frozen pre-tip with ``as_of`` < ``before`` and a final."""
    out, cnt = [], defaultdict(int)
    for gid, b in sorted(frozen[BASE].items()):
        if gid not in finals:
            cnt["no_final"] += 1
            continue
        if any(gid not in frozen[v] for v in VERSIONS):
            cnt["version_missing"] += 1
            continue
        if any(frozen[v][gid]["as_of"] >= before for v in VERSIONS):
            cnt["prospective_wave14_excluded"] += 1
            continue
        f = finals[gid]
        row: dict[str, Any] = {
            "game_id": gid, "date": w.et_date(b["tip"]), "actual_margin": f["home"] - f["away"],
            "actual_total": f["home"] + f["away"], "y": int(f["home"] > f["away"]),
            "min_seen": _min_seen(b), "poss": b["poss"],
        }  # fmt: skip
        for v in VERSIONS:
            p = frozen[v][gid]
            row[v] = {
                k: p[k] for k in ("margin", "total", "margin_sd", "total_sd", "home_wp", "poss")
            }
        m = market.get(gid)
        if m is not None and m.get("total") is not None and m.get("spread") is not None:
            row[MARKET] = {"margin": -float(m["spread"]), "total": float(m["total"])}
        out.append(row)
        cnt["scored"] += 1
    return out, dict(cnt)


def _min_seen(g: dict[str, Any]) -> int | None:
    s = [x for x in (g.get("home_games_seen"), g.get("away_games_seen")) if x is not None]
    return int(min(s)) if s else None


def _ols_slope(x: Sequence[float], y: Sequence[float]) -> float:
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sxx if sxx > 0 else float("nan")  # fmt: skip


def boot(rows: Sequence[dict[str, Any]], stat: Callable[[Sequence[dict[str, Any]]], float]) -> dict[str, float]:  # fmt: skip
    """Point estimate plus a 90% date-clustered percentile interval."""
    if not rows:
        return {"est": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["date"]].append(r)
    keys = sorted(by)
    rng = random.Random(SEED)
    vals = []
    for _ in range(REPS):
        smp = [r for _k in keys for r in by[keys[rng.randrange(len(keys))]]]
        v = stat(smp)
        if not math.isnan(v):
            vals.append(v)
    vals.sort()
    lo, hi = (vals[int(0.05 * len(vals))], vals[int(0.95 * len(vals)) - 1]) if vals else (float("nan"),) * 2  # fmt: skip
    return {"est": stat(rows), "lo": lo, "hi": hi, "n": len(rows), "dates": len(keys)}


def err(r: dict[str, Any], v: str, k: str) -> float:
    return r[f"actual_{k}"] - r[v][k]


def version_table(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out = {}
    for v in VERSIONS:
        te = [err(r, v, "total") for r in rows]
        me = [err(r, v, "margin") for r in rows]
        tz = [e / r[v]["total_sd"] for e, r in zip(te, rows, strict=True)]
        mz = [e / r[v]["margin_sd"] for e, r in zip(me, rows, strict=True)]
        out[v] = {
            "n": float(len(rows)),
            "total_bias": w.mean(te), "total_mae": w.mean([abs(x) for x in te]),
            "margin_bias": w.mean(me), "margin_mae": w.mean([abs(x) for x in me]),
            "logloss": w.mean([w.logloss(r[v]["home_wp"], r["y"]) for r in rows]),
            "brier": w.mean([w.brier(r[v]["home_wp"], r["y"]) for r in rows]),
            "total_z_sd": _sd(tz), "margin_z_sd": _sd(mz),
            "total_cover80": w.mean([float(abs(z) <= Z80) for z in tz]),
            "margin_cover80": w.mean([float(abs(z) <= Z80) for z in mz]),
            "total_slope": _ols_slope([r[v]["total"] for r in rows], [r["actual_total"] for r in rows]),
            "margin_slope": _ols_slope([r[v]["margin"] for r in rows], [r["actual_margin"] for r in rows]),
        }  # fmt: skip
    return out


def _sd(x: Sequence[float]) -> float:
    if len(x) < 2:
        return float("nan")
    m = sum(x) / len(x)
    return math.sqrt(sum((a - m) ** 2 for a in x) / (len(x) - 1))


def segments(rows: Sequence[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> dict[str, dict[str, float]]:  # fmt: skip
    """Total/margin bias and MAE of the base and roster versions (and market where present) per segment."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    out = {}
    for k in sorted(by):
        g = by[k]
        mk = [r for r in g if MARKET in r]
        out[k] = {"n": float(len(g)),
                  "total_bias_base": w.mean([err(r, BASE, "total") for r in g]),
                  "total_bias_market": w.mean([err(r, MARKET, "total") for r in mk]) if mk else float("nan"),
                  "margin_mae_base": w.mean([abs(err(r, BASE, "margin")) for r in g]),
                  "margin_mae_roster": w.mean([abs(err(r, "pure-0.5.0_roster", "margin")) for r in g]),
                  "margin_mae_market": w.mean([abs(err(r, MARKET, "margin")) for r in mk]) if mk else float("nan"),
                  "n_market": float(len(mk))}  # fmt: skip
    return out


def seen_bucket(r: dict[str, Any]) -> str:
    s = r["min_seen"]
    return "unknown" if s is None else str(s) if s < 3 else "3+"


def tercile_key(rows: Sequence[dict[str, Any]], f: Callable[[dict[str, Any]], float]) -> Callable[[dict[str, Any]], str]:  # fmt: skip
    xs = sorted(f(r) for r in rows)
    a, b = xs[len(xs) // 3], xs[2 * len(xs) // 3]
    return lambda r: "1_low" if f(r) < a else "2_mid" if f(r) < b else "3_high"


def market_disagreement(
    rows: Sequence[dict[str, Any]], v: str = BASE
) -> dict[str, dict[str, float]]:
    """BENCHMARK DIAGNOSTIC: slope of (actual - model) on (market - model). ~1 = the market's
    disagreement with the model is fully borne out; ~0 = it is noise. Date-clustered interval."""
    mk = [r for r in rows if MARKET in r]
    out = {}
    for k in ("total", "margin"):

        def stat(s: Sequence[dict[str, Any]], k: str = k) -> float:
            return _ols_slope([r[MARKET][k] - r[v][k] for r in s], [err(r, v, k) for r in s])

        out[k] = boot(mk, stat)
    return out


def reliability(
    rows: Sequence[dict[str, Any]], v: str = BASE, bins: int = 5
) -> list[dict[str, float]]:
    """Home-win probability reliability: mean forecast vs observed home-win rate per equal-count bin."""
    s = sorted(rows, key=lambda r: r[v]["home_wp"])
    out = []
    for i in range(bins):
        g = s[i * len(s) // bins : (i + 1) * len(s) // bins]
        if g:
            out.append({"n": float(len(g)), "mean_p": w.mean([r[v]["home_wp"] for r in g]),
                        "observed": w.mean([float(r["y"]) for r in g])})  # fmt: skip
    return out


def roster_effect(rows: Sequence[dict[str, Any]], threshold: float = 2.0) -> dict[str, Any]:
    """Roster overlay vs base where the overlay moves the margin by >= ``threshold`` points."""
    big = [
        r for r in rows if abs(r["pure-0.5.0_roster"]["margin"] - r[BASE]["margin"]) >= threshold
    ]

    def d(s: Sequence[dict[str, Any]]) -> float:
        return w.mean([abs(err(r, "pure-0.5.0_roster", "margin")) - abs(err(r, BASE, "margin")) for r in s]) if s else float("nan")  # fmt: skip

    return {"threshold": threshold, "roster_minus_base_margin_mae_big_moves": boot(big, d),
            "roster_minus_base_margin_mae_all": boot(rows, d)}  # fmt: skip


def _abs_margin_groups(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"lt8": [], "8to16": [], "ge16": []}
    for r in rows:
        a = abs(r[BASE]["margin"])
        out["lt8" if a < 8 else "8to16" if a < 16 else "ge16"].append(r)
    return out


def run(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    poss_key = tercile_key(rows, lambda r: r[BASE]["poss"])
    tot_key = tercile_key(rows, lambda r: r[BASE]["total"])
    mk = [r for r in rows if MARKET in r]
    return {
        "n_games": len(rows), "n_dates": len({r["date"] for r in rows}), "n_with_market": len(mk),
        "versions": version_table(rows),
        "market_on_market_games": {
            "total_bias": w.mean([err(r, MARKET, "total") for r in mk]) if mk else None,
            "total_mae": w.mean([abs(err(r, MARKET, "total")) for r in mk]) if mk else None,
            "margin_mae": w.mean([abs(err(r, MARKET, "margin")) for r in mk]) if mk else None,
            "base_total_mae_same_games": w.mean([abs(err(r, BASE, "total")) for r in mk]) if mk else None,
            "base_margin_mae_same_games": w.mean([abs(err(r, BASE, "margin")) for r in mk]) if mk else None,
        },
        "ci_base": {
            "total_bias": boot(rows, lambda s: w.mean([err(r, BASE, "total") for r in s])),
            "total_slope": boot(rows, lambda s: _ols_slope([r[BASE]["total"] for r in s], [r["actual_total"] for r in s])),
            "margin_slope": boot(rows, lambda s: _ols_slope([r[BASE]["margin"] for r in s], [r["actual_margin"] for r in s])),
            "margin_z_sd": boot(rows, lambda s: _sd([err(r, BASE, "margin") / r[BASE]["margin_sd"] for r in s])),
            "total_z_sd": boot(rows, lambda s: _sd([err(r, BASE, "total") / r[BASE]["total_sd"] for r in s])),
        },
        "ci_roster": {
            "margin_bias": boot(rows, lambda s: w.mean([err(r, "pure-0.5.0_roster", "margin") for r in s])),
            "margin_slope": boot(rows, lambda s: _ols_slope([r["pure-0.5.0_roster"]["margin"] for r in s], [r["actual_margin"] for r in s])),
        },
        "ci_base_margin_bias": boot(rows, lambda s: w.mean([err(r, BASE, "margin") for r in s])),
        "margin_compression_by_abs_projected_margin": {
            k: {"n": len(g), "base_slope": boot(g, lambda s: _ols_slope([r[BASE]["margin"] for r in s], [r["actual_margin"] for r in s])),
                "base_signed_err_toward_favourite": w.mean([math.copysign(1, r[BASE]["margin"]) * err(r, BASE, "margin") for r in g]),
                "base_margin_z_sd": _sd([err(r, BASE, "margin") / r[BASE]["margin_sd"] for r in g])}
            for k, g in _abs_margin_groups(rows).items()
        },
        "by_date": segments(rows, lambda r: r["date"]),
        "by_min_games_seen": segments(rows, seen_bucket),
        "by_projected_possessions": segments(rows, poss_key),
        "by_projected_total": segments(rows, tot_key),
        "market_disagreement": market_disagreement(rows),
        "reliability_base": reliability(rows),
        "reliability_roster": reliability(rows, "pure-0.5.0_roster"),
        "roster": roster_effect(rows),
    }  # fmt: skip
