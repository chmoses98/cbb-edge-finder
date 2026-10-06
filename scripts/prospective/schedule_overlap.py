"""ESPN-vs-SDV schedule overlap validation (Wave 11 B). Schema/source validation only:
nothing here feeds or tunes a projection.

For every game present in BOTH the SDV schedule and the live ESPN scoreboard it
compares (1) every SDV schedule field the pipeline reads, raw, and (2) the silver games
row each source produces through the SAME transform
(``cbb_edge.data.silver.build.schedule_rows_to_silver``), the actual projection input.
Run on the current season (all dates) and on a completed season (results, postseason,
tournament ids, neutral sites, final scores).

    python scripts/prospective/schedule_overlap.py --season 2027 --hist-season 2026 --out ov
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from cbb_edge.data.bronze import sportsdataverse as sdv
from cbb_edge.data.silver.build import schedule_rows_to_silver
from cbb_edge.ops import schedule_completion as sc
from cbb_edge.ops import schedule_state as ss

SILVER_COLS = ["season", "season_type", "start_time_utc", "neutral_site", "conference_game",
               "tournament_id", "notes", "venue_id", "venue_name", "venue_city", "venue_state",
               "home_espn_id", "away_espn_id", "home_name", "away_name", "home_conference_id",
               "away_conference_id", "home_score", "away_score", "periods", "status",
               "completed", "game_date_et", "available_at", "n_ot"]  # fmt: skip


def dates_between(a: date, b: date, step: int = 1) -> list[str]:
    out, d = [], a
    while d <= b:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=step)
    return out


def silver_compare(s_rows: pd.DataFrame, e_rows: pd.DataFrame, season: int) -> pd.DataFrame:
    a = schedule_rows_to_silver(s_rows, season).set_index("game_id")
    b = schedule_rows_to_silver(e_rows, season).set_index("game_id")
    ids = sorted(set(a.index) & set(b.index))
    rows = []
    for c in SILVER_COLS:
        x, y = a.loc[ids, c], b.loc[ids, c]
        eq = [(pd.isna(u) and pd.isna(v)) or (not pd.isna(u) and not pd.isna(v) and u == v)
              or str(u) == str(v) for u, v in zip(x, y, strict=True)]  # fmt: skip
        rows.append({"field": c, "games": len(ids), "equal": int(sum(eq)),
                     "different": int(len(ids) - sum(eq)),
                     "examples": [{"game_id": int(g), "sdv": str(u), "espn": str(v)}
                                  for g, u, v, e in zip(ids, x, y, eq, strict=True) if not e][:5]})  # fmt: skip
    return pd.DataFrame(rows)


def validate(season: int, dates: list[str], stamp: str, sdv_path: Path | None) -> dict:
    raw, failed = ss.fetch_scoreboard_raw(dates, stamp)
    espn = pd.DataFrame([r for js, at in raw for r in sc.espn_rows(js, at)])
    s = pd.read_parquet(sdv_path) if sdv_path is not None else pd.DataFrame(columns=sc.ROW_COLS)
    if not len(espn):
        return {"season": season, "dates": len(dates), "failed_dates": failed, "espn_games": 0}
    espn["observed_at"] = pd.to_datetime(espn["observed_at"], utc=True)
    espn = espn[pd.to_numeric(espn["season"], errors="coerce") == season]
    shared = sorted(set(s["game_id"].astype(int)) & set(espn["game_id"].astype(int)))
    cmp = sc.compare(s[s["game_id"].isin(shared)], espn[espn["game_id"].isin(shared)])
    by_field = (cmp.groupby(["field", "result"]).size().unstack(fill_value=0)
                if len(cmp) else pd.DataFrame())  # fmt: skip
    diffs = cmp[cmp["result"] == "different"]
    fb = sc._as_sdv_types(espn[espn["game_id"].isin(shared)][sc.ROW_COLS].copy(), s)
    silver = silver_compare(s[s["game_id"].isin(shared)], fb, season) if shared else pd.DataFrame()
    dts = {d[:4] + "-" + d[4:6] + "-" + d[6:] for d in dates}
    s_in = s[pd.to_datetime(s["date"], utc=True).dt.tz_convert(ss.ET).dt.date.astype(str).isin(dts)]
    return {
        "season": season, "dates": len(dates), "failed_dates": failed,
        "espn_games": int(espn["game_id"].nunique()), "sdv_games_on_dates": int(len(s_in)),
        "shared_games": len(shared),
        "espn_only": int(len(set(espn["game_id"]) - set(s["game_id"].astype(int)))),
        "sdv_only_on_dates": int(len(set(s_in["game_id"].astype(int)) - set(espn["game_id"]))),
        "raw_fields": by_field.reset_index().to_dict("records") if len(by_field) else [],
        "raw_differences": diffs.groupby("field").size().to_dict() if len(diffs) else {},
        "raw_difference_examples": {f: g.head(5).to_dict("records")
                                    for f, g in diffs.groupby("field")} if len(diffs) else {},
        "silver_fields": silver.to_dict("records") if len(silver) else [],
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--hist-season", type=int, default=2026)
    ap.add_argument(
        "--hist-step", type=int, default=6, help="every Nth day of the completed season"
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    a.out.mkdir(parents=True, exist_ok=True)
    cur = sdv.download_live("schedules", a.season, stamp)
    y = a.season - 1
    rep = {"stamp": stamp, "current": validate(
        a.season, dates_between(date(y, 11, 1), date(a.season, 4, 10)), stamp, cur)}  # fmt: skip
    hp = sdv.download("schedules", [a.hist_season])
    hist = hp[0] if hp else None
    hy = a.hist_season - 1
    hd = sorted(set(dates_between(date(hy, 11, 3), date(a.hist_season, 4, 7), a.hist_step))
                | set(dates_between(date(a.hist_season, 3, 10), date(a.hist_season, 3, 22))))  # fmt: skip
    rep["completed_season"] = validate(a.hist_season, hd, stamp, hist)
    (a.out / "overlap.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: {kk: v.get(kk) for kk in ("espn_games", "shared_games", "espn_only",
                                                   "raw_differences")}
                      for k, v in rep.items() if isinstance(v, dict)}, default=str))  # fmt: skip


if __name__ == "__main__":
    main()
