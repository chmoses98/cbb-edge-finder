"""Wave 6 roster truth: precedence rules, identity, experience, school-site parsing."""

from __future__ import annotations

import pandas as pd

from cbb_edge.rosters import school_sites, truth

CFG = truth.TruthConfig(target_season=2027)
NOW = pd.Timestamp("2026-10-06T12:00:00Z")


def _row(src, team, pid, name, season, ts="2026-10-05T12:00:00Z", cls=None):
    return {"source": src, "captured_at": ts, "team_id": team, "player_id": pid, "name": name,
            "source_season": season, "class_label": cls}  # fmt: skip


def _exp():
    pg = pd.DataFrame(
        {
            "season": [2026, 2026, 2025],
            "game_id": [1, 2, 3],
            "team_id": ["T1", "T9", "T1"],
            "player_id": ["P1", "P2", "P3"],
            "min": [30.0, 25.0, 10.0],
            "available_at": pd.to_datetime(["2026-01-01", "2026-01-02", "2025-01-01"], utc=True),
        }
    )
    return truth.experience(pg, 2027)


def test_stale_label_and_copy_detection():
    rows = truth.rows_frame(
        [
            _row("espn_site", "T1", "P1", "A One", 2026),  # stale label
            _row("espn_core", "T2", "P5", None, 2027),  # identical to last season -> copy
            _row("espn_core", "T3", "P6", None, 2027),
        ]
    )
    f = truth.team_freshness(rows, 2027, {"T2": {"P5"}, "T3": {"P7"}}).set_index(
        ["source", "team_id"]
    )
    assert f.loc[("espn_site", "T1"), "reason"] == "season_label_2026"
    assert f.loc[("espn_core", "T2"), "reason"] == "copy_of_previous_season"
    assert bool(f.loc[("espn_core", "T3"), "fresh"])


def test_same_feed_newer_capture_supersedes_and_cross_feed_conflict_flags():
    rows = truth.rows_frame(
        [
            _row("sdv_rosters", "T1", "P2", "Bee Two", 2027, ts="2026-09-15T08:00:00Z"),
            _row("espn_site", "T2", "P2", "Bee Two", 2027, ts="2026-10-05T12:00:00Z"),
            _row("espn_site", "T3", "P4", "Dee Four", 2027),
            _row("school_site", "T4", None, "Dee Four", 2027),
            _row("espn_site", "T4", "P8", "Other Guy", 2027),
        ]
    )
    f = truth.team_freshness(rows, 2027)
    t, conf = truth.resolve(rows, f, _exp(), CFG, NOW)
    st = t.set_index(["player_id", "team_id"])["status"]
    # same feed, later capture: moved, not a conflict
    assert st[("P2", "T2")] == "LIKELY" and st[("P2", "T1")] == "STALE"
    # the official T4 row has no unique ESPN match on T4 -> never fuzzy-matched
    assert "UNKNOWN" in set(t["status"])
    assert conf.empty


def test_official_exact_name_match_confirms_and_conflict_across_groups():
    rows = truth.rows_frame(
        [
            _row("espn_site", "T1", "P1", "José  Núñez Jr.", 2027),
            _row("school_site", "T1", None, "Jose Nunez", 2027),
            _row("espn_site", "T5", "P9", "Kay Nine", 2027),
            _row("school_site", "T6", None, "Kay Nine", 2027),
            _row("espn_site", "T6", "P9", "Kay Nine", 2027, ts="2026-10-05T11:00:00Z"),
        ]
    )
    t, conf = truth.resolve(rows, truth.team_freshness(rows, 2027), _exp(), CFG, NOW)
    st = t.set_index(["player_id", "team_id"])["status"]
    assert st[("P1", "T1")] == "CONFIRMED"  # ESPN + official agree (accents/suffix normalized)
    # P9: latest ESPN capture says T5, the school says T6 -> CONFLICTED on both, kept
    assert st[("P9", "T5")] == "CONFLICTED" and st[("P9", "T6")] == "CONFLICTED"
    assert len(conf) == 2


def test_experience_is_observed_not_labelled():
    rows = truth.rows_frame(
        [
            _row("espn_site", "T1", "P1", "A One", 2027, cls="FR"),  # FR label, played 2026
            _row("espn_site", "T1", "P2", "Bee Two", 2027),  # last team T9 -> transfer
            _row("espn_site", "T1", "P3", "Cee Three", 2027),  # gap since 2025
            _row("espn_site", "T1", "P4", "Dee Four", 2027, cls="FR"),  # no history
        ]
    )
    t, _ = truth.resolve(rows, truth.team_freshness(rows, 2027), _exp(), CFG, NOW)
    c = t.set_index("player_id")
    assert c.loc["P1", "classification"] == "returning" and bool(
        c.loc["P1", "class_label_conflict"]
    )
    assert c.loc["P2", "classification"] == "transfer"
    assert c.loc["P3", "classification"] == "returning_after_gap"
    assert c.loc["P4", "classification"] == "first_d1" and not bool(
        c.loc["P4", "class_label_conflict"]
    )


def test_state_carries_first_seen_forward():
    rows = truth.rows_frame([_row("espn_site", "T1", "P1", "A One", 2027)])
    prev = pd.DataFrame({"player_id": ["P1"], "team_id": ["T1"],
                         "first_seen": ["2026-09-01T00:00:00+00:00"],
                         "last_confirmed": ["2026-09-01T00:00:00+00:00"]})  # fmt: skip
    t, _ = truth.resolve(rows, truth.team_freshness(rows, 2027), _exp(), CFG, NOW, prev)
    assert t["first_seen"].iloc[0] == "2026-09-01T00:00:00+00:00"
    assert t["last_confirmed"].iloc[0] == NOW.isoformat()


SIDEARM = """<h1>2026-27 Men's Basketball Roster</h1>
<div class="s-person-card s-person-card--list flex"><span data-test-id="x" class="sr-only">
Jersey Number</span> 3<!--]--></span><h3>Ann Guard</h3><span class="s-person-details__bio-stats-item">
<span class="sr-only">Position</span> G </span><span class="x"><span class="sr-only">Academic Year</span>
 So.</span><span class="x"><span class="sr-only">Height</span> 6&#39; 2&#39;&#39; </span>
<span class="x"><span class="sr-only">Last School</span> Some HS</span></div>
<div class="s-person-card s-person-card--standard">staff</div>
<div class="s-person-card s-person-card--list"><h3>Coach Person</h3></div>"""


def test_sidearm_parser_players_only_and_season():
    rows = school_sites.parse_sidearm(SIDEARM)
    assert school_sites.season_label(SIDEARM) == 2027
    assert len(rows) == 1
    r = rows[0]
    assert (r["name"], r["jersey"], r["position"], r["class_label"]) == (
        "Ann Guard",
        "3",
        "G",
        "So.",
    )
    assert r["height_in"] == 74.0 and r["previous_school"] == "Some HS"
