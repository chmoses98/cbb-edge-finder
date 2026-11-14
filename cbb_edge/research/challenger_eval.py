"""Shared, read-only evaluation machinery for the Wave 15/16 margin challengers (RESEARCH_ONLY).

Waves 15 (margin calibration) and 16 (roster centring) form ONE preregistered family of three
primary tests (``FAMILY``). Each test is judged with a Bonferroni one-sided level of
``FAMILY_ALPHA / len(FAMILY)``, so a wave's verdict never depends on the other wave's result.

Challenger forecasts are deterministic functions of (a) a frozen pre-tip production record,
(b) code and parameters frozen at the registration commit and (c) finals first observed at or
before that record's ``as_of``. Nothing here writes to an archive or changes a model.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from cbb_edge.research import wave1 as w
from cbb_edge.research import wave14 as w14

# ---- registered constants (shared by both waves; a test pins them to the specs) -----------------
PROSPECTIVE_FROM = (
    "2026-11-15T00:00:00+00:00"  # record as_of at or after this (registration + ~1 day)
)
LAST_ET_DATE = "2026-12-20"  # fixed window: tips on ET dates <= this; no optional stopping
ANALYSIS_NOT_BEFORE = "2026-12-22T12:00:00+00:00"  # the single confirmatory analysis time
MIN_GAMES, MIN_DATES = 300, 10
MODEL_SHA = "c4600f62351b26c159f1eaf9153d5a78a0c07e0c77fe20ed8bbc47e8e9ac0a19"
# Frozen production win-probability link: logit(p) = LINK_SLOPE * margin + c (verified on archive
# records to 1e-12; only the slope is needed to move a probability with a margin change).
LINK_SLOPE = 0.161365
FAMILY = ("W15-A1 margin stretch", "W15-A2 heteroscedastic margin SD", "W16-B roster centring")
FAMILY_ALPHA = 0.05  # one-sided family-wise error rate
PRIMARY_Q = 1.0 - FAMILY_ALPHA / len(FAMILY)  # one-sided bound quantile per primary test
GUARD_Q = 0.95  # one-sided bound quantile for guards (non-inferiority checks)
REPS, SEED = 10000, 20261113
Z80 = 1.2815515655446004
P_CLIP = 1e-4


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def logit(p: float) -> float:
    p = min(max(p, P_CLIP), 1.0 - P_CLIP)
    return math.log(p / (1.0 - p))


def phi_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def shift_prob(p: float, d_margin: float) -> float:
    """Move a frozen production probability along the frozen logistic link by ``d_margin``."""
    return sigmoid(logit(p) + LINK_SLOPE * d_margin)


def score(pred: dict[str, float], y_margin: float) -> dict[str, float]:
    """Per-game scores of ``{"margin", "margin_sd", "p_home"}`` against the actual margin."""
    yh = int(y_margin > 0)
    p = min(max(pred["p_home"], P_CLIP), 1.0 - P_CLIP)
    sd = pred["margin_sd"]
    e = y_margin - pred["margin"]
    return {
        "margin_err": e,
        "abs_margin_err": abs(e),
        "logloss": -(yh * math.log(p) + (1 - yh) * math.log(1.0 - p)),
        "brier": (p - yh) ** 2,
        "margin_nll": 0.5 * math.log(2.0 * math.pi * sd * sd) + 0.5 * (e / sd) ** 2,
        "in80": float(abs(e) <= Z80 * sd),
        "z": e / sd,
        "p_home": p,
    }


def training_history(
    games: Sequence[dict[str, Any]], finals: dict[int, dict[str, Any]]
) -> list[tuple[datetime, dict[str, Any]]]:
    """(final first-observed time, game) for every game with a final, sorted by that time."""
    hist = [
        (finals[g["game_id"]]["available_at"], g)
        for g in games
        if g["game_id"] in finals and finals[g["game_id"]].get("available_at") is not None
    ]
    hist.sort(key=lambda t: t[0])
    return hist


def before(
    hist: Sequence[tuple[datetime, dict[str, Any]]], as_of: datetime
) -> list[dict[str, Any]]:
    """Walk-forward training set: games whose final was observed at or before ``as_of``."""
    return [g for at, g in hist if at <= as_of]


def pushed_by(
    frozen: dict[str, dict[int, dict[str, Any]]],
    versions: Sequence[str],
    rec_manifest: dict[tuple[str, int, str], str],
    provenance: dict[str, Any],
) -> dict[int, Any]:
    """Per game: latest verified push time over the manifests holding each version's selected
    record, or ``None`` when any of them is not provably frozen (fail closed)."""
    out: dict[int, Any] = {}
    for gid in frozen[versions[0]]:
        times = []
        for v in versions:
            r = frozen[v].get(gid)
            stem = None if r is None else rec_manifest.get((v, gid, r["as_of"].isoformat()))
            t = w.parse_ts((provenance.get(stem) or {}).get("pushed_by")) if stem else None
            if t is None:
                times = []
                break
            times.append(t)
        out[gid] = max(times) if times else None
    return out


# ---- AMENDMENT 1 (registered 2026-11-14, before PROSPECTIVE_FROM; research/hypotheses/WAVES15_16_AMENDMENT_1.md)
# Record selection = Wave 14 amendment 5a, applied identically to every version of both waves.
AMENDMENT_1 = "verified_pre_tip_push_selection"


def load_verified(
    root: Path, versions: Sequence[str], provenance: dict[str, Any]
) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, Any]]:
    """Per version, the latest frozen record with ``as_of`` < tip whose push before tip is VERIFIED.

    Uses ``wave14.VerifiedPush`` (WAVE14.md 5a) with this family's boundary ``PROSPECTIVE_FROM``:
    a record with ``as_of >= PROSPECTIVE_FROM`` is selectable only if a verified manifest lists it and
    that manifest's server-side ``pushed_by`` is strictly before tip. Any other such record (pushed at or
    after tip, unverifiable push time, listed in no manifest) is quarantined and never selected; the
    game falls back to the latest earlier admitted record, which must still pass ``eligibility``
    (so a fallback to a record before ``PROSPECTIVE_FROM`` is ineligible, never graded). Records
    before ``PROSPECTIVE_FROM`` are selected exactly as registered (they only train). Provenance
    only - never outcomes. Waves 15 and 16 call this one function, so the ``pure-0.5.0`` record
    selected for a game is the same in both (``base_selection_digest``)."""
    rec_manifest = w14.record_manifests(root)
    frozen: dict[str, dict[int, dict[str, Any]]] = {}
    audit: dict[str, Any] = {"rule": AMENDMENT_1, "since": PROSPECTIVE_FROM, "quarantined": {},
                             "fallback": {}, "no_verified_pre_tip_record": {}}  # fmt: skip
    for v in versions:
        adm = w14.VerifiedPush(v, rec_manifest, provenance, PROSPECTIVE_FROM)
        frozen[v] = w.load_frozen(root, v, allow=adm)
        naive = w.load_frozen(root, v)
        audit["quarantined"][v] = [
            {"game_id": g, "as_of": a, "reason": r} for (g, a), r in sorted(adm.quarantined.items())
        ]
        audit["fallback"][v] = sorted(
            g for g, r in frozen[v].items() if g in naive and r["as_of"] < naive[g]["as_of"]
        )
        audit["no_verified_pre_tip_record"][v] = sorted(set(naive) - set(frozen[v]))
    audit["base_selection_digest"] = selection_digest(frozen[versions[0]])
    return frozen, audit


def selection_digest(records: dict[int, dict[str, Any]]) -> str:
    """sha256 over the sorted (game_id, selected as_of) pairs: equal digests = identical selection."""
    s = "\n".join(f"{g},{records[g]['as_of'].isoformat()}" for g in sorted(records))
    return hashlib.sha256(s.encode()).hexdigest()


def eligibility(
    gid: int,
    frozen: dict[str, dict[int, dict[str, Any]]],
    versions: Sequence[str],
    finals: dict[int, dict[str, Any]],
    pushed: dict[int, Any],
    n_train: int,
    min_train: int,
) -> str:
    """``"eligible"`` or the first failing funnel stage (identical rule for every forecaster)."""
    cut = w.parse_ts(PROSPECTIVE_FROM)
    base = frozen[versions[0]][gid]
    if cut is None or any(gid not in frozen[v] or frozen[v][gid]["as_of"] < cut for v in versions):
        return "record_before_registration_or_missing"
    if w.et_date(base["tip"]) > LAST_ET_DATE:
        return "after_registered_window"
    if any(frozen[v][gid].get("sha") != MODEL_SHA for v in versions):
        return "model_sha_differs_from_registered"
    if gid not in finals:
        return "no_verified_final_yet"
    pb = pushed.get(gid)
    if pb is None:
        return "freeze_time_not_provable"
    if not pb < base["tip"]:
        return "freeze_pushed_at_or_after_tip"
    if n_train < min_train:
        return "challenger_undefined_too_few_finished_games"
    return "eligible"


def cluster_boot(
    rows: Sequence[dict[str, Any]],
    a: str,
    b: str,
    metric: str,
    *,
    reps: int = REPS,
    seed: int = SEED,
) -> dict[str, float]:
    """Matched-game mean of (a - b) for ``metric`` with a bootstrap over whole ET dates.

    Returns the point difference, ``p_ge0`` (share of bootstrap means >= 0: a one-sided p-value for
    "a is lower"), the PRIMARY_Q upper bound, the GUARD_Q upper bound and the matching lower bounds.
    """
    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by[r["date"]].append(r[a][metric] - r[b][metric])
    cl = [(sum(v), len(v)) for v in by.values()]
    n = sum(c for _, c in cl)
    if n == 0:
        nan = float("nan")
        return {"n": 0.0, "n_dates": 0.0, "diff": nan, "p_ge0": nan, "hi_primary": nan,
                "hi_guard": nan, "lo_primary": nan, "lo_guard": nan}  # fmt: skip
    rng = random.Random(seed)
    k = len(cl)
    means = []
    for _ in range(reps):
        s = c = 0.0
        for _i in range(k):
            ds, dn = cl[rng.randrange(k)]
            s, c = s + ds, c + dn
        means.append(s / c)
    means.sort()

    def q(x: float) -> float:
        return means[min(reps - 1, max(0, int(math.ceil(x * reps)) - 1))]

    return {
        "n": float(n),
        "n_dates": float(k),
        "diff": sum(s for s, _ in cl) / n,
        "p_ge0": sum(m >= 0 for m in means) / reps,
        "hi_primary": q(PRIMARY_Q),
        "lo_primary": q(1.0 - PRIMARY_Q),
        "hi_guard": q(GUARD_Q),
        "lo_guard": q(1.0 - GUARD_Q),
    }


def summarize(rows: Sequence[dict[str, Any]], names: Sequence[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for f in names:
        if not rows:
            break
        col: Callable[[str], list[float]] = lambda k, f=f: [r[f][k] for r in rows]  # noqa: E731
        zs = col("z")
        mz = sum(zs) / len(zs)
        out[f] = {
            "n": float(len(rows)),
            "margin_mae": w.mean(col("abs_margin_err")),
            "margin_bias": w.mean(col("margin_err")),
            "logloss": w.mean(col("logloss")),
            "brier": w.mean(col("brier")),
            "margin_nll": w.mean(col("margin_nll")),
            "coverage80": w.mean(col("in80")),
            "z_sd": math.sqrt(sum((z - mz) ** 2 for z in zs) / len(zs)),
        }
    return out


def calibration(rows: Sequence[dict[str, Any]], names: Sequence[str]) -> dict[str, Any]:
    """Win-probability reliability by forecast quintile and margin z-SD/80% coverage by |margin|."""
    out: dict[str, Any] = {}
    for f in names:
        srt = sorted(rows, key=lambda r: r[f]["p_home"])
        bins = []
        for i in range(5):
            part = srt[i * len(srt) // 5 : (i + 1) * len(srt) // 5]
            if part:
                bins.append({"n": len(part), "forecast": w.mean([r[f]["p_home"] for r in part]),
                             "observed": w.mean([float(r["y_margin"] > 0) for r in part])})  # fmt: skip
        bands = {}
        for lo, hi in ((0.0, 8.0), (8.0, 16.0), (16.0, 1e9)):
            sub = [r for r in rows if lo <= abs(r["ref_margin"]) < hi]
            if sub:
                zs = [r[f]["z"] for r in sub]
                bands[f"{lo:g}-{hi:g}" if hi < 1e9 else f">={lo:g}"] = {
                    "n": len(sub),
                    "z_sd": math.sqrt(sum(z * z for z in zs) / len(zs)),
                    "coverage80": w.mean([r[f]["in80"] for r in sub]),
                }
        out[f] = {"win_prob_quintiles": bins, "abs_margin_bands": bands}
    return out


def window_status(now: datetime) -> str:
    """COLLECTING before the single registered analysis time, FINAL_ANALYSIS at/after it."""
    t = w.parse_ts(ANALYSIS_NOT_BEFORE)
    return "FINAL_ANALYSIS" if t is not None and now >= t else "COLLECTING"


def primary_verdict(
    rows: Sequence[dict[str, Any]],
    challenger: str,
    comparator: str,
    primary: str,
    guards: dict[str, tuple[str, float]],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Preregistered rule for one primary test of the family (see WAVE15.md / WAVE16.md).

    ``guards``: name -> (metric, tolerance) for non-inferiority vs the comparator (GUARD_Q bound).
    Before ANALYSIS_NOT_BEFORE the status is COLLECTING whatever the data show (no early stopping).
    """
    n, dates = len(rows), len({r["date"] for r in rows})
    out: dict[str, Any] = {"n_games": n, "n_dates": dates, "floor": {"games": MIN_GAMES, "dates": MIN_DATES},
                           "test": f"{challenger} - {comparator} [{primary}]", "alpha_one_sided": FAMILY_ALPHA / len(FAMILY)}  # fmt: skip
    if window_status(now) == "COLLECTING":
        out["status"] = "COLLECTING / INSUFFICIENT EVIDENCE"
        out["reason"] = (
            f"single analysis at {ANALYSIS_NOT_BEFORE}; {n} games on {dates} dates so far"
        )
        return out
    if n < MIN_GAMES or dates < MIN_DATES:
        out["status"] = "INSUFFICIENT EVIDENCE"
        out["reason"] = f"{n}/{MIN_GAMES} games, {dates}/{MIN_DATES} dates in the closed window"
        return out
    c = cluster_boot(rows, challenger, comparator, primary)
    g = {k: {**cluster_boot(rows, challenger, comparator, m), "tolerance": tol} for k, (m, tol) in guards.items()}  # fmt: skip
    out["primary"], out["guards"] = c, g
    guards_ok = all(v["hi_guard"] <= v["tolerance"] for v in g.values())
    guard_failed = any(v["lo_guard"] > v["tolerance"] for v in g.values())
    if c["hi_primary"] < 0 and guards_ok:
        out["status"] = "IMPROVED"
    elif c["diff"] >= 0 or c["lo_primary"] > 0 or guard_failed:
        out["status"] = "NOT IMPROVED"
    else:
        out["status"] = "INSUFFICIENT EVIDENCE"
    return out
