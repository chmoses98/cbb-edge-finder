"""Probe FREE roster sources for the Wave 6 roster-source audit (docs/ROSTER_SOURCE_AUDIT.md).

Runs from GitHub Actions (the sandbox blocks ESPN / NCAA / school sites). About fifty
requests through the cost-policy chokepoint, each source at its registered spacing.
Teams: six that ESPN's site roster still labelled 2025-26 on 2026-10-05, four current.

For every source / team: reachable?, season label, player count, ids present, class /
experience field, previous-school field, and the source-side Last-Modified / ETag.
Prints one JSON document.
"""

from __future__ import annotations

import json
import re
from typing import Any

from cbb_edge.data.http import fetch

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball"
STALE = [13, 27, 36, 48, 56, 108]
FRESH = [2, 150, 103, 120]
SCHOOLS = {
    150: "https://goduke.com/sports/mens-basketball/roster",
    103: "https://bceagles.com/sports/mens-basketball/roster",
    120: "https://umterps.com/sports/mens-basketball/roster",
}


def _get(source: str, url: str, params: dict | None = None) -> tuple[Any, dict]:
    try:
        r = fetch(source, url, params, use_cache=False, not_found_ok=True, timeout=30,
                  max_attempts=2)  # fmt: skip
    except Exception as e:  # noqa: BLE001  report, never crash the probe
        return None, {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    if r is None:
        return None, {"status": 404}
    m = {k: r.meta.get(k) for k in ("bytes", "content_type", "last_modified", "etag")}
    try:
        return r.json(), m
    except ValueError:
        return r.path.read_text(errors="replace"), m


def site_roster(t: int) -> dict:
    js, m = _get("espn_public", f"{SITE}/teams/{t}/roster")
    if not isinstance(js, dict):
        return m
    ath = js.get("athletes") or []
    if ath and isinstance(ath[0], dict) and "items" in ath[0]:
        ath = [a for g in ath for a in g.get("items", [])]
    exp = {}
    for a in ath:
        e = (a.get("experience") or {}).get("displayValue") or (a.get("experience") or {}).get(
            "abbreviation"
        )
        exp[str(e)] = exp.get(str(e), 0) + 1
    keys = sorted({k for a in ath[:20] for k in a})
    return {
        **m,
        "season": js.get("season"),
        "timestamp": js.get("timestamp"),
        "n_athletes": len(ath),
        "experience": exp,
        "athlete_keys": keys,
        "has_college_history": any("college" in k.lower() for k in keys),
    }


def core_season(t: int, season: int) -> dict:
    js, m = _get("espn_public", f"{CORE}/seasons/{season}/teams/{t}/athletes", {"limit": "200"})
    if not isinstance(js, dict):
        return m
    items = js.get("items") or []
    return {**m, "count": js.get("count"), "n_items": len(items),
            "first_ref": (items[0] or {}).get("$ref") if items else None}  # fmt: skip


def core_athlete(ref: str | None) -> dict:
    if not ref:
        return {}
    js, m = _get("espn_public", ref.replace("http://", "https://"))
    if not isinstance(js, dict):
        return m
    keep = ("id", "displayName", "experience", "position", "height", "jersey", "team",
            "collegeAthlete", "college", "status", "active", "debutYear", "draft")  # fmt: skip
    return {**m, "keys": sorted(js)[:60], **{k: js.get(k) for k in keep if k in js}}


def site_team(t: int) -> dict:
    js, m = _get("espn_public", f"{SITE}/teams/{t}")
    if not isinstance(js, dict):
        return m
    team = js.get("team") or {}
    links = [
        {"rel": li.get("rel"), "href": li.get("href"), "text": li.get("text")}
        for li in team.get("links") or []
    ]
    return {**m, "links": links[:12]}


def school(url: str) -> dict:
    txt, m = _get("school_athletics", url)
    if not isinstance(txt, str):
        return m if txt is None else {**m, "json": True}
    seasons = sorted(set(re.findall(r"20\d\d-\d\d", txt)))[-4:]
    return {
        **m,
        "sidearm_player_cards": len(re.findall(r"sidearm-roster-player(?![-\w])", txt)),
        "season_strings": seasons,
        "mentions_previous_school": bool(re.search(r"[Pp]revious [Ss]chool|Last School", txt)),
        "mentions_class": bool(re.search(r"\b(Fr\.|So\.|Jr\.|Sr\.|Gr\.|R-Fr\.)", txt)),
    }


def _strip(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def ncaa_team_list() -> dict:
    url = "https://stats.ncaa.org/team/inst_team_list"
    txt, m = _get("ncaa_stats", url, {"academic_year": "2027", "conf_id": "-1",
                                     "division": "1", "sport_code": "MBB"})  # fmt: skip
    if not isinstance(txt, str):
        return m
    teams = re.findall(r'href="/teams/(\d+)"[^>]*>([^<]+)<', txt)
    rep = {**m, "n_team_links": len(teams), "sample": teams[:5]}
    rosters = {}
    for tid, name in teams[:2]:
        r, mm = _get("ncaa_stats", f"https://stats.ncaa.org/teams/{tid}/roster")
        if not isinstance(r, str):
            rosters[name] = mm
            continue
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", r, flags=re.S)
        cells = [[_strip(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", x, flags=re.S)]
                 for x in rows]  # fmt: skip
        rosters[name] = {**mm, "n_rows": len(rows), "header": cells[0] if cells else None,
                         "rows": cells[1:4], "player_links": len(re.findall(
                             r"/players/\d+", r))}  # fmt: skip
    rep["rosters"] = rosters
    return rep


def main() -> None:
    out: dict[str, Any] = {"site_roster": {}, "core_2027": {}, "core_2026": {}, "site_team": {}}
    for t in STALE + FRESH:
        out["site_roster"][t] = site_roster(t)
        out["core_2027"][t] = core_season(t, 2027)
        out["core_2026"][t] = core_season(t, 2026)
    out["core_athlete_sample"] = core_athlete(out["core_2027"][FRESH[1]].get("first_ref"))
    for t in (STALE[0], FRESH[1]):
        out["site_team"][t] = site_team(t)
    out["school_sites"] = {t: school(u) for t, u in SCHOOLS.items()}
    js, m = _get("ncaa_stats", "https://stats.ncaa.org/")
    out["ncaa_stats_root"] = {**m, "reachable": js is not None}
    out["ncaa_team_list"] = ncaa_team_list()
    js, m = _get(
        "sportsdataverse_releases",
        "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
        "espn_mens_college_basketball_rosters/rosters_2027.parquet",
    )
    out["sdv_rosters_2027"] = m
    print(json.dumps(out, indent=1, default=str))
    summary = {
        str(t): {
            "site_season": (out["site_roster"][t].get("season") or {}).get("year")
            if isinstance(out["site_roster"][t].get("season"), dict)
            else out["site_roster"][t].get("season"),
            "site_n": out["site_roster"][t].get("n_athletes"),
            "site_exp": out["site_roster"][t].get("experience"),
            "site_college_hist": out["site_roster"][t].get("has_college_history"),
            "core27_n": out["core_2027"][t].get("count"),
            "core27_ref": str(out["core_2027"][t].get("first_ref"))[-60:],
            "core26_n": out["core_2026"][t].get("count"),
        }
        for t in STALE + FRESH
    }
    print("SUMMARY " + json.dumps(summary, default=str))
    print("NCAA " + json.dumps(out.get("ncaa_team_list"), default=str)[:6000])
    sch = {}
    for t, u in SCHOOLS.items():
        txt, _ = _get("school_athletics", u)
        if isinstance(txt, str):
            cls = sorted(set(re.findall(r'class="([^"]*(?:roster|person|player)[^"]*)"', txt)))
            sch[t] = cls[:40]
    print("SCHOOL_CLASSES " + json.dumps(sch)[:6000])
    save_samples()


SAMPLES = {
    "school_duke_roster.html": ("school_athletics", SCHOOLS[150], None),
    "ncaa_team_list_2027.html": (
        "ncaa_stats",
        "https://stats.ncaa.org/team/inst_team_list",
        {"academic_year": "2027", "conf_id": "-1", "division": "1", "sport_code": "MBB"},
    ),
    "ncaa_team_627275.html": ("ncaa_stats", "https://stats.ncaa.org/teams/627275", None),
    "ncaa_team_627275_roster.html": (
        "ncaa_stats",
        "https://stats.ncaa.org/teams/627275/roster",
        None,
    ),
    "espn_core_2027_team_13.json": (
        "espn_public",
        f"{CORE}/seasons/2027/teams/13/athletes",
        {"limit": "200"},
    ),  # fmt: skip
}


def save_samples(out_dir: str = "samples") -> None:
    """Raw responses for offline parser development (committed to the
    roster-source-samples branch by the workflow; the sandbox cannot reach them)."""
    from pathlib import Path

    d = Path(out_dir)
    d.mkdir(exist_ok=True)
    for name, (src, url, params) in SAMPLES.items():
        try:
            r = fetch(src, url, params, use_cache=False, not_found_ok=True, timeout=30,
                      max_attempts=2)  # fmt: skip
        except Exception as e:  # noqa: BLE001
            (d / f"{name}.error.txt").write_text(repr(e)[:500])
            continue
        if r is not None:
            (d / name).write_bytes(r.path.read_bytes())
            (d / f"{name}.meta.json").write_text(json.dumps(r.meta, indent=1))


if __name__ == "__main__":
    main()
