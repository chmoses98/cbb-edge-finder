"""Project upcoming games and emit Sift records (research state; no wagering).

    python -m cbb_edge.app.project --season 2027 --as-of 2026-11-01T00:00:00Z

Uses only information available before ``--as-of``: priors from completed seasons and
current-season results with ``available_at < as_of``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from cbb_edge import __version__
from cbb_edge.app.sift import (
    Freshness,
    GameRef,
    ModelRef,
    Projection,
    SiftProjection,
    TeamRatings,
    TeamRef,
    validate,
)
from cbb_edge.backtest.config import tuned_config
from cbb_edge.backtest.walkforward import (
    EngineConfig,
    d1_rows,
    fit_all,
    priors_from_previous,
    state_rows,
)
from cbb_edge.data.http import data_dir
from cbb_edge.data.ids.teams import _registry
from cbb_edge.model.arms import FACTORS, matchup_features

MARGIN_SD_PRESEASON = 11.6  # from validation residuals, early-season bucket
TOTAL_SD_PRESEASON = 17.5


def project(season: int, as_of: pd.Timestamp, cfg: EngineConfig, warmup: int = 6) -> list[dict]:
    g = pd.read_parquet(data_dir() / "silver" / "games.parquet")
    tg = pd.read_parquet(data_dir() / "silver" / "team_games.parquet")
    team_ids = sorted(_registry()["team_id"].tolist())
    index = {t: i for i, t in enumerate(team_ids)}
    # end-of-season fit of season-1 (walk-forward run supplies the prior chain)
    hist = list(range(season - warmup, season))
    from cbb_edge.backtest import walkforward as wf

    prev_end = None
    for s in hist:
        tgs = d1_rows(tg[tg.season == s])
        pri = (
            wf.default_priors(team_ids)
            if prev_end is None
            else priors_from_previous(team_ids, team_ids, prev_end, cfg)
        )
        _, prev_end = wf.replay_season(s, g, tg, pri, cfg) if len(tgs) else (None, prev_end)
    assert prev_end is not None
    pri = priors_from_previous(team_ids, team_ids, prev_end, cfg)
    cur = d1_rows(tg[tg.season == season]).copy()
    info = cur[cur.available_at < as_of]
    if len(info):
        info = info.assign(
            t_idx=info.team_id.map(index).astype(int), o_idx=info.opp_id.map(index).astype(int)
        )
    fits = fit_all(info, pri, cfg, as_of)
    up = g[
        (g.season == season)
        & (g.start_time_utc >= as_of)
        & g.home_team_id.notna()
        & g.away_team_id.notna()
        & g.home_is_d1
        & g.away_is_d1
        & ~g.status.isin(["STATUS_CANCELED", "STATUS_POSTPONED"])
    ]
    n = len(team_ids)
    t_idx = info.team_id.map(index).to_numpy().astype(int) if len(info) else np.array([], int)
    poss_seen = np.bincount(t_idx, weights=info.poss.to_numpy() if len(info) else None, minlength=n)
    games_seen = np.bincount(t_idx, minlength=n).astype(float)
    st = state_rows(up, fits, index, poss_seen, games_seen)
    df = st.merge(up, on="game_id")
    df["L"] = (~df.neutral_site.astype(bool)).astype(float)
    f = matchup_features(df)
    reg = _registry().set_index("team_id")
    out = []
    for i, r in df.iterrows():
        fr = f.loc[i]
        margin, total = float(fr.margin_an), float(fr.total_an)
        msd, tsd = MARGIN_SD_PRESEASON, TOTAL_SD_PRESEASON
        wp = float(np.clip(norm.cdf(margin / msd), 1e-4, 1 - 1e-4))
        hs, as_ = (total + margin) / 2, (total - margin) / 2

        def ratings(side: str, r=r) -> TeamRatings:
            return TeamRatings(
                adj_off=float(r["mu_eff"] + r[f"{side}_off_eff"]),
                adj_def=float(r["mu_eff"] + r[f"{side}_def_eff"]),
                adj_tempo=float(r["mu_tempo"] + 2 * r[f"{side}_off_tempo"]),
                four_factors={
                    f"{x}_{k}": float(r[f"mu_{x}"] + r[f"{side}_{k}_{x}"])
                    for x in FACTORS
                    for k in ("off", "def")
                },
            )

        def tref(tid: str, espn: Any) -> TeamRef:
            row = reg.loc[tid]
            return TeamRef(
                tid,
                int(espn) if pd.notna(espn) else None,
                str(row.espn_display_name),
                row.conference_latest if isinstance(row.conference_latest, str) else None,
            )

        rec = SiftProjection(
            game=GameRef(
                f"G{int(r.game_id)}",
                int(r.game_id),
                season,
                pd.Timestamp(r.start_time_utc).isoformat(),
                "neutral" if r.neutral_site else "home",
                r.venue_name if isinstance(r.venue_name, str) else None,
                r.venue_city if isinstance(r.venue_city, str) else None,
                r.venue_state if isinstance(r.venue_state, str) else None,
                str(r.status),
            ),
            home=tref(r.home_team_id, r.home_espn_id),
            away=tref(r.away_team_id, r.away_espn_id),
            projection=Projection(
                float(fr.poss),
                float(fr.eff_h) / 100,
                float(fr.eff_a) / 100,
                hs,
                as_,
                margin,
                total,
                wp,
                msd,
                tsd,
            ),
            model=ModelRef("cbb-edge-possession-baseline", __version__, "B2", "research"),
            freshness=Freshness(
                as_of.isoformat(),
                int(len(info)),
                int(r.h_games_seen),
                int(r.a_games_seen),
                ["sportsdataverse_releases (ESPN-derived bulk)"],
            ),
            ratings={"home": ratings("h"), "away": ratings("a")},
            matchup_factors={
                f"{x}_{s}": float(fr[f"{x}_{s}"]) for x in FACTORS for s in ("h", "a")
            },
        ).to_dict()
        validate(rec)
        out.append(rec)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    as_of = pd.Timestamp(a.as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    recs = project(a.season, as_of, tuned_config())
    out = Path(a.out or data_dir() / "outputs" / "sift" / f"projections_{a.season}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in recs) + "\n")
    print(f"wrote {len(recs)} Sift records -> {out}")


if __name__ == "__main__":
    main()
