"""Wave 16 (RESEARCH_ONLY): centring the roster overlay ``pure-0.5.0_roster``.

Challenger B ``rcenter-0.5.0r-v1``: ``margin' = roster_margin + c`` where ``c`` is a walk-forward,
ridge-shrunk (toward 0) mean of ``actual - roster_margin`` over finished games. Total and margin SD
are unchanged; the probability moves along the frozen production logistic link. The overlay's
game-to-game adjustments (its apparent accuracy advantage) are kept; only its mean offset moves.

Protocol: ``research/hypotheses/WAVE16.md``; immutable spec ``research/wave16/spec.json``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cbb_edge.research import challenger_eval as ce
from cbb_edge.research import wave1 as w

BASE, ROSTER = "pure-0.5.0", "pure-0.5.0_roster"
VERSIONS = (BASE, ROSTER)  # eligibility requires both (identical games; base is a descriptive ref)
B = "rcenter-0.5.0r-v1"
B_OUTCOME_FREE = "rcenter-delta0-0.5.0r (descriptive)"  # mean-zero overlay delta, no outcomes
FORECASTERS = (BASE, ROSTER, B, B_OUTCOME_FREE)


@dataclass(frozen=True)
class Params:
    k: float = 30.0  # pseudo-games shrinking the offset toward 0
    min_games: int = 30


def fit_offset(hist: Sequence[dict[str, Any]], y: dict[int, float], roster: dict[int, dict[str, Any]], p: Params) -> float | None:  # fmt: skip
    """``c = sum(y - roster_margin) / (n + k)`` over finished games that have a roster record."""
    h = [g for g in hist if g["game_id"] in roster]
    if len(h) < p.min_games:
        return None
    return sum(y[g["game_id"]] - roster[g["game_id"]]["margin"] for g in h) / (len(h) + p.k)


def mean_delta(prior: Sequence[dict[str, Any]], roster: dict[int, dict[str, Any]]) -> float | None:
    """Outcome-free reference: mean (roster - base) margin over records frozen before the target."""
    d = [roster[g["game_id"]]["margin"] - g["margin"] for g in prior if g["game_id"] in roster]
    return sum(d) / len(d) if d else None


def adapt(r: dict[str, Any], shift: float) -> dict[str, float]:
    return {"margin": r["margin"] + shift, "margin_sd": r["margin_sd"], "p_home": ce.shift_prob(r["home_wp"], shift)}  # fmt: skip


def build_rows(
    frozen: dict[str, dict[int, dict[str, Any]]],
    finals: dict[int, dict[str, Any]],
    *,
    pushed: dict[int, Any] | None,
    params: Params | None = None,
    select: str = "prospective",
    exploratory_before: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    p = params or Params()
    base, roster = frozen[BASE], frozen[ROSTER]
    games = sorted(base.values(), key=lambda g: g["as_of"])
    y = {gid: float(f["home"] - f["away"]) for gid, f in finals.items()}
    hist = ce.training_history(games, finals)
    funnel: Counter[str] = Counter()
    rows = []
    for i, g in enumerate(games):
        gid = g["game_id"]
        train = [h for h in ce.before(hist, g["as_of"]) if h["game_id"] in roster]
        if select == "prospective":
            stage = ce.eligibility(gid, frozen, VERSIONS, finals, pushed or {}, len(train), p.min_games)  # fmt: skip
        else:
            ok = exploratory_before is not None and g["as_of"] < exploratory_before and gid in roster  # fmt: skip
            stage = ("eligible" if len(train) >= p.min_games else "challenger_undefined_too_few_finished_games") if ok and gid in finals else "not_in_exploratory_set"  # fmt: skip
        funnel[stage] += 1
        if stage != "eligible":
            continue
        c = fit_offset(train, y, roster, p)
        d0 = mean_delta([x for x in games[:i] if x["as_of"] < g["as_of"]], roster)
        assert c is not None
        r, ym = roster[gid], y[gid]
        preds = {
            BASE: {"margin": g["margin"], "margin_sd": g["margin_sd"], "p_home": g["home_wp"]},
            ROSTER: {"margin": r["margin"], "margin_sd": r["margin_sd"], "p_home": r["home_wp"]},
            B: adapt(r, c),
            B_OUTCOME_FREE: adapt(r, -(d0 or 0.0)),
        }
        row: dict[str, Any] = {"game_id": gid, "date": w.et_date(g["tip"]), "tip": g["tip"], "as_of": g["as_of"],
                               "y_margin": ym, "ref_margin": g["margin"], "n_train": len(train),
                               "offset_c": c, "mean_delta": d0}  # fmt: skip
        for name, pr in preds.items():
            row[name] = ce.score(pr, ym)
        rows.append(row)
    return rows, dict(funnel)


GUARDS_B = {"margin_mae": ("abs_margin_err", 0.05), "brier": ("brier", 0.002)}


def verdicts(rows: Sequence[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    return {ce.FAMILY[2]: ce.primary_verdict(rows, B, ROSTER, "logloss", GUARDS_B, now=now)}


def descriptive(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not rows:
        return out
    for ch, ref in ((B, ROSTER), (B, BASE), (ROSTER, BASE), (B_OUTCOME_FREE, ROSTER)):
        for m in ("abs_margin_err", "margin_err", "logloss", "brier"):
            c = ce.cluster_boot(rows, ch, ref, m, reps=2000)
            out[f"{ch} - {ref} [{m}]"] = {k: c[k] for k in ("n", "n_dates", "diff", "lo_guard", "hi_guard")}  # fmt: skip
    return out
