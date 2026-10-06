"""Synthetic ESPN scoreboard payloads (the shape SDV's schedule flattens), for tests."""

from __future__ import annotations

from typing import Any


def event(gid: int, start: str, home: int, away: int, *, tv: bool = True, state: str = "pre",
          name: str = "STATUS_SCHEDULED", detail: str = "7:00 PM EST", neutral: bool = False,
          conf: bool = False, season: int = 2027, stype: int = 2, hs: float = 0, as_: float = 0,
          completed: bool = False, tournament: int | None = None) -> dict[str, Any]:  # fmt: skip
    comp = {
        "id": str(gid), "date": start, "startDate": start, "timeValid": tv,
        "neutralSite": neutral, "conferenceCompetition": conf,
        "venue": {"id": "100", "fullName": "Arena", "address": {"city": "Town", "state": "ST"}},
        "notes": [],
        "status": {"period": 0 if state == "pre" else 2,
                   "type": {"state": state, "name": name, "completed": completed,
                            "shortDetail": detail}},
        "competitors": [
            {"id": str(home), "homeAway": "home", "score": str(int(hs)),
             "team": {"id": str(home), "location": f"Team {home}", "conferenceId": "1"}},
            {"id": str(away), "homeAway": "away", "score": str(int(as_)),
             "team": {"id": str(away), "location": f"Team {away}", "conferenceId": "2"}},
        ],
    }  # fmt: skip
    if tournament is not None:
        comp["tournamentId"] = tournament
    return {"id": str(gid), "date": start, "season": {"year": season, "type": stype},
            "competitions": [comp]}  # fmt: skip


def payload(*events: dict[str, Any]) -> dict[str, Any]:
    return {"events": list(events)}
