"""Exact YES-settlement semantics and (where defensible) model probabilities for Kalshi CBB contracts.

Nothing here infers a probability from a projected mean. A probability is produced only when

1. the series has a validated payoff parser (see ``SERIES``),
2. the contract's subject team/strike were parsed AND cross-checked against the structured
   Kalshi fields and the mapped game, and
3. the frozen as-of projection carries the distribution parameter the project's own
   preregistered function needs (``Phi((margin - line) / margin_sd)``).

Every other contract gets ``probability = None`` with an explicit ``gap`` reason.
Settlement (``settle``) is likewise only defined for the families whose payoff is a pure
function of final scores; halves, overtime and race markets return ``needs_*`` reasons.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from cbb_edge.data.ids import teams


@dataclass(frozen=True)
class SeriesSpec:
    market_type: str  # WINNER | MARGIN | TOTAL | TEAM_TOTAL | OVERTIME | RACE
    period: str  # FULL | 1H | 2H
    subject: str  # team | game
    overtime: str  # included | excluded | n/a
    gap: str | None  # why no model probability exists for this series (None = supported)


# Verified against rules_primary text in the 2026-11-02 archive.
#   FULL: "official final result" (overtime counts); 1H: only first-half points;
#   2H: "including overtime".
SERIES: dict[str, SeriesSpec] = {
    "KXNCAAMBGAME": SeriesSpec("WINNER", "FULL", "team", "included", None),
    "KXNCAAMBSPREAD": SeriesSpec("MARGIN", "FULL", "team", "included", None),
    "KXNCAAMBTOTAL": SeriesSpec("TOTAL", "FULL", "game", "included", None),
    "KXNCAAMBTEAMTOTAL": SeriesSpec(
        "TEAM_TOTAL", "FULL", "team", "included", "no_team_score_distribution_in_frozen_model"
    ),
    "KXNCAAMB1H": SeriesSpec("WINNER", "1H", "team", "n/a", "no_half_distribution_in_frozen_model"),
    "KXNCAAMB1HSPREAD": SeriesSpec(
        "MARGIN", "1H", "team", "n/a", "no_half_distribution_in_frozen_model"
    ),
    "KXNCAAMB1HTOTAL": SeriesSpec(
        "TOTAL", "1H", "game", "n/a", "no_half_distribution_in_frozen_model"
    ),
    "KXNCAAMB2H": SeriesSpec(
        "WINNER", "2H", "team", "included", "no_half_distribution_in_frozen_model"
    ),
    "KXNCAAMB2HSPREAD": SeriesSpec(
        "MARGIN", "2H", "team", "included", "no_half_distribution_in_frozen_model"
    ),
    "KXNCAAMB2HTOTAL": SeriesSpec(
        "TOTAL", "2H", "game", "included", "no_half_distribution_in_frozen_model"
    ),
    "KXNCAAMBOT": SeriesSpec("OVERTIME", "FULL", "game", "n/a", "no_overtime_model"),
    "KXNCAAMBRACE": SeriesSpec("RACE", "FULL", "team", "n/a", "no_race_to_points_model"),
}

_MARGIN_RE = re.compile(
    r"^(?P<team>.+?)\s+wins\s+(?:the\s+\w+\s+half\s+)?by over\s+(?P<k>[\d.]+)", re.I
)
_TEAM_TOTAL_RE = re.compile(r"^(?P<team>.+?)\s+over\s+(?P<k>[\d.]+)\s+points", re.I)
_TOTAL_RE = re.compile(r"over\s+(?P<k>[\d.]+)\s+points", re.I)
_RULES_MATCHUP_RE = re.compile(
    r"\bthe\s+(?P<a>(?:(?!\bthe\s).)+?)\s+vs\.?\s+(?P<b>.+?)\s+men'?s college basketball game"
)


def rules_matchup(market: dict[str, Any]) -> tuple[str, str] | None:
    """The two team names Kalshi's own settlement rules say are playing (order is NOT home/away)."""
    m = _RULES_MATCHUP_RE.search(str(market.get("rules_primary") or ""))
    return (m.group("a").strip(), m.group("b").strip()) if m else None


# Exact Kalshi display names that differ from every registered alias (checked by hand
# against the schedule; extend only with verified one-to-one identities).
KALSHI_NAME_OVERRIDES = {
    "University at Albany": "Albany",
    "Central Connecticut St.": "Central Connecticut",
    "Southern University": "Southern",  # Southern Jaguars (not Southern Miss/Illinois/Utah)
}


def resolve_team(name: str | None) -> str | None:
    """Kalshi display name -> canonical team id. Exact alias match, plus ONE deterministic rule:
    a trailing ``St.`` is ``State`` (``NC St.``, ``Chicago St.``). Misses stay misses."""
    if not name:
        return None
    name = KALSHI_NAME_OVERRIDES.get(name.strip(), name)
    tid = teams.resolve(name, "kalshi", log=False)
    if (
        tid is None
        and re.search(r"\bSt\.?$", name.strip())
        and not name.strip().lower().startswith("st")
    ):
        tid = teams.resolve(re.sub(r"\bSt\.?$", "State", name.strip()), "kalshi", log=False)
    return tid


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def parse_contract(
    series_ticker: str,
    market: dict[str, Any],
    home_team_id: str | None,
    away_team_id: str | None,
) -> dict[str, Any]:
    """Return exact YES semantics. ``status`` is 'parsed' only if every cross-check passes."""
    spec = SERIES.get(series_ticker)
    out: dict[str, Any] = {
        "market_type": spec.market_type if spec else None,
        "period": spec.period if spec else None,
        "overtime": spec.overtime if spec else None,
        "direction": None,
        "strike": None,
        "subject_team_id": None,
        "subject_side": None,
        "yes_condition": None,
        "status": "unsupported_series",
        "model_gap": spec.gap if spec else "no_validated_payoff_parser",
    }
    if spec is None:
        return out

    strike_type = market.get("strike_type")
    floor = market.get("floor_strike")
    title = str(market.get("title") or "")
    sub = str(market.get("yes_sub_title") or "")
    subject_name: str | None = None
    strike: float | None = None

    if spec.market_type in ("WINNER", "RACE"):
        subject_name = sub or None
    elif spec.market_type == "MARGIN":
        m = _MARGIN_RE.match(sub) or _MARGIN_RE.match(title)
        if m:
            subject_name, strike = m.group("team"), float(m.group("k"))
    elif spec.market_type == "TEAM_TOTAL":
        m = _TEAM_TOTAL_RE.match(sub) or _TEAM_TOTAL_RE.match(title)
        if m:
            subject_name, strike = m.group("team"), float(m.group("k"))
    elif spec.market_type == "TOTAL":
        m = _TOTAL_RE.search(sub) or _TOTAL_RE.search(title)
        if m:
            strike = float(m.group("k"))
    elif spec.market_type == "OVERTIME":
        out["status"] = "parsed"
        out["yes_condition"] = "at_least_one_overtime_period_played"
        return out

    if spec.market_type in ("MARGIN", "TOTAL", "TEAM_TOTAL"):
        # Text strike must agree with the structured strike and be a strict 'greater' payoff.
        if strike is None or floor is None or abs(float(floor) - strike) > 1e-9:
            out["status"] = "strike_mismatch"
            return out
        if strike_type != "greater":
            out["status"] = "unsupported_strike_type"
            return out
        out["direction"], out["strike"] = "greater", strike

    if spec.market_type == "WINNER" and (subject_name or "").strip().lower() == "tie":
        # three-way half markets (home / away / Tie): YES only if the half ends level
        out["subject_side"] = "tie"
        out["status"] = "parsed"
        out["yes_condition"] = f"tied_{spec.period}"
        return out

    if spec.subject == "team":
        tid = resolve_team(subject_name)
        if tid is None:
            out["status"] = "subject_unresolved"
            return out
        if tid == home_team_id:
            out["subject_side"] = "home"
        elif tid == away_team_id:
            out["subject_side"] = "away"
        else:
            out["status"] = "subject_not_in_mapped_game"
            return out
        out["subject_team_id"] = tid

    out["status"] = "parsed"
    t, s = spec.market_type, out["strike"]
    who = out["subject_side"]
    out["yes_condition"] = {
        "WINNER": f"{who}_wins_{spec.period}",
        "MARGIN": f"{who}_margin_{spec.period}_gt_{s}",
        "TOTAL": f"total_{spec.period}_gt_{s}",
        "TEAM_TOTAL": f"{who}_points_{spec.period}_gt_{s}",
        "RACE": f"{who}_first_to_target_points",
    }[t]
    return out


def probability(parsed: dict[str, Any], proj: dict[str, Any]) -> tuple[float | None, str]:
    """(probability, method-or-gap). Uses only the frozen projection's own preregistered functions."""
    if parsed.get("status") != "parsed":
        return None, f"parse:{parsed.get('status')}"
    if parsed.get("model_gap"):
        return None, str(parsed["model_gap"])
    side = parsed.get("subject_side")
    t = parsed["market_type"]
    try:
        if t == "WINNER":
            p = proj.get("home_win_prob")
            if p is None:
                return None, "projection_missing_home_win_prob"
            return (float(p) if side == "home" else 1.0 - float(p)), "frozen_home_win_prob"
        strike = float(parsed["strike"])
        if t == "MARGIN":
            m, sd = proj.get("margin"), proj.get("margin_sd")
            if m is None or not sd or float(sd) <= 0:
                return None, "projection_missing_margin_sd"
            mean = float(m) if side == "home" else -float(m)
            return _norm_cdf((mean - strike) / float(sd)), "Phi((margin-line)/margin_sd)"
        if t == "TOTAL":
            m, sd = proj.get("total"), proj.get("total_sd")
            if m is None or not sd or float(sd) <= 0:
                return None, "projection_missing_total_sd"
            return _norm_cdf((float(m) - strike) / float(sd)), "Phi((total-line)/total_sd)"
    except (TypeError, ValueError):
        return None, "projection_not_numeric"
    return None, "no_probability_method"


def settle(
    parsed: dict[str, Any], home_points: int | None, away_points: int | None
) -> tuple[str | None, str]:
    """Expected YES/NO from final full-game scores only; (None, reason) when not determinable.

    Overtime is included in final scores, which matches the FULL-period series. Half and
    overtime markets need period scores this repo does not archive, so they return needs_*.
    """
    if parsed.get("status") != "parsed":
        return None, f"parse:{parsed.get('status')}"
    if parsed["period"] != "FULL":
        return None, "needs_half_scores"
    if parsed["market_type"] in ("OVERTIME", "RACE"):
        return None, "needs_play_by_play"
    if home_points is None or away_points is None:
        return None, "no_final_score"
    side = parsed.get("subject_side")
    mine, other = (home_points, away_points) if side == "home" else (away_points, home_points)
    t = parsed["market_type"]
    if t == "WINNER":
        return ("yes" if mine > other else "no" if mine < other else None), "final_score"
    if t == "MARGIN":
        return ("yes" if mine - other > parsed["strike"] else "no"), "final_score"
    if t == "TOTAL":
        return ("yes" if home_points + away_points > parsed["strike"] else "no"), "final_score"
    if t == "TEAM_TOTAL":
        return ("yes" if mine > parsed["strike"] else "no"), "final_score"
    return None, "no_settlement_method"
