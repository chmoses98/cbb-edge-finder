"""Parsing ESPN public roster / injury / summary JSON into availability rows.

Sources (all FREE_RATE_LIMITED ``espn_public``, probed 2026-10-05 from GitHub runners):

* team roster   ``site/v2/.../teams/{id}/roster``: per athlete ``status`` (active ...),
  ``injuries[]`` (status, date, short/long comment when present), position, height,
  weight, class (``experience``), jersey;
* league injuries ``site/v2/.../injuries``: league-wide injury list (empty offseason);
* game summary  ``site/v2/.../summary?event=``: an ``injuries`` section when ESPN
  publishes one pregame; after the game ``boxscore.players[].statistics[].athletes[]``
  carries ``starter`` / ``didNotPlay`` (outcome labels, never pregame inputs).

Status vocabulary is source-native text; :func:`canonical_status` maps it to a fixed
canonical set and :data:`P_PLAY` gives the PREREGISTERED (research/hypotheses/WAVE4.md)
probability of playing. ESPN's college injury coverage is unknown until the season
starts; every capture records the raw text so coverage can be measured honestly.
"""

from __future__ import annotations

import re
from typing import Any

# fixed before the 2026-27 season (WAVE4.md, P-AVAIL); never tuned on results
P_PLAY: dict[str, float] = {
    "out": 0.0,
    "suspended": 0.0,
    "inactive": 0.0,
    "doubtful": 0.25,
    "questionable": 0.5,
    "probable": 0.85,
    "day_to_day": 0.85,
    "available": 1.0,
    "unknown": 1.0,
}

_PATTERNS = (
    ("suspended", r"suspend"),
    ("out", r"\bout\b|season|surgery|redshirt|not with team|left (the )?team|transfer"),
    ("inactive", r"inactive|injured reserve|\bir\b"),
    ("doubtful", r"doubtful"),
    ("questionable", r"questionable|game[- ]time"),
    ("day_to_day", r"day[- ]to[- ]day|\bdtd\b"),
    ("probable", r"probable"),
    ("available", r"^active$|available"),
)


def canonical_status(text: str | None) -> str:
    """Map source-native status text to the canonical vocabulary (first match wins)."""
    t = (text or "").strip().lower()
    if not t:
        return "unknown"
    for name, pat in _PATTERNS:
        if re.search(pat, t):
            return name
    return "unknown"


def _get(d: Any, *path: str, default: Any = None) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return d if d is not None else default


def _injury_fields(inj: list[dict[str, Any]]) -> dict[str, Any]:
    """Most recent injury entry -> status text, date, comment, type."""
    if not inj:
        return {
            "injury_status": None,
            "injury_date": None,
            "injury_comment": None,
            "injury_type": None,
        }
    e = sorted(inj, key=lambda x: str(x.get("date", "")))[-1]
    typ = e.get("type")
    return {
        "injury_status": e.get("status") or _get(e, "type", "description"),
        "injury_date": e.get("date"),
        "injury_comment": e.get("shortComment")
        or e.get("longComment")
        or _get(e, "details", "detail"),
        "injury_type": (typ.get("name") or typ.get("description"))
        if isinstance(typ, dict)
        else typ,
    }


def parse_roster(js: dict[str, Any], espn_team_id: int) -> list[dict[str, Any]]:
    """One row per athlete on a team roster (site roster or team?enable=roster)."""
    athletes = js.get("athletes")
    if athletes is None:
        athletes = _get(js, "team", "athletes", default=[])
    # some ESPN rosters group athletes by position: [{position, items: [...]}]
    flat: list[dict[str, Any]] = []
    for a in athletes or []:
        if isinstance(a, dict) and "items" in a and "id" not in a:
            flat.extend(a["items"])
        elif isinstance(a, dict):
            flat.append(a)
    rows = []
    for a in flat:
        inj = _injury_fields(a.get("injuries") or [])
        status_text = _get(a, "status", "name") or _get(a, "status", "type")
        native = inj["injury_status"] or status_text
        can = (
            canonical_status(inj["injury_status"])
            if inj["injury_status"]
            else (
                "available"
                if str(_get(a, "status", "type", default="")).lower() == "active"
                else canonical_status(status_text)
            )
        )
        rows.append(
            {
                "espn_team_id": int(espn_team_id),
                "espn_athlete_id": str(a.get("id")),
                "player_id": f"P{a.get('id')}",
                "name": a.get("displayName") or a.get("fullName"),
                "jersey": a.get("jersey"),
                "position": _get(a, "position", "abbreviation"),
                "height_in": a.get("height"),
                "weight_lb": a.get("weight"),
                "class": _get(a, "experience", "abbreviation")
                or _get(a, "experience", "displayValue"),
                "class_years": _get(a, "experience", "years"),
                "birthplace": _get(a, "birthPlace", "displayText")
                or ", ".join(
                    x for x in (_get(a, "birthPlace", "city"), _get(a, "birthPlace", "state")) if x
                )
                or None,
                "roster_status": status_text,
                "native_status": native,
                **inj,
                "status": can,
                "p_play": P_PLAY[can],
                "source": "espn_team_roster",
                "confidence": "reported" if inj["injury_status"] else "no_report",
            }
        )
    return rows


def parse_injury_list(js: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """League ``/injuries`` or summary ``injuries`` section -> rows (team, athlete, status)."""
    groups = js.get("injuries") or []
    rows = []
    for g in groups:
        team_id = _get(g, "team", "id") or g.get("id")
        for e in g.get("injuries") or []:
            ath = e.get("athlete") or {}
            native = e.get("status") or _get(e, "type", "description")
            can = canonical_status(native)
            rows.append(
                {
                    "espn_team_id": int(team_id) if team_id is not None else None,
                    "espn_athlete_id": str(ath.get("id")) if ath.get("id") else None,
                    "player_id": f"P{ath.get('id')}" if ath.get("id") else None,
                    "name": ath.get("displayName"),
                    "native_status": native,
                    "injury_date": e.get("date"),
                    "injury_comment": e.get("shortComment") or e.get("longComment"),
                    "injury_type": _get(e, "type", "name"),
                    "status": can,
                    "p_play": P_PLAY[can],
                    "source": source,
                    "confidence": "reported",
                }
            )
    return rows


def parse_box_participation(js: dict[str, Any]) -> list[dict[str, Any]]:
    """Post-game outcome labels from a summary: starter / didNotPlay per athlete."""
    rows = []
    for t in _get(js, "boxscore", "players", default=[]) or []:
        team_id = _get(t, "team", "id")
        for block in t.get("statistics") or []:
            for a in block.get("athletes") or []:
                ath = a.get("athlete") or {}
                rows.append(
                    {
                        "espn_team_id": int(team_id) if team_id else None,
                        "espn_athlete_id": str(ath.get("id")),
                        "starter": bool(a.get("starter")),
                        "did_not_play": bool(a.get("didNotPlay")),
                        "reason": a.get("reason"),
                    }
                )
    return rows
