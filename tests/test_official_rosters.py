"""Wave 7: NCAA directory registry, discovery, parsers, identity, freshness, events,
rotation allocation, and the chokepoint's per-host spacing / redirect authorization."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from cbb_edge.data import cost_policy, http
from cbb_edge.rosters import discovery, events, identity, ncaa_directory, official, rotation
from cbb_edge.rosters.parsers import parse_roster, table

REPO = Path(__file__).resolve().parents[1]


def _member(org, name, url, conf="X Conference"):
    return {"orgId": org, "nameOfficial": name, "athleticWebUrl": url, "divisionRoman": "I",
            "academicYear": 2027, "conferenceName": conf, "memberOrgAddress": {"state": "NC"},
            "reclassYear": None, "reclassDivision": None, "provisionalMember": False}  # fmt: skip


TEAMS = pd.DataFrame({
    "team_id": ["T1", "T2", "T3"], "espn_team_id": [1, 2, 3],
    "espn_location": ["Duke", "UNC", "Gone State"], "conference_latest": ["ACC"] * 3,
    "first_d1_season": [2006] * 3, "last_d1_season": [2027, 2027, 2027],
})  # fmt: skip


def test_reconcile_exact_alias_and_unresolved_reported():
    members = [
        _member(1, "Duke University", "goduke.com"),
        _member(2, "University of North Carolina, Chapel Hill", "https://goheels.com/"),
        _member(3, "New School University", "//newschool.edu"),
    ]
    al = pd.DataFrame({"ncaa_org_id": [2], "team_id": ["T2"]})
    u, rep = ncaa_directory.reconcile(members, TEAMS, al)
    m = u.set_index("ncaa_org_id")
    assert m.loc[1, "team_id"] == "T1" and m.loc[1, "resolution"] == "exact_name"
    assert m.loc[2, "team_id"] == "T2" and m.loc[2, "resolution"] == "verified_alias"
    assert pd.isna(m.loc[3, "team_id"]) and m.loc[3, "athletics_host"] == "newschool.edu"
    assert [r["team_id"] for r in rep["in_model_not_ncaa"]] == ["T3"]
    assert [r["ncaa_org_id"] for r in rep["in_ncaa_not_model"]] == [3]


def test_registry_checksum_shared_host_and_fail_closed(tmp_path):
    members = [_member(1, "Duke University", "goduke.com"),
               _member(2, "UNC", "www.goduke.com/index.html")]  # fmt: skip
    u, _ = ncaa_directory.reconcile(
        members, TEAMS, pd.DataFrame(columns=["ncaa_org_id", "team_id"])
    )
    reg = ncaa_directory.build_registry(u, "2026-10-05T00:00:00Z", "src")
    assert {r["status"] for r in reg["teams"]} == {"EXCEPTION"}  # one host, two schools
    assert ncaa_directory.registry_problems(reg) == []
    p = tmp_path / "r.json"
    p.write_text(json.dumps(reg))
    assert cost_policy.registry_hosts(p) == ()  # nothing VERIFIED
    reg["teams"][0]["status"] = "VERIFIED"  # tampering breaks the checksum -> fail closed
    p.write_text(json.dumps(reg))
    assert cost_policy.registry_hosts(p) == ()


def test_committed_registry_is_pinned_and_covers_the_universe():
    reg = json.loads((REPO / "models" / "rosters" / "ncaa_athletics_domains.json").read_text())
    assert ncaa_directory.registry_problems(reg) == []
    hosts = cost_policy.registry_hosts()
    assert len(hosts) >= 360 and cost_policy.SCHOOL_HOSTS == hosts
    rep = json.loads((REPO / "models" / "rosters" / "ncaa_reconciliation.json").read_text())
    covered = {r["team_id"] for r in reg["teams"] if r["status"] == "VERIFIED"}
    excepted = {r["team_id"] for r in rep["in_model_not_ncaa"]}
    cur = set(ncaa_directory.current_teams()["team_id"])
    assert cur - covered <= excepted  # every current team: verified domain or logged exception


def test_athletics_url_normalization():
    assert ncaa_directory.athletics_url("//lrtrojans.com") == (
        "https://lrtrojans.com",
        "lrtrojans.com",
    )
    assert ncaa_directory.athletics_url("www.gwsports.com/index.html")[1] == "gwsports.com"
    assert ncaa_directory.athletics_url("") == (None, None)


def test_roster_links_men_only_same_site_and_platform():
    html = """<a href="/sports/mens-basketball/roster">Roster</a>
    <a href="/sports/womens-basketball/roster">Roster</a>
    <a href="https://other.com/sports/mens-basketball/roster">x</a>
    <div class="s-person-card">sidearm</div>"""
    links = discovery.roster_links(html, "https://goduke.com/", "goduke.com")
    assert links == ["https://goduke.com/sports/mens-basketball/roster"]
    assert discovery.detect_platform(html) == "sidearm"
    assert discovery.season_path(2027) == "2026-27"


def test_table_parser_maps_columns_by_header_and_skips_non_rosters():
    page = (
        """<h2>2026-27 Men's Basketball Roster</h2><table><tr><th>Pos.</th><th>#</th>
    <th>Full Name</th><th>Ht.</th><th>Yr.</th></tr>"""
        + "".join(
            f"<tr><td>G</td><td>{i}</td><td>Player Number{i} Smith</td><td>6-{i % 10}</td>"
            f"<td>So.</td></tr>"
            for i in range(1, 11)
        )
        + "</table><table><tr><th>Date</th><th>Opponent</th></tr><tr><td>1</td><td>2</td></tr></table>"
    )
    r = table.parse(page, "https://x.edu/r")
    assert len(r.players) == 10 and r.season_label == 2027
    assert r.players[0]["jersey"] == "1" and r.players[0]["position"] == "G"
    assert parse_roster(page, "presto", "https://x.edu/r", 2027).platform == "presto"


IDT = pd.DataFrame({
    "player_id": ["P1", "P2", "P3", "P4"],
    "name_key": ["ann bee", "cal dee", "cal dee", "old timer"],
    "last_team": ["T9", "T8", "T7", "T1"], "last_season": [2026, 2026, 2025, 2012],
})  # fmt: skip


def test_identity_exact_unique_only_and_freshman_guards():
    off = pd.DataFrame({
        "team_id": ["T1"] * 5,
        "name": ["Ann Bee Jr.", "Cal Dee", "Eve Fay", "Gus Hal", "Old Timer"],
        "class_label": ["Sr.", "Jr.", "Fr.", "Jr.", "Fr."],
    })  # fmt: skip
    espn = pd.DataFrame(columns=["team_id", "player_id", "name"])
    o = identity.resolve(off, espn, 2027, IDT, pd.DataFrame(columns=["team_id", "official_name",
                                                                     "player_id"]))  # fmt: skip
    got = dict(zip(o["name"], zip(o["identity"], o["player_id"], strict=True), strict=True))
    assert got["Ann Bee Jr."][0] == "exact_history" and got["Ann Bee Jr."][1] == "P1"
    assert got["Cal Dee"][0] == "unresolved"  # two recent players share the name
    assert got["Eve Fay"][0] == "no_d1_history"  # freshman with no D-I trace
    assert got["Gus Hal"][0] == "unresolved"  # non-freshman with no trace: never assumed new
    # a 2012 namesake is too old to be this freshman: no recent D-I trace
    assert got["Old Timer"][0] == "no_d1_history"


def test_identity_true_freshman_matched_to_d1_minutes_is_a_conflict():
    off = pd.DataFrame({"team_id": ["T1"], "name": ["Ann Bee"], "class_label": ["FR"]})
    o = identity.resolve(off, pd.DataFrame(columns=["team_id", "player_id", "name"]), 2027, IDT,
                         pd.DataFrame(columns=["team_id", "official_name", "player_id"]))  # fmt: skip
    assert o["identity"].iloc[0] == "conflicting_identity" and pd.isna(o["player_id"].iloc[0])


def _disc(team, n, label):
    d = discovery.Discovery(team, "https://x.com", "x.com")
    d.players = [{"name": f"P {i}"} for i in range(n)]
    d.season_label = label
    return d


def test_page_freshness_rules():
    exp = pd.DataFrame({"player_id": ["A", "B", "C", "D", "E", "F"],
                        "d1_seasons": [4, 4, 4, 1, 2, 2],
                        "last_team": ["T1", "T1", "T1", "T9", "T2", "T3"],
                        "last_season": [2026] * 6})  # fmt: skip
    off = pd.DataFrame({"team_id": ["T1"] * 3 + ["T2"] * 2 + ["T3"],
                        "player_id": ["A", "B", "C", "D", "E", "F"]})  # fmt: skip
    pf = official.page_freshness(off, exp, 2027, [_disc("T1", 10, 2027), _disc("T2", 10, None),
                                                   _disc("T3", 10, None)]).set_index("team_id")  # fmt: skip
    assert pf.loc["T1", "page_status"] == "STALE"  # 3 eligibility-exhausted players listed
    assert pf.loc["T2", "page_status"] == "PROBABLY_CURRENT"  # D played 2025-26 for T9
    assert pf.loc["T3", "page_status"] == "UNKNOWN"


def test_events_added_removed_team_change_confidence():
    prev = pd.DataFrame({"player_id": ["P1", "P2"], "team_id": ["T1", "T1"],
                         "name": ["A", "B"], "status": ["LIKELY", "LIKELY"]})  # fmt: skip
    now = pd.DataFrame({"player_id": ["P1", "P2", "P3"], "team_id": ["T1", "T2", "T1"],
                        "name": ["A", "B", "C"], "status": ["CONFIRMED"] * 3})  # fmt: skip
    t0 = pd.DataFrame({"team_id": ["T1"], "roster_confidence": ["LIKELY"]})
    t1 = pd.DataFrame({"team_id": ["T1"], "roster_confidence": ["CONFIRMED"]})
    ev = events.diff("S", now, t1, pd.DataFrame(), prev, t0, None)
    kinds = sorted(e["event"] for e in ev)
    assert kinds == ["confidence_changed", "player_added", "player_added", "player_removed",
                     "player_team_changed"]  # fmt: skip
    assert events.diff("S", now, t1, pd.DataFrame(), None, None, None) == []


def test_waterfill_200_minutes_cap_40_and_sanity():
    s = rotation.waterfill(np.array([3.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.2, 0.0]), 5.0)
    assert np.isclose(s.sum(), 5.0) and s.max() <= 1.0 + 1e-12 and s[0] == 1.0 and s[-1] == 0.0
    df = pd.DataFrame({"team_id": ["T1"] * 8, "player_id": [f"P{i}" for i in range(8)],
                       "pos_g": [1, 1, 1, 0, 0, 0, 0, 0], "pos_c": [0, 0, 0, 0, 0, 1, 0, 0],
                       "share_raw": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.2, 0.1],
                       "prev_usage": [0.06] + [0.03] * 7, "first_d1": [0] * 7 + [1]})  # fmt: skip
    a = rotation.allocate(df)
    assert np.isclose(a["minutes"].sum(), 200.0) and a["expected_starter"].sum() == 5
    assert a.loc[7, "usage_role"] == "unknown" and a.loc[0, "usage_role"] == "primary"
    sc = rotation.sanity(a, departed={"P7"})
    assert not bool(sc["ok"].iloc[0]) and sc["departed_listed"].iloc[0] == 1


class _Resp:
    def __init__(self, url, status=200, location=None, body=b"ok"):
        self.url, self.status_code, self.headers = url, status, {}
        if location:
            self.headers["Location"] = location
        self.is_redirect = location is not None
        self._b = body

    def iter_content(self, n):
        yield self._b

    def raise_for_status(self):
        pass

    def close(self):
        pass


def test_redirect_to_unregistered_host_is_never_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("CBB_DATA_DIR", str(tmp_path))
    host = cost_policy.SCHOOL_HOSTS[0]
    calls = []

    def get(url, **kw):
        calls.append(url)
        return _Resp(url, 301, location="https://evil.example.com/x")

    sess = mock.Mock(get=get)
    with pytest.raises(http.RedirectNotAuthorized) as e:
        http.fetch("school_athletics", f"https://{host}/sports/mens-basketball/roster",
                   session=sess, use_cache=False)  # fmt: skip
    assert e.value.target == "https://evil.example.com/x"
    assert calls == [f"https://{host}/sports/mens-basketball/roster"]  # target not requested


def test_per_host_spacing_is_independent_across_hosts(monkeypatch):
    spec = cost_policy.SOURCES["school_athletics"]
    assert spec.per_host and spec.min_interval_s >= 5.0
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(s))
    http._last_request.clear()
    h1, h2 = cost_policy.SCHOOL_HOSTS[:2]
    http._space(spec, f"https://{h1}/a")
    http._space(spec, f"https://{h2}/a")  # other host: no wait
    assert slept == []
    http._space(spec, f"https://{h1}/b")  # same host: waits ~5 s
    assert len(slept) == 1 and slept[0] > 4.5
