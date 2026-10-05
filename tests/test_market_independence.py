"""PERMANENT CI TEST: PURE_BASKETBALL projections are independent of every market input.

1. structural — PURE modules cannot import cbb_edge.market / cbb_edge.kalshi;
2. data — PURE input frames are rejected if they carry market-looking columns;
3. behavioural — run PURE projections, mutate every stored line / Kalshi price / ESPN
   pregame probability on disk, rerun: projections must be bit-identical;
4. Sift — the projection block of a Sift record never changes with the market block.
"""

from __future__ import annotations

import ast
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cbb_edge.model import arms
from cbb_edge.model.families import (
    FORBIDDEN_IMPORTS,
    PURE_PACKAGES,
    MarketLeakError,
    assert_pure_frame,
)
from cbb_edge.model.pure import pure_projections
from tests.synthetic import make_league

REPO = Path(__file__).resolve().parents[1]


def _pure_files():
    for spec in PURE_PACKAGES:
        p = REPO / spec
        yield from ([p] if p.suffix == ".py" else sorted(p.rglob("*.py")))


def test_pure_modules_never_import_market_code():
    offenders = []
    for f in _pure_files():
        if not f.exists():
            continue
        for node in ast.walk(ast.parse(f.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for n in names:
                if any(n == b or n.startswith(b + ".") for b in FORBIDDEN_IMPORTS):
                    offenders.append((str(f.relative_to(REPO)), n))
    assert not offenders, offenders


@pytest.mark.parametrize(
    "col",
    [
        "home_spread_close",
        "total_close",
        "home_ml_open",
        "kalshi_yes_mid",
        "yes_bid",
        "line_move",
        "market_prob",
        "pregame_home_prob",
        "espn_wp",
        "consensus_total",
    ],
)
def test_market_columns_rejected(col):
    with pytest.raises(MarketLeakError):
        assert_pure_frame(pd.DataFrame({"game_id": [1], col: [0.0]}))


def test_basketball_columns_accepted():
    assert_pure_frame(
        pd.DataFrame(
            {
                "game_id": [1],
                "h_off_eff": [1.0],
                "poss": [68.0],
                "lineup_net": [0.5],
                "total": [140.0],
                "margin": [3.0],
            }
        )
    )


def _write_world(root: Path) -> None:
    gs, ts = [], []
    for i, season in enumerate((2018, 2019, 2020, 2021)):
        g, tg, _ = make_league(season=season, seed=i, n_days=30, gid_start=1000 + 10000 * i)
        g["completed"] = True
        gs.append(g)
        ts.append(tg)
    silver = root / "silver"
    silver.mkdir(parents=True)
    games = pd.concat(gs, ignore_index=True)
    pd.concat(ts, ignore_index=True).to_parquet(silver / "team_games.parquet")
    games.to_parquet(silver / "games.parquet")
    # market artefacts that a careless pipeline could read
    lines = pd.DataFrame(
        {
            "game_id": games.game_id,
            "home_spread_close": -3.0,
            "total_close": 140.0,
            "home_ml_close": -150.0,
        }
    )
    (root / "bronze" / "github_raw" / "espn_lines").mkdir(parents=True)
    lines.to_parquet(root / "bronze" / "github_raw" / "espn_lines" / "espn_lines_2021.parquet")
    pd.DataFrame({"game_id": games.game_id, "pregame_home_prob": 0.6}).to_parquet(
        silver / "espn_pregame.parquet"
    )
    snap = root / "kalshi" / "snapshots" / "2021" / "01" / "01"
    snap.mkdir(parents=True)
    with gzip.open(snap / "kalshi_cbb_x.jsonl.gz", "wt") as fh:
        fh.write(json.dumps({"market": {"ticker": "X", "yes_bid": 40, "yes_ask": 42}}) + "\n")


def _mutate_markets(root: Path) -> None:
    rng = np.random.default_rng(0)
    p = root / "bronze" / "github_raw" / "espn_lines" / "espn_lines_2021.parquet"
    d = pd.read_parquet(p)
    for c in ("home_spread_close", "total_close", "home_ml_close"):
        d[c] = rng.normal(0, 50, len(d))
    d.to_parquet(p)
    q = root / "silver" / "espn_pregame.parquet"
    e = pd.read_parquet(q)
    e["pregame_home_prob"] = rng.uniform(0, 1, len(e))
    e.to_parquet(q)
    for f in (root / "kalshi").rglob("*.jsonl.gz"):
        with gzip.open(f, "wt") as fh:
            fh.write(json.dumps({"market": {"ticker": "X", "yes_bid": 1, "yes_ask": 99}}) + "\n")


@pytest.mark.parametrize("arm", [arms.analytic, lambda d: arms.stacked(d, min_train_seasons=2)])
def test_pure_projection_bit_identical_after_market_mutation(tmp_path, monkeypatch, arm):
    monkeypatch.setenv("CBB_DATA_DIR", str(tmp_path))
    _write_world(tmp_path)
    seasons = [2018, 2019, 2020, 2021]
    before = pure_projections(arm, seasons)
    _mutate_markets(tmp_path)
    after = pure_projections(arm, seasons)
    assert before["margin"].notna().any()
    pd.testing.assert_frame_equal(before, after, check_exact=True)


def test_sift_projection_unchanged_by_market_block():
    from cbb_edge.app import sift

    def rec(market):
        return sift.SiftProjection(
            game=sift.GameRef("G1", 1, 2027, "2026-11-04T00:00:00+00:00", "home"),
            home=sift.TeamRef("T0001", 2, "Auburn Tigers"),
            away=sift.TeamRef("T0002", 333, "Alabama Crimson Tide"),
            projection=sift.Projection(70.0, 1.13, 1.09, 79.4, 76.1, 3.3, 155.5, 0.618),
            model=sift.ModelRef("m", "0.2.0", "PURE"),
            freshness=sift.Freshness("2026-11-03T00:00:00+00:00", 0, 0, 0),
            market=market,
        ).to_dict()

    a = rec(None)
    b = rec({"kalshi": {"yes_mid": 55.0}, "spread": -4.5, "total": 153.5})
    assert a["projection"] == b["projection"]
    assert a["model"] == b["model"]


@pytest.mark.parametrize("version", ["pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0"])
def test_frozen_artifact_features_are_pure(version):
    """Every input of every frozen PURE artifact passes the market-column guard."""
    spec = json.loads(
        (Path(__file__).resolve().parents[1] / "models" / "pure" / f"{version}.json").read_text()
    )
    assert spec["market_inputs"] == "NONE"
    feats = set(spec["margin"]["features"]) | set(spec["total"]["features"])
    assert_pure_frame(pd.DataFrame(columns=sorted(feats)), version)
