"""Live (prospective) inputs for wave-3 PURE models (``pure-0.3.0`` and later).

Rebuilds, with information available before ``as_of`` only, everything a frozen
wave-3 artifact needs beyond the wave-2 pipeline:

* base engine run (same config, no hook) -> previous-season final ratings, used for
  the conference anchor and the transfer team-strength change (as in research, where
  the B9 engine finals were used);
* the base walk-forward RAPM chain -> end-of-season player ratings -> player-season
  roster graph -> preseason roster state (``preseason.preseason_team_features``);
* the roster-strength series: observed rotation x season-start player ratings, with
  transfer translation (``update_ratings=False``), from the FROZEN player-prior
  coefficients stored in the artifact;
* the in-season player features with the box-score-updated provider (frozen
  coefficients);
* the hooked engine run (``TeamPriorHook`` with the frozen DEV-fitted coefficients).

Known, documented differences vs the research replay: the live RAPM chain starts at
``season - pf_warmup`` instead of 2011, and the live roster graph is built from the
silver seasons present on the runner.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from cbb_edge.backtest.walkforward import EngineConfig, run
from cbb_edge.data.http import data_dir
from cbb_edge.players import box_prior, preseason, roster_graph, team_prior
from cbb_edge.players.rapm import RapmConfig, SeasonRapm, player_team_features


def _provider(
    model: dict[str, Any], key: str, ps, pg, team_net
) -> box_prior.PlayerPriorProvider | None:
    spec = model["player_prior"].get(key)
    if spec is None:  # wave-2 carry priors (no provider)
        return None
    prov = box_prior.PlayerPriorProvider(
        ps,
        pg,
        team_net,
        kind=spec["kind"],
        box_update=spec["box_update"],
        translate=spec["translate"],
        half_minutes=spec.get("half_minutes", box_prior.BOX_HALF_MINUTES),
        carry=spec.get("carry", 0.95),
    )
    for s, m in model["player_prior"]["models"].items():
        prov.models[int(s)] = box_prior.PriorModel(**m)
    return prov


def wave3_inputs(
    model: dict[str, Any],
    season: int,
    games_info: pd.DataFrame,
    tg_e: pd.DataFrame,
    as_of: pd.Timestamp,
    cfg: EngineConfig,
    warmup: int = 8,
    pf_warmup: int = 4,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (hooked engine pregame states, player features for the player block)."""
    seasons = list(range(season - warmup, season + 1))
    pf_seasons = list(range(season - pf_warmup, season + 1))
    base = run(games_info, tg_e, seasons, cfg, verbose=False)
    finals = team_prior.season_final_ratings(base, games_info)
    team_net = finals.assign(net=finals["o"] - finals["d"])
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[(pg["available_at"] < as_of) & pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    pg_min = pg[["season", "game_id", "team_id", "player_id", "min"]]
    rc = RapmConfig(**model["rapm_config"])
    ends: dict[int, SeasonRapm] = {}
    player_team_features(pf_seasons, games_info, pg_min, rc, verbose=False, end_ratings=ends)
    ps = roster_graph.build(pg=pg, save=False, attach_rapm=False)
    r = pd.concat(
        [
            pd.DataFrame(
                {
                    "player_id": e.players,
                    "season": s,
                    "rapm_o": e.o,
                    "rapm_d": e.d,
                    "rapm_poss": e.poss,
                }
            )
            for s, e in ends.items()
            if s < season
        ]
    )
    ps = ps.merge(r, on=["player_id", "season"], how="left")
    ps["rapm_matched"] = ps["rapm_poss"].fillna(0) > 0
    ps["rapm_net"] = ps["rapm_o"] - ps["rapm_d"]
    hk = model["team_prior_hook"]
    comps = tuple(hk["components"])
    strength = pre = None
    if "S" in comps:
        prov_rot = _provider(model, "roster_strength", ps, pg, team_net)
        pf_rot = player_team_features(
            pf_seasons,
            games_info,
            pg_min,
            rc,
            verbose=False,
            prior_provider=prov_rot,
            update_ratings=False,
        )
        strength = team_prior.team_day_strength(pf_rot, games_info)
        pre = preseason.all_seasons(ps, [s for s in pf_seasons if s - 1 in ends])
    ca = team_prior.conference_anchor(finals, games_info) if "conf" in comps else None
    coefs = team_prior.PriorCoefficients(
        components=comps, pre=hk["pre"], obs=hk["obs"], n=hk.get("n", {})
    )
    hook = team_prior.TeamPriorHook(coefs, strength, pre, ca, stats=tuple(hk.get("stats", ["eff"])))
    states = run(games_info, tg_e, seasons, cfg, verbose=False, prior_hook=hook)
    prov = _provider(model, "player_features", ps, pg, team_net)
    pf = player_team_features(
        pf_seasons, games_info, pg_min, rc, verbose=False, prior_provider=prov
    )
    return states, pf
