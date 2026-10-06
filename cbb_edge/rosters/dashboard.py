"""Daily roster confirmation scorecard (Wave 7): one Markdown page per truth snapshot
(``reports/roster_dashboard_<stamp>.md``, plus ``reports/latest_dashboard.md``) and the
same numbers as JSON inside the quality report. Every unresolved team is listed with
its reason; nothing is rounded up."""

from __future__ import annotations

from typing import Any

import pandas as pd

from cbb_edge.rosters import discovery


def scorecard(
    registry: dict[str, Any],
    found: list[discovery.Discovery],
    pages: pd.DataFrame,
    orows: pd.DataFrame,
    fresh: pd.DataFrame,
    teams: pd.DataFrame,
    universe_n: int,
) -> dict[str, Any]:
    reg = pd.DataFrame(registry["teams"])
    verified = reg[reg["status"] == "VERIFIED"]
    found_ok = {d.team_id for d in found if d.roster_url}
    cur = pages[pages["page_status"].isin(["CURRENT", "PROBABLY_CURRENT"])] if len(pages) else pages
    ids = orows["identity"] if len(orows) else pd.Series(dtype=object)
    resolved = ids.isin(["verified_alias", "exact_same_team", "exact_history",
                         "exact_espn_any_team", "no_d1_history"])  # fmt: skip
    espn = fresh[fresh["group"] == "espn"] if len(fresh) else fresh
    conf = teams["roster_confidence"].value_counts() if len(teams) else pd.Series(dtype=int)
    reasons: dict[str, str] = {}
    for r in reg.itertuples():
        if r.status != "VERIFIED":
            reasons[str(r.team_id or r.school)] = f"domain: {r.exception or r.status}"
    for d in found:
        if not d.roster_url:
            why = d.error or "roster_not_found"
            reasons[d.team_id] = (
                f"roster page: {why}"
                + (f" (redirects to {d.redirect_to})" if d.redirect_to else "")
                + (f" (official link to unregistered {d.linked_to})"
                   if getattr(d, "linked_to", None) else "")
            )  # fmt: skip
    if len(pages):
        for r in pages[~pages["page_status"].isin(["CURRENT", "PROBABLY_CURRENT"])].itertuples():
            reasons.setdefault(r.team_id, f"official page {r.page_status}: {r.page_reason}")
    if len(teams):
        for r in teams[~teams["roster_confidence"].isin(["CONFIRMED", "LIKELY"])].itertuples():
            reasons.setdefault(
                r.team_id, f"confidence {r.roster_confidence}: {r.confidence_reason}"
            )
    n = universe_n
    return {
        "total_d1_teams": n,
        "athletics_domains_verified": int(len(verified)),
        "roster_pages_found": int(len(found_ok)),
        "official_pages_current": int((pages["page_status"] == "CURRENT").sum())
        if len(pages)
        else 0,
        "official_pages_probably_current": int((pages["page_status"] == "PROBABLY_CURRENT").sum())
        if len(pages)
        else 0,
        "official_pages_fresh": int(len(cur)),
        "confidence": {
            k: int(conf.get(k, 0))
            for k in ("CONFIRMED", "LIKELY", "CONFLICTED", "STALE", "UNKNOWN")
        },  # fmt: skip
        "player_identity_match_rate": float(resolved.mean()) if len(ids) else None,
        "official_players": int(len(ids)),
        "unresolved_players": int((~resolved).sum()) if len(ids) else 0,
        "stale_espn_team_sources": int((~espn["fresh"]).sum()) if len(espn) else 0,
        "unresolved_teams": dict(sorted(reasons.items())),
    }


def markdown(sc: dict[str, Any], stamp: str) -> str:
    n = max(sc["total_d1_teams"], 1)

    def pct(k: int) -> str:
        return f"{k} ({100 * k / n:.1f}%)"

    c = sc["confidence"]
    lines = [
        f"# Roster confirmation scorecard — {stamp}",
        "",
        "| measure | value |",
        "|---|---|",
        f"| D-I men's basketball teams (NCAA directory) | {sc['total_d1_teams']} |",
        f"| official athletics domains verified | {pct(sc['athletics_domains_verified'])} |",
        f"| official roster pages found | {pct(sc['roster_pages_found'])} |",
        f"| official pages CURRENT | {pct(sc['official_pages_current'])} |",
        f"| official pages PROBABLY_CURRENT | {pct(sc['official_pages_probably_current'])} |",
        *[f"| teams {k} | {pct(c[k])} |" for k in c],
        f"| official players | {sc['official_players']} |",
        "| player identity match rate | "
        + (
            f"{100 * sc['player_identity_match_rate']:.1f}%"
            if sc["player_identity_match_rate"] is not None
            else "n/a"
        )
        + " |",  # fmt: skip
        f"| unresolved players | {sc['unresolved_players']} |",
        f"| stale ESPN team sources | {sc['stale_espn_team_sources']} |",
        "",
        f"## Teams not yet confirmed or likely ({len(sc['unresolved_teams'])})",
        "",
        *[f"* `{t}` — {why}" for t, why in sc["unresolved_teams"].items()],
    ]
    return "\n".join(lines) + "\n"
