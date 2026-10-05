"""Official athletics roster capture across the D-I universe (Wave 7).

For every VERIFIED team in the NCAA-derived domain registry: discover the men's
basketball roster page (``discovery``), parse it (``parsers``), and return one row per
listed player plus a per-team discovery record. Requests are polite by construction:
per-host spacing >= 5 s in the chokepoint, robots.txt checked, at most a handful of
pages per site, and a site whose roster URL is already known costs one page request.
Workers run in parallel only ACROSS hosts.

Also here, because they need the parsed pages:

* ``page_freshness``  CURRENT / PROBABLY_CURRENT / STALE / UNKNOWN per official page
                      (rules preregistered in research/hypotheses/WAVE7.md);
* ``evidence``        gzip copies of raw pages whose parsed content changed.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from cbb_edge.data import cost_policy
from cbb_edge.rosters import discovery, truth

WORKERS = 12
FRESH_PAGE = ("CURRENT", "PROBABLY_CURRENT")


def load_registry(path: Path | None = None) -> dict[str, Any]:
    p = path or Path(os.environ.get("CBB_DOMAIN_REGISTRY", str(cost_policy.DOMAIN_REGISTRY)))
    reg = json.loads(p.read_text())
    from cbb_edge.rosters.ncaa_directory import registry_problems

    if "checksum" in registry_problems(reg):
        raise ValueError(f"domain registry {p} was modified (checksum)")
    return reg


def capture(
    season: int,
    stamp: str,
    known: dict[str, str] | None = None,
    teams: list[str] | None = None,
    registry: dict[str, Any] | None = None,
) -> list[discovery.Discovery]:
    reg = registry or load_registry()
    rows = [r for r in reg["teams"] if r["status"] == "VERIFIED" and r["team_id"]]
    if teams:
        rows = [r for r in rows if r["team_id"] in set(teams)]

    def one(r: dict[str, Any]) -> discovery.Discovery:
        return discovery.discover(r["team_id"], r["athletics_url"], season, stamp,
                                  (known or {}).get(r["team_id"]))  # fmt: skip

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(one, rows))


def official_rows(found: list[discovery.Discovery]) -> list[dict[str, Any]]:
    out = []
    for d in found:
        if not d.players:
            continue
        cap = (d.page_meta or {}).get("retrieved_at")
        for p in d.players:
            out.append({
                "source": "school_site", "captured_at": cap, "team_id": d.team_id,
                "player_id": None, "name": p["name"], "jersey": p.get("jersey"),
                "position": p.get("position"), "class_label": p.get("class_label"),
                "height_in": p.get("height_in"), "previous_school": p.get("previous_school"),
                "hometown": p.get("hometown"), "profile_url": p.get("profile_url"),
                "source_url": d.roster_url, "source_season": d.season_label,
                "platform": d.platform,
            })  # fmt: skip
    return out


def page_freshness(
    off: pd.DataFrame, exp: pd.DataFrame, target: int, discoveries: list[discovery.Discovery]
) -> pd.DataFrame:
    """Per official page. ``off``: resolved official rows (team_id, player_id).

    * STALE             season label older than the target season, or more than
                        ``truth.EXHAUSTED_LISTED_MAX`` listed players already played
                        ``truth.EXHAUSTED_SEASONS`` D-I seasons;
    * CURRENT           season label = target season (and not STALE);
    * PROBABLY_CURRENT  no season label, but >= 1 listed player whose 2025-26 D-I team
                        was a DIFFERENT team (an incoming transfer: a 2025-26 page
                        cannot list him) and not STALE;
    * UNKNOWN           otherwise (not used as fresh evidence).
    """
    e = exp.set_index("player_id") if "player_id" in exp else exp
    rows = []
    for d in discoveries:
        if not d.players:
            continue
        x = off[(off["team_id"] == d.team_id) & off["player_id"].notna()]
        ids = [p for p in x["player_id"] if p in e.index]
        seas = e.loc[ids, "d1_seasons"] if ids else pd.Series(dtype=float)
        exhausted = int((seas >= truth.EXHAUSTED_SEASONS).sum())
        last_t = e.loc[ids, "last_team"] if ids else pd.Series(dtype=object)
        last_s = e.loc[ids, "last_season"] if ids else pd.Series(dtype=float)
        incoming = int(((last_t != d.team_id) & (last_s == target - 1)).sum())
        lbl = d.season_label
        if (lbl is not None and lbl < target) or exhausted > truth.EXHAUSTED_LISTED_MAX:
            st = "STALE"
            why = f"season_label_{lbl}" if lbl is not None and lbl < target else "exhausted"
        elif lbl == target:
            st, why = "CURRENT", "season_label_current"
        elif lbl is None and incoming >= 1:
            st, why = "PROBABLY_CURRENT", "incoming_transfer_listed"
        else:
            st, why = "UNKNOWN", "no_label_no_new_player_evidence"
        rows.append({"team_id": d.team_id, "page_status": st, "page_reason": why,
                     "season_label": lbl, "exhausted_listed": exhausted,
                     "incoming_transfers_listed": incoming, "n_listed": len(d.players),
                     "roster_url": d.roster_url, "platform": d.platform})  # fmt: skip
    return pd.DataFrame(rows)


def content_hash(players: list[dict[str, Any]]) -> str:
    key = sorted((p["name"], str(p.get("jersey")), str(p.get("class_label"))) for p in players)
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()


def save_evidence(found: list[discovery.Discovery], archive: Path, stamp: str,
                  prev: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    """Gzip the raw page when the parsed roster changed (append-only); returns the new
    per-team official state (roster URL, platform, content hash, last change)."""
    state = dict(prev)
    for d in found:
        old = prev.get(d.team_id, {})
        if not d.players or d.page_path is None:
            state[d.team_id] = {**old, "last_attempt": stamp, "error": d.error}
            continue
        h = content_hash(d.players)
        changed = h != old.get("content_hash")
        if changed:
            p = archive / "official" / "pages" / stamp[:8] / f"{stamp}_{d.team_id}.html.gz"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(gzip.compress(Path(d.page_path).read_bytes()))
        state[d.team_id] = {
            "roster_url": d.roster_url, "platform": d.platform, "content_hash": h,
            "last_change": stamp if changed else old.get("last_change"),
            "last_attempt": stamp, "error": None,
        }  # fmt: skip
    return state


def discovery_report(found: list[discovery.Discovery]) -> dict[str, Any]:
    df = pd.DataFrame([{k: v for k, v in asdict(d).items() if k not in ("players", "page_meta")}
                       | {"n_players": len(d.players)} for d in found])  # fmt: skip
    if df.empty:
        return {"teams": 0}
    ok = df["roster_url"].notna()
    return {
        "teams": int(len(df)),
        "roster_pages_found": int(ok.sum()),
        "by_platform": df.loc[ok, "platform"].value_counts().to_dict(),
        "by_method": df.loc[ok, "method"].value_counts().to_dict(),
        "requests": int(df["requests"].sum()),
        "not_found": df.loc[
            ~ok, ["team_id", "base_url", "platform", "error", "redirect_to"]
        ].to_dict(orient="records"),
        "redirects": {
            r.team_id: [{"from": r.base_url, "to": r.redirect_to, "observed_at": None}]
            for r in df.itertuples()
            if r.redirect_to
        },
    }
