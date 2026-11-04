"""Non-authoritative progress and eligibility diagnostics for frozen CBB candidate rules.

The preregistered candidate config, hypothesis, sample requirement and promotion
logic remain unchanged. Early checkpoints are descriptive, NOT statistical
evidence of edge or new gates. Each stage counts independent GAME clusters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

CHECKPOINTS = (25, 50, 100)


def utc_time(value: Any) -> datetime | None:
    """Parse ISO timestamps as aware instants; unknown/naive timestamps fail closed."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None and stamp.utcoffset() is not None else None


def prospective_bet(bet: dict[str, Any], registered_at: str) -> bool:
    """A registered signal exists only if a quoted entry and tip follow registration."""
    reg = utc_time(registered_at)
    price_at = utc_time(bet.get("t"))
    tip_at = utc_time(bet.get("tip"))
    return bool(reg and price_at and tip_at and reg <= price_at < tip_at and tip_at > reg)


def progress(sample_games: int, min_games: int, status: str) -> dict[str, Any]:
    """Nonbinding checkpoints at 25/50/100, alongside the untouched formal min."""
    if min_games <= 0 or sample_games < 0:
        raise ValueError("sample sizes must be nonnegative and min_games positive")
    milestones = sorted({*filter(lambda n: n < min_games, CHECKPOINTS), min_games})
    if not sample_games:
        stage = "AWAITING_PROSPECTIVE_EVIDENCE"
    elif sample_games >= min_games:
        stage = "FORMAL_SAMPLE_MINIMUM_REACHED"
    elif sample_games >= 100:
        stage = "PRELIMINARY"
    elif sample_games >= 50:
        stage = "EARLY"
    elif sample_games >= 25:
        stage = "INITIAL"
    else:
        stage = "TOO_EARLY"
    return {
        "independent_games": sample_games,
        "formal_min_games": min_games,
        "remaining_games_to_formal_min": max(0, min_games - sample_games),
        "fraction_of_formal_min": round(min(1.0, sample_games / min_games), 4),
        "stage": stage,
        "milestones": [{"games": n, "reached": sample_games >= n} for n in milestones],
        "next_milestone_games": next((n for n in milestones if sample_games < n), None),
        "not_authority": True,
        "formal_candidate_status": status,
        "note": (
            "Preliminary checkpoints describe sample accumulation, NOT validated returns. "
            "Formal status additionally requires registered out-of-sample evidence, "
            "the candidate's unchanged inference criteria, and verified fees."
        ),
    }


def eligibility_funnel(
    cfg: dict[str, Any],
    registered_at: str,
    evaluations: list[dict[str, Any]],
    tips: dict[str, str],
    prospective_bets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Why a preregistered strategy has few observations; never count contracts as games.

    Denominator = observed contract evaluation rows in this series+entry (not all
    scheduled CBB games). Stages are nested, with independent game counts.
    """
    series = set(cfg["series"])
    entry = cfg["entry"]
    model_version = cfg["rule"].get("model_version")
    reg = utc_time(registered_at)
    stage_names = (
        "observed_series_entry_games",
        "tipped_after_registration",
        "observed_valid_postregistration_pretip_quote",
        "verified_pretip_tip",
        "independently_settled",
        "model_supported",
        "fillable_quote",
    )
    stages: dict[str, set[str]] = {k: set() for k in stage_names}
    for r in evaluations:
        if r.get("series") not in series or r.get("entry") != entry:
            continue
        key = r.get("cluster")
        if not isinstance(key, str) or not key:
            continue
        stages[stage_names[0]].add(key)
        tip = utc_time(tips.get(r.get("ticker", "")))
        if reg is None or tip is None or tip <= reg:
            continue
        stages[stage_names[1]].add(key)
        quote = utc_time(r.get("t"))
        if quote is None or not (reg <= quote < tip):
            continue
        stages[stage_names[2]].add(key)
        if not r.get("tip_verified"):
            continue
        stages[stage_names[3]].add(key)
        if r.get("y") not in (0, 1):
            continue
        stages[stage_names[4]].add(key)
        if model_version:
            model = (r.get("model") or {}).get(model_version) or {}
            if not any(model.get("ev_" + side) is not None for side in ("yes", "no")):
                continue
        stages[stage_names[5]].add(key)
        if not any(
            (r.get(side) or {}).get("fill") == "FILLED"
            and (r.get(side) or {}).get("net_pnl") is not None
            for side in ("yes", "no")
        ):
            continue
        stages[stage_names[6]].add(key)

    selected = {b["cluster"] for b in prospective_bets}
    # A fully matched baseline can be in model_supported/fillable, but never all
    # filled single-contract games are guaranteed to satisfy a two-sided rule.
    if not selected <= stages["fillable_quote"]:
        raise ValueError("selected prospective games have no valid eligible fill")
    counts = {k: len(v) for k, v in stages.items()}
    counts["selected_rule_games"] = len(selected)
    keys = [*stage_names, "selected_rule_games"]
    dropoffs = {
        f"{previous}_to_{later}": counts[previous] - counts[later]
        for previous, later in zip(keys, keys[1:], strict=False)
    }
    return {
        "unit": "independent_game",
        "denominator": "observed_series_entry_games_not_all_scheduled_games",
        "counts": counts,
        "stage_dropoffs": dropoffs,
        "reason_if_zero": (
            "no_eligible_postregistration_pretip_quote_or_verified_settlement"
            if not selected
            else None
        ),
        "note": (
            "The rule can reject otherwise fillable games. Counts are NOT "
            "independent contracts, and missing quote/model/outcome evidence is not fabricated."
        ),
    }
