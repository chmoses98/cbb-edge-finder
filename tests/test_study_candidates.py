"""Side study design guarantees and the preregistered candidate registry."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from cbb_edge.kalshi.research import candidates as C
from cbb_edge.kalshi.research import study as S


def row(cluster, ticker, series="KXNCAAMBGAME", entry="H1", y=1, mid=0.6, yes_px=0.62, no_px=0.40,
        ev_yes=0.01, ev_no=-0.01, t="2026-11-05T10:00:00+00:00", ver="pure-0.5.0"):  # fmt: skip
    def fill(px, won):
        gross = (1.0 if won else 0.0) - px
        fee = 0.02
        return {"fill": "FILLED", "price": px, "gross_pnl": gross, "net_pnl": gross - fee,
                "total_cost": px + fee}  # fmt: skip

    return {
        "cluster": cluster, "ticker": ticker, "series": series, "entry": entry, "y": y,
        "tip_verified": True, "mid": mid, "spread": 0.02, "hours_before_ref": 1.0, "t": t,
        "yes": fill(yes_px, y == 1), "no": fill(no_px, y == 0),
        "model": {ver: {"p": 0.6, "ev_yes": ev_yes, "ev_no": ev_no}},
    }  # fmt: skip


def test_holm_controls_family_wise_error_and_is_monotone():
    adj = S.holm({"a": 0.01, "b": 0.02, "c": 0.5})
    assert adj["a"] == pytest.approx(0.03) and adj["b"] == pytest.approx(0.04)
    assert adj["c"] == pytest.approx(0.5) and all(0 <= v <= 1 for v in adj.values())
    assert S.holm({"x": 0.4, "y": 0.45})["y"] >= S.holm({"x": 0.4, "y": 0.45})["x"]


def test_chronological_split_is_disjoint_ordered_and_skips_untipped_games():
    rows = [{"cluster": f"G{i}", "tip": f"2026-11-0{i + 1}T00:00:00+00:00"} for i in range(9)]
    rows.append({"cluster": "Gx", "tip": ""})
    disc, hold = S.chrono_split(rows)
    assert not disc & hold and "Gx" not in disc | hold
    assert max(disc) < min(hold) and len(disc) == 5 and len(hold) == 4  # 60/40 of 9 games


def test_games_not_contracts_are_the_unit_of_inference():
    rows = []
    for g in range(6):  # six games, each with MANY identical winning contracts
        for k in range(10):
            rows.append(
                {"cluster": f"G{g}", "net": 0.5 if g == 0 else -0.1, "cost": 1.0, "gross": 0.5,
                 "price": 1.0, "won": g == 0, "tip": "x", "ticker": f"T{g}{k}"}
            )  # fmt: skip
    s = S.summarize(rows, random.Random(1))
    assert s["games"] == 6 and s["contracts"] == 60
    # one lucky game among six cannot be significant no matter how many contracts it has
    assert s["p_le_zero"] > 0.1


def test_concentration_flags_a_result_carried_by_one_game():
    rows = [{"cluster": "G0", "net": 5.0, "cost": 1.0}] + [
        {"cluster": f"G{i}", "net": -0.1, "cost": 1.0} for i in range(1, 8)
    ]
    c = S.concentration(rows)
    assert c["top3_share_of_positive_pnl"] == 1.0 and c["sign_flips_if_top_game_removed"]


def test_one_bet_per_game_takes_the_highest_model_ev_and_respects_min_edge():
    rows = [
        row("G1", "A", ev_yes=0.01, ev_no=0.05),  # best = NO on A
        row("G1", "B", ev_yes=0.03, ev_no=-0.02),
        row("G2", "C", ev_yes=0.001, ev_no=-0.01),
    ]
    bets = S.one_bet_per_game(rows, {}, ("KXNCAAMBGAME",), "H1", "pure-0.5.0", 0.0)
    assert {b["cluster"]: (b["ticker"], b["side"]) for b in bets} == {
        "G1": ("A", "no"),
        "G2": ("C", "yes"),
    }
    strict = S.one_bet_per_game(rows, {}, ("KXNCAAMBGAME",), "H1", "pure-0.5.0", 0.02)
    assert [b["cluster"] for b in strict] == ["G1"]


def test_moneyline_underdog_baseline_is_one_bet_per_game_using_the_cheaper_equivalent_side():
    fav = row("G1", "FAV", mid=0.8, y=1, yes_px=0.82, no_px=0.22)
    dog = row("G1", "DOG", mid=0.2, y=0, yes_px=0.2, no_px=0.80)
    b = S.moneyline_baselines([fav, dog], {}, "H1")["UNDERDOG"]
    assert (
        len(b) == 1 and b[0]["side"] == "yes" and b[0]["price"] == 0.2
    )  # YES dog beats NO fav (0.22)
    assert b[0]["won"] is False
    f = S.moneyline_baselines([fav, dog], {}, "H1")["FAVORITE"]
    assert len(f) == 1 and f[0]["won"] is True


# ----------------------------------------------------------------- registry
def cfg(cid="c1"):
    return {
        "id": cid, "family": "GAME_WINNER", "entry": "H1", "series": ["KXNCAAMBGAME"],
        "hypothesis": "h", "rule": {"type": "baseline_underdog"},
        "success": {"min_games": 4, "alpha_family": 0.05, "ci": 0.9},
    }  # fmt: skip


def test_registry_is_immutable_and_tamper_evident(tmp_path: Path):
    p = C.register(cfg(), {"games": 0}, directory=tmp_path)
    assert C.verify_registry(tmp_path) == []
    with pytest.raises(FileExistsError):
        C.register(cfg(), {"games": 0}, directory=tmp_path)  # cannot re-register an id
    reg = json.loads(p.read_text())
    reg["config"]["rule"] = {"type": "baseline_favorite"}  # edit the frozen rule after the fact
    p.write_text(json.dumps(reg))
    assert any("config changed" in v for v in C.verify_registry(tmp_path))
    reg2 = json.loads(p.read_text())
    reg2["config"]["rule"] = {"type": "baseline_underdog"}
    reg2["registered_at"] = "2020-01-01T00:00:00+00:00"  # backdate the registration
    p.write_text(json.dumps(reg2))
    assert any("timestamp" in v for v in C.verify_registry(tmp_path))


def games(prefix, n, t, tip, winners):
    out = []
    for i in range(n):
        won = winners[i % len(winners)]
        out.append(row(f"{prefix}{i}", f"{prefix}{i}F", mid=0.8, y=1, yes_px=0.82, no_px=0.22, t=t))
        out.append(
            row(
                f"{prefix}{i}",
                f"{prefix}{i}D",
                mid=0.2,
                y=1 if won else 0,
                yes_px=0.2,
                no_px=0.80,
                t=t,
            )
        )
    return out, {r["ticker"]: tip for r in out}


def test_retrospective_results_can_never_validate_and_prospective_only_counts_after_registration(
    tmp_path: Path,
):
    C.register(cfg(), {"games": 0}, directory=tmp_path)
    reg = C.load_registry(tmp_path)
    at = reg[0]["registered_at"]
    # 12 huge-winning games BEFORE registration (discovery) -> must stay retrospective
    old, tips_old = games("O", 12, "2000-01-01T00:00:00+00:00", "2000-01-01T01:00:00+00:00", [True])
    res = C.evaluate(old, tips_old, reg, fee_verified=True)["candidates"][0]
    assert res["status"] == "PREREGISTERED" and res["prospective"]["games"] == 0
    assert res["discovery_retrospective"]["games"] == 12 and res["status"] != "VALIDATED"
    # prospective games after registration
    new, tips_new = games("N", 8, "2999-01-01T00:00:00+00:00", "2999-01-01T01:00:00+00:00", [True])
    good = C.evaluate(new, tips_new, reg, fee_verified=True)["candidates"][0]
    assert good["prospective"]["games"] == 8
    assert good["status"] == "VALIDATED"  # >= min_games, lower bound > 0, p < alpha, fee verified
    unverified = C.evaluate(new, tips_new, reg, fee_verified=False)["candidates"][0]
    assert unverified["status"] == "SHADOW_VALIDATING"  # unverified fees can never validate
    assert at < "2999"


def test_candidate_is_rejected_when_prospective_results_are_confidently_negative(tmp_path: Path):
    C.register(cfg(), {"games": 0}, directory=tmp_path)
    reg = C.load_registry(tmp_path)
    new, tips = games("L", 8, "2999-01-01T00:00:00+00:00", "2999-01-01T01:00:00+00:00", [False])
    assert C.evaluate(new, tips, reg, fee_verified=True)["candidates"][0]["status"] == "REJECTED"


def test_committed_registry_is_intact():
    assert C.verify_registry(Path("research/candidates")) == []
    ids = {r["config"]["id"] for r in C.load_registry(Path("research/candidates"))}
    assert "cbb-gw-underdog-h1-v1" in ids and len(ids) >= 5
