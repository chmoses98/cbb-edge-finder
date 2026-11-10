"""Backward-compatible per-team modelling inputs exported with NEW prospective projection records.

Added to a record as the extra top-level block ``model_inputs`` (the Sift contract fields are
untouched, so older readers ignore it). Every value is derived from the engine state or the
current-season team-games that were available BEFORE ``as_of``; nothing is computed after the fact and
archived records are never back-filled. A value that cannot be reproduced is ``null`` with an entry in
the team's ``missing`` map giving the reason - missing is never silently zero.

Weighting basis (``ridge_diagonal_approx``): the ratings engine is a prior-anchored ridge
(``cbb_edge/ratings/adjusted.py``): with prior strength ``lam`` (in observation-weight units: games
for pace, possessions for efficiency) and ``n`` current-season weight accumulated, the data weight is
``n / (n + lam)`` and the prior weight ``lam / (n + lam)``. This ignores opponent coupling and the
recency decay, so it is an explicit APPROXIMATION of the exact posterior; the exact prior value and
posterior covariance are not exposed by the engine state rows (stated in ``missing``).
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

INPUTS_VERSION = "cbb-model-inputs-1"
BASIS = "ridge_diagonal_approx"
MIN_NOISE_ROWS = 60  # current-season team-games needed to estimate within-team noise


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def league_noise(tg: pd.DataFrame, season: int) -> dict[str, Any]:
    """Within-team game-to-game noise from current-season team-games available before ``as_of``
    (the frame passed in is already filtered to ``available_at < as_of``).

    ``tempo_game_sd``: SD of a team's single-game tempo around its own season mean.
    ``eff_unit_sd``: SD of single-game points per 100 possessions around the team mean, scaled to one
    possession of weight (x sqrt(poss)), so ``eff_unit_sd / sqrt(weight)`` is a posterior-mean SD."""
    need = {"team_id", "season", "tempo", "ppp", "poss"}
    if not need <= set(tg.columns):
        return {"missing": f"columns_absent:{sorted(need - set(tg.columns))}"}
    cur = tg[(tg["season"] == season) & tg["team_id"].notna()]
    cur = cur.dropna(subset=["tempo", "ppp", "poss"])
    if len(cur) < MIN_NOISE_ROWS:
        return {
            "missing": f"fewer_than_{MIN_NOISE_ROWS}_current_season_team_games",
            "n_rows": len(cur),
        }
    g = cur.groupby("team_id")
    cnt = g["tempo"].transform("count")
    ok = cnt >= 2
    if ok.sum() < MIN_NOISE_ROWS // 2:
        return {"missing": "too_few_teams_with_two_games", "n_rows": len(cur)}
    c = cur[ok]
    dof = float((c.groupby("team_id")["tempo"].count() - 1).sum())
    t_dev = c["tempo"] - c.groupby("team_id")["tempo"].transform("mean")
    e = c["ppp"] * 100.0
    e_dev = (e - e.groupby(c["team_id"]).transform("mean")) * c["poss"].pow(0.5)
    return {
        "tempo_game_sd": float(math.sqrt((t_dev**2).sum() / dof)),
        "eff_unit_sd": float(math.sqrt((e_dev**2).sum() / dof)),
        "n_rows": int(len(cur)),
        "n_teams": int(c["team_id"].nunique()),
    }


def _team(r: pd.Series, s: str, lam: dict[str, float], noise: dict[str, Any]) -> dict[str, Any]:
    miss: dict[str, str] = {}
    games = _num(r.get(f"{s}_games_seen"))
    poss = _num(r.get(f"{s}_poss_seen"))
    off_t, off_e, def_e = (_num(r.get(f"{s}_{k}")) for k in ("off_tempo", "off_eff", "def_eff"))
    mu_t, mu_e = _num(r.get("mu_tempo")), _num(r.get("mu_eff"))
    lam_t, lam_e = _num(lam.get("tempo")), _num(lam.get("eff"))
    out: dict[str, Any] = {
        "team_game_number": None if games is None else int(games) + 1,
        "games_seen": None if games is None else int(games),
        "possessions_seen": poss,
    }
    out["expected_tempo"] = None if None in (mu_t, off_t) else mu_t + 2 * off_t  # type: ignore[operator]
    out["tempo_effect"] = off_t
    out["efficiency"] = {
        "league_mean": mu_e,
        "offense_effect": off_e,
        "defense_effect": def_e,  # positive = allows more (adj_def = league_mean + this)
        "adj_off": None if None in (mu_e, off_e) else mu_e + off_e,  # type: ignore[operator]
        "adj_def": None if None in (mu_e, def_e) else mu_e + def_e,  # type: ignore[operator]
    }
    for key, n, lm in (("pace", games, lam_t), ("efficiency", poss, lam_e)):
        if n is None or lm is None:
            out[f"{key}_weighting"] = None
            miss[f"{key}_weighting"] = "state_or_lambda_unavailable"
            continue
        out[f"{key}_weighting"] = {
            "prior_weight": lm / (n + lm),
            "current_weight": n / (n + lm),
            "effective_sample": n + lm,
            "effective_sample_unit": "games" if key == "pace" else "possessions",
            "prior_strength": lm,
            "basis": BASIS,
        }
    # posterior SDs from the league within-team noise (also from information before as_of)
    if "missing" in noise:
        miss["pace_posterior_sd"] = miss["efficiency_posterior_sd"] = str(noise["missing"])
        out["pace_posterior_sd"] = out["efficiency_posterior_sd"] = None
    else:
        pw, ew = out["pace_weighting"], out["efficiency_weighting"]
        out["pace_posterior_sd"] = (
            noise["tempo_game_sd"] / math.sqrt(pw["effective_sample"]) if pw else None
        )
        out["efficiency_posterior_sd"] = (
            noise["eff_unit_sd"] / math.sqrt(ew["effective_sample"]) if ew else None
        )
    rest = _num(r.get(f"{s}_rest"))
    out["days_since_last_game"] = rest
    if rest is None:
        miss["days_since_last_game"] = "rest_feature_not_in_this_model_frame"
    miss["prior_season_rating_value"] = "not_exposed_by_engine_state_rows"
    miss["exact_posterior_covariance"] = "not_exposed_by_engine_state_rows"
    out["missing"] = miss
    return out


def game_block(
    r: pd.Series, model: dict[str, Any], noise: dict[str, Any], as_of: pd.Timestamp
) -> dict[str, Any]:
    lam = (model.get("engine_config") or {}).get("lam") or {}
    mu_t, h_t, a_t = (_num(r.get(k)) for k in ("mu_tempo", "h_off_tempo", "a_off_tempo"))
    poss = None if None in (mu_t, h_t, a_t) else mu_t + h_t + a_t  # type: ignore[operator]
    return {
        "version": INPUTS_VERSION,
        "info_cutoff_utc": as_of.isoformat(),
        "info_rows": None if _num(r.get("info_rows")) is None else int(r["info_rows"]),
        "expected_possessions": {
            "value": poss,
            "league_mean_tempo": mu_t,
            "home_tempo_effect": h_t,
            "away_tempo_effect": a_t,
        },  # fmt: skip
        "noise": noise,
        "home": _team(r, "h", lam, noise),
        "away": _team(r, "a", lam, noise),
        "note": "derived only from pre-as_of state; new records only; old records are never back-filled",
    }
