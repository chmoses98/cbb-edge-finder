"""Wave 15 (RESEARCH_ONLY): margin calibration challengers on frozen ``pure-0.5.0`` records.

Two SEPARATE challengers, each tested on its own primary metric (protocol:
``research/hypotheses/WAVE15.md``; immutable spec ``research/wave15/spec.json``):

* A1 ``mstretch-0.5.0-v1`` - margin magnitude. ``margin' = s * margin`` with ``s`` a walk-forward
  ridge slope of actual on projected margin, shrunk toward 1. Total, margin SD unchanged; the
  probability moves along the frozen production logistic link.
* A2 ``hsd-0.5.0-v1`` - margin-dependent predictive uncertainty. ``margin_sd' = margin_sd *
  sqrt(max(floor, c0 + c1 * |margin| / m_ref))`` with (c0, c1) a walk-forward ridge fit of the
  squared standardized residual, shrunk toward (1, 0). Margin unchanged; ``p = Phi(margin / sd')``.

Scaling the margin and scaling its uncertainty are NOT assumed equivalent: they change different
quantities, are fit separately and are judged on different primary metrics.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cbb_edge.research import challenger_eval as ce
from cbb_edge.research import wave1 as w

BASE = "pure-0.5.0"
VERSIONS = (BASE,)
A1, A2 = "mstretch-0.5.0-v1", "hsd-0.5.0-v1"
A2_LINK_MATCHED = "pure-0.5.0:phi(margin/margin_sd)"  # isolates A2's SD change from its link
FORECASTERS = (BASE, A1, A2, A2_LINK_MATCHED)


@dataclass(frozen=True)
class Params:
    k: float = 30.0  # pseudo-games of shrinkage (both challengers)
    m_ref: float = 15.0  # reference |margin| (points)
    min_games: int = 30  # finished games needed before a challenger is defined
    var_floor: float = 0.25  # A2: variance multiplier floor (SD multiplier >= 0.5)


def fit_stretch(hist: Sequence[dict[str, Any]], y: dict[int, float], p: Params) -> float | None:
    """A1: ``s = (sum m*y + k*m_ref^2) / (sum m^2 + k*m_ref^2)`` (ridge toward s = 1)."""
    if len(hist) < p.min_games:
        return None
    sxy = sum(g["margin"] * y[g["game_id"]] for g in hist)
    sxx = sum(g["margin"] ** 2 for g in hist)
    prior = p.k * p.m_ref**2
    return (sxy + prior) / (sxx + prior)


def fit_hsd(
    hist: Sequence[dict[str, Any]], y: dict[int, float], p: Params
) -> tuple[float, float] | None:
    """A2: ridge regression of ``z^2`` on ``[1, |m|/m_ref]`` with ``k`` pseudo-observations per
    coefficient pulling (c0, c1) toward (1, 0). Closed-form 2x2 solve."""
    if len(hist) < p.min_games:
        return None
    s11 = s12 = s22 = t1 = t2 = 0.0
    for g in hist:
        a = abs(g["margin"]) / p.m_ref
        z2 = ((y[g["game_id"]] - g["margin"]) / g["margin_sd"]) ** 2
        s11, s12, s22, t1, t2 = s11 + 1, s12 + a, s22 + a * a, t1 + z2, t2 + a * z2
    s11, s22, t1 = s11 + p.k, s22 + p.k, t1 + p.k * 1.0
    det = s11 * s22 - s12 * s12
    return ((s22 * t1 - s12 * t2) / det, (s11 * t2 - s12 * t1) / det)


def adapt_stretch(g: dict[str, Any], s: float) -> dict[str, float]:
    m = s * g["margin"]
    return {"margin": m, "margin_sd": g["margin_sd"], "p_home": ce.shift_prob(g["home_wp"], m - g["margin"])}  # fmt: skip


def adapt_hsd(g: dict[str, Any], c: tuple[float, float], p: Params) -> dict[str, float]:
    mult = max(p.var_floor, c[0] + c[1] * abs(g["margin"]) / p.m_ref)
    sd = g["margin_sd"] * math.sqrt(mult)
    return {"margin": g["margin"], "margin_sd": sd, "p_home": ce.phi_cdf(g["margin"] / sd)}


def build_rows(
    frozen: dict[str, dict[int, dict[str, Any]]],
    finals: dict[int, dict[str, Any]],
    *,
    pushed: dict[int, Any] | None,
    params: Params | None = None,
    select: str = "prospective",
    exploratory_before: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Identical-game rows for every forecaster plus an eligibility funnel.

    ``select="prospective"``: the registered eligibility rule (``ce.eligibility``).
    ``select="exploratory"``: historical development only - games whose record ``as_of`` precedes
    ``exploratory_before`` (never mixed with prospective rows; reported separately).
    """
    p = params or Params()
    base = frozen[BASE]
    games = sorted(base.values(), key=lambda g: g["as_of"])
    y = {gid: float(f["home"] - f["away"]) for gid, f in finals.items()}
    hist = ce.training_history(games, finals)
    funnel: Counter[str] = Counter()
    rows = []
    for g in games:
        gid = g["game_id"]
        train = ce.before(hist, g["as_of"])
        if select == "prospective":
            stage = ce.eligibility(gid, frozen, VERSIONS, finals, pushed or {}, len(train), p.min_games)  # fmt: skip
        else:
            ok = exploratory_before is not None and g["as_of"] < exploratory_before
            stage = ("eligible" if len(train) >= p.min_games else "challenger_undefined_too_few_finished_games") if ok and gid in finals else "not_in_exploratory_set"  # fmt: skip
        funnel[stage] += 1
        if stage != "eligible":
            continue
        s, c = fit_stretch(train, y, p), fit_hsd(train, y, p)
        assert s is not None and c is not None
        ym = y[gid]
        preds = {
            BASE: {"margin": g["margin"], "margin_sd": g["margin_sd"], "p_home": g["home_wp"]},
            A1: adapt_stretch(g, s),
            A2: adapt_hsd(g, c, p),
            A2_LINK_MATCHED: {"margin": g["margin"], "margin_sd": g["margin_sd"],
                              "p_home": ce.phi_cdf(g["margin"] / g["margin_sd"])},
        }  # fmt: skip
        row: dict[str, Any] = {"game_id": gid, "date": w.et_date(g["tip"]), "tip": g["tip"],
                               "as_of": g["as_of"], "y_margin": ym, "ref_margin": g["margin"],
                               "n_train": len(train), "stretch_s": s, "hsd_c": list(c)}  # fmt: skip
        for name, pr in preds.items():
            row[name] = ce.score(pr, ym)
        rows.append(row)
    return rows, dict(funnel)


GUARDS_A1 = {"logloss": ("logloss", 0.005), "brier": ("brier", 0.002)}
GUARDS_A2 = {"logloss": ("logloss", 0.005), "brier": ("brier", 0.002)}


def verdicts(rows: Sequence[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    return {
        ce.FAMILY[0]: ce.primary_verdict(rows, A1, BASE, "abs_margin_err", GUARDS_A1, now=now),
        ce.FAMILY[1]: ce.primary_verdict(rows, A2, BASE, "margin_nll", GUARDS_A2, now=now),
    }


def descriptive(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Matched contrasts reported for every metric (NOT a verdict)."""
    out: dict[str, Any] = {}
    if not rows:
        return out
    for ch, ref in ((A1, BASE), (A2, BASE), (A2, A2_LINK_MATCHED)):
        for m in ("abs_margin_err", "margin_err", "logloss", "brier", "margin_nll"):
            c = ce.cluster_boot(rows, ch, ref, m, reps=2000)
            out[f"{ch} - {ref} [{m}]"] = {k: c[k] for k in ("n", "n_dates", "diff", "lo_guard", "hi_guard")}  # fmt: skip
    return out
