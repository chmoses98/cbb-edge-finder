"""Stable machine-readable projection output for Sift Sports Intelligence.

The schema is versioned (``SCHEMA_VERSION``) and decoupled from the model: Sift reads
only these records, never model internals. Additive changes bump the minor version;
breaking changes bump the major version and are announced in docs/SIFT_SCHEMA.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

SCHEMA_VERSION = "sift-cbb-projection-1.0"
ResearchState = Literal["research", "shadow", "production"]
Site = Literal["home", "neutral"]


@dataclass
class TeamRef:
    team_id: str  # canonical (T0001 ...)
    espn_team_id: int | None
    name: str
    conference: str | None = None


@dataclass
class GameRef:
    game_id: str  # canonical game id ("G" + ESPN event id)
    espn_game_id: int | None
    season: int
    start_time_utc: str
    site: Site
    venue_name: str | None = None
    venue_city: str | None = None
    venue_state: str | None = None
    status: str | None = None


@dataclass
class Projection:
    possessions: float
    home_ppp: float
    away_ppp: float
    home_score: float
    away_score: float
    margin: float  # home minus away
    total: float
    home_win_prob: float
    margin_sd: float | None = None
    total_sd: float | None = None


@dataclass
class TeamRatings:
    adj_off: float  # points per 100 possessions vs average D-I defense
    adj_def: float  # points allowed per 100 vs average D-I offense (lower is better)
    adj_tempo: float  # possessions per 40 vs average opponent
    four_factors: dict[str, float] = field(default_factory=dict)  # adjusted, off/def


@dataclass
class Freshness:
    info_cutoff_utc: str
    info_games: int
    home_games_seen: int
    away_games_seen: int
    sources: list[str] = field(default_factory=list)


@dataclass
class ModelRef:
    name: str
    version: str
    arm: str
    research_state: ResearchState = "research"


@dataclass
class SiftProjection:
    game: GameRef
    home: TeamRef
    away: TeamRef
    projection: Projection
    model: ModelRef
    freshness: Freshness
    ratings: dict[str, TeamRatings] = field(default_factory=dict)  # keys: home, away
    matchup_factors: dict[str, float] = field(default_factory=dict)
    player_context: dict[str, Any] | None = None
    market: dict[str, Any] | None = None
    schema_version: str = SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, allow_nan=False)


class SchemaError(ValueError):
    pass


def validate(rec: dict[str, Any]) -> None:
    """Contract checks Sift relies on. Raises SchemaError."""
    for key in (
        "schema_version",
        "game",
        "home",
        "away",
        "projection",
        "model",
        "freshness",
        "generated_at",
    ):
        if key not in rec:
            raise SchemaError(f"missing {key}")
    if not str(rec["schema_version"]).startswith("sift-cbb-projection-1."):
        raise SchemaError("unsupported schema major version")
    p = rec["projection"]
    for k in ("possessions", "home_score", "away_score", "margin", "total", "home_win_prob"):
        v = p.get(k)
        if v is None or not isinstance(v, int | float) or not math.isfinite(v):
            raise SchemaError(f"projection.{k} must be a finite number")
    if not 0.0 < p["home_win_prob"] < 1.0:
        raise SchemaError("home_win_prob must be strictly inside (0, 1)")
    if abs((p["home_score"] - p["away_score"]) - p["margin"]) > 0.05:
        raise SchemaError("margin inconsistent with scores")
    if abs((p["home_score"] + p["away_score"]) - p["total"]) > 0.05:
        raise SchemaError("total inconsistent with scores")
    for sd in ("margin_sd", "total_sd"):
        if p.get(sd) is not None and not p[sd] > 0:
            raise SchemaError(f"{sd} must be positive")
    if rec["game"]["site"] not in ("home", "neutral"):
        raise SchemaError("game.site must be home|neutral")
    if rec["model"]["research_state"] not in ("research", "shadow", "production"):
        raise SchemaError("bad research_state")
    if rec["home"]["team_id"] == rec["away"]["team_id"]:
        raise SchemaError("home and away must differ")


def json_schema() -> dict[str, Any]:
    """A JSON-Schema (draft 2020-12) description of the record for consumers."""
    num = {"type": "number"}
    opt_num = {"type": ["number", "null"]}
    team = {
        "type": "object",
        "required": ["team_id", "name"],
        "properties": {
            "team_id": {"type": "string", "pattern": "^T[0-9]{4}$"},
            "espn_team_id": {"type": ["integer", "null"]},
            "name": {"type": "string"},
            "conference": {"type": ["string", "null"]},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SiftProjection",
        "type": "object",
        "required": [
            "schema_version",
            "game",
            "home",
            "away",
            "projection",
            "model",
            "freshness",
            "generated_at",
        ],
        "properties": {
            "schema_version": {"type": "string"},
            "generated_at": {"type": "string", "format": "date-time"},
            "game": {
                "type": "object",
                "required": ["game_id", "season", "start_time_utc", "site"],
                "properties": {
                    "game_id": {"type": "string"},
                    "espn_game_id": {"type": ["integer", "null"]},
                    "season": {"type": "integer"},
                    "start_time_utc": {"type": "string"},
                    "site": {"enum": ["home", "neutral"]},
                    "venue_name": {"type": ["string", "null"]},
                    "venue_city": {"type": ["string", "null"]},
                    "venue_state": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"]},
                },
            },
            "home": team,
            "away": team,
            "projection": {
                "type": "object",
                "required": [
                    "possessions",
                    "home_score",
                    "away_score",
                    "margin",
                    "total",
                    "home_win_prob",
                ],
                "properties": {
                    "possessions": num,
                    "home_ppp": num,
                    "away_ppp": num,
                    "home_score": num,
                    "away_score": num,
                    "margin": num,
                    "total": num,
                    "home_win_prob": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "exclusiveMaximum": 1,
                    },
                    "margin_sd": opt_num,
                    "total_sd": opt_num,
                },
            },
            "ratings": {"type": "object"},
            "matchup_factors": {"type": "object"},
            "player_context": {"type": ["object", "null"]},
            "market": {"type": ["object", "null"]},
            "model": {
                "type": "object",
                "required": ["name", "version", "arm", "research_state"],
                "properties": {"research_state": {"enum": ["research", "shadow", "production"]}},
            },
            "freshness": {"type": "object", "required": ["info_cutoff_utc", "info_games"]},
        },
    }
