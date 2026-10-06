"""Season-boundary checkpoints: the canonical live reconstruction (Wave 5, Priority 0).

A frozen model's features for season ``s`` depend on long histories (the team engine
replayed from 2006, the walk-forward RAPM chains from 2011, career shooting since
2006, P(return) models trained on many seasons). Rebuilding those from a shorter
warm-up on a CI runner reproduces them only approximately.

A checkpoint for (model version, boundary season B = s − 1) stores the exact
end-of-season state that the RESEARCH replay reached at the end of B:

* ``engine_end``    end-of-season fits of the model's team engine (all stats), with
                    the team id order;
* ``finals``        base-engine final ratings for seasons <= B (conference anchor,
                    transfer team-strength change);
* ``rapm_<chain>``  end-of-season player ratings of each RAPM chain the model uses,
                    for B (and B − 1 where the player-prior provider needs history);
* ``preseason``     the research preseason roster table for season s;
* ``shooting``      career makes / attempts per player through B, and each team's
                    last-five-game shooting expectation in B (first-game fallback);
* ``poss_*``        (pure-0.5.0+) player possession-model state: career counts through
                    B, end-of-season posteriors of B-2..B, each team's final EWMA
                    minute weights in B, P(return) for B+1, league zone means of B.

The live run then replays ONLY season ``s`` from that state with the same code, so
live and research are the same computation (parity test:
``tests/test_parity.py`` + ``scripts/research/parity_diagnostics.py``).
Checkpoints are content-hashed in ``manifest.json``; they are written once and never
modified (a new boundary is a new directory).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cbb_edge.players.rapm import SeasonRapm
from cbb_edge.ratings.adjusted import Fit

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "models" / "pure" / "checkpoints"


def path_for(version: str, boundary: int) -> Path:
    return ROOT / version / f"boundary_{boundary}"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save_engine(fits: dict[str, Fit], team_ids: list[str], p: Path) -> None:
    arrays: dict[str, np.ndarray] = {"team_ids": np.array(team_ids, dtype=object)}
    meta = {}
    for stat, f in fits.items():
        arrays[f"{stat}|off"] = f.off
        arrays[f"{stat}|deff"] = f.deff
        arrays[f"{stat}|n_obs"] = f.n_obs
        if f.raw is not None:
            arrays[f"{stat}|raw"] = f.raw
        meta[stat] = {"mu": float(f.mu), "eta": float(f.eta)}
    np.savez_compressed(p, **arrays, meta=np.array(json.dumps(meta)))


class EngineEnd(dict):
    """End-of-season fits in the CHECKPOINT's own team order (``team_ids``)."""

    team_ids: list[str]


def load_engine(p: Path, team_ids: list[str], entering: set[str] | None = None) -> EngineEnd:
    """``team_ids``: the current registry. It must equal the checkpoint's team list, or
    extend it ONLY by ``entering`` teams (teams that joined D-I after the checkpoint's
    boundary, Wave 9: West Florida). Those start from the engine's own rule for teams
    absent from the previous season (``walkforward.priors_from_previous``); every
    checkpointed team's state is used exactly as stored."""
    z = np.load(p, allow_pickle=True)
    ids = list(z["team_ids"])
    if ids != list(team_ids):
        extra = set(team_ids) - set(ids)
        if set(ids) - set(team_ids) or not extra or not extra <= (entering or set()):
            raise ValueError("checkpoint team order differs from the current registry")
    meta = json.loads(str(z["meta"]))
    out = EngineEnd(
        {
            s: Fit(
                m["mu"],
                m["eta"],
                z[f"{s}|off"],
                z[f"{s}|deff"],
                z[f"{s}|n_obs"],
                z[f"{s}|raw"] if f"{s}|raw" in z.files else None,
            )
            for s, m in meta.items()
        }
    )
    out.team_ids = ids
    return out


def save_rapm(r: SeasonRapm, p: Path) -> None:
    pd.DataFrame({"player_id": r.players, "o": r.o, "d": r.d, "poss": r.poss}).to_parquet(
        p, index=False
    )
    p.with_suffix(".json").write_text(json.dumps({"mu": r.mu, "eta": r.eta}))


def load_rapm(p: Path) -> SeasonRapm:
    df = pd.read_parquet(p)
    m = json.loads(p.with_suffix(".json").read_text())
    return SeasonRapm(
        list(df["player_id"]),
        df["o"].to_numpy(),
        df["d"].to_numpy(),
        float(m["mu"]),
        float(m["eta"]),
        df["poss"].to_numpy(),
    )


def write_manifest(d: Path, info: dict[str, Any]) -> dict[str, Any]:
    files = {f.name: _sha(f) for f in sorted(d.iterdir()) if f.name != "manifest.json"}
    man = {**info, "files": files}
    man["sha256"] = hashlib.sha256(json.dumps(man, sort_keys=True).encode()).hexdigest()
    (d / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True))
    return man


class Checkpoint:
    """Read-only view of one (version, boundary) checkpoint; verifies file hashes."""

    def __init__(self, version: str, boundary: int):
        self.dir = path_for(version, boundary)
        self.boundary = boundary
        self.manifest = json.loads((self.dir / "manifest.json").read_text())
        for name, sha in self.manifest["files"].items():
            if _sha(self.dir / name) != sha:
                raise ValueError(f"checkpoint file modified: {self.dir / name}")

    @staticmethod
    def exists(version: str, boundary: int) -> bool:
        return (path_for(version, boundary) / "manifest.json").exists()

    def engine(self, team_ids: list[str]) -> EngineEnd:
        from cbb_edge.data.ids.teams import _registry

        reg = _registry()
        entering = set(reg.loc[reg["first_d1_season"] > self.boundary, "team_id"])
        return load_engine(self.dir / "engine_end.npz", team_ids, entering)

    def finals(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "finals.parquet")

    def rapm(self, chain: str, season: int) -> SeasonRapm:
        return load_rapm(self.dir / f"rapm_{chain}_{season}.parquet")

    def has(self, name: str) -> bool:
        return (self.dir / name).exists()

    def preseason(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "preseason.parquet")

    def shooting_careers(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "shooting_careers.parquet")

    def shooting_prev_team(self) -> dict[tuple[str, int], dict[str, float]]:
        t = pd.read_parquet(self.dir / "shooting_prev_team.parquet")
        out: dict[tuple[str, int], dict[str, float]] = {}
        for r in t.itertuples(index=False):
            out.setdefault((r.team_id, int(r.season)), {})[r.typ] = float(r.value)
        return out

    # ---- pure-0.5.0+: player possession model (cbb_edge.players.possession) ----------
    def poss_careers(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "poss_careers.parquet")

    def poss_end_values(self) -> dict[tuple[str, int], np.ndarray]:
        from cbb_edge.players.possession import RATES

        t = pd.read_parquet(self.dir / "poss_end_values.parquet")
        v = t[list(RATES)].to_numpy()
        return {
            (p, int(s)): v[i]
            for i, (p, s) in enumerate(zip(t["player_id"], t["season"], strict=True))
        }

    def poss_end_weights(self) -> dict[tuple[str, int], dict[str, float]]:
        t = pd.read_parquet(self.dir / "poss_end_weights.parquet")
        out: dict[tuple[str, int], dict[str, float]] = {}
        for r in t.itertuples(index=False):
            out.setdefault((r.team_id, int(r.season)), {})[r.player_id] = float(r.w)
        return out

    def poss_p_ret(self) -> dict[tuple[str, str, int], float]:
        t = pd.read_parquet(self.dir / "poss_p_ret.parquet")
        return {
            (p, tm, int(s)): float(v)
            for p, tm, s, v in zip(t["player_id"], t["team_id"], t["season"], t["p"], strict=True)
        }

    def poss_league(self) -> dict[int, tuple[float, float]]:
        d = json.loads((self.dir / "poss_league.json").read_text())
        return {int(k): (float(v[0]), float(v[1])) for k, v in d.items()}
