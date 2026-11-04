"""Minutes-first CBB player stat MEANS from pregame silver box scores and expected rotations.

Research only. This deliberately does NOT output PrizePicks MORE/LESS probabilities, claim
opponent-adjusted rates, or authorize a wager. Historical results must be timestamped,
a rotation must be frozen before game tip, and all source rows must predate as_of.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

VERSION = "cbb-player-means-0.1.0-shadow"
STATS = ("pts", "orb", "drb", "ast", "fg3m")
MIN_HISTORY_MINUTES = 120.0
RECENT_GAMES = 20


def _stamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return ts.tz_convert("UTC")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


def _minutes(value: Any) -> float | None:
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return None
        minute, second = map(int, parts)
        if second >= 60:
            return None
        return minute + second / 60
    return _number(value)


def player_stat_means(
    history: pd.DataFrame,
    rotation: pd.DataFrame,
    *,
    as_of: Any,
    tip: Any,
    rotation_as_of: Any,
    min_history_minutes: float = MIN_HISTORY_MINUTES,
) -> list[dict[str, Any]]:
    """Return as-of projected means for a *complete*, independently frozen rotation.

    `history` is the existing silver player_games table, with `available_at`
    (actual outcome-publication cutoff), `player_id`, `game_id`, `min`,
    and box-stat columns; `rotation` is the current game roster overlay with
    `player_id`, `team_id`, and `minutes` (expected minutes already inclusive
    of participation uncertainty; do NOT multiply by p_rotation again).
    """
    at, game_tip, rot_at = _stamp(as_of), _stamp(tip), _stamp(rotation_as_of)
    if not (rot_at <= at < game_tip):
        raise ValueError("rotation must be known as-of before verified tip")
    if not math.isfinite(min_history_minutes) or min_history_minutes <= 0:
        raise ValueError("min_history_minutes must be positive")
    if not {"player_id", "game_id", "available_at", "min"}.issubset(history.columns):
        raise ValueError("historical player-game source lacks identity/time/minutes")
    if not {"player_id", "team_id", "minutes"}.issubset(rotation.columns):
        raise ValueError("rotation lacks identity, team, or expected minutes")
    if rotation[["player_id", "team_id"]].isna().any().any():
        raise ValueError("unidentified rotation member")
    if rotation["player_id"].duplicated().any():
        raise ValueError("rotation contains duplicate canonical player IDs")
    if rotation.empty:
        return []
    rot = rotation.copy()
    rot["minutes"] = rot["minutes"].map(_number)
    if rot["minutes"].isna().any() or (rot["minutes"] > 40).any():
        raise ValueError("expected player minutes outside regulation bounds")
    for _team, players in rot.groupby("team_id"):
        if len(players) < 5 or abs(players["minutes"].sum() - 200) > 0.5:
            raise ValueError("rotation must reconcile to 200 regulation team minutes")

    past = history.copy()
    past["available_at"] = pd.to_datetime(past["available_at"], utc=True, errors="coerce")
    if past["available_at"].isna().any():
        raise ValueError("historical results have missing or invalid availability timestamps")
    past = past[past["available_at"] < at].copy()
    if past.duplicated(["player_id", "game_id"]).any():
        raise ValueError("duplicate pregame player-game box rows")
    past["min_numeric"] = past["min"].map(_minutes)
    # A DNP row is not a played-game denominator and should not poison valid
    # historical rates. Missing or malformed minutes never become fake zeroes.
    past = past[past["min_numeric"].notna() & (past["min_numeric"] > 0)].copy()
    for stat in STATS:
        if stat in past:
            past[stat] = past[stat].map(_number)
    groups = {
        key: g.sort_values("available_at").tail(RECENT_GAMES)
        for key, g in past.groupby("player_id")
    }

    out: list[dict[str, Any]] = []
    for rr in rot.to_dict("records"):
        pid = rr["player_id"]
        x = groups.get(pid)
        hm = 0.0 if x is None else float(x["min_numeric"].dropna().sum())
        eligible = x is not None and hm >= min_history_minutes
        means: dict[str, float | None] = {}
        for stat in STATS:
            if not eligible or stat not in x or x[["min_numeric", stat]].isna().any().any():
                means[stat] = None
            else:
                rate = float(x[stat].sum()) / hm
                means[stat] = round(rate * float(rr["minutes"]), 3)
        reb = (
            round(means["orb"] + means["drb"], 3)
            if means["orb"] is not None and means["drb"] is not None
            else None
        )
        means["reb"] = reb
        means["pra"] = (
            round(means["pts"] + reb + means["ast"], 3)
            if means["pts"] is not None and reb is not None and means["ast"] is not None
            else None
        )
        out.append(
            {
                "player_id": str(pid),
                "team_id": str(rr["team_id"]),
                "model_version": VERSION,
                "as_of": at.isoformat(),
                "rotation_as_of": rot_at.isoformat(),
                "projected_minutes": round(float(rr["minutes"]), 2),
                "p_rotation": _number(rr.get("p_rotation")),
                "history_minutes": round(hm, 1),
                "history_games": 0 if x is None else len(x),
                "history_latest_available_at": (
                    None if x is None or x.empty else x["available_at"].max().isoformat()
                ),
                "projections": means,
                "status": "EXPLORATORY_MEANS_ONLY" if eligible else "INSUFFICIENT_HISTORY",
                "missing_reason": None if eligible else "insufficient_pregame_box_minutes",
                "line_probability": None,
                "authorized_bet": False,
                "notes": "raw historical rates; minutes-first, not opponent-adjusted or calibrated",
            }
        )
    return out
