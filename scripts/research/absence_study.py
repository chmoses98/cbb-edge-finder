"""Wave-4 absence study (B19 diagnostics) + replacement / persistence fits.

* absence table 2011-2026 from actual minutes (pregame info only)
* class frequencies (first surprise / 2nd / 3rd+ / return) for regulars
* P(plays | miss run) by era (persistence model fitted per season on earlier seasons)
* replacement (γ, β) chosen on DEV 2012-2014 from the preregistered grid
Outputs research/wave4/absence_study.json, replacement_grid.csv, data/research/wave4/absence_table.parquet
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cbb_edge.data.http import data_dir
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players import availability_model as am

OUT = Path("research/wave4")
WORK = data_dir() / "research" / "wave4"


def main() -> None:
    games, _ = load_pure_silver()
    pg = pd.read_parquet(
        data_dir() / "silver" / "player_games.parquet",
        columns=["season", "game_id", "team_id", "player_id", "min", "position"],
    )
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    pg = pg.merge(games[["game_id", "start_time_utc"]], on="game_id")
    WORK.mkdir(parents=True, exist_ok=True)
    p = WORK / "absence_table.parquet"
    if p.exists():
        t = pd.read_parquet(p)
    else:
        t = am.absence_table(pg, list(range(2011, 2027)))
        t.to_parquet(p, index=False)
    t["cls"] = am.absence_class(t)
    reg = t[t["regular"]]
    rep: dict[str, object] = {"n_rows": len(t), "n_regular_rows": len(reg)}
    freq = reg.groupby("season")["cls"].value_counts(normalize=True).unstack().fillna(0)
    rep["regular_class_share_by_season"] = freq.round(4).to_dict("index")
    rep["regular_class_counts"] = reg["cls"].value_counts().to_dict()
    # empirical P(plays) for regulars by run of missed games
    r = reg.assign(run=reg["miss_run"].clip(upper=5))
    rep["p_play_by_miss_run_regulars"] = (
        r.groupby("run")["played"].agg(["mean", "size"]).round(4).to_dict("index")
    )
    rep["p_play_by_miss_run_by_era"] = {
        era: x.groupby(x["miss_run"].clip(upper=3))["played"].mean().round(4).to_dict()
        for era, x in (("2011-2020", r[r.season <= 2020]), ("2021-2026", r[r.season >= 2021]))
    }
    dev = t[t["season"].between(2012, 2014)]
    g, b, grid = am.fit_replacement(dev)
    grid.to_csv(OUT / "replacement_grid.csv", index=False)
    rep["replacement"] = {"gamma": g, "beta": b, "fit_seasons": [2012, 2014]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "absence_study.json").write_text(json.dumps(rep, indent=1, default=float))
    print(
        json.dumps(
            {k: v for k, v in rep.items() if k != "regular_class_share_by_season"},
            indent=1,
            default=float,
        )
    )


if __name__ == "__main__":
    main()
