"""Free historical closing lines from ESPN ``pickcenter`` blocks.

Source: per-game ESPN summary JSON archived by SportsDataverse in the public repo
``sportsdataverse/hoopR-mbb-raw`` (``mbb/json/final/{game_id}.json``), fetched from
raw.githubusercontent.com (FREE_RATE_LIMITED). Each raw JSON is ~1 MB, so we keep only
the extracted betting block (plus the raw file's sha256 for provenance) and discard the
rest of the payload.

Coverage found in the audit (sampled): 2015-2017 spread only (consensus/teamrankings),
2018-2023 spread + total (consensus / Caesars), 2024-2025 none, 2026 DraftKings with
explicit open AND close spread/total/moneyline.

Timing caveat: before 2026 ESPN exposes a single line with no timestamp. It is captured
after the game and is treated as an approximate CLOSING line. It must never be used as an
"opening"/earlier-snapshot line, and CLV analysis is only valid where open/close exist.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cbb_edge.data.bronze import manifest
from cbb_edge.data.bronze.sportsdataverse import local_rel
from cbb_edge.data.http import data_dir, fetch, sha256_file

SOURCE = "github_raw"
RAW_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/hoopR-mbb-raw/main/mbb/json/final/{gid}.json"
)


def _odds_dir(season: int) -> Path:
    return data_dir() / "bronze" / SOURCE / "espn_game_odds" / str(season)


def harvest_game(season: int, game_id: int) -> str:
    out = _odds_dir(season) / f"{game_id}.json"
    if out.exists():
        return "cached"
    tmp_rel = Path("espn_game_json_tmp") / f"{game_id}.json"
    res = fetch(
        SOURCE,
        RAW_URL.format(gid=game_id),
        dest=tmp_rel,
        not_found_ok=True,
        schema_version="espn-summary-raw",
        timeout=90,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    if res is None:
        out.write_text(json.dumps({"game_id": game_id, "status": 404}))
        return "404"
    try:
        g = json.loads(res.path.read_text())
    except json.JSONDecodeError:
        g = {}
    comp = ((g.get("header") or {}).get("competitions") or [{}])[0]
    rec: dict[str, Any] = {
        "game_id": game_id,
        "season": season,
        "status": 200,
        "game_date": comp.get("date"),
        "pickcenter": g.get("pickcenter") or [],
        "odds": g.get("odds") or [],
        "raw_url": res.meta["url"],
        "raw_sha256": res.meta["sha256"],
        "raw_bytes": res.meta["bytes"],
        "retrieved_at": res.meta["retrieved_at"],
        "raw_discarded": True,
    }
    out.write_text(json.dumps(rec, sort_keys=True))
    res.path.unlink(missing_ok=True)
    res.path.with_name(res.path.name + ".meta.json").unlink(missing_ok=True)
    return "ok" if rec["pickcenter"] else "no_lines"


def _num(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, int | float):
        return float(x)
    s = str(x).strip().lstrip("ou").replace("+", "")
    if s.upper() in {"OFF", "EVEN", ""}:
        return 100.0 if s.upper() == "EVEN" else None
    try:
        return float(s)
    except ValueError:
        return None


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def parse_pickcenter(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten the highest-priority provider into home-perspective numbers.

    ESPN ``spread`` is quoted from the HOME team's perspective (negative = home favored)
    in the providers we inspected; we cross-check it with the explicit favorite flags and
    the ``pointSpread.home.close.line`` field when present.
    """
    pcs = rec.get("pickcenter") or []
    if not pcs:
        return None
    pc = sorted(pcs, key=lambda p: (p.get("provider") or {}).get("priority", 99))[0]
    home = pc.get("homeTeamOdds") or {}
    away = pc.get("awayTeamOdds") or {}
    spread = _num(pc.get("spread"))
    # Sign check: if home is flagged favorite, the home spread must be <= 0.
    if spread is not None and home.get("favorite") is True and spread > 0:
        spread = -spread
    if spread is not None and away.get("favorite") is True and spread < 0:
        spread = -spread
    out: dict[str, Any] = {
        "game_id": rec["game_id"],
        "provider": (pc.get("provider") or {}).get("name"),
        "home_spread_close": spread,
        "total_close": _num(pc.get("overUnder")),
        "home_ml_close": _num(home.get("moneyLine")),
        "away_ml_close": _num(away.get("moneyLine")),
        "home_spread_open": None,
        "total_open": None,
        "home_ml_open": None,
        "away_ml_open": None,
        "has_open_close": False,
        # ESPN team ids the line is quoted for (orientation key; see orient_to_games)
        "pc_home_espn_id": _int(home.get("teamId")),
        "pc_away_espn_id": _int(away.get("teamId")),
    }
    ps = pc.get("pointSpread")
    if isinstance(ps, dict) and "home" in ps:
        out["has_open_close"] = True
        out["home_spread_open"] = _num((ps["home"].get("open") or {}).get("line"))
        close = _num((ps["home"].get("close") or {}).get("line"))
        if close is not None:
            out["home_spread_close"] = close
    tot = pc.get("total")
    if isinstance(tot, dict) and "over" in tot:
        out["total_open"] = _num((tot["over"].get("open") or {}).get("line"))
        close = _num((tot["over"].get("close") or {}).get("line"))
        if close is not None:
            out["total_close"] = close
    ml = pc.get("moneyline")
    if isinstance(ml, dict) and "home" in ml:
        out["home_ml_open"] = _num((ml["home"].get("open") or {}).get("odds"))
        out["away_ml_open"] = _num((ml["away"].get("open") or {}).get("odds"))
        hc = _num((ml["home"].get("close") or {}).get("odds"))
        ac = _num((ml["away"].get("close") or {}).get("odds"))
        out["home_ml_close"] = hc if hc is not None else out["home_ml_close"]
        out["away_ml_close"] = ac if ac is not None else out["away_ml_close"]
    return out


HOME_COLS = ("home_spread_close", "home_spread_open")
# Market sources only. ESPN pickcenter also carries lines from analytics/projection
# sites (numberfire, teamrankings); those are not sportsbook prices and are excluded
# from the MARKET benchmark (decided by provider identity, not by outcomes).
MARKET_PROVIDERS = frozenset({"consensus", "DraftKings", "Caesars Sportsbook (New Jersey)"})
ML_PAIRS = (("home_ml_close", "away_ml_close"), ("home_ml_open", "away_ml_open"))


def orient_to_games(lines: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Orient every line to OUR home team using the team ids ESPN quoted it for.

    ESPN's pickcenter sometimes lists neutral-site games with home/away reversed relative
    to the schedule. Joining by position flips the spread sign for those games (found in
    the baseline audit: 2-3% of lined games, ~20% of the largest model-vs-line edges).
    Rules: pickcenter home == our home -> keep; == our away -> negate spreads and swap
    moneylines; neither / missing ids -> ``orientation = "unknown"`` (excluded from
    market research). Finally ``line_suspect`` flags |spread| >= 3 whose sign disagrees
    with the moneyline favorite.
    """
    g = games[["game_id", "home_espn_id", "away_espn_id"]]
    d = lines.merge(g, on="game_id", how="left", validate="one_to_one")
    ph = pd.to_numeric(d["pc_home_espn_id"], errors="coerce")
    pa = pd.to_numeric(d["pc_away_espn_id"], errors="coerce")
    gh = pd.to_numeric(d["home_espn_id"], errors="coerce")
    ga = pd.to_numeric(d["away_espn_id"], errors="coerce")
    same = ((ph == gh) & (pa == ga)).fillna(False).astype(bool)
    flip = ((ph == ga) & (pa == gh)).fillna(False).astype(bool)
    d["orientation"] = np.select([same, flip], ["as_quoted", "flipped"], "unknown")
    for c in HOME_COLS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
        d.loc[flip, c] = -d.loc[flip, c]
    for h, a in ML_PAIRS:
        hv, av = d.loc[flip, h].copy(), d.loc[flip, a].copy()
        d.loc[flip, h], d.loc[flip, a] = av, hv
    ml = pd.to_numeric(d["home_ml_close"], errors="coerce")
    sp = d["home_spread_close"]
    d["line_suspect"] = ml.notna() & sp.abs().ge(3) & ((ml < 0) != (sp < 0))
    d["line_usable"] = d["orientation"].ne("unknown") & ~d["line_suspect"]
    if "provider" in d:
        d["market_provider"] = d["provider"].isin(MARKET_PROVIDERS)
        d["line_usable"] &= d["market_provider"]
    return d.drop(columns=["home_espn_id", "away_espn_id"])


def consolidate(season: int) -> Path:
    rows = []
    for p in sorted(_odds_dir(season).glob("*.json")):
        rec = json.loads(p.read_text())
        if rec.get("status") != 200:
            continue
        parsed = parse_pickcenter(rec)
        if parsed:
            parsed["season"] = season
            parsed["retrieved_at"] = rec["retrieved_at"]
            parsed["raw_sha256"] = rec["raw_sha256"]
            rows.append(parsed)
    df = pd.DataFrame(rows)
    out = data_dir() / "bronze" / SOURCE / "espn_lines" / f"espn_lines_{season}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    manifest.record(
        {
            "source": SOURCE,
            "cost_class": "FREE_RATE_LIMITED",
            "url": RAW_URL.format(gid="{game_id}"),
            "params": {},
            "retrieved_at": datetime.now(UTC).isoformat(),
            "sha256": sha256_file(out),
            "bytes": out.stat().st_size,
            "schema_version": "espn-lines-v1",
            "local_path": str(out.relative_to(data_dir())),
        },
        dataset="espn_lines",
        season=season,
        n_games_with_lines=len(df),
        n_games_requested=len(list(_odds_dir(season).glob("*.json"))),
    )
    return out


def harvest_season(season: int, workers: int = 6) -> dict[str, int]:
    sched = pd.read_parquet(
        data_dir() / "bronze" / "sportsdataverse_releases" / local_rel("schedules", season)
    )
    sched = sched[sched["status_type_completed"].fillna(False).astype(bool)]
    ids = sorted(int(x) for x in sched["game_id"].dropna().unique())
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(lambda g: _safe(season, g), ids)):
            counts[r] = counts.get(r, 0) + 1
            if i % 500 == 0:
                print(f"  {season}: {i}/{len(ids)} {counts}", flush=True)
    consolidate(season)
    print(f"  {season}: done {counts}", flush=True)
    return counts


def _safe(season: int, gid: int) -> str:
    try:
        return harvest_game(season, gid)
    except Exception as exc:  # noqa: BLE001 - keep harvesting; retried on next run
        return f"error:{type(exc).__name__}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("seasons", nargs="+", type=int)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    for s in args.seasons:
        harvest_season(s, args.workers)


if __name__ == "__main__":
    main()
