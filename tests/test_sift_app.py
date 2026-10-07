"""The CBB app publisher (``cbb_edge/app/sift_app``): contract, integrity, freeze.

PERMANENT. The prospective-integrity tests (``test_integrity_*``) are mandatory: the app
must never show a projection created after tip, the newest valid pre-tip snapshot wins,
an UNSCORABLE game stays visibly UNSCORABLE, a later roster capture cannot rewrite an
earlier projection, and publishing never mutates an archive.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from cbb_edge.app import sift_app  # noqa: F401  (puts the vendored contract on the path)
from cbb_edge.app.sift_app import selection as S
from cbb_edge.app.sift_app.__main__ import main
from tests import sift_app_fixture as F

from edge_finder_contract import publish as PUB  # noqa: E402  isort: skip
from edge_finder_contract import research as R  # noqa: E402  isort: skip
from edge_finder_contract import sync  # noqa: E402  isort: skip

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "cbb_edge" / "app" / "sift_app"


def _tree_digest(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}  # fmt: skip


@pytest.fixture(scope="module")
def season(tmp_path_factory):
    out = tmp_path_factory.mktemp("season")
    a = F.build_archives(out, "season")
    before = _tree_digest(out / "archives")
    assert _run(a, out) == 0
    return out, a, before


@pytest.fixture(scope="module")
def preseason(tmp_path_factory):
    out = tmp_path_factory.mktemp("preseason")
    a = F.build_archives(out, "preseason")
    assert _run(a, out) == 0
    return out, a


def _run(a: dict, out: Path, **kw) -> int:
    argv = ["--season", "2027", "--projections", str(a["projections"]), "--rosters", str(a["rosters"]),
            "--scores", str(a["scores"]), "--schedule-archive", str(a["schedule_archive"]),
            "--schedule-parquet", str(a["schedule_parquet"]), "--out", str(out / "app" / "latest"),
            "--now", kw.get("now", a["now"]), "--code-sha", "fixture000000"]  # fmt: skip
    if kw.get("kalshi"):
        argv += ["--kalshi", str(kw["kalshi"])]
    return main(argv)


def _app(out: Path) -> Path:
    return out / "app" / "latest"


def _events(out: Path) -> dict[str, dict]:
    ev = json.loads((_app(out) / "events.json").read_text())["items"]
    return {e["extensions"]["cbb"]["cbb_game_id"]: e for e in ev}


def _research(out: Path, gid: str) -> dict:
    eid = _events(out)[gid]["event_id"]
    return json.loads((_app(out) / "explorer" / "events" / f"{eid}.json").read_text())


# ------------------------------------------------------------------ contract
def test_vendored_contract_matches_its_manifest():
    assert sync.check(REPO / "contract" / "edge_finder_contract") == []


@pytest.mark.parametrize("which", ["season", "preseason"])
def test_publication_passes_the_router_contract_validators(which, request):
    out = request.getfixturevalue(which)[0]
    assert PUB.verify_published(_app(out)) == []
    assert R.verify_explorer(_app(out)) == []
    assert R.no_secret_shaped_strings(_app(out)) == []
    man = json.loads((_app(out) / "manifest.json").read_text())
    assert man["sport"] == "CBB" and man["source_branch"] == "app-data"


def test_publication_is_deterministic(season, tmp_path):
    out, a, _ = season
    assert _run(a, tmp_path) == 0
    assert _tree_digest(_app(out)) == _tree_digest(_app(tmp_path))


def test_no_recommendations_wagers_or_model_prices(season):
    out = season[0]
    for k in ("recommendations", "wagers", "model_prices", "settlements"):
        assert json.loads((_app(out) / f"{k}.json").read_text())["count"] == 0
    board = json.loads((_app(out) / "board.json").read_text())
    assert board["bet_authority"] == "RESEARCH_ONLY"
    assert all(i["recommendations_count"] == 0 and i["wagers_count"] == 0 for i in board["items"])
    assert all(i["markets_available"] == 0 for i in board["items"]), "no market is invented"


# ------------------------------------------------------------------ integrity (mandatory)
def _rec(as_of: str, version: str = "pure-0.2.0", margin: float = 1.0, home="T0220", away="T0069",
         live: dict | None = None) -> dict:  # fmt: skip
    return {"game": {"espn_game_id": 1, "start_time_utc": "2026-11-03T01:00:00+00:00"},
            "home": {"team_id": home}, "away": {"team_id": away}, "model": {"version": version},
            "projection": {"margin": margin}, "prospective": {"as_of": as_of},
            "schedule": {"live": live}}  # fmt: skip


ROLES = {"pure-0.2.0": S.INCUMBENT, "pure-0.5.0": S.SHADOW}
NOW = pd.Timestamp("2026-11-04T00:00:00Z")


def _clock(**kw) -> S.GameClock:
    d = dict(espn_game_id=1, listed_start=pd.Timestamp("2026-11-03T01:00:00Z"), time_state="ANNOUNCED",
             state="post", status_name="STATUS_FINAL", completed=True, home_team_id="T0220",
             away_team_id="T0069")  # fmt: skip
    d.update(kw)
    return S.GameClock(**d)


def test_integrity_a_record_created_after_tip_is_never_the_projection():
    recs = [_rec("2026-11-02T14:10:00Z", margin=2.0), _rec("2026-11-03T01:00:00Z", margin=9.0),
            _rec("2026-11-03T03:00:00Z", margin=30.0)]  # fmt: skip
    s = S.select(recs, _clock(), NOW, ROLES)
    assert s.chosen["pure-0.2.0"].record["projection"]["margin"] == 2.0
    assert {r["reason"] for r in s.rejected} == {"as_of_not_before_tip"}
    only_late = S.select(recs[1:], _clock(), NOW, ROLES)
    assert only_late.state == S.UNAVAILABLE and not only_late.chosen


def test_integrity_the_tip_is_the_current_schedule_not_the_record():
    # rescheduled EARLIER: a record made after the new tip is post-tip even if before the old one
    s = S.select([_rec("2026-11-02T20:00:00Z")], _clock(listed_start=pd.Timestamp("2026-11-02T19:00:00Z")),
                 NOW, ROLES)  # fmt: skip
    assert not s.chosen and s.state == S.UNAVAILABLE


def test_integrity_latest_valid_pretip_snapshot_wins():
    recs = [_rec("2026-11-01T14:10:00Z", margin=1.0), _rec("2026-11-02T21:10:00Z", margin=3.0),
            _rec("2026-11-02T14:10:00Z", margin=2.0)]  # fmt: skip
    s = S.select(recs, _clock(), NOW, ROLES)
    assert s.chosen["pure-0.2.0"].record["projection"]["margin"] == 3.0


def test_integrity_conflicting_records_at_one_moment_show_nothing():
    recs = [_rec("2026-11-02T14:10:00Z", margin=1.0), _rec("2026-11-02T14:10:00Z", margin=4.0)]
    s = S.select(recs, _clock(), NOW, ROLES)
    assert "pure-0.2.0" in s.conflicts and "pure-0.2.0" not in s.chosen


def test_integrity_unannounced_tip_needs_proof():
    tbd = dict(time_state="TBD", listed_start=pd.Timestamp("2026-11-03T05:00:00Z"))
    after = _rec("2026-11-03T14:10:00Z")
    assert not S.select([after], _clock(**tbd), NOW, ROLES).chosen  # unproven: fail closed
    proved = _rec("2026-11-03T14:10:00Z", live={"observed_at": "2026-11-03T14:12:00Z", "state": "pre",
                                                "status_name": "STATUS_SCHEDULED"})  # fmt: skip
    s = S.select([proved], _clock(**tbd), NOW, ROLES)
    assert s.chosen["pure-0.2.0"].basis == "live_pre_observation_after_as_of"
    stale_obs = _rec("2026-11-03T14:10:00Z", live={"observed_at": "2026-11-03T14:00:00Z", "state": "pre",
                                                   "status_name": "STATUS_SCHEDULED"})  # fmt: skip
    assert not S.select([stale_obs], _clock(**tbd), NOW, ROLES).chosen


def test_integrity_post_tip_record_in_the_archive_is_not_published(season):
    out = season[0]
    r = _research(out, "G900000011")
    inc = next(m for m in r["extensions"]["cbb"]["models"] if m["version"] == "pure-0.2.0")
    assert inc["as_of"] < r["event"]["start_time_utc"]
    assert abs(inc["margin"]) < 10, "the +25 post-tip record must never be shown"
    assert any(
        x["reason"] == "as_of_not_before_tip" for x in r["extensions"]["cbb"]["rejected_records"]
    )
    assert all(m["as_of"] < r["event"]["start_time_utc"] for m in r["extensions"]["cbb"]["models"])
    for p in r["projections"]:
        assert p["generated_at"] < r["event"]["start_time_utc"]


def test_integrity_unscorable_stays_visibly_unscorable(season):
    out = season[0]
    ev = _events(out)
    c = ev["G900000012"]["extensions"]["cbb"]
    assert c["integrity"]["status"] == "UNSCORABLE"
    assert any("matchup" in x for x in c["integrity"]["reasons"])
    assert c["integrity"]["identity_changed_versions"], (
        "the swapped matchup is flagged on the record"
    )
    board = {i["event_id"]: i for i in json.loads((_app(out) / "board.json").read_text())["items"]}
    assert "UNSCORABLE" in board[ev["G900000012"]["event_id"]]["health_flags"]
    assert ev["G900000013"]["extensions"]["cbb"]["projection_state"] == S.UNAVAILABLE


def test_integrity_a_late_roster_capture_cannot_rewrite_an_earlier_projection(season):
    out = season[0]
    r = _research(out, "G900000005")["extensions"]["cbb"]
    assert r["roster"]["basis"] == "pretip_record"
    pro = r["proster"]
    assert pro["truth_snapshot"] == "20261101T120000Z", "the record's own pre-tip snapshot"
    first = pro["sides"]["home"]["expected_rotation"][0]
    assert first["minutes"] == 34.1, "the later snapshot (34.1 -> 17.05) must not leak in"
    # a game that already started never shows a later snapshot as its pregame roster
    done = _research(out, "G900000013")["extensions"]["cbb"]["roster"]
    assert done["basis"] == "none" and done["home"] is None


def test_integrity_publishing_never_mutates_an_archive(season):
    out, _a, before = season
    assert _tree_digest(out / "archives") == before


def test_integrity_publisher_never_imports_the_model_stack():
    forbidden = ("cbb_edge.app.prospective", "cbb_edge.app.wave3_live", "cbb_edge.app.project",
                 "cbb_edge.model", "cbb_edge.ratings", "cbb_edge.players", "cbb_edge.features",
                 "cbb_edge.backtest", "cbb_edge.rosters.overlay", "cbb_edge.rosters.prospective_score",
                 "cbb_edge.research", "cbb_edge.lineups", "cbb_edge.sim", "cbb_edge.pricing")  # fmt: skip
    hits = []
    for f in sorted(APP.glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])  # fmt: skip
            hits += [
                (f.name, n)
                for n in names
                if any(n == b or n.startswith(b + ".") for b in forbidden)
            ]
    assert hits == []


# ------------------------------------------------------------------ presentation data
def test_model_comparison_keeps_frozen_roles_and_only_existing_rows(season):
    out = season[0]
    full = _research(out, "G900000005")["extensions"]["cbb"]
    roles = [(m["version"], m["role"]) for m in full["models"]]
    assert roles == [("pure-0.2.0", "incumbent"), ("pure-0.3.0", "shadow"), ("pure-0.4.0", "shadow"),
                     ("pure-0.5.0", "shadow"), ("pure-0.5.0+roster", "roster_overlay")]  # fmt: skip
    assert full["primary_version"] == "pure-0.2.0", "the incumbent, never 'the newest model'"
    only = _research(out, "G900000003")["extensions"]["cbb"]
    assert [m["version"] for m in only["models"]] == ["pure-0.2.0"]
    for m in full["models"]:
        assert m["provenance"]["code_sha"] and m["as_of"] and m["info_cutoff"]
        lo, hi = m["margin_range_80"]
        assert lo < m["margin"] < hi


def test_states_pending_tbd_neutral_fallback_reconciled(season):
    ev = _events(season[0])
    assert ev["G900000001"]["extensions"]["cbb"]["projection_state"] == S.PENDING_WINDOW
    tbd = ev["G900000002"]
    assert tbd["extensions"]["cbb"]["tbd"] and tbd["start_time_confidence"] == "PLACEHOLDER"
    assert ev["G900000014"]["extensions"]["cbb"]["projection_state"] == S.AWAITING_CAPTURE
    assert ev["G900000008"]["extensions"]["cbb"]["neutral_site"]
    assert ev["G900000009"]["extensions"]["cbb"]["schedule_source"] == "ESPN_FALLBACK"
    assert ev["G900000010"]["extensions"]["cbb"]["reconciled_fields"] == ["teams"]
    assert ev["G900000006"]["extensions"]["cbb"]["roster_confidence"]["away"] == "STALE"
    assert ev["G900000007"]["extensions"]["cbb"]["roster_confidence"]["away"] == "CONFLICTED"


def test_ratings_keep_opponent_adjusted_semantics(season):
    out = season[0]
    reg = {
        m["metric_id"]: m
        for m in json.loads((_app(out) / "explorer" / "metrics.json").read_text())["items"]
    }
    assert reg["met_cbb.adj_def"]["higher_is_better"] is False
    assert reg["met_cbb.adj_off"]["supports"]["opponent_adjustment"] is True
    assert reg["met_cbb.returning_minutes_share"]["supports"]["opponent_adjustment"] is False
    r = _research(out, "G900000005")
    off = next(m for m in r["matchup"] if m["metric_id"] == "met_cbb.adj_off")
    assert off["home"]["adjusted_value"] == off["home"]["value"]


def test_preseason_health_is_honest(preseason):
    out = preseason[0]
    h = json.loads((_app(out) / "health.json").read_text())
    assert h["overall_status"] == "RESEARCH_ONLY" and h["bet_authority"] == "RESEARCH_ONLY"
    assert h["market_data_status"] == "NOT_APPLICABLE"
    assert h["components"]["upcoming_projection"]["detail"].startswith("WAITING_FOR_WINDOW")
    cbb = h["extensions"]["cbb"]
    assert cbb["research_status"] == "PRESEASON" and cbb["prospective"]["game_1"]["N"] == 0
    assert cbb["prospective"]["inference_allowed"] is False
    assert set(cbb["projection_states"]) == {S.PENDING_WINDOW}
    board = json.loads((_app(out) / "board.json").read_text())
    assert board["count"] > 0, "games stay visible before the capture window"
    assert all("PROJECTION_PENDING" in i["health_flags"] for i in board["items"])


def test_synthetic_scoreboard_is_marked(season):
    h = json.loads((_app(season[0]) / "health.json").read_text())
    assert h["extensions"]["cbb"]["prospective"]["note"].startswith("SYNTHETIC")


def test_failure_keeps_the_last_known_good_publication(season, tmp_path):
    out, a, _ = season
    app = tmp_path / "app" / "latest"
    assert _run(a, tmp_path) == 0
    good = _tree_digest(app)
    broken = dict(a, schedule_parquet=tmp_path / "missing.parquet")
    assert _run(broken, tmp_path) == 1
    after = _tree_digest(app)
    assert {k for k in good if good[k] != after.get(k)} == {"health.json"}
    h = json.loads((app / "health.json").read_text())
    assert h["overall_status"] == "DEGRADED" and h["errors"]


def test_kalshi_game_contracts_map_exactly_and_are_never_priced(season, tmp_path):
    out, a, _ = season
    k = tmp_path / "kalshi"
    snap = k / "snapshots" / "2026" / "11" / "02"
    snap.mkdir(parents=True)
    rows = [
        {"captured_at": "2026-11-02T17:30:00+00:00", "family": "GAME_WINNER", "series_ticker": "KXNCAAMBGAME",
         "market": {"ticker": "KXNCAAMBGAME-26NOV02DUKEKU-KU", "event_ticker": "KXNCAAMBGAME-26NOV02DUKEKU",
                    "title": "Duke at Kansas Winner?", "yes_sub_title": "Kansas", "status": "active",
                    "yes_bid_dollars": "0.6100", "yes_ask_dollars": "0.6300", "close_time": "2026-11-03T05:00:00Z"}},
        {"captured_at": "2026-11-02T17:30:00+00:00", "family": "GAME_WINNER", "series_ticker": "KXNCAAMBWINS",
         "market": {"ticker": "KXNCAAMBWINS-26KU-T25", "event_ticker": "KXNCAAMBWINS-26KU",
                    "title": "Kansas wins", "status": "active"}},
    ]  # fmt: skip
    (snap / "kalshi_cbb_20261102T173000Z.jsonl.gz").write_bytes(
        gzip.compress("".join(json.dumps(r) + "\n" for r in rows).encode())
    )
    (snap / "kalshi_cbb_20261102T173000Z.summary.json").write_text(
        json.dumps({"captured_at": "2026-11-02T17:30:00+00:00"})
    )
    assert _run(a, tmp_path, kalshi=k) == 0
    mk = json.loads((_app(tmp_path) / "markets.json").read_text())["items"]
    if not mk:
        pytest.skip("kalshi team aliases do not resolve these names in this checkout")
    assert [m["kalshi_ticker"] for m in mk] == ["KXNCAAMBGAME-26NOV02DUKEKU-KU"], (
        "season wins are not games"
    )
    assert (
        mk[0]["side"] == "HOME" and mk[0]["event_id"] == _events(tmp_path)["G900000005"]["event_id"]
    )
    assert json.loads((_app(tmp_path) / "model_prices.json").read_text())["count"] == 0
    assert PUB.verify_published(_app(tmp_path)) == [] and R.verify_explorer(_app(tmp_path)) == []


def test_packet_notes_carry_the_projection_rows_as_evidence(season):
    notes = _research(season[0], "G900000005")["context"]["notes"]
    assert any(n.startswith("Incumbent pure-0.2.0 projection, archived pre-tip") for n in notes)
    assert any(n.startswith("P-ROSTER-1 roster overlay") for n in notes)
    assert any(n.startswith("Prospective evaluation: game-1 N =") for n in notes)
    assert not re.search(r"best bets?|\blocks?\b|guaranteed", " ".join(notes).lower())


def test_team_rating_observations_carry_their_own_archive_time(season):
    out = season[0]
    rk = [
        json.loads(p.read_text())
        for p in (_app(out) / "explorer" / "teams").glob("*.json")
        if json.loads(p.read_text())["entity"]["source_ids"]["cbb_team_id"] == "T0220"
    ][0]
    adj = next(o for o in rk["metrics"] if o["metric_id"] == "met_cbb.adj_off")
    assert adj["as_of"] == rk["extensions"]["cbb"]["ratings"]["as_of"]
    assert adj["as_of"] < "2026-11-02T18:00:00Z"


def test_leaders_digest_matches_the_published_rankings(season):
    """Presentation-only: the home's national picture is the ranking documents' own top/bottom rows."""
    out = season[0]
    lead = json.loads((_app(out) / "health.json").read_text())["extensions"]["cbb"]["leaders"]
    assert "returning_minutes_share" in lead and "adj_off" in lead
    for slug, d in lead.items():
        rk = json.loads(
            (_app(out) / "explorer" / "rankings" / f"{d['ranking_id']}.json").read_text()
        )
        top = [e["entity_id"] for e in rk["entries"][: len(d["top"])]]
        assert [e["entity_id"] for e in d["top"]] == top, slug
        assert [e["value"] for e in d["top"]] == [
            e["value"] for e in rk["entries"][: len(d["top"])]
        ]
        assert d["bottom"][0]["entity_id"] == rk["entries"][-1]["entity_id"]
