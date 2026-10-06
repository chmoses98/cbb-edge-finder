"""Wave 6 roster truth: precedence rules, identity, experience, school-site parsing."""

from __future__ import annotations

import pandas as pd

from cbb_edge.rosters import truth
from cbb_edge.rosters.parsers import sidearm

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
    assert t.loc[t["status"] == "UNKNOWN", "classification"].eq("unknown").all()
    # T4's fresh official listing omits P8 -> not counted on T4, logged
    assert st[("P8", "T4")] == "STALE"
    assert set(conf["kind"]) == {"unmatched_official_name", "absent_from_official_roster"}


def test_team_level_same_feed_supersession_and_official_identity_coverage():
    rows = truth.rows_frame(
        [  # September copy lists P1+P2, the October pull of the same feed lists P1 only
            _row("sdv_rosters", "T1", "P1", "A One", 2027, ts="2026-09-15T08:00:00Z"),
            _row("sdv_rosters", "T1", "P2", "Bee Two", 2027, ts="2026-09-15T08:00:00Z"),
            _row("espn_core", "T1", "P1", None, 2027),
            # official T2 roster: 1 of 3 names matches an ESPN id
            _row("espn_site", "T2", "P3", "Cee Three", 2027),
            *[_row("school_site", "T2", None, n, 2027) for n in ("Cee Three", "X Y", "Z W")],
        ]
    )
    f = truth.team_freshness(rows, 2027)
    t, _ = truth.resolve(rows, f, _exp(), CFG, NOW)
    st = t.dropna(subset=["player_id"]).set_index(["player_id", "team_id"])["status"]
    assert st[("P1", "T1")] == "LIKELY" and st[("P2", "T1")] == "STALE"
    s = truth.team_summary(t, f).set_index("team_id")
    assert s.loc["T2", "roster_confidence"] == "UNKNOWN"
    assert s.loc["T2", "confidence_reason"] == "official_roster_unidentified"
    assert s.loc["T1", "roster_confidence"] == "LIKELY"


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


def test_classification_is_per_player_and_team():
    rows = truth.rows_frame(
        [  # P1 played 2026 for T1; a stale feed still lists him on T1, a fresh one on T2
            _row("espn_site", "T1", "P1", "A One", 2026),
            _row("espn_core", "T2", "P1", None, 2027),
        ]
    )
    t, _ = truth.resolve(rows, truth.team_freshness(rows, 2027), _exp(), CFG, NOW)
    c = t.set_index("team_id")["classification"]
    assert c["T1"] == "returning" and c["T2"] == "transfer"


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
    parsed = sidearm.parse(SIDEARM, "https://goduke.com/sports/mens-basketball/roster")
    rows = parsed.players
    assert parsed.season_label == 2027
    assert len(rows) == 1
    r = rows[0]
    assert (r["name"], r["jersey"], r["position"], r["class_label"]) == (
        "Ann Guard",
        "3",
        "G",
        "So.",
    )
    assert r["height_in"] == 74.0 and r["previous_school"] == "Some HS"


def test_transfer_omitted_by_old_teams_official_roster_is_not_a_conflict():
    rows = truth.rows_frame(
        [
            _row("espn_site", "T1", "P2", "Bee Two", 2027),  # stale ESPN: still on T1
            _row("school_site", "T1", None, "Other Guy", 2027),  # T1 official omits him
            _row("espn_site", "T1", "P8", "Other Guy", 2027),
            _row("school_site", "T2", "P2", "Bee Two", 2027),  # T2 official (identity resolved)
            _row("espn_core", "T2", "P2", None, 2027),
        ]
    )
    t, conf = truth.resolve(rows, truth.team_freshness(rows, 2027), _exp(), CFG, NOW)
    st = t.dropna(subset=["player_id"]).set_index(["player_id", "team_id"])
    assert st.loc[("P2", "T2"), "status"] == "CONFIRMED"
    assert st.loc[("P2", "T1"), "status"] == "STALE" and bool(
        st.loc[("P2", "T1"), "absent_from_official"]
    )
    assert "listed_on_multiple_teams" not in set(conf["kind"])


def test_norm_name_initials_apostrophes_nicknames():
    assert truth.norm_name("D.J. Wagner") == truth.norm_name("DJ Wagner") == "dj wagner"
    assert truth.norm_name('Samuel "Tobi" Ariyibi') == "samuel ariyibi"
    assert truth.norm_name("Patrick D'Arcy") == "patrick darcy"
