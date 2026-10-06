"""Offline end-to-end run of the roster-truth capture (Wave 7) with every network
source mocked: ESPN site / core / SDV rows, the official discovery result. Checks the
archive layout and that a fresh official roster defines membership end to end."""

from __future__ import annotations

import json

import pandas as pd

from cbb_edge.rosters import capture, discovery, official


def test_capture_run_offline(tmp_path, monkeypatch):
    h = pd.read_parquet(capture.HISTORY)
    team = "T0069"
    last = h[(h["role_team"] == team) & (h["role_season"] == 2026)].nlargest(10, "min_share")
    ids = list(last["player_id"])
    idt = pd.read_parquet("models/rosters/player_identity_2026.parquet").set_index("player_id")
    names = [idt.loc[p, "name"] for p in ids]
    site = [{"source": "espn_site", "captured_at": "2026-10-05T10:00:00+00:00", "team_id": team,
             "player_id": p, "name": n, "source_season": 2027} for p, n in zip(ids, names)]  # fmt: skip
    monkeypatch.setattr(capture, "site_rows", lambda archive: site)
    monkeypatch.setattr(capture, "core_lists", lambda teams, season, stamp: {})
    monkeypatch.setattr(capture, "sdv_rows", lambda season, stamp: [])
    monkeypatch.setattr(capture, "current_d1_teams", lambda: [150])
    page = tmp_path / "page.html"
    page.write_text("<html>roster</html>")

    def fake_capture(season, stamp, known=None, teams=None, registry=None):
        d = discovery.Discovery(team, "https://goduke.com", "goduke.com", platform="sidearm",
                                roster_url="https://goduke.com/sports/mens-basketball/roster",
                                method="platform_route", requests=2)  # fmt: skip
        # official page keeps 7 of the 10 ESPN-listed players plus one freshman
        d.players = [{"name": n, "class_label": "Jr."} for n in names[:7]] + [
            {"name": "Totally Newfreshman", "class_label": "Fr."}]  # fmt: skip
        d.season_label = 2027
        d.page_path, d.page_meta = str(page), {"retrieved_at": "2026-10-05T11:00:00+00:00"}
        return [d]

    monkeypatch.setattr(official, "capture", fake_capture)
    rep = capture.run(tmp_path, 2027, pd.Timestamp("2026-10-05T12:00:00Z").to_pydatetime())
    day = tmp_path / "truth" / "2026" / "10" / "05"
    recs = pd.read_json(next(day.glob("*_records.jsonl")), lines=True)
    t = recs[recs["team_id"] == team].set_index("name")
    assert (t.loc[names[:7], "status"] == "CONFIRMED").all()
    assert (t.loc[names[7:], "status"] == "STALE").all()  # omitted by the official page
    assert t.loc["Totally Newfreshman", "classification"] == "first_d1"
    teams = json.loads(next(day.glob("*_teams.json")).read_text())
    assert {x["team_id"]: x["roster_confidence"] for x in teams}[team] == "CONFIRMED"
    state = json.loads(next(day.glob("*_proster_state.json")).read_text())
    rot = {
        r["player_id"] for r in next(x for x in state if x["team_id"] == team)["expected_rotation"]
    }
    assert not rot & set(ids[7:])  # departed players never enter the rotation
    assert abs(sum(r["minutes"] for r in next(x for x in state if x["team_id"] == team)
                   ["expected_rotation"]) - 200) < 1  # fmt: skip
    assert (tmp_path / "reports" / "latest_dashboard.md").exists()
    assert rep["scorecard"]["roster_pages_found"] == 1
    assert list((tmp_path / "official" / "pages").rglob("*.html.gz"))
    assert next(day.glob("*_continuity_audit.json"))
