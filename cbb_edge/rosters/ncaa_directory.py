"""NCAA Membership Directory ingestion (Wave 7): the D-I men's basketball universe and
the official athletics-domain registry.

Data path (found by reading the directory web app's own script bundle,
``samples/ncaa_directory`` on the roster-source-samples branch): the public page
https://web3.ncaa.org/directory/ calls the unauthenticated JSON endpoint

    https://web3.ncaa.org/directory/api/directory/memberList?type=12&division=I&sportCode=MBB

which returns every Division I member that sponsors men's basketball in the current
academic year (``academicYear`` 2027 = 2026-27), with conference, reclassification
fields and the institution's official ``athleticWebUrl`` ("Athletics Link"). robots.txt
does not disallow /directory/. One request per refresh, cached, through the
``ncaa_directory`` source (2 s spacing). Refresh weekly September-November, monthly
otherwise (``official-rosters.yml``); never per projection run.

Reconciliation to canonical teams (``cbb_edge/data/ids/teams.csv``) is exact only:

* ``exact_name``: one normalized form of the official name (leading "the",
  "university of", trailing "university"/"college" removed) equals exactly one current
  team's ESPN location;
* ``verified_alias``: ``models/rosters/ncaa_team_aliases.csv``, keyed by NCAA org id,
  each row checked by hand (official name, ESPN name and athletics domain shown);
* anything else is reported, never guessed.

The registry (``models/rosters/ncaa_athletics_domains.json``) is checksum-pinned and is
the ONLY source of official school hosts for the cost policy
(``cost_policy.SCHOOL_HOSTS``). A host that two unrelated schools share is an exception,
not verified. A redirect observed from an NCAA Athletics Link to another host (recorded
by roster discovery, ``redirects``) adds that host to the school's row, with evidence.
Wave 8: so does a men's basketball roster link on the Athletics Link HOME page to
another host (``linked``), when ``linked_host_ok`` holds (preregistered in
research/hypotheses/WAVE8.md): the linked host's second-level label contains the
registered host's second-level label (>= 5 characters, e.g. sundevils.com ->
thesundevils.com) and the host is not registered to any other member.

    python -m cbb_edge.rosters.ncaa_directory --out <archive dir> [--write-models]
                                              [--redirects <discovery report json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

from cbb_edge.data.http import fetch
from cbb_edge.data.ids.teams import normalize

REPO = Path(__file__).resolve().parents[2]
TEAMS = REPO / "cbb_edge" / "data" / "ids" / "teams.csv"
ALIASES = REPO / "models" / "rosters" / "ncaa_team_aliases.csv"
REGISTRY = REPO / "models" / "rosters" / "ncaa_athletics_domains.json"
UNIVERSE = REPO / "models" / "rosters" / "ncaa_d1_mbb_universe.csv"
MEMBER_LIST = "https://web3.ncaa.org/directory/api/directory/memberList"
PARAMS = {"type": "12", "division": "I", "sportCode": "MBB"}


def fetch_members(stamp: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    r = fetch("ncaa_directory", MEMBER_LIST, PARAMS, dest=f"memberList/{stamp}.json",
              timeout=60, headers={"Accept": "application/json"})  # fmt: skip
    assert r is not None
    return r.json(), r.meta


def name_keys(name: str) -> set[str]:
    n = normalize(name)
    a = re.sub(r"^the ", "", n)
    return {
        n,
        a,
        re.sub(r"^university of (the )?", "", a),
        re.sub(r" university$", "", a),
        re.sub(r" college$", "", a),
    }


def athletics_url(raw: str | None) -> tuple[str | None, str | None]:
    """Normalized https URL and host (``www.`` stripped) of an Athletics Link."""
    if not raw or not str(raw).strip():
        return None, None
    u = str(raw).strip()
    u = "https:" + u if u.startswith("//") else u
    u = u if re.match(r"^https?://", u, flags=re.I) else "https://" + u
    host = (urlsplit(u).hostname or "").lower()
    if not host or "." not in host:
        return None, None
    return u, host.removeprefix("www.")


def current_teams(teams: pd.DataFrame | None = None) -> pd.DataFrame:
    t = pd.read_csv(TEAMS, dtype={"team_id": str}) if teams is None else teams
    return t[t["last_d1_season"] >= t["last_d1_season"].max() - 1].copy()


def reconcile(
    members: list[dict[str, Any]],
    teams: pd.DataFrame | None = None,
    aliases: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Universe crosswalk (one row per NCAA member) and the reconciliation report."""
    t = current_teams(teams)
    al = pd.read_csv(ALIASES, dtype={"team_id": str}) if aliases is None else aliases
    alias = dict(zip(al["ncaa_org_id"].astype(int), al["team_id"], strict=True))
    loc: dict[str, list[str]] = {}
    for x, tid in zip(t["espn_location"], t["team_id"], strict=True):
        loc.setdefault(normalize(x), []).append(tid)
    rows = []
    for m in members:
        org = int(m["orgId"])
        hits = {tid for k in name_keys(m["nameOfficial"]) for tid in loc.get(k, [])}
        if org in alias:
            tid, method = alias[org], "verified_alias"
            if hits and hits != {tid}:
                method = "alias_conflicts_exact_name"
        elif len(hits) == 1:
            tid, method = hits.pop(), "exact_name"
        else:
            tid, method = None, "ambiguous_name" if hits else "unresolved"
        url, host = athletics_url(m.get("athleticWebUrl"))
        rows.append({
            "ncaa_org_id": org, "team_id": tid, "school": m["nameOfficial"].strip(),
            "division": m.get("divisionRoman") or m.get("division"),
            "academic_year": m.get("academicYear"),
            "conference": (m.get("conferenceName") or "").strip() or None,
            "state": (m.get("memberOrgAddress") or {}).get("state"),
            "reclass_year": m.get("reclassYear"), "reclass_division": m.get("reclassDivision"),
            "provisional_member": bool(m.get("provisionalMember")),
            "athletics_url": url, "athletics_host": host,
            "mbb_sponsored": True,  # listed by the sportCode=MBB member query
            "resolution": method,
        })  # fmt: skip
    u = pd.DataFrame(rows)
    u = u.merge(
        t[["team_id", "espn_team_id", "espn_location", "conference_latest", "first_d1_season"]],
        on="team_id",
        how="left",
    )
    u["resolution_confidence"] = (
        u["resolution"].map({"exact_name": "HIGH", "verified_alias": "HIGH"}).fillna("UNRESOLVED")
    )
    mapped = set(u["team_id"].dropna())
    dup = u["team_id"].dropna()
    rep = {
        "ncaa_members": int(len(u)),
        "model_current_teams": int(len(t)),
        "resolved": int(u["team_id"].notna().sum()),
        "by_method": u["resolution"].value_counts().to_dict(),
        "in_model_not_ncaa": t.loc[~t["team_id"].isin(mapped), ["team_id", "espn_team_id",
                               "espn_location", "conference_latest", "last_d1_season"]]
        .to_dict(orient="records"),  # fmt: skip
        "in_ncaa_not_model": u.loc[u["team_id"].isna(), ["ncaa_org_id", "school", "conference",
                                   "state", "athletics_url", "resolution"]]
        .to_dict(orient="records"),  # fmt: skip
        "duplicate_team_mappings": sorted(set(dup[dup.duplicated()])),
        "reclassifying": u.loc[
            u["reclass_year"].notna() | u["provisional_member"] | (u["first_d1_season"] >= 2024),
            ["ncaa_org_id", "school", "team_id", "first_d1_season", "reclass_year",
             "reclass_division", "provisional_member"],
        ].to_dict(orient="records"),  # fmt: skip
        "naming_differences": u.loc[u["resolution"] == "verified_alias",
                                    ["ncaa_org_id", "school", "espn_location"]]
        .to_dict(orient="records"),  # fmt: skip
        "unresolved": u.loc[~u["resolution"].isin(["exact_name", "verified_alias"]),
                            ["ncaa_org_id", "school", "resolution"]].to_dict(orient="records"),
        "conference_label_differences": int(
            (u["conference"].map(_conf) != u["conference_latest"].map(_conf))
            .loc[u["team_id"].notna()].sum()
        ),
    }  # fmt: skip
    return u, rep


def _conf(s: object) -> str:
    return normalize(str(s or "")).replace(" conference", "").replace(" conf", "")


def _sld(host: str) -> str:
    parts = host.lower().removeprefix("www.").split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def linked_host_ok(registered: str, linked: str) -> bool:
    """A roster link from the official home page to ``linked`` may add ``linked`` to the
    school's hosts: its second-level label contains the registered one (>= 5 chars)."""
    a, b = _sld(registered), _sld(linked)
    return len(a) >= 5 and a in b and registered.lower() != linked.lower()


def _hosts_of(ev: list[dict[str, Any]], own: str) -> list[str]:
    return sorted({(urlsplit(x["to"]).hostname or "").lower().removeprefix("www.")
                   for x in ev} - {own, ""})  # fmt: skip


def build_registry(
    u: pd.DataFrame,
    retrieved_at: str,
    source_url: str,
    redirects: dict[str, list[dict[str, str]]] | None = None,
    linked: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Official athletics-domain registry rows (one per NCAA member). ``redirects``:
    team_id -> [{"from": url, "to": url, "observed_at": ts}] observed by discovery;
    ``linked``: the same for home-page roster links to another host (Wave 8)."""
    host_n = u["athletics_host"].value_counts()
    taken = set(u["athletics_host"].dropna())
    rows = []
    for r in u.sort_values("ncaa_org_id").itertuples(index=False):
        if r.athletics_host is None:
            status, why = "EXCEPTION", "no_athletics_link"
        elif host_n[r.athletics_host] > 1:
            status, why = "EXCEPTION", "host_shared_by_several_members"
        elif r.team_id is None or pd.isna(r.team_id):
            status, why = "VERIFIED_UNMAPPED", "no_canonical_team"
        else:
            status, why = "VERIFIED", None
        rd = (redirects or {}).get(str(r.team_id), [])
        lk = [e for e in (linked or {}).get(str(r.team_id), [])
              if r.athletics_host and linked_host_ok(r.athletics_host,
                                                     urlsplit(e["to"]).hostname or "")
              and (urlsplit(e["to"]).hostname or "").lower().removeprefix("www.") not in taken]  # fmt: skip
        extra = {}
        if lk:
            extra = {"linked_hosts": _hosts_of(lk, r.athletics_host), "linked_evidence": lk}
        rows.append({
            "team_id": None if pd.isna(r.team_id) else r.team_id,
            "ncaa_org_id": int(r.ncaa_org_id), "school": r.school,
            "espn_team_id": None if pd.isna(r.espn_team_id) else int(r.espn_team_id),
            "athletics_url": r.athletics_url, "host": r.athletics_host,
            "redirect_hosts": sorted({(urlsplit(x["to"]).hostname or "").lower()
                                      .removeprefix("www.") for x in rd} - {r.athletics_host}),
            "redirect_evidence": rd,
            **extra,
            "status": status, "exception": why,
            "retrieved_at": retrieved_at, "source_url": source_url,
        })  # fmt: skip
    body = {
        "generated_by": "cbb_edge.rosters.ncaa_directory",
        "source": "NCAA Membership Directory, Athletics Link (athleticWebUrl)",
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "academic_year": int(u["academic_year"].dropna().max()) if len(u) else None,
        "teams": rows,
    }
    body["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def registry_problems(reg: dict[str, Any]) -> list[str]:
    """Structural checks (also run by tests): checksum, valid hosts, no host for two
    unrelated schools without an exception, every current team covered or excepted."""
    out = []
    body = {k: v for k, v in reg.items() if k != "sha256"}
    if reg.get("sha256") != hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest():
        out.append("checksum")
    owner: dict[str, str] = {}
    for r in reg["teams"]:
        for h in [r["host"], *r.get("redirect_hosts", []), *r.get("linked_hosts", [])]:
            if h is None:
                continue
            if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", h):
                out.append(f"invalid_host:{h}")
            if r["status"] == "VERIFIED" and owner.setdefault(h, r["team_id"]) != r["team_id"]:
                out.append(f"host_two_schools:{h}")
    return out


def is_due(latest_stamp: str, now: datetime) -> bool:
    """Weekly September-November, monthly otherwise. Stamps look like 20261005T212117Z
    (pandas reads the Z as UTC, so the parsed stamp is already tz-aware)."""
    ts = pd.Timestamp(latest_stamp)
    ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    age = pd.Timestamp(now).tz_convert("UTC") - ts
    return age.days >= (7 if now.month in (9, 10, 11) else 28)


def _redirect_hosts(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    return {(str(r.get("team_id")), h) for r in json.loads(path.read_text()).get("teams", [])
            for h in [*r.get("redirect_hosts", []), *r.get("linked_hosts", [])]}  # fmt: skip


def _report_hosts(report: Path | None) -> set[tuple[str, str]]:
    if report is None or not Path(report).exists():
        return set()
    rep = json.loads(Path(report).read_text())
    out = set()
    for kind in ("redirects", "linked"):
        for t, ev in (rep.get(kind) or {}).items():
            for e in ev:
                if isinstance(e.get("to"), str):
                    out.add((str(t), (urlsplit(e["to"]).hostname or "").lower()
                             .removeprefix("www.")))  # fmt: skip
    return out


def missing_evidence(out: Path, report: Path | None = None) -> bool:
    """The committed registry or the latest discovery report carries redirect / linked
    evidence the archived registry lacks: regenerate now (otherwise the archived
    registry would override it, or new evidence would wait for the next refresh)."""
    have = _redirect_hosts(out / "ncaa_directory" / "latest_registry.json")
    own = {
        (str(r.get("team_id")), r.get("host")) for r in json.loads(REGISTRY.read_text())["teams"]
    }
    return bool((_redirect_hosts(REGISTRY) | (_report_hosts(report) - own)) - have)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="archive directory (append-only)")
    ap.add_argument("--write-models", action="store_true", help="refresh committed artifacts")
    ap.add_argument("--redirects", help="discovery report with observed redirects")
    ap.add_argument("--if-due", action="store_true",
                    help="skip unless the newest snapshot is older than 7 days (Sep-Nov) "
                    "or 28 days (otherwise)")  # fmt: skip
    a = ap.parse_args()
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    snaps = sorted((Path(a.out) / "ncaa_directory").glob("2*"))
    if a.if_due and snaps:
        if not is_due(snaps[-1].name, now) and not missing_evidence(
            Path(a.out), Path(a.redirects) if a.redirects else None
        ):
            print(json.dumps({"skipped": True, "latest": snaps[-1].name}))
            return
    members, meta = fetch_members(stamp)
    u, rep = reconcile(members)
    # redirect evidence carries forward: the committed registry, the newest archived
    # registry, then the newest discovery report (latest observation last)
    redirects: dict[str, list[dict[str, str]]] = {}
    linked: dict[str, list[dict[str, Any]]] = {}
    prev_regs = [REGISTRY, Path(a.out) / "ncaa_directory" / "latest_registry.json"]
    for pr in prev_regs:
        if pr.exists():
            for r in json.loads(pr.read_text()).get("teams", []):
                if r.get("team_id") and r.get("redirect_evidence"):
                    redirects[r["team_id"]] = r["redirect_evidence"]
                if r.get("team_id") and r.get("linked_evidence"):
                    linked[r["team_id"]] = r["linked_evidence"]
    if a.redirects and Path(a.redirects).exists():
        rep_d = json.loads(Path(a.redirects).read_text())
        for kind, into in (("redirects", redirects), ("linked", linked)):
            for t, ev in (rep_d.get(kind) or {}).items():
                ok = [e for e in ev if isinstance(e.get("to"), str)]
                if ok:
                    into[t] = ok
    src = MEMBER_LIST + "?" + "&".join(f"{k}={v}" for k, v in PARAMS.items())
    reg = build_registry(u, meta["retrieved_at"], src, redirects, linked)
    rep["registry_problems"] = registry_problems(reg)
    rep["registry_status"] = pd.Series([r["status"] for r in reg["teams"]]).value_counts().to_dict()
    out = Path(a.out) / "ncaa_directory" / stamp
    out.mkdir(parents=True, exist_ok=False)
    (out / "members.json").write_text(json.dumps(members))
    u.to_csv(out / "universe.csv", index=False)
    (out / "registry.json").write_text(json.dumps(reg, indent=1))
    (out / "reconciliation.json").write_text(json.dumps(rep, indent=1, default=str))
    latest = Path(a.out) / "ncaa_directory" / "latest_registry.json"
    latest.write_text(json.dumps(reg, indent=1))  # pointer copy; dated snapshots are kept
    if a.write_models:
        u.to_csv(UNIVERSE, index=False)
        REGISTRY.write_text(json.dumps(reg, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if not isinstance(v, list)}, default=str))


if __name__ == "__main__":
    main()
