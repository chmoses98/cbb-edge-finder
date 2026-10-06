"""Projection selection policy: which archived record Sift may show as a game's projection.

Sift must never show a hindsight projection. The policy only SELECTS among records the
prospective pipeline already archived; it never projects, adjusts or re-scores anything.

For each (game, model version):

* a record is ELIGIBLE only when it provably existed before tip:

  - it carries prospective provenance (``prospective.as_of``) and was not stamped in the
    future relative to the publication clock;
  - announced tip (``time_state`` ANNOUNCED): ``as_of`` strictly before the CURRENT listed
    tip (a rescheduled game is judged against when it really starts, never against the
    tip stored in the record);
  - start time not announced (ESPN "TBD" placeholder, 00:00 ET of the game date):
    ``as_of`` before that placeholder, or the record's own live ESPN observation, made at
    or after ``as_of``, showing the game had not started (Wave 10). Anything else is
    ``pretip_unproven`` (fail closed, the same rule the scorer's gate applies);

* the SELECTED record is the eligible one with the newest ``as_of`` (latest valid pre-tip
  snapshot wins); two different records of one version with the same ``as_of`` are a
  conflict and none of them is shown;
* a record of another matchup than the current schedule (Wave 11
  ``schedule_identity_changed``) is shown only with that flag, never as clean evidence.

The integrity verdict of a SETTLED game comes from the prospective scoreboard's pre-tip
gate (VALID / INVALID / UNSCORABLE), which this module only reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from cbb_edge.ops.schedule_state import ANNOUNCED, not_started

INCUMBENT, SHADOW, ROSTER_OVERLAY, OTHER = "incumbent", "shadow", "roster_overlay", "other"
ROLE_LABEL = {
    INCUMBENT: "Incumbent",
    SHADOW: "Shadow research",
    ROSTER_OVERLAY: "Prospective roster overlay",
    OTHER: "Other research overlay",
}
CAPTURE_WINDOW_H = 30.0  # the frozen projection horizon (prospective.py / cadence.py)

# game-level projection states (what Sift says instead of a number when there is none)
PROJECTED = "PROJECTED"  # a pre-tip record is shown
PENDING_WINDOW = "PENDING_WINDOW"  # upcoming; not yet inside the 30 h capture window
AWAITING_CAPTURE = "AWAITING_CAPTURE"  # inside the window; the next scheduled run records it
UNAVAILABLE = "UNAVAILABLE"  # started / settled without any pre-tip record
STATE_TEXT = {
    PROJECTED: "Projection published before tip.",
    PENDING_WINDOW: "Projection pending — game has not entered the prospective capture window.",
    AWAITING_CAPTURE: "Inside the 30-hour capture window — the next scheduled prospective run "
    "records the projection before tip.",
    UNAVAILABLE: "No projection was archived before tip for this game; none is shown.",
}


def ts(x: object) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def roles(active: dict[str, Any]) -> dict[str, str]:
    """Version -> frozen role, from ``models/pure/active.json`` (read, never written)."""
    out = {active["incumbent"]: INCUMBENT}
    for v in active.get("challengers", []):
        out[v] = SHADOW
    return out


def role_of(version: str, frozen: dict[str, str]) -> str:
    if version in frozen:
        return frozen[version]
    if version.endswith("+roster") and version[: -len("+roster")] in frozen:
        return ROSTER_OVERLAY
    return OTHER


@dataclass(frozen=True)
class GameClock:
    """What the CURRENT schedule says about a game's start."""

    espn_game_id: int
    listed_start: pd.Timestamp
    time_state: str
    state: str | None = None  # ESPN game state: pre / in / post
    status_name: str | None = None
    completed: bool = False
    home_team_id: str | None = None
    away_team_id: str | None = None

    def started(self, now: pd.Timestamp) -> bool:
        """Fail closed: anything but positive not-started evidence, or an announced tip
        that has passed, counts as started."""
        if self.completed or not not_started(self.state, self.status_name):
            return True
        return self.time_state == ANNOUNCED and self.listed_start <= now


def pretip_basis(rec: dict[str, Any], clock: GameClock, now: pd.Timestamp) -> tuple[bool, str]:
    """(eligible, reason) for one archived record against the current schedule."""
    asof_raw = (rec.get("prospective") or {}).get("as_of")
    if not asof_raw:
        return False, "no_prospective_provenance"
    as_of = ts(asof_raw)
    if as_of > now:
        return False, "as_of_after_publication_clock"
    if clock.time_state == ANNOUNCED:
        return (
            (True, "before_announced_tip")
            if as_of < clock.listed_start
            else (
                False,
                "as_of_not_before_tip",
            )
        )
    if as_of < clock.listed_start:
        return True, "before_unannounced_game_date"
    live = (rec.get("schedule") or {}).get("live") or {}
    obs = live.get("observed_at")
    if obs and not_started(live.get("state"), live.get("status_name")) and ts(obs) >= as_of:
        return True, "live_pre_observation_after_as_of"
    return False, "pretip_unproven"


@dataclass
class Choice:
    version: str
    role: str
    record: dict[str, Any]
    basis: str

    @property
    def as_of(self) -> pd.Timestamp:
        return ts(self.record["prospective"]["as_of"])


@dataclass
class Selection:
    espn_game_id: int
    state: str
    chosen: dict[str, Choice] = field(default_factory=dict)  # version -> choice
    rejected: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    identity_changed: list[str] = field(default_factory=list)  # versions whose record is
    # for another matchup than the current schedule

    @property
    def message(self) -> str:
        return STATE_TEXT[self.state]

    def primary(self, order: list[str]) -> Choice | None:
        """The first role in ``order`` present (incumbent first; never 'the newest model')."""
        for role in order:
            for c in sorted(self.chosen.values(), key=lambda c: c.version):
                if c.role == role:
                    return c
        return None


def select(
    records: list[dict[str, Any]],
    clock: GameClock,
    now: pd.Timestamp,
    frozen_roles: dict[str, str],
    include_roles: tuple[str, ...] = (INCUMBENT, SHADOW, ROSTER_OVERLAY),
) -> Selection:
    """Pick, per version, the newest provably pre-tip record of one game."""
    by_version: dict[str, list[tuple[pd.Timestamp, str, dict, str]]] = {}
    rejected = []
    for r in records:
        if int(r["game"]["espn_game_id"]) != clock.espn_game_id:
            continue
        v = str((r.get("model") or {}).get("version"))
        role = role_of(v, frozen_roles)
        if role not in include_roles:
            continue
        ok, why = pretip_basis(r, clock, now)
        if not ok:
            rejected.append({"version": v, "as_of": (r.get("prospective") or {}).get("as_of"),
                             "reason": why})  # fmt: skip
            continue
        by_version.setdefault(v, []).append((ts(r["prospective"]["as_of"]), why, r, role))
    chosen: dict[str, Choice] = {}
    conflicts = []
    for v, rows in by_version.items():
        rows.sort(key=lambda x: x[0])
        newest = rows[-1][0]
        top = [x for x in rows if x[0] == newest]
        bodies = {_canonical(x[2]) for x in top}
        if len(bodies) > 1:
            conflicts.append(v)  # two different records claim the same pre-tip moment
            continue
        _, why, rec, role = top[0]
        chosen[v] = Choice(v, role, rec, why)
    identity = [
        v
        for v, c in chosen.items()
        if clock.home_team_id
        and clock.away_team_id
        and (c.record["home"]["team_id"], c.record["away"]["team_id"])
        != (clock.home_team_id, clock.away_team_id)
    ]
    if chosen:
        state = PROJECTED
    elif not clock.started(now):
        hours = (clock.listed_start - now).total_seconds() / 3600.0
        state = AWAITING_CAPTURE if hours <= CAPTURE_WINDOW_H else PENDING_WINDOW
    else:
        state = UNAVAILABLE
    return Selection(
        clock.espn_game_id, state, chosen, rejected, sorted(conflicts), sorted(identity)
    )


def _canonical(rec: dict[str, Any]) -> str:
    import json

    return json.dumps({k: v for k, v in rec.items() if not k.startswith("_")}, sort_keys=True)


# ---------------------------------------------------------------- integrity (read-only)
VALID, INVALID, UNSCORABLE, PENDING = "VALID", "INVALID", "UNSCORABLE", "PENDING"
GATE_TEXT = {
    VALID: "Prospective evidence: every pre-tip check passed; this game counts in the scoreboard.",
    INVALID: "Integrity gate failed: a pre-tip record exists but a check failed. Not scored.",
    UNSCORABLE: "UNSCORABLE: no provable pre-tip record for the scored pair. Never reconstructed.",
    PENDING: "Not settled yet.",
    "NOT_SCORED": "Settled; the prospective scoreboard has not scored this game yet.",
}
REASON_TEXT = {
    "schedule_identity_changed": "the schedule changed this game's matchup or home/away after "
    "the pre-tip projection was recorded",
    "tbd_start_unprovable": "the start time was never announced, so the latest pre-tip record "
    "cannot be proven",
    "not_paired": "the base and roster-overlay records could not be paired",
}


def reason_text(reasons: str) -> list[str]:
    out = []
    for r in [x for x in str(reasons or "").split(";") if x]:
        key = r.split(":")[0]
        if key == "no_pre_tip_record":
            out.append(f"no pre-tip record for {r.split(':', 1)[1]}")
        else:
            out.append(REASON_TEXT.get(key, r.replace("_", " ")))
    return out
