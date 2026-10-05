"""Wave 3: roster/conference prior hook, player prior provider, scorecard, artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.backtest.walkforward import SeasonPriors
from cbb_edge.players import box_prior, team_prior
from cbb_edge.players.rapm import RapmConfig, _ns_scalar
from cbb_edge.research import scorecard

REPO = Path(__file__).resolve().parents[1]
PURE_020_SHA = "cc3c62ae4e55deeb4362c4103b6a0b9b8280ef0f9e4ab6e8fb686b24c7837cf1"
T = pd.Timestamp("2020-11-20 23:00", tz="UTC")


def _pri(teams):
    z = np.zeros(len(teams))
    return SeasonPriors(
        teams,
        {"eff": np.array([1.0, -1.0])},
        {"eff": np.array([0.5, 0.0])},
        {"eff": 100.0},
        {"eff": 1.5},
        {"eff": z},
        {"eff": z},
    )


def _coefs():
    k = {"c0": 0.0, "base": 1.0, "S": 0.5}
    return team_prior.PriorCoefficients(
        components=("S",),
        pre={"off": dict(k), "def": dict(k)},
        obs={"off": {**k, "S": 1.0}, "def": {**k, "S": 1.0}},
    )


def _strength(future_value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "team_id": ["A", "A"],
            "season": [2021, 2021],
            "cutoff": [T, T + pd.Timedelta(days=3)],
            "s_off": [2.0, future_value],
            "s_def": [1.0, future_value],
            "known": [1, 1],
            "games_seen": [1, 2],
        }
    )


def test_roster_hook_uses_only_rows_up_to_cutoff():
    pre = pd.DataFrame(
        {"team_id": ["A", "B"], "season": [2021, 2021], "pre_o": [4.0, -4.0], "pre_d": [0.0, 0.0]}
    )
    outs = []
    for fut in (0.0, 99.0):
        hook = team_prior.TeamPriorHook(_coefs(), _strength(fut), pre)
        outs.append(hook(2021, T + pd.Timedelta(hours=1), _pri(["A", "B"])))
    for o in outs:
        # A: roster observed -> obs coefs: base + 1.0 * S ; B: preseason -> base + 0.5 * pre
        assert np.allclose(o.off["eff"], [1.0 + 2.0, -1.0 + 0.5 * -4.0])
        assert np.allclose(o.deff["eff"], [0.5 + 1.0, 0.0])
    assert np.allclose(outs[0].off["eff"], outs[1].off["eff"])


def test_roster_hook_before_first_game_uses_preseason():
    pre = pd.DataFrame({"team_id": ["A"], "season": [2021], "pre_o": [4.0], "pre_d": [2.0]})
    hook = team_prior.TeamPriorHook(_coefs(), _strength(0.0), pre)
    o = hook(2021, T - pd.Timedelta(days=1), _pri(["A", "B"]))
    assert np.isclose(o.off["eff"][0], 1.0 + 0.5 * 4.0)
    assert np.isclose(o.off["eff"][1], -1.0)  # no information: default prior kept


def test_conference_anchor_is_leave_one_out_previous_season():
    finals = pd.DataFrame(
        {
            "team_id": ["A", "B", "C"],
            "season": [2020] * 3,
            "o": [3.0, 1.0, 5.0],
            "d": [0.0, 0.0, 0.0],
        }
    )
    games = pd.DataFrame(
        {
            "season": [2021, 2021],
            "home_team_id": ["A", "C"],
            "away_team_id": ["B", "A"],
            "home_conference_id": [1, 1],
            "away_conference_id": [1, 1],
        }
    )
    ca = team_prior.conference_anchor(finals, games).set_index("team_id")
    assert np.isclose(ca.loc["A", "conf_o"], 3.0)  # mean of B and C
    assert np.isclose(ca.loc["B", "conf_o"], 4.0)


def _provider(future_minutes: float):
    ps = pd.DataFrame(
        {
            "player_id": ["p0"],
            "season": [2020],
            "team_id": ["A"],
            "minutes": [600.0],
            "position": ["G"],
            "rapm_o": [1.0],
            **{c: [100.0] for c in box_prior.BOX_COLS},
        }
    )
    rows = []
    for k, (t, m) in enumerate(((T, 30.0), (T + pd.Timedelta(days=2), future_minutes))):
        rows.append(
            {
                "player_id": "p1",
                "season": 2021,
                "team_id": "B",
                "game_id": k,
                "available_at": t + pd.Timedelta(hours=3),
                "min": m,
                "position": "F",
                **{c: 5.0 for c in box_prior.BOX_COLS},
            }
        )
    pg = pd.DataFrame(rows)
    prov = box_prior.PlayerPriorProvider(
        ps,
        pg,
        pd.DataFrame({"team_id": ["A", "B"], "season": [2020, 2020], "net": [0.0, 5.0]}),
        kind="both",
    )
    pm = box_prior.PriorModel(
        kind="both",
        spm_o=[1.0] + [0.0] * len(box_prior.SPM_FEATURES),
        spm_d=[-1.0] + [0.0] * len(box_prior.SPM_FEATURES),
        ret_o=[0.0, 0.5, 0.5],
        ret_d=[0.0, 0.5, 0.5],
        tr_o=[0.0, 0.3, 0.3, 0.1],
        tr_d=[0.0, 0.3, 0.3, -0.1],
    )
    prov.models[2021] = pm
    return prov


def test_player_prior_provider_ignores_future_box_rows():
    outs = []
    for fut in (0.0, 999.0):
        prov = _provider(fut)
        po, pd_ = prov.start(2021, ["p0", "p1"], None, RapmConfig())
        assert np.isclose(po[0], 0.5 * 1.0 + 0.5 * 1.0)  # returner: rapm + spm
        assert np.isclose(po[1], RapmConfig().new_o)  # newcomer: generic prior
        outs.append(prov.day(_ns_scalar(T + pd.Timedelta(days=1))))
    assert np.allclose(outs[0][0], outs[1][0]) and np.allclose(outs[0][1], outs[1][1])
    w = 30.0 / (30.0 + box_prior.BOX_HALF_MINUTES)
    assert np.isclose(outs[0][0][1], (1 - w) * RapmConfig().new_o + w * 1.0)


def test_time_to_parity():
    c = pd.DataFrame({"games_seen": [0, 1, 2, 3, 4], "gap": [0.6, 0.3, 0.09, 0.2, 0.04]})
    t = scorecard.time_to_parity(c)
    s, f = t["sustained"], t["first"]
    assert s["+0.50"] == 1 and s["+0.25"] == 2 and s["+0.10"] == 4 and s["+0.05"] == 4
    assert f["+0.10"] == 2 and f["+0.05"] == 4


def test_pure_020_artifact_unchanged():
    """pure-0.2.0 is frozen: its content hash must match the recorded one forever."""
    spec = json.loads((REPO / "models" / "pure" / "pure-0.2.0.json").read_text())
    sha = spec.pop("sha256")
    assert sha == hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    assert sha == PURE_020_SHA
    assert spec["version"] == "pure-0.2.0" and spec["market_inputs"] == "NONE"


def test_espn_line_capture_parse_and_horizons():
    from datetime import UTC, datetime

    from cbb_edge.market import espn_capture

    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    board = {
        "events": [
            {
                "id": "401",
                "date": "2026-11-20T13:30Z",
                "competitions": [
                    {
                        "status": {"type": {"state": "pre"}},
                        "neutralSite": False,
                        "competitors": [
                            {"homeAway": "home", "id": "1"},
                            {"homeAway": "away", "id": "2"},
                        ],
                        "odds": [
                            {
                                "provider": {"name": "ESPN BET"},
                                "details": "H -5.5",
                                "spread": -5.5,
                                "overUnder": 141.5,
                                "homeTeamOdds": {"moneyLine": -220, "favorite": True},
                                "awayTeamOdds": {"moneyLine": 180},
                            }
                        ],
                    }
                ],
            },
            {
                "id": "402",
                "date": "2026-11-20T11:00Z",
                "competitions": [{"status": {"type": {"state": "in"}}, "odds": [{}]}],
            },
        ]
    }
    rows = espn_capture.parse(board, now)
    assert len(rows) == 1 and rows[0]["game_id"] == 401 and rows[0]["horizon"] == "T-90m"
    assert espn_capture.horizon(24 * 60) == "T-24h" and espn_capture.horizon(10) == "latest"


PURE_030_SHA = "6a58fb5069df1de80fca1e944268cd2ee1301eadacf0ba7348a19212e9ce7459"


def test_pure_030_artifact_unchanged():
    """pure-0.3.0 is frozen (Wave 3 challenger): content hash pinned forever."""
    spec = json.loads((REPO / "models" / "pure" / "pure-0.3.0.json").read_text())
    sha = spec.pop("sha256")
    assert sha == hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    assert sha == PURE_030_SHA
    assert spec["version"] == "pure-0.3.0" and spec["market_inputs"] == "NONE"


PURE_040_SHA = "4a807ed55f1cbb921b85a1c98e2d1eeb95a043cf00e905ddda9a746a76fa95db"


def test_pure_040_artifact_unchanged():
    """pure-0.4.0 is frozen (Wave 4 challenger): content hash pinned forever."""
    spec = json.loads((REPO / "models" / "pure" / "pure-0.4.0.json").read_text())
    sha = spec.pop("sha256")
    assert sha == hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    assert sha == PURE_040_SHA
    assert spec["version"] == "pure-0.4.0" and spec["market_inputs"] == "NONE"


def test_active_models_list():
    a = json.loads((REPO / "models" / "pure" / "active.json").read_text())
    assert a["incumbent"] == "pure-0.2.0"
    assert a["challengers"] == ["pure-0.3.0", "pure-0.4.0"]
