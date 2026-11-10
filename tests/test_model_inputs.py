"""Wave 13 export block: reproducible, explicit-missing, additive."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from cbb_edge.app import model_inputs as mi
from cbb_edge.app.sift import validate  # noqa: F401

LAM = {"tempo": 3.0, "eff": 225.0}
MODEL = {"engine_config": {"lam": LAM}}
ASOF = pd.Timestamp("2026-11-05T12:00:00Z")


def row(**kw):
    base = {"mu_tempo": 68.0, "mu_eff": 105.0, "h_off_tempo": 1.0, "a_off_tempo": -0.5,
            "h_off_eff": 2.0, "a_off_eff": -1.0, "h_def_eff": -0.5, "a_def_eff": 1.5,
            "h_games_seen": 2, "a_games_seen": 0, "h_poss_seen": 140.0, "a_poss_seen": 0.0,
            "info_rows": 300, "h_rest": 3.0}  # fmt: skip
    base.update(kw)
    return pd.Series(base)


def noise_frame(n_teams=40, games=3, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(n_teams):
        for _ in range(games):
            poss = rng.normal(68, 4)
            rows.append({"team_id": f"T{t}", "season": 2027, "tempo": poss, "poss": poss,
                         "ppp": rng.normal(1.05, 0.12)})  # fmt: skip
    return pd.DataFrame(rows)


def test_league_noise_needs_enough_current_season_rows():
    assert "missing" in mi.league_noise(noise_frame(5, 2), 2027)
    assert "missing" in mi.league_noise(noise_frame().drop(columns=["ppp"]), 2027)
    n = mi.league_noise(noise_frame(), 2027)
    assert n["tempo_game_sd"] == pytest.approx(4.0, rel=0.3)
    assert n["n_teams"] == 40


def test_noise_ignores_other_seasons():
    f = noise_frame()
    other = f.copy()
    other["season"] = 2026
    other["tempo"] = 200.0  # would wreck the SD if it leaked
    got = mi.league_noise(pd.concat([f, other]), 2027)
    assert got["tempo_game_sd"] == pytest.approx(mi.league_noise(f, 2027)["tempo_game_sd"])


def test_game_block_values_are_reproducible_from_state():
    noise = mi.league_noise(noise_frame(), 2027)
    b = mi.game_block(row(), MODEL, noise, ASOF)
    assert b["version"] == mi.INPUTS_VERSION and b["info_cutoff_utc"] == ASOF.isoformat()
    assert b["expected_possessions"]["value"] == pytest.approx(68.0 + 1.0 - 0.5)
    h, a = b["home"], b["away"]
    assert h["team_game_number"] == 3 and a["team_game_number"] == 1
    assert h["expected_tempo"] == pytest.approx(70.0)
    assert h["pace_weighting"]["prior_weight"] == pytest.approx(3.0 / 5.0)
    assert h["efficiency_weighting"]["prior_weight"] == pytest.approx(225.0 / 365.0)
    assert h["efficiency_weighting"]["current_weight"] + h["efficiency_weighting"][
        "prior_weight"
    ] == pytest.approx(1)
    assert a["pace_weighting"]["prior_weight"] == pytest.approx(1.0)  # no games: pure prior
    assert h["efficiency"]["adj_off"] == pytest.approx(107.0) and h["efficiency"][
        "adj_def"
    ] == pytest.approx(104.5)
    assert h["pace_posterior_sd"] == pytest.approx(noise["tempo_game_sd"] / math.sqrt(5.0))
    assert a["pace_posterior_sd"] > h["pace_posterior_sd"]  # less data, more uncertainty
    json.dumps(b)  # archivable


def test_missing_values_are_explicit_never_zero():
    b = mi.game_block(row(h_rest=np.nan, h_def_eff=np.nan), MODEL, {"missing": "too_few"}, ASOF)
    h = b["home"]
    assert h["days_since_last_game"] is None and "days_since_last_game" in h["missing"]
    assert h["efficiency"]["defense_effect"] is None and h["efficiency"]["adj_def"] is None
    assert h["pace_posterior_sd"] is None and h["missing"]["pace_posterior_sd"] == "too_few"
    assert (
        "prior_season_rating_value" in h["missing"]
    )  # engine does not expose it: stated, not invented
    nolam = mi.game_block(row(), {"engine_config": {}}, mi.league_noise(noise_frame(), 2027), ASOF)
    assert nolam["home"]["pace_weighting"] is None
    assert nolam["home"]["missing"]["pace_weighting"] == "state_or_lambda_unavailable"


def test_block_is_additive_to_a_valid_sift_record():
    rec = {"schema_version": "sift-cbb-projection-1.0", "game": {"site": "home"}, "home": {"team_id": "T1"}, "away": {"team_id": "T2"},
           "model": {"research_state": "research"}, "freshness": {}, "generated_at": "x",
           "projection": {"possessions": 68, "home_score": 70, "away_score": 66, "margin": 4,
                          "total": 136, "home_win_prob": 0.6}}  # fmt: skip
    before = json.dumps(rec, sort_keys=True)
    rec["model_inputs"] = mi.game_block(row(), MODEL, {"missing": "x"}, ASOF)
    validate(rec)  # the contract check ignores the extra block
    rec.pop("model_inputs")
    assert json.dumps(rec, sort_keys=True) == before  # nothing else was touched
