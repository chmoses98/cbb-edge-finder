"""Canonical home/away orientation identity across schedule, projection and scoring (fail closed).

A neutral-site event game can list the two teams in the opposite order in the schedule archive and in
a frozen projection. Scoring such a game by position silently flips the margin sign. Identity here is
by CANONICAL TEAM ID (never by display name or list position):

* ``SAME``       - schedule home/away are the projection's home/away;
* ``SWAPPED``    - same two teams, reversed, on a neutral site: scores are mapped to the projected teams;
* ``UNVERIFIED`` - anything else (unresolved id, different team set, missing ids, a reversal at a
                   non-neutral site). Such a game is never scored and never "fixed".

Nothing here edits an archived projection or schedule row; it only decides how a result may be mapped
onto a projection that already exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Orientation(StrEnum):
    SAME = "SAME"
    SWAPPED = "SWAPPED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class OrientationCheck:
    status: Orientation
    reason: str | None
    proj_home: str | None
    proj_away: str | None
    sched_home: str | None  # canonical ids resolved from the schedule's ESPN ids
    sched_away: str | None

    @property
    def scorable(self) -> bool:
        return self.status is not Orientation.UNVERIFIED


def _resolver(season: int) -> Callable[[Any], str | None]:
    from cbb_edge.data.ids.teams import canonical_from_espn_in

    return lambda espn_id: canonical_from_espn_in(espn_id, season)


def _bad(reason: str, ph: Any, pa: Any, sh: Any = None, sa: Any = None) -> OrientationCheck:
    return OrientationCheck(Orientation.UNVERIFIED, reason, ph, pa, sh, sa)


def check_orientation(
    proj_home: str | None,
    proj_away: str | None,
    sched_home_espn: Any,
    sched_away_espn: Any,
    *,
    neutral: bool,
    season: int,
    resolve: Callable[[Any], str | None] | None = None,
) -> OrientationCheck:
    """Compare a projection's (home, away) canonical ids with a schedule row's ESPN team ids."""
    if not proj_home or not proj_away or proj_home == proj_away:
        return _bad("projection_team_ids_missing_or_equal", proj_home, proj_away)
    if sched_home_espn is None or sched_away_espn is None:
        return _bad("schedule_team_ids_missing", proj_home, proj_away)
    res = resolve or _resolver(season)
    try:
        sh, sa = res(sched_home_espn), res(sched_away_espn)
    except (TypeError, ValueError):
        return _bad("schedule_team_id_unparseable", proj_home, proj_away)
    if sh is None or sa is None:
        return _bad("schedule_team_id_unresolved", proj_home, proj_away, sh, sa)
    if sh == sa:
        return _bad("schedule_teams_identical", proj_home, proj_away, sh, sa)
    if (sh, sa) == (proj_home, proj_away):
        return OrientationCheck(Orientation.SAME, None, proj_home, proj_away, sh, sa)
    if (sh, sa) == (proj_away, proj_home):
        if not neutral:
            return _bad("reversed_at_non_neutral_site", proj_home, proj_away, sh, sa)
        return OrientationCheck(Orientation.SWAPPED, None, proj_home, proj_away, sh, sa)
    return _bad("team_set_mismatch", proj_home, proj_away, sh, sa)


def check_record(
    record: dict[str, Any], schedule_row: dict[str, Any], *, season: int, resolve: Any = None
) -> OrientationCheck:
    """``record``: a frozen projection record; ``schedule_row``: a schedule-archive row
    (``home_id`` / ``away_id`` ESPN ids, ``neutral_site``)."""
    return check_orientation(
        (record.get("home") or {}).get("team_id"),
        (record.get("away") or {}).get("team_id"),
        schedule_row.get("home_id"),
        schedule_row.get("away_id"),
        neutral=bool(schedule_row.get("neutral_site")),
        season=season,
        resolve=resolve,
    )


def to_projection_frame(
    check: OrientationCheck, sched_home_score: float, sched_away_score: float
) -> tuple[float, float]:
    """(score of the PROJECTED home team, score of the PROJECTED away team).

    Raises ``ValueError`` for an UNVERIFIED game: callers must exclude it, never guess."""
    if check.status is Orientation.SAME:
        return sched_home_score, sched_away_score
    if check.status is Orientation.SWAPPED:
        return sched_away_score, sched_home_score
    raise ValueError(f"orientation unverified ({check.reason}); refusing to map result")
