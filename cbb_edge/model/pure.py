"""PURE_BASKETBALL projection entry point.

Reads ONLY basketball silver tables (games, team_games, optional player/lineup feature
tables) — never ``bronze/github_raw/espn_lines``, Kalshi snapshots, or any market file —
and returns walk-forward projections. Every PURE arm in reports, Sift and the
prospective archive goes through :func:`pure_projections`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.backtest.walkforward import EngineConfig, run
from cbb_edge.data.http import data_dir
from cbb_edge.model import arms
from cbb_edge.model.families import assert_pure_frame

PURE_TABLES = ("games.parquet", "team_games.parquet")


def load_pure_silver(root: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = (root or data_dir()) / "silver"
    games = assert_pure_frame(pd.read_parquet(base / "games.parquet"), "silver games")
    tg = assert_pure_frame(pd.read_parquet(base / "team_games.parquet"), "silver team_games")
    return games, tg


def finalize(df: pd.DataFrame, proj: arms.Projection) -> pd.DataFrame:
    """Scores, win probability and SDs from a margin/total projection (prior seasons only)."""
    out = pd.DataFrame(
        {"game_id": df["game_id"].to_numpy(), "season": df["season"].to_numpy()}, index=df.index
    )
    out["margin"] = proj.margin
    out["total"] = proj.total
    out["poss"] = proj.poss if proj.poss is not None else np.nan
    out["home_pts"] = (out["total"] + out["margin"]) / 2
    out["away_pts"] = (out["total"] - out["margin"]) / 2
    out["home_wp"] = arms.win_prob(df, proj.margin)
    out["margin_sd"] = arms.residual_sd(df, proj.margin, "margin")
    out["total_sd"] = arms.residual_sd(df, proj.total, "total")
    return out


def pure_projections(
    arm: Callable[[pd.DataFrame], arms.Projection],
    seasons: list[int],
    cfg: EngineConfig | None = None,
    *,
    root: Path | None = None,
    extra_features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run the walk-forward engine + one PURE arm. ``extra_features`` (keyed by game_id)
    must itself be market-free (checked)."""
    games, tg = load_pure_silver(root)
    states = run(games, tg, seasons, cfg or EngineConfig(), verbose=False)
    df = arms.attach_games(states, games)
    if extra_features is not None:
        assert_pure_frame(extra_features, "extra_features")
        df = df.merge(extra_features, on="game_id", how="left")
    return finalize(df, arm(df))
