"""Wave 14 prospective evaluation tooling (RESEARCH ONLY; protocol research/hypotheses/WAVE14.md).

Reads immutable archives, never writes to them. Eligible game = the latest frozen pure-0.5.0 record
(``as_of`` < tip) has ``as_of`` >= ``PROSPECTIVE_FROM``, valid ``model_inputs``, an orientation-verified
final, a frozen record for every compared version, and both level challengers defined. Until the
preregistered sample exists the only verdict is COLLECTING / INSUFFICIENT EVIDENCE.
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cbb_edge.model import level_adapt as l12
from cbb_edge.model import pw_level as pw
from cbb_edge.research import wave1 as w

#: Registration boundary: set to the registration commit's UTC time (see spec.json / WAVE14.md).
PROSPECTIVE_FROM = "2026-11-11T22:00:00+00:00"
VERSIONS = ("pure-0.2.0", "pure-0.5.0", "pure-0.5.0_roster")
FORECASTERS = (
    "pure-0.2.0",
    "pure-0.5.0",
    "pure-0.5.0_roster",
    "wf-level-0.5.0-v1:level-only",
    pw.VERSION,
)
REPS, SEED, CI = 4000, 20261111, 0.90
MIN_GAMES, MIN_DATES = 150, 5
NONINF_TOTAL_VS_W12 = 0.10  # points of total MAE
MARGIN_MAE_TOL, LOGLOSS_TOL = 0.10, 0.005


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_inputs(root: Path, version: str = pw.BASE_VERSION) -> dict[int, dict[str, Any]]:
    """``model_inputs`` of the SAME record ``wave1.load_frozen`` selects (latest, as_of < tip)."""
    best: dict[int, tuple[Any, Any]] = {}
    for path in sorted(glob.glob(str(root / w.VERSION_DIRS[version] / "*" / "*" / "*.json"))):
        with open(path, encoding="utf-8") as fh:
            r = json.load(fh)
        g = r.get("game") or {}
        tip, as_of = (
            w.parse_ts(g.get("start_time_utc")),
            w.parse_ts((r.get("prospective") or {}).get("as_of")),
        )
        if g.get("espn_game_id") is None or tip is None or as_of is None or not as_of < tip:
            continue
        gid = int(g["espn_game_id"])
        if gid not in best or as_of > best[gid][0]:
            best[gid] = (as_of, r.get("model_inputs"))
    return {gid: {"as_of": a, "mi": mi} for gid, (a, mi) in best.items()}


def attach_inputs(
    base: dict[int, dict[str, Any]], inputs: dict[int, dict[str, Any]]
) -> dict[str, Counter]:
    """Annotate frozen pure-0.5.0 games in place with ``pbar`` (None = fail closed) and ``input_issues``."""
    why: Counter = Counter()
    for gid, g in base.items():
        rec = inputs.get(gid)
        issues = ["no_record"] if rec is None or rec["as_of"] != g["as_of"] else pw.validate_inputs(rec["mi"], as_of=g["as_of"], possessions=g["poss"])  # fmt: skip
        g["input_issues"] = issues
        g["pbar"] = None if issues else pw.pbar(rec["mi"])  # type: ignore[index]
        why.update(issues or ["valid"])
    return {"issues": why}


def verify_manifests(root: Path) -> dict[str, Any]:
    """Frozen-record integrity: every manifest sha256 equals the file's bytes; none missing."""
    total = bad = missing = 0
    for m in sorted(glob.glob(str(root / "projections" / "manifests" / "*.json"))):
        for rel, h in _load(Path(m))["files"].items():
            total += 1
            p = root / "projections" / rel
            if not p.exists():
                missing += 1
            elif hashlib.sha256(p.read_bytes()).hexdigest() != h:
                bad += 1
    return {
        "files": total,
        "hash_mismatch": bad,
        "missing": missing,
        "ok": bad == 0 and missing == 0,
    }


def input_audit(root: Path) -> dict[str, Any]:
    """model_inputs coverage + consistency over EVERY version and manifest (counts only)."""
    out: dict[str, Any] = {"manifests": {}, "records": Counter(), "issues": Counter()}
    for m in sorted(glob.glob(str(root / "projections" / "manifests" / "*.json"))):
        d = _load(Path(m))
        per: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for rel in d["files"]:
            v = "pure-0.2.0" if rel.startswith("2027/") else rel.split("/")[0]
            r = _load(root / "projections" / rel)
            mi = r.get("model_inputs")
            per[v][0] += 1
            per[v][1] += mi is not None
            if mi is not None:
                as_of = w.parse_ts((r.get("prospective") or {}).get("as_of"))
                iss = pw.validate_inputs(
                    mi, as_of=as_of, possessions=float(r["projection"]["possessions"])
                )
                per[v][2] += not iss
                out["issues"].update(iss)
                out["records"][v] += 1
        out["manifests"][Path(m).stem] = {"as_of": d["as_of"], "code_sha": d["code_sha"][:7], "by_version": dict(per)}  # fmt: skip
    out["records"], out["issues"] = dict(out["records"]), dict(out["issues"])
    return out


def reliability(
    base: dict[int, dict[str, Any]], inputs: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Descriptive checks of the exported ridge-diagonal weights over valid-input games."""
    gs, pace_w, eff_w, seen = [], [], [], []
    for gid, g in base.items():
        if g.get("pbar") is None:
            continue
        mi = inputs[gid]["mi"]
        for s in ("home", "away"):
            gs.append(mi[s]["games_seen"])
            pace_w.append(mi[s]["pace_weighting"]["prior_weight"])
            eff_w.append(mi[s]["efficiency_weighting"]["prior_weight"])
            seen.append(mi[s]["pace_weighting"]["effective_sample"] - mi[s]["pace_weighting"]["prior_strength"] - mi[s]["games_seen"])  # fmt: skip
    pb = [g["pbar"] for g in base.values() if g.get("pbar") is not None]
    return {
        "n_games": len(pb), "pbar_min": min(pb, default=None), "pbar_max": max(pb, default=None),
        "pbar_mean": w.mean(pb) if pb else None,
        "games_seen_counts": dict(sorted(Counter(gs).items())),
        "pace_prior_weight_is_function_of_games_seen": max((abs(p - 3.0 / (3.0 + n)) for p, n in zip(pace_w, gs, strict=True)), default=0.0) < 1e-9,  # fmt: skip
        "pace_ess_minus_prior_minus_games_max_abs": max((abs(x) for x in seen), default=0.0),
        "corr_pace_vs_eff_prior_weight": _corr(pace_w, eff_w),
        "pbar_distinct_values": len({round(x, 4) for x in pb}),
    }  # fmt: skip


def _corr(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 3:
        return None
    ma, mb = w.mean(a), w.mean(b)
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / math.sqrt(va * vb)


def build_rows(
    frozen: dict[str, dict[int, dict[str, Any]]],
    finals: dict[int, dict[str, Any]],
    *,
    prospective_from: str = PROSPECTIVE_FROM,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Identical-game rows for every forecaster plus an eligibility funnel. ``frozen['pure-0.5.0']``
    must already carry ``pbar`` (``attach_inputs``)."""
    cut = w.parse_ts(prospective_from)
    base = frozen[pw.BASE_VERSION]
    games = sorted(base.values(), key=lambda g: g["as_of"])
    st_pw = pw.walk_forward(games, finals)
    st_12 = l12.walk_forward(games, finals, l12.Params(sd=False))
    funnel: Counter = Counter()
    rows = []
    for g in games:
        gid = g["game_id"]
        if cut is None or g["as_of"] < cut:
            funnel["record_before_registration"] += 1
            continue
        if g["pbar"] is None:
            funnel["inputs_invalid_or_missing"] += 1
            continue
        if gid not in finals:
            funnel["no_verified_final_yet"] += 1
            continue
        if any(gid not in frozen[v] or frozen[v][gid]["as_of"] < cut for v in VERSIONS):
            funnel["comparator_record_missing"] += 1
            continue
        if st_pw[gid] is None or st_12[gid] is None:
            funnel["challenger_undefined_too_few_finished_games"] += 1
            continue
        f = finals[gid]
        fc: dict[str, dict[str, float]] = {v: frozen[v][gid] for v in VERSIONS}
        # margin is untouched by both level challengers, so they inherit the frozen win probability
        fc["wf-level-0.5.0-v1:level-only"] = {**l12.adapt(g, st_12[gid]), "home_wp": g["home_wp"]}  # type: ignore[arg-type]
        fc[pw.VERSION] = {**pw.adapt(g, st_pw[gid], g["pbar"]), "home_wp": g["home_wp"]}  # type: ignore[arg-type]
        y = int(f["home"] > f["away"])
        row: dict[str, Any] = {"game_id": gid, "date": w.et_date(g["tip"]), "pbar": g["pbar"], "y_home": y,
                               "beta": st_pw[gid]["beta"], "n_train": st_pw[gid]["n_games"]}  # fmt: skip
        for name, p in fc.items():
            wp = p["home_wp"] if "home_wp" in p else w._cdf(p["margin"] / p["margin_sd"])
            row[name] = {"margin_err": (f["home"] - f["away"]) - p["margin"], "total_err": (f["home"] + f["away"]) - p["total"],  # fmt: skip
                         "p_home": wp, "logloss": w.logloss(wp, y), "brier": w.brier(wp, y),
                         "home_err": f["home"] - p["home_score"], "away_err": f["away"] - p["away_score"]}  # fmt: skip
        rows.append(row)
        funnel["eligible"] += 1
    return rows, dict(funnel)


def cluster_diff(rows: Sequence[dict[str, Any]], a: str, b: str, metric: str, *, reps: int = REPS, seed: int = SEED) -> dict[str, float]:  # fmt: skip
    """Matched-game mean of (a - b) of ``metric`` (``abs:total_err`` = absolute error), 90% percentile
    interval from a bootstrap that resamples whole ET game dates (clusters)."""

    def val(r: dict[str, Any], k: str) -> float:
        return abs(r[k][metric[4:]]) if metric.startswith("abs:") else r[k][metric]

    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by[r["date"]].append(val(r, a) - val(r, b))
    clusters = [(sum(v), len(v)) for v in by.values()]
    n = sum(c for _, c in clusters)
    if n == 0:
        return {
            "n": 0.0,
            "n_dates": 0.0,
            "diff": float("nan"),
            "lo": float("nan"),
            "hi": float("nan"),
        }
    rng = random.Random(seed)
    k = len(clusters)
    means = []
    for _ in range(reps):
        s = c = 0.0
        for _i in range(k):
            ds, dn = clusters[rng.randrange(k)]
            s, c = s + ds, c + dn
        means.append(s / c)
    means.sort()
    lo_i, hi_i = int(((1 - CI) / 2) * reps), int((1 - (1 - CI) / 2) * reps) - 1
    return {"n": float(n), "n_dates": float(k), "diff": sum(s for s, _ in clusters) / n, "lo": means[lo_i], "hi": means[hi_i]}  # fmt: skip


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out = {}
    for f in FORECASTERS:
        if not rows:
            break
        te, me = [r[f]["total_err"] for r in rows], [r[f]["margin_err"] for r in rows]
        out[f] = {"n": float(len(rows)), "total_mae": w.mean([abs(x) for x in te]), "total_bias": w.mean(te),
                  "margin_mae": w.mean([abs(x) for x in me]), "margin_bias": w.mean(me),
                  "logloss": w.mean([r[f]["logloss"] for r in rows]), "brier": w.mean([r[f]["brier"] for r in rows])}  # fmt: skip
    return out


def verdict(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Preregistered decision rule (WAVE14.md section 6). Below the sample floor the ONLY outcome is
    COLLECTING / INSUFFICIENT EVIDENCE."""
    ch = pw.VERSION
    w12 = "wf-level-0.5.0-v1:level-only"
    n, dates = len(rows), len({r["date"] for r in rows})
    out: dict[str, Any] = {
        "n_games": n,
        "n_dates": dates,
        "floor": {"games": MIN_GAMES, "dates": MIN_DATES},
    }
    if n < MIN_GAMES or dates < MIN_DATES:
        out["status"] = "COLLECTING / INSUFFICIENT EVIDENCE"
        out["reason"] = f"{n}/{MIN_GAMES} games, {dates}/{MIN_DATES} dates"
        return out
    c = {
        "total_mae_vs_pure050": cluster_diff(rows, ch, "pure-0.5.0", "abs:total_err"),
        "total_mae_vs_w12_level": cluster_diff(rows, ch, w12, "abs:total_err"),
        "total_mae_vs_pure020": cluster_diff(rows, ch, "pure-0.2.0", "abs:total_err"),
        "total_mae_vs_roster": cluster_diff(rows, ch, "pure-0.5.0_roster", "abs:total_err"),
        "margin_mae_vs_pure050": cluster_diff(rows, ch, "pure-0.5.0", "abs:margin_err"),
        "logloss_vs_pure050": cluster_diff(rows, ch, "pure-0.5.0", "logloss"),
    }
    out["contrasts"] = c
    a, b = c["total_mae_vs_pure050"], c["total_mae_vs_w12_level"]
    guards = (
        c["margin_mae_vs_pure050"]["hi"] <= MARGIN_MAE_TOL
        and c["logloss_vs_pure050"]["hi"] <= LOGLOSS_TOL
    )
    out["checks"] = {
        "total_mae_improves_vs_pure050": a["hi"] < 0,
        "no_regression_vs_w12_level": b["hi"] <= NONINF_TOTAL_VS_W12,
        "margin_and_calibration_guards": guards,
    }
    if all(out["checks"].values()):
        out["status"] = "IMPROVED (exploratory-prospective; nothing is promoted)"
    elif a["diff"] >= 0 or a["lo"] > 0 or b["lo"] > NONINF_TOTAL_VS_W12:
        out["status"] = "NOT IMPROVED"
    else:
        out["status"] = "INSUFFICIENT EVIDENCE"
    return out
