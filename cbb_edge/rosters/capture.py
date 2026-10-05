"""Roster truth capture (Wave 6): collect every free roster source, resolve, archive.

    python -m cbb_edge.rosters.capture --archive <roster-archive checkout> [--season 2027]

Runs in GitHub Actions right after the ESPN site roster capture (roster-capture.yml).
Sources (docs/ROSTER_SOURCE_AUDIT.md), all through the network chokepoint:

* ``espn_site``   latest ESPN site roster per team = the roster-archive snapshots;
* ``espn_core``   ESPN core season athletes for the target season (and, once, the
                  previous season: the "copy" freshness test);
* ``sdv_rosters`` the SportsDataverse rosters release asset (a dated live copy);
* ``school_site`` official athletics roster pages for every team in the NCAA-derived
                  domain registry (``official`` / ``discovery`` / ``parsers``), with
                  identities resolved by ``identity`` and page freshness from
                  ``official.page_freshness`` (Wave 7).

stats.ncaa.org roster pages sit behind a bot challenge and are NOT used.

Writes (append-only, never rewriting an earlier file) into the archive checkout:

* ``truth/YYYY/MM/DD/<stamp>_records.jsonl``   one record per player x listed team;
* ``truth/YYYY/MM/DD/<stamp>_teams.json``      per-team summary + roster confidence;
* ``truth/YYYY/MM/DD/<stamp>_freshness.jsonl`` per source x team freshness + reason;
* ``truth/YYYY/MM/DD/<stamp>_conflicts.jsonl``;
* ``evidence/core/<season>/<stamp>.json``       ESPN core athlete-id lists;
* ``reports/roster_quality_<stamp>.json``      the source-quality report;
* ``state/truth_state.json``                    first_seen / last_confirmed carry-forward.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cbb_edge.availability.capture import current_d1_teams
from cbb_edge.data.http import fetch
from cbb_edge.data.ids.teams import _espn_map
from cbb_edge.rosters import events, identity, official, truth

CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball"
REPO = Path(__file__).resolve().parents[2]
HISTORY = REPO / "models" / "rosters" / "history_2026.parquet"


def _json(source: str, url: str, params: dict | None, dest: str) -> Any:
    try:
        r = fetch(source, url, params, dest=dest, not_found_ok=True, timeout=60)
    except Exception:  # noqa: BLE001  one failed team never stops the capture
        return None
    return r.json() if r is not None else None


def site_rows(archive: Path) -> list[dict]:
    """Latest ESPN site roster rows per team from the roster-archive snapshots."""
    latest: dict[int, tuple[str, list[dict]]] = {}
    for f in sorted((archive / "snapshots").rglob("*.jsonl")):
        per: dict[int, list[dict]] = {}
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                per.setdefault(int(r["espn_team_id"]), []).append(r)
        for t, rows in per.items():
            latest[t] = (f.name, rows)
    emap = _espn_map()
    out = []
    for t, (_, rows) in latest.items():
        for r in rows:
            lbl = str(r.get("season_label") or "")
            out.append(
                {
                    "source": "espn_site",
                    "captured_at": r["captured_at"],
                    "team_id": emap.get(t),
                    "player_id": r.get("player_id"),
                    "name": r.get("name"),
                    "position": r.get("position"),
                    "class_label": r.get("class"),
                    "height_in": r.get("height_in"),
                    "jersey": r.get("jersey"),
                    "source_season": int(lbl[:4]) + 1 if lbl[:4].isdigit() else None,
                }
            )
    return out


def core_lists(teams: list[int], season: int, stamp: str) -> dict[int, list[str]]:
    out = {}
    for t in teams:
        js = _json("espn_public", f"{CORE}/seasons/{season}/teams/{t}/athletes",
                   {"limit": "200"}, f"rosters_core/{season}/{stamp}_{t}.json")  # fmt: skip
        if not isinstance(js, dict):
            continue
        ids = [
            m.group(1)
            for it in js.get("items") or []
            if (m := re.search(r"/athletes/(\d+)", str(it.get("$ref", ""))))
        ]
        out[t] = ids
    return out


def sdv_rows(season: int, stamp: str) -> list[dict]:
    from cbb_edge.data.bronze import sportsdataverse as sdv

    p = sdv.download_live("rosters", season, stamp)
    if p is None or not p.exists():
        return []
    r = pd.read_parquet(p)
    mp = p.parent / "live" / stamp / (p.name + ".meta.json")
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    cap = meta.get("last_modified") or meta.get("retrieved_at")
    cap = pd.Timestamp(cap).tz_convert("UTC").isoformat() if cap else datetime.now(UTC).isoformat()
    emap = _espn_map()
    return [
        {
            "source": "sdv_rosters",
            "captured_at": cap,
            "team_id": emap.get(int(x.team_id)),
            "player_id": f"P{x.athlete_id}",
            "name": x.display_name,
            "position": x.position_abbreviation,
            "class_label": x.experience_display_value,
            "jersey": x.jersey,
            "source_season": int(x.season),
        }
        for x in r.itertuples(index=False)
    ]


def run(archive: Path, season: int, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    teams = current_d1_teams()
    emap = _espn_map()
    core = core_lists(teams, season, stamp)
    prev_path = archive / "evidence" / "core" / str(season - 1) / "list.json"
    if prev_path.exists():
        prev = {int(k): v for k, v in json.loads(prev_path.read_text()).items()}
    else:  # fetched once: the previous season's lists are complete and do not change
        prev = core_lists(teams, season - 1, stamp)
        prev_path.parent.mkdir(parents=True, exist_ok=True)
        prev_path.write_text(json.dumps(prev))
    ev = archive / "evidence" / "core" / str(season) / f"{stamp}.json"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(core))
    rows = site_rows(archive)
    rows += [
        {"source": "espn_core", "captured_at": now.isoformat(), "team_id": emap.get(t),
         "player_id": f"P{a}", "source_season": season}
        for t, ids in core.items() for a in ids
    ]  # fmt: skip
    rows += sdv_rows(season, stamp)
    hist = pd.read_parquet(HISTORY) if HISTORY.exists() else pd.DataFrame(columns=["player_id"])
    ost_p = archive / "state" / "official_state.json"
    ostate = json.loads(ost_p.read_text()) if ost_p.exists() else {}
    known = {t: v["roster_url"] for t, v in ostate.items() if v.get("roster_url")}
    found = official.capture(season, stamp, known)
    orows = pd.DataFrame(official.official_rows(found))
    if len(orows):
        espn_named = pd.DataFrame([r for r in rows if r.get("name") and r.get("player_id")])
        orows = identity.resolve(orows, espn_named, season)
        rows += orows.drop(columns=["identity_resolved", "platform"]).to_dict("records")
    pages = official.page_freshness(orows, hist, season, found) if len(orows) else pd.DataFrame()
    official_pages = {r.team_id: (r.page_status, r.page_reason) for r in pages.itertuples()}
    df = truth.rows_frame(rows)
    df = df[df["team_id"].notna()]
    prev_core = {emap.get(t): {f"P{a}" for a in ids} for t, ids in prev.items() if emap.get(t)}
    d1 = (
        dict(zip(hist["player_id"], hist["d1_seasons"], strict=True))
        if "d1_seasons" in hist
        else {}
    )
    fresh = truth.team_freshness(df, season, prev_core, d1, official_pages)
    state_p = archive / "state" / "truth_state.json"
    prev_state = pd.DataFrame(json.loads(state_p.read_text())) if state_p.exists() else None
    recs, conflicts = truth.resolve(df, fresh, hist, truth.TruthConfig(season), pd.Timestamp(now),
                                    prev_state)  # fmt: skip
    teams_s = truth.team_summary(recs, fresh)
    prev_snap = latest_snapshot(archive, stamp)
    day = archive / "truth" / now.strftime("%Y/%m/%d")
    day.mkdir(parents=True, exist_ok=True)
    for name, frame in (("records", recs), ("freshness", fresh), ("conflicts", conflicts)):
        p = day / f"{stamp}_{name}.jsonl"
        if p.exists():
            raise FileExistsError(p)
        frame.to_json(p, orient="records", lines=True, date_format="iso", default_handler=str)
    (day / f"{stamp}_teams.json").write_text(teams_s.to_json(orient="records", indent=1))
    # P-ROSTER-1 team state at this snapshot (expected rotation + continuity inputs):
    # the archived T-7d / T-72h / T-24h / T-6h states for game-1 evaluation
    from cbb_edge.rosters import overlay, rotation

    try:
        rot = overlay.expected_rotation(recs, season, teams_s)
        cont = overlay.continuity(rot, season)
        conf = teams_s.set_index("team_id")["roster_confidence"] if len(teams_s) else {}
        state = []
        for t, x in rot.groupby("team_id"):
            c = cont[cont["team_id"] == t].iloc[0].to_dict() if (cont["team_id"] == t).any() else {}
            state.append({
                "team_id": t, "as_of": now.isoformat(), "roster_confidence": conf.get(t, "UNKNOWN"),
                **{k: v for k, v in c.items() if k != "team_id"},
                "expected_rotation": [
                    {"player_id": q, "share": round(float(v), 4), "class": cl,
                     "minutes": round(float(mi), 1), "p_rotation": float(pr),
                     "expected_starter": bool(es), "usage_role": ur}
                    for q, v, cl, mi, pr, es, ur in zip(
                        x["player_id"], x["share"], x["classification"], x["minutes"],
                        x["p_rotation"], x["expected_starter"], x["usage_role"], strict=True)
                ],
            })  # fmt: skip
        (day / f"{stamp}_proster_state.json").write_text(json.dumps(state, default=str))
        audit = overlay.continuity_audit(cont, dict(conf), season)
        (day / f"{stamp}_continuity_audit.json").write_text(json.dumps(audit, indent=1))
        gone = recs[recs["status"].eq("STALE") & recs["player_id"].notna()]
        sanity = rotation.sanity(
            rot, departed=set(zip(gone["team_id"], gone["player_id"], strict=True)),
            exhausted=set(hist.loc[hist["d1_seasons"] >= 5, "player_id"]) if "d1_seasons" in hist else set(),
        )  # fmt: skip
        sanity.to_json(day / f"{stamp}_rotation_sanity.jsonl", orient="records", lines=True)
    except Exception as e:  # noqa: BLE001  the truth snapshot itself is already written
        (day / f"{stamp}_proster_state.error.txt").write_text(repr(e)[:2000])
    new_keys = 0
    if prev_state is not None and len(prev_state):
        old = set(zip(prev_state["player_id"], prev_state["team_id"], strict=True))
        ided = recs[recs["player_id"].notna()]  # unidentified names are never in the state
        new_keys = sum(
            1 for k in zip(ided["player_id"], ided["team_id"], strict=True) if k not in old
        )
    st = recs[["player_id", "team_id", "first_seen", "last_confirmed"]].dropna(subset=["player_id"])
    state_p.parent.mkdir(parents=True, exist_ok=True)
    state_p.write_text(st.to_json(orient="records"))
    # official pages: discovery report, page freshness, parsed rows, raw evidence
    od = archive / "official" / now.strftime("%Y/%m/%d")
    od.mkdir(parents=True, exist_ok=True)
    disc = official.discovery_report(found)
    (od / f"{stamp}_discovery.json").write_text(json.dumps(disc, indent=1, default=str))
    if len(pages):
        pages.to_json(od / f"{stamp}_pages.jsonl", orient="records", lines=True)
    if len(orows):
        orows.to_json(od / f"{stamp}_rows.jsonl", orient="records", lines=True,
                      default_handler=str)  # fmt: skip
    ost_p.parent.mkdir(parents=True, exist_ok=True)
    ost_p.write_text(json.dumps(official.save_evidence(found, archive, stamp, ostate), indent=1))
    # roster change events vs the previous snapshot (append-only)
    ev = events.diff(stamp, recs, teams_s, fresh, *prev_snap)
    evp = archive / "events" / now.strftime("%Y") / f"{stamp}_events.jsonl"
    evp.parent.mkdir(parents=True, exist_ok=True)
    evp.write_text("".join(json.dumps(e, default=str) + "\n" for e in ev))
    rep = quality_report(df, fresh, recs, conflicts, teams_s, new_keys, stamp)
    rep["official"] = {k: v for k, v in disc.items() if k not in ("not_found", "redirects")}
    rep["official"]["page_status"] = (
        pages["page_status"].value_counts().to_dict() if len(pages) else {}
    )
    rep["official"]["identity"] = orows["identity"].value_counts().to_dict() if len(orows) else {}
    rep["events"] = pd.Series([e["event"] for e in ev]).value_counts().to_dict() if ev else {}
    rp = archive / "reports" / f"roster_quality_{stamp}.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(rep, indent=1, default=str))
    return rep


def latest_snapshot(
    archive: Path, before: str
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Records, teams and freshness of the newest truth snapshot older than ``before``."""
    snaps = sorted(
        f for f in (archive / "truth").rglob("*_records.jsonl") if f.name.split("_")[0] < before
    )
    if not snaps:
        return None, None, None
    f = snaps[-1]
    stamp = f.name.split("_")[0]
    recs = pd.read_json(f, lines=True, dtype={"player_id": str, "team_id": str})
    tp, fp = f.with_name(f"{stamp}_teams.json"), f.with_name(f"{stamp}_freshness.jsonl")
    teams = pd.read_json(tp) if tp.exists() else None
    fresh = pd.read_json(fp, lines=True) if fp.exists() else None
    return recs, teams, fresh


def quality_report(df, fresh, recs, conflicts, teams_s, new_keys, stamp) -> dict[str, Any]:
    by_src = {}
    for src, f in fresh.groupby("source"):
        by_src[src] = {
            "teams": int(f["team_id"].nunique()),
            "teams_current": int(f["fresh"].sum()),
            "teams_stale": int((~f["fresh"]).sum()),
            "stale_reasons": f.loc[~f["fresh"], "reason"].value_counts().to_dict(),
            "players": int((df["source"] == src).sum()),
        }
    return {
        "stamp": stamp,
        "sources": by_src,
        "players_by_status": recs["status"].value_counts().to_dict() if len(recs) else {},
        "classification": recs.loc[recs["status"].isin(["CONFIRMED", "LIKELY"]), "classification"]
        .value_counts()
        .to_dict()
        if len(recs)
        else {},
        "class_label_conflicts": int(recs["class_label_conflict"].sum()) if len(recs) else 0,
        "conflicts": int(len(conflicts)),
        "conflicts_by_kind": conflicts["kind"].value_counts().to_dict() if len(conflicts) else {},
        "unresolved_transfers": int((recs["status"] == "CONFLICTED").sum()) if len(recs) else 0,
        "unresolved_identities": int((recs["status"] == "UNKNOWN").sum()) if len(recs) else 0,
        "teams_by_confidence": teams_s["roster_confidence"].value_counts().to_dict()
        if len(teams_s)
        else {},
        "new_player_team_keys_since_last": int(new_keys),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    ap.add_argument("--season", type=int, default=2027)
    a = ap.parse_args()
    print(json.dumps(run(Path(a.archive), a.season), default=str))


if __name__ == "__main__":
    main()
