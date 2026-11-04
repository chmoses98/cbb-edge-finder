"""Shadow calibration challenger: fitting, probabilities, and out-of-sample-only publication."""

from __future__ import annotations

import gzip
import json
import math
import random
from pathlib import Path

import pytest

from cbb_edge.kalshi.research import challenger as CH
from cbb_edge.kalshi.research.universe import Contract, attach_panel


def games(n, bias=3.0, scale=1.2, seed=1):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        m, tot = rng.uniform(-15, 15), rng.uniform(130, 160)
        actual_margin = m + rng.gauss(0, 12.0 * scale)
        actual_total = tot + bias + rng.gauss(0, 16.0)
        out.append(
            {"game_id": i, "tip": f"2026-11-{1 + i // 20:02d}T{i % 20:02d}:00:00+00:00", "margin": m,
             "margin_sd": 12.0, "total": tot, "total_sd": 16.0,
             "home": round((actual_total + actual_margin) / 2), "away": round((actual_total - actual_margin) / 2)}
        )  # fmt: skip
    return out


def test_fit_recovers_bias_and_scale_from_the_earliest_games_only():
    g = games(400)
    p = CH.fit(g)
    assert p["total_bias"] == pytest.approx(3.0, abs=1.0)
    assert p["margin_sd_scale"] == pytest.approx(1.2, abs=0.1)
    assert p["fit_games"] == 240 and p["fit_share"] == 0.6
    ordered = sorted(g, key=lambda x: (x["tip"], x["game_id"]))
    assert p["fit_window_end"] == ordered[239]["tip"]  # later games are strictly out of sample


def test_fit_refuses_tiny_samples():
    with pytest.raises(ValueError):
        CH.fit(games(20))


PARAMS = {"base_version": "pure-0.5.0", "version": "calib-0.5.0-v1", "total_bias": 3.0,
          "margin_sd_scale": 1.2, "total_sd_scale": 1.0, "fit_window_end": "2026-11-03T00:00:00+00:00"}  # fmt: skip
PROJ = {"margin": 6.0, "margin_sd": 10.0, "total": 140.0, "total_sd": 15.0}


def cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def test_probability_transforms_match_the_documented_formulae():
    tot = {"status": "parsed", "period": "FULL", "market_type": "TOTAL", "strike": 145.5}
    assert CH.probability(tot, PROJ, PARAMS) == pytest.approx(cdf((143.0 - 145.5) / 15.0))
    home = {
        "status": "parsed",
        "period": "FULL",
        "market_type": "MARGIN",
        "strike": 3.5,
        "subject_side": "home",
    }
    away = dict(home, subject_side="away")
    assert CH.probability(home, PROJ, PARAMS) == pytest.approx(cdf((6.0 - 3.5) / 12.0))
    assert CH.probability(away, PROJ, PARAMS) == pytest.approx(cdf((-6.0 - 3.5) / 12.0))
    win = {"status": "parsed", "period": "FULL", "market_type": "WINNER", "subject_side": "home"}
    assert CH.probability(win, PROJ, PARAMS) == pytest.approx(cdf(6.0 / 12.0))


def test_unsupported_contracts_get_no_probability_never_a_guess():
    half = {"status": "parsed", "period": "1H", "market_type": "TOTAL", "strike": 70.5}
    assert CH.probability(half, PROJ, PARAMS) is None
    assert CH.probability({"status": "strike_mismatch"}, PROJ, PARAMS) is None
    assert (
        CH.probability(
            {"status": "parsed", "period": "FULL", "market_type": "TOTAL", "strike": 1}, {}, PARAMS
        )
        is None
    )


def _panel(tmp_path: Path, tip: str) -> Path:
    d = tmp_path / "panels/2026/11/04"
    d.mkdir(parents=True)
    row = {
        "kalshi_ticker": "KXNCAAMBTOTAL-26NOV04AAABBB-145", "captured_at": "2026-11-04T10:00:00+00:00",
        "market_phase": "PRETIP", "game_start_utc": tip, "espn_game_id": 1,
        "contract_semantics": {"status": "parsed", "period": "FULL", "market_type": "TOTAL", "strike": 145.5},
        "market_specific_model_probability": {"pure-0.5.0": {"probability": 0.4, "method_or_gap": "x"}},
        "models_as_of_capture": {"versions": {"pure-0.5.0": PROJ}},
    }  # fmt: skip
    with gzip.open(d / "kalshi_cbb_20261104T100000Z.panel.jsonl.gz", "wt") as fh:
        fh.write(json.dumps(row) + "\n")
    return tmp_path


def _contract():
    c = Contract(ticker="KXNCAAMBTOTAL-26NOV04AAABBB-145", series="KXNCAAMBTOTAL", family="TOTAL")
    return {c.ticker: c}


def test_challenger_probability_only_after_the_fit_window_and_champion_untouched(tmp_path: Path):
    cs = _contract()
    attach_panel(cs, _panel(tmp_path, "2026-11-05T00:00:00+00:00"), PARAMS)
    mp = next(iter(cs.values())).models[0]
    assert mp.probs["pure-0.5.0"] == 0.4  # the frozen champion value is preserved verbatim
    assert mp.probs["calib-0.5.0-v1"] == pytest.approx(cdf((143.0 - 145.5) / 15.0))
    inside = _contract()
    attach_panel(inside, _panel(tmp_path / "x", "2026-11-02T00:00:00+00:00"), PARAMS)
    m2 = next(iter(inside.values())).models[0]
    assert "calib-0.5.0-v1" not in m2.probs and m2.probs["pure-0.5.0"] == 0.4
    assert m2.gaps["calib-0.5.0-v1"] == "game_inside_fit_window_no_out_of_sample_value"


def test_without_challenger_params_nothing_changes(tmp_path: Path):
    cs = _contract()
    attach_panel(cs, _panel(tmp_path, "2026-11-05T00:00:00+00:00"))
    assert set(next(iter(cs.values())).models[0].probs) == {"pure-0.5.0"}


def test_committed_challenger_parameters_are_frozen_and_sane():
    p = json.loads(Path("models/challengers/calib-0.5.0-v1.json").read_text())
    assert p["version"] == CH.CHALLENGER_VERSION and p["base_version"] == CH.BASE_VERSION
    assert p["fit_games"] >= CH.MIN_FIT_GAMES and 0.5 < p["margin_sd_scale"] < 2.0
