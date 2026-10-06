"""Wave 11: ESPN scoreboard rows as a fallback for games the SDV schedule lacks."""

from __future__ import annotations

import pandas as pd
import pytest

from cbb_edge.data.silver import build as silver
from cbb_edge.ops import schedule_completion as sc
from tests.espn_fixtures import event, payload

AT = "2026-10-06T18:00:00+00:00"


def _sdv(*evs) -> pd.DataFrame:
    """An SDV-schema frame built from the same fixtures (dtypes as SDV's file)."""
    rows = sc.espn_rows(payload(*evs), AT)
    d = pd.DataFrame(rows)[sc.ROW_COLS]
    for c in ("game_id", "season", "season_type", "home_id", "away_id", "home_score", "away_score"):
        d[c] = d[c].astype("int32")
    for c in ("time_valid", "neutral_site", "conference_competition", "status_type_completed"):
        d[c] = d[c].astype(bool)
    for c in ("tournament_id", "venue_id", "home_conference_id", "away_conference_id",
              "status_period"):  # fmt: skip
        d[c] = d[c].astype("float64")
    return d


def _espn(*evs, at=AT) -> pd.DataFrame:
    d = pd.DataFrame(sc.espn_rows(payload(*evs), at))
    d["observed_at"] = pd.to_datetime(d["observed_at"], utc=True)
    return d


G1 = event(401902275, "2026-11-03T00:00Z", 2000, 5, detail="11/2 - 7:00 PM EST")
G2 = event(401913099, "2026-11-04T00:30Z", 2010, 6, neutral=True, conf=False)
G3 = event(401913100, "2026-11-05T05:00Z", 2020, 7, tv=False, detail="TBD")


def test_espn_rows_carry_sdv_schema():
    (r,) = sc.espn_rows(payload(event(9, "2027-03-14T19:00Z", 1, 2, neutral=True, conf=True,
                                      stype=3, tournament=22, hs=70, as_=65, state="post",
                                      name="STATUS_FINAL", completed=True)), AT)  # fmt: skip
    assert r["game_id"] == 9 and r["season"] == 2027 and r["season_type"] == 3
    assert r["neutral_site"] is True and r["conference_competition"] is True
    assert r["tournament_id"] == 22.0 and r["home_score"] == 70.0 and r["away_score"] == 65.0
    assert r["status_type_name"] == "STATUS_FINAL" and r["status_type_completed"] is True
    assert r["home_id"] == 1 and r["away_id"] == 2 and r["venue_address_state"] == "ST"
    assert set(sc.ROW_COLS) <= set(r)


def test_sdv_first_espn_only_when_absent_with_provenance():
    sdv = _sdv(G1)
    espn_g1 = event(401902275, "2026-11-03T00:00Z", 2000, 5, neutral=True)  # disagrees
    frame, rep = sc.complete(sdv, _espn(espn_g1, G2, G3), 2027)
    s = frame.set_index("game_id")
    assert s.loc[401902275, "schedule_source"] == sc.SDV
    assert not s.loc[401902275, "neutral_site"]  # SDV kept; ESPN never overwrites
    assert [d["field"] for d in rep["material_disagreements"]] == ["neutral_site"]
    assert s.loc[401913099, "schedule_source"] == sc.ESPN_FALLBACK
    assert s.loc[401913099, "source_observed_at"] == pd.Timestamp(AT).isoformat()
    assert rep["fallback_games"] == 2 and rep["sdv_games"] == 1
    # fallback rows take SDV's dtypes (one schema downstream)
    assert frame["game_id"].dtype == sdv["game_id"].dtype
    assert frame["neutral_site"].dtype == bool


def test_fail_closed_exclusions():
    sdv = _sdv(G1)
    no_teams = event(401913200, "2026-11-04T00:00Z", 1, 2)
    no_teams["competitions"][0]["competitors"] = []
    same_matchup = event(401913201, "2026-11-02T23:00Z", 5, 2000)  # G1's teams, same ET day
    dup_a = event(401913202, "2026-11-06T00:00Z", 30, 31)
    dup_b = event(401913203, "2026-11-06T01:00Z", 31, 30)
    frame, rep = sc.complete(sdv, _espn(no_teams, same_matchup, dup_a, dup_b), 2027)
    why = {e["game_id"]: e["reason"] for e in rep["excluded"]}
    assert why == {401913200: "missing_required_field", 401913201: "ambiguous_reconciliation",
                   401913202: "duplicate_scheduled_game", 401913203: "duplicate_scheduled_game"}  # fmt: skip
    assert set(frame["game_id"]) == {401902275}


def test_historical_seasons_are_never_completed():
    old = _sdv(event(1, "2026-01-03T00:00Z", 1, 2, season=2026))
    frame, rep = sc.complete(old, _espn(event(2, "2026-01-04T00:00Z", 3, 4, season=2026)), 2026)
    assert list(frame["game_id"]) == [1] and rep["fallback_games"] == 0
    # an ESPN row of another season never enters the current one
    frame, _ = sc.complete(_sdv(G1), _espn(event(3, "2026-01-04T00:00Z", 3, 4, season=2026)), 2027)
    assert set(frame["game_id"]) == {401902275}


def test_sdv_catch_up_reconciles_to_the_same_game():
    """T1: ESPN lists G2, SDV does not -> fallback. T2: SDV publishes G2 -> SDV row,
    same game id, no second game."""
    t1, _ = sc.complete(_sdv(G1), _espn(G2), 2027)
    t2, rep = sc.complete(_sdv(G1, G2), _espn(G2, at="2026-11-01T06:00:00+00:00"), 2027)
    assert t1.set_index("game_id").loc[401913099, "schedule_source"] == sc.ESPN_FALLBACK
    assert t2.set_index("game_id").loc[401913099, "schedule_source"] == sc.SDV
    assert t2["game_id"].is_unique and len(t2) == 2 and rep["fallback_games"] == 0


def test_fallback_row_becomes_the_same_silver_row_as_sdv(tmp_path, monkeypatch):
    """The projection input of a fallback game equals what SDV's row would produce."""
    sdv_rows = _sdv(G1, G2, G3)
    frame, _ = sc.complete(_sdv(G1), _espn(G2, G3), 2027)
    fb = frame[frame["schedule_source"] == sc.ESPN_FALLBACK]
    a = silver.schedule_rows_to_silver(sdv_rows[sdv_rows["game_id"] != 401902275], 2027)
    b = silver.schedule_rows_to_silver(fb[sdv_rows.columns], 2027)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True),
                                  check_dtype=False)  # fmt: skip
    # silver load_schedule appends this run's fallback rows, SDV first, current season only
    monkeypatch.setenv("CBB_DATA_DIR", str(tmp_path))
    p = tmp_path / "bronze" / silver.BRONZE / silver.local_rel("schedules", 2027)
    p.parent.mkdir(parents=True)
    _sdv(G1).to_parquet(p)
    sc.completed_schedule(2027, "s", fresh=sc.espn_rows(payload(G2, G3), AT),
                          sdv_frame=_sdv(G1))  # fmt: skip
    g = silver.load_schedule(2027)
    assert sorted(g["game_id"]) == [401902275, 401913099, 401913100]
    assert g["game_id"].is_unique


def test_row_archive_is_append_only_and_change_only(tmp_path):
    rows = sc.espn_rows(payload(G2, G3), AT)
    assert sc.write_rows(tmp_path, sc.thin_rows(rows, sc.load_rows(tmp_path)), "20261006T180000Z")
    with pytest.raises(FileExistsError):
        sc.write_rows(tmp_path, rows, "20261006T180000Z")
    again = sc.espn_rows(
        payload(G2, event(401913100, "2026-11-05T23:00Z", 2020, 7)), AT[:11] + "19:00:00+00:00"
    )
    kept = sc.thin_rows(again, sc.load_rows(tmp_path))
    assert [r["game_id"] for r in kept] == [401913100]  # G3's tip was announced
    sc.write_rows(tmp_path, kept, "20261006T190000Z")
    lat = sc.latest(sc.load_rows(tmp_path)).set_index("game_id")
    assert bool(lat.loc[401913100, "time_valid"]) and len(lat) == 2


def test_placeholder_brackets_and_identity_disagreements():
    bracket = event(401920568, "2026-11-14T20:30Z", -1, -2, neutral=True)
    bracket2 = event(401920567, "2026-11-14T18:00Z", -1, -2, neutral=True)
    sdv = _sdv(G1, G2, event(401911454, "2026-11-12T02:00Z", 9999, 2440))
    espn = _espn(event(401902275, "2026-11-03T00:00Z", 5, 2000, detail="x"),  # swapped
                 event(401911454, "2026-11-12T02:00Z", 2540, 2440),  # new opponent
                 G2, bracket, bracket2)  # fmt: skip
    frame, rep = sc.complete(sdv, espn, 2027)
    why = {e["game_id"]: e["reason"] for e in rep["excluded"]}
    assert why == {401920568: "teams_not_determined", 401920567: "teams_not_determined"}
    kinds = {
        d["game_id"]: d["result"] for d in rep["material_disagreements"] if d["field"] == "teams"
    }
    assert kinds == {401902275: "orientation_swap", 401911454: "different_teams"}
    s = frame.set_index("game_id")
    assert s.loc[401911454, "home_id"] == 9999 and s.loc[401902275, "home_id"] == 2000  # SDV kept


def test_scorer_fails_closed_when_the_matchup_changes_under_the_same_id(tmp_path):
    from cbb_edge.rosters import prospective_score as ps
    from tests.test_pretip_gate import archive, rec, results, roster_archive, status

    ra = roster_archive(tmp_path)
    recs = [rec(ps.BASE, 1, "T1", "T2", 2.0, ra), rec(ps.ROSTER, 1, "T1", "T2", 3.0, ra)]
    pa = archive(tmp_path, recs)

    def score(h, a):
        g = pd.DataFrame({"espn_game_id": [1], "home_team_id": [h], "away_team_id": [a],
                          "tip": [pd.Timestamp(recs[0]["game"]["start_time_utc"])]})  # fmt: skip
        return ps.score(ps.load_records(pa, 2027), results(1), roster_archive=ra, games=g,
                        committed=ps.git_first_commit_times(pa),
                        committed_roster=ps.git_first_commit_times(ra), projections_root=pa,
                        expected=pd.DataFrame({"espn_game_id": [1]}))[0]  # fmt: skip

    assert status(score("T1", "T2"), 1) == ("VALID", "")
    assert status(score("T2", "T1"), 1) == ("UNSCORABLE", "schedule_identity_changed")
    assert status(score("T1", "T3"), 1) == ("UNSCORABLE", "schedule_identity_changed")
