"""Per-period scores: ESPN parsing, archive immutability, period-market settlement."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cbb_edge.kalshi import semantics as S
from cbb_edge.kalshi.research.universe import load_period_scores
from cbb_edge.market import period_scores as P

NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)
URL = "https://site.api.espn.com/test"


def _ls(*pts: int) -> list[dict[str, Any]]:
    return [{"value": float(p), "displayValue": str(p)} for p in pts]


def comp(
    home: list[int] | None,
    away: list[int] | None,
    final: tuple[int, int] | None = None,
    *,
    name: str = "STATUS_FINAL",
    completed: bool = True,
) -> dict[str, Any]:
    fh = sum(home) if home else 0
    fa = sum(away) if away else 0
    if final:
        fh, fa = final
    h: dict[str, Any] = {"homeAway": "home", "id": "150", "team": {"id": "150"}, "score": str(fh)}
    a: dict[str, Any] = {"homeAway": "away", "id": "153", "team": {"id": "153"}, "score": str(fa)}
    if home is not None:
        h["linescores"] = _ls(*home)
    if away is not None:
        a["linescores"] = _ls(*away)
    return {
        "status": {"type": {"name": name, "completed": completed, "state": "post"}},
        "competitors": [a, h],  # ESPN does not order by home/away
    }


def board(*games: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {"events": [{"id": gid, "competitions": [c]} for gid, c in games]}


def rec_for(c: dict[str, Any], gid: str = "401") -> dict[str, Any]:
    r = P.parse_competition(gid, c, URL, NOW)
    assert r is not None
    return r


# ---------------------------------------------------------------- parsing
def test_normal_game():
    r = rec_for(comp([38, 40], [30, 41]))
    assert r["verified"] and r["flags"] == []
    assert (r["espn_game_id"], r["home_team_id"], r["away_team_id"]) == (401, "150", "153")
    assert r["home_periods"] == [38, 40] and r["away_periods"] == [30, 41]
    assert (r["first_half_home"], r["first_half_away"]) == (38, 30)
    assert (r["regulation_home"], r["regulation_away"]) == (78, 71)
    assert (r["overtime_home"], r["overtime_away"], r["overtime_periods"]) == (0, 0, 0)
    assert (r["final_home"], r["final_away"]) == (78, 71)
    assert r["schema_version"] == "period-scores-v1" and r["source_url"] == URL
    assert r["observed_at"] == NOW.isoformat()


def test_overtime_and_double_overtime():
    r = rec_for(comp([30, 35, 9], [32, 33, 6]))
    assert r["verified"] and r["overtime_periods"] == 1
    assert (r["regulation_home"], r["regulation_away"]) == (65, 65)
    assert (r["overtime_home"], r["overtime_away"]) == (9, 6)
    assert (r["final_home"], r["final_away"]) == (74, 71)
    d = rec_for(comp([30, 35, 9, 8], [32, 33, 9, 5]))
    assert d["verified"] and d["overtime_periods"] == 2
    assert (d["overtime_home"], d["overtime_away"], d["final_home"]) == (17, 14, 82)


def test_missing_linescores_flagged_not_inferred():
    r = rec_for(comp(None, None, (78, 71)))
    assert not r["verified"] and "missing_linescores" in r["flags"]
    assert r["first_half_home"] is None and r["home_periods"] is None


def test_non_final_games_yield_no_record():
    assert (
        P.parse_competition(
            "1", comp([20], [18], name="STATUS_IN_PROGRESS", completed=False), URL, NOW
        )
        is None
    )
    assert (
        P.parse_competition(
            "1", comp(None, None, name="STATUS_SCHEDULED", completed=False), URL, NOW
        )
        is None
    )
    assert P.parse_competition("1", comp([1, 1], [1, 0], name="STATUS_POSTPONED"), URL, NOW) is None
    assert (
        P.parse_scoreboard(
            board(("1", comp([20], [18], name="STATUS_HALFTIME", completed=False))), URL, NOW
        )
        == []
    )


def test_mismatching_sums_are_flagged():
    r = rec_for(comp([38, 40], [30, 41], final=(80, 71)))
    assert not r["verified"] and "final_total_mismatch" in r["flags"]
    assert r["home_periods"] == [38, 40]  # raw numbers kept, nothing repaired
    # OT played but regulation not level
    r = rec_for(comp([38, 40, 5], [30, 41, 5]))
    assert "overtime_without_regulation_tie" in r["flags"]
    # tied final
    assert "tied_final" in rec_for(comp([38, 40], [40, 38]))["flags"]
    # one period only / ragged / fractional
    assert "fewer_than_two_periods" in rec_for(comp([78], [71]))["flags"]
    assert "period_count_mismatch" in rec_for(comp([38, 40], [30, 41, 0]))["flags"]
    frac = comp([38, 40], [30, 41])
    frac["competitors"][1]["linescores"][0]["value"] = 38.5
    frac["competitors"][1]["linescores"][0]["displayValue"] = "38.5"
    assert "non_integer_period_points" in rec_for(frac)["flags"]


def test_check_catches_tampered_totals():
    r = rec_for(comp([38, 40], [30, 41]))
    assert P.check(r) == []
    bad = {**r, "regulation_home": 99}
    assert "regulation_total_mismatch" in P.check(bad)
    assert "overtime_total_mismatch" in P.check({**r, "overtime_away": 3})


def test_scoreboard_and_summary_shapes():
    b = board(
        ("401", comp([38, 40], [30, 41])),
        ("402", comp([20], [18], name="STATUS_IN_PROGRESS", completed=False)),
    )
    assert [x["espn_game_id"] for x in P.parse_scoreboard(b, URL, NOW)] == [401]
    s = {"header": {"id": "401", "competitions": [comp([38, 40], [30, 41])]}}
    assert P.parse_summary(s, URL, NOW)["verified"]  # type: ignore[index]
    assert P.parse_summary({}, URL, NOW) is None


# ---------------------------------------------------------------- archive
def _write_day(out: Path, recs: list[dict[str, Any]], stamp: datetime = NOW) -> Path | None:
    return P.append_records(out, "20261103", recs, stamp)


def test_append_never_overwrites(tmp_path: Path):
    r = rec_for(comp([38, 40], [30, 41]))
    f1 = _write_day(tmp_path, [r])
    f2 = _write_day(tmp_path, [r])  # same stamp -> distinct file
    assert f1 != f2 and f1 and f2 and f1.exists() and f2.exists()
    assert f1.parent == tmp_path / "periods" / "2026" / "11" / "03"
    assert _write_day(tmp_path, []) is None


def test_plan_idempotent_and_conflict(tmp_path: Path):
    r = rec_for(comp([38, 40], [30, 41]))
    assert P.plan(r, []) is r
    assert P.plan({**r, "observed_at": "later"}, [r]) is None  # identical facts -> skipped
    changed = rec_for(comp([38, 41], [30, 41]))
    out = P.plan(changed, [r])
    assert out is not None and P.CONFLICT_FLAG in out["flags"]
    # unverified re-observation of a verified game is kept (not a conflict)
    broken = rec_for(comp([38, 40], [30, 41], final=(1, 2)))
    kept = P.plan(broken, [r])
    assert kept is not None and P.CONFLICT_FLAG not in kept["flags"]


def test_collect_end_to_end_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    b = board(
        ("401", comp([38, 40], [30, 41])),
        ("402", comp([30, 35, 9], [32, 33, 6])),
        ("403", comp(None, None, (60, 55))),
        ("404", comp([10], [9], name="STATUS_IN_PROGRESS", completed=False)),
    )
    calls: list[str] = []

    def fake_get(url: str, params: dict[str, str], tag: str) -> Any:
        calls.append(url)
        return b if url == P.SCOREBOARD_URL else None  # summary fallback unavailable

    monkeypatch.setattr(P, "_get", fake_get)
    s1 = P.collect(tmp_path, ["20261103"], NOW)
    d = s1["dates"]["20261103"]
    assert (d["final_games"], d["verified"], d["appended"]) == (3, 2, 3)
    assert d["flagged"] == [{"id": 403, "flags": ["missing_linescores"]}]
    before = {p: p.read_text() for p in (tmp_path / "periods").rglob("*.jsonl")}
    s2 = P.collect(tmp_path, ["20261103"], datetime(2026, 11, 4, 13, tzinfo=UTC))
    assert s2["dates"]["20261103"]["appended"] == 0 and s2["files"] == []
    assert {p: p.read_text() for p in (tmp_path / "periods").rglob("*.jsonl")} == before
    # a changed re-observation is appended as a flagged conflict, old files untouched
    b2 = copy.deepcopy(b)
    b2["events"][0]["competitions"][0] = comp([39, 40], [30, 41])
    monkeypatch.setattr(P, "_get", lambda u, p, t: b2 if u == P.SCOREBOARD_URL else None)
    s3 = P.collect(tmp_path, ["20261103"], datetime(2026, 11, 4, 14, tzinfo=UTC))
    assert s3["dates"]["20261103"]["conflicts"] == 1
    assert all(p.read_text() == t for p, t in before.items())


def test_summary_fallback_used_when_scoreboard_lacks_linescores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    b = board(("403", comp(None, None, (78, 71))))
    s = {"header": {"id": "403", "competitions": [comp([38, 40], [30, 41])]}}
    monkeypatch.setattr(P, "_get", lambda u, p, t: b if u == P.SCOREBOARD_URL else s)
    out = P.collect(tmp_path, ["20261103"], NOW)
    assert out["dates"]["20261103"]["verified"] == 1


def test_load_period_scores(tmp_path: Path):
    good = rec_for(comp([38, 40], [30, 41]), "401")
    ot = rec_for(comp([30, 35, 9], [32, 33, 6]), "402")
    bad = rec_for(comp([38, 40], [30, 41], final=(1, 2)), "403")
    forged = {
        **rec_for(comp([38, 40], [30, 41]), "404"),
        "regulation_home": 1,
    }  # verified flag lies
    P.append_records(tmp_path, "20261103", [good, ot, bad, forged], NOW)
    newer = {**good, "observed_at": "x"}
    P.append_records(tmp_path, "20261103", [newer], datetime(2026, 11, 4, 13, tzinfo=UTC))
    got = load_period_scores(tmp_path)
    assert set(got) == {401, 402}
    assert got[401]["observed_at"] == "x"  # newest verified wins
    assert load_period_scores(None) == {}
    assert load_period_scores(tmp_path / "missing") == {}
    # a conflicting verified observation makes the game ambiguous -> excluded
    conflict = P.plan(rec_for(comp([39, 40], [30, 41]), "401"), [good])
    assert conflict is not None
    P.append_records(tmp_path, "20261103", [conflict], datetime(2026, 11, 4, 14, tzinfo=UTC))
    assert set(load_period_scores(tmp_path)) == {402}


# ---------------------------------------------------------------- settle_period
HOME, AWAY = "h", "a"


def parsed(
    series: str, sub: str = "", floor: float | None = None, who: str = "home"
) -> dict[str, Any]:
    spec = S.SERIES[series]
    p: dict[str, Any] = {
        "market_type": spec.market_type, "period": spec.period, "overtime": spec.overtime,
        "direction": None, "strike": None, "subject_team_id": None, "subject_side": who,
        "yes_condition": "x", "status": "parsed", "model_gap": spec.gap,
    }  # fmt: skip
    if floor is not None:
        p["direction"], p["strike"] = "greater", floor
    if spec.market_type in ("TOTAL", "OVERTIME"):
        p["subject_side"] = None
    return p


def periods(h: list[int], a: list[int]) -> dict[str, Any]:
    return rec_for(comp(h, a))


# 1H: home 38-30, 2H regulation: 40-41 (away wins 2H), no OT
NORMAL = periods([38, 40], [30, 41])
# OT: 1H 30-32, 2H 35-33 (level 65-65), OT 9-6
OT = periods([30, 35, 9], [32, 33, 6])


def test_winner_1h_2h():
    assert S.settle_period(parsed("KXNCAAMB1H"), NORMAL) == ("yes", "period_scores")
    assert S.settle_period(parsed("KXNCAAMB1H", who="away"), NORMAL)[0] == "no"
    assert S.settle_period(parsed("KXNCAAMB2H"), NORMAL)[0] == "no"
    assert S.settle_period(parsed("KXNCAAMB2H", who="away"), NORMAL)[0] == "yes"


def test_2h_includes_overtime_1h_excludes():
    # 2H alone: 35-33 home; with OT: 44-39 home. 1H: away leads 32-30.
    assert S.settle_period(parsed("KXNCAAMB2H"), OT)[0] == "yes"
    assert S.settle_period(parsed("KXNCAAMB1H"), OT)[0] == "no"
    # 2H team loses in regulation but wins incl. OT
    swing = periods([30, 30, 10], [20, 40, 0])  # 2H incl OT: 40-40
    assert S.settle_period(parsed("KXNCAAMB2H"), swing) == (None, "tied_period_two_way_market")
    swing2 = periods([30, 30, 11], [20, 40, 1])
    assert swing2["verified"]
    flip = periods([20, 30, 12], [25, 25, 7])  # reg 50-50, OT 12-7
    assert S.settle_period(parsed("KXNCAAMB2HTOTAL", floor=80.5), flip)[0] == "no"  # 42+32=74
    assert S.settle_period(parsed("KXNCAAMB2HTOTAL", floor=73.5), flip)[0] == "yes"
    assert S.settle_period(parsed("KXNCAAMB1HTOTAL", floor=89.5), flip)[0] == "no"  # 45
    assert S.settle_period(parsed("KXNCAAMB1HTOTAL", floor=44.5), flip)[0] == "yes"


def test_three_way_tie_market():
    tie = parsed("KXNCAAMB1H", who="tie")
    assert S.settle_period(tie, periods([35, 40], [35, 38]))[0] == "yes"
    assert S.settle_period(tie, NORMAL)[0] == "no"
    tie2 = parsed("KXNCAAMB2H", who="tie")
    assert S.settle_period(tie2, periods([30, 30, 10], [20, 40, 0]))[0] == "yes"  # 2H incl OT level
    assert S.settle_period(tie2, NORMAL)[0] == "no"


def test_two_way_tie_is_undetermined():
    level = periods([35, 40], [35, 38])
    assert S.settle_period(parsed("KXNCAAMB1H"), level) == (None, "tied_period_two_way_market")
    assert S.settle_period(parsed("KXNCAAMB1H", who="away"), level)[0] is None


def test_spread_boundaries_strict_greater():
    # 1H margin home +8
    assert S.settle_period(parsed("KXNCAAMB1HSPREAD", floor=7.5), NORMAL)[0] == "yes"
    assert S.settle_period(parsed("KXNCAAMB1HSPREAD", floor=8.5), NORMAL)[0] == "no"
    assert (
        S.settle_period(parsed("KXNCAAMB1HSPREAD", floor=8.0), NORMAL)[0] == "no"
    )  # exact tie -> No
    assert S.settle_period(parsed("KXNCAAMB1HSPREAD", floor=0.5, who="away"), NORMAL)[0] == "no"
    # 2H margin (incl OT) in OT game: home +5
    assert S.settle_period(parsed("KXNCAAMB2HSPREAD", floor=4.5), OT)[0] == "yes"
    assert S.settle_period(parsed("KXNCAAMB2HSPREAD", floor=5.0), OT)[0] == "no"


def test_total_boundaries_strict_greater():
    # 1H total 68; 2H total 81
    assert S.settle_period(parsed("KXNCAAMB1HTOTAL", floor=67.5), NORMAL)[0] == "yes"
    assert S.settle_period(parsed("KXNCAAMB1HTOTAL", floor=68.0), NORMAL)[0] == "no"
    assert S.settle_period(parsed("KXNCAAMB1HTOTAL", floor=68.5), NORMAL)[0] == "no"
    assert S.settle_period(parsed("KXNCAAMB2HTOTAL", floor=80.5), NORMAL)[0] == "yes"
    assert S.settle_period(parsed("KXNCAAMB2HTOTAL", floor=81.0), NORMAL)[0] == "no"


def test_overtime_market():
    ot_mkt = parsed("KXNCAAMBOT")
    assert S.settle_period(ot_mkt, OT) == ("yes", "period_scores")
    assert S.settle_period(ot_mkt, periods([30, 35, 9, 8], [32, 33, 9, 5]))[0] == "yes"
    assert S.settle_period(ot_mkt, NORMAL) == ("no", "period_scores")


def test_race_and_missing_periods():
    assert S.settle_period(parsed("KXNCAAMBRACE"), NORMAL) == (None, "needs_play_by_play")
    assert S.settle_period(parsed("KXNCAAMBRACE"), None) == (None, "needs_play_by_play")
    for bad in (
        None,
        {},
        {**NORMAL, "verified": False},
        {**NORMAL, "superseded_by_conflict": True},
        {**NORMAL, "home_periods": [38]},
        {**NORMAL, "home_periods": [38, 40], "away_periods": [30]},
        {**NORMAL, "home_periods": [38.0, 40]},
        {**NORMAL, "home_periods": [True, 40]},
    ):
        assert S.settle_period(parsed("KXNCAAMB1H"), bad) == (None, "no_verified_period_scores")
        assert S.settle_period(parsed("KXNCAAMBOT"), bad) == (None, "no_verified_period_scores")
    unparsed = {**parsed("KXNCAAMB1H"), "status": "subject_unresolved"}
    assert S.settle_period(unparsed, NORMAL) == (None, "parse:subject_unresolved")


def test_full_markets_via_settle_period_match_settle():
    for h, a in (([38, 40], [30, 41]), ([30, 35, 9], [32, 33, 6])):
        rec = periods(h, a)
        fh, fa = rec["final_home"], rec["final_away"]
        for series, floor in (
            ("KXNCAAMBGAME", None),
            ("KXNCAAMBSPREAD", 5.5),
            ("KXNCAAMBTOTAL", 140.5),
        ):
            p = parsed(series, floor=floor)
            assert S.settle_period(p, rec)[0] == S.settle(p, fh, fa)[0]


# ---------------------------------------------------------------- existing behaviour unchanged
def test_full_settle_unchanged():
    assert S.settle(parsed("KXNCAAMB1H"), 40, 30) == (None, "needs_half_scores")
    assert S.settle(parsed("KXNCAAMBOT"), 40, 30) == (None, "needs_play_by_play")
    assert S.settle(parsed("KXNCAAMBGAME"), 40, 30) == ("yes", "final_score")
    assert S.settle(parsed("KXNCAAMBGAME"), 40, 40) == (None, "final_score")
    assert S.settle(parsed("KXNCAAMBTOTAL", floor=70.0), 40, 30) == ("no", "final_score")


def test_json_roundtrip_of_record():
    r = rec_for(comp([38, 40], [30, 41]))
    assert json.loads(json.dumps(r)) == r


# ---------------------------------------------------------------- research wiring
def test_official_check_uses_periods_when_available():
    from cbb_edge.kalshi.research.evaluate import status_dimensions
    from tests.test_market_research import contract

    c = contract([], result="yes")
    c.semantics = parsed("KXNCAAMB1HSPREAD", floor=7.5)
    scores = {7: (78, 71)}
    rec = rec_for(comp([38, 40], [30, 41]), "7")  # 1H margin +8 > 7.5 -> yes
    assert status_dimensions(c, scores)["official_check"] == "NOT_CHECKABLE:needs_half_scores"
    assert status_dimensions(c, scores, {})["official_check"] == "NOT_CHECKABLE:needs_half_scores"
    assert status_dimensions(c, scores, {7: rec})["official_check"] == "CONFIRMED"
    c.result = "no"
    assert status_dimensions(c, scores, {7: rec})["official_check"] == "DISAGREE"
    c.semantics = parsed("KXNCAAMBOT")
    c.result = "no"
    assert status_dimensions(c, scores, {7: rec})["official_check"] == "CONFIRMED"
    assert status_dimensions(c, scores)["official_check"] == "NOT_CHECKABLE:needs_play_by_play"
