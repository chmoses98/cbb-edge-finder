"""Side-aware, game-clustered market study (RESEARCH ONLY; discovery, never validation).

Question: where, if anywhere, does buying YES or NO at the displayed price earn a positive NET return
after fees, and is it more than noise, concentration or selection? Rules enforced here:

* unit of inference = GAME (cluster); contracts of one game are never counted as independent;
* a FIXED grid of slices, declared in code before looking at results; every slice is counted in the
  multiple-comparison correction (Holm) so the leaderboard cannot hide the number of looks;
* chronological split: the earliest 60% of games (by tip) are DISCOVERY, the latest 40% HOLDOUT;
* returns use the engine's hypothetical-fill rows only (displayed size must cover the order);
* nothing here assigns VALIDATED: a retrospective slice is at best EXPLORATORY.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

BOOT = 2000
SEED = 20261104
DISCOVERY_SHARE = 0.6
PRICE_BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001))
SPREAD_BUCKETS = (("<=2c", 0.0, 0.0201), ("2-5c", 0.0201, 0.0501), (">5c", 0.0501, 1.01))
HOURS_BUCKETS = (("<=2h", 0.0, 2.0), ("2-12h", 2.0, 12.0), (">12h", 12.0, 1e9))
STUDY_ENTRIES = ("OPEN", "H24", "H6", "H1")
SERIES_SETS = {
    "GAME_WINNER": ("KXNCAAMBGAME",),
    "SPREAD": ("KXNCAAMBSPREAD",),
    "TOTAL": ("KXNCAAMBTOTAL",),
    "FIRST_HALF": ("KXNCAAMB1H", "KXNCAAMB1HSPREAD", "KXNCAAMB1HTOTAL"),
}


def side_rows(
    eval_rows: list[dict[str, Any]], tips: dict[str, str], series: tuple[str, ...]
) -> list[dict[str, Any]]:
    """One row per (contract, side, entry) that was FILLED and whose outcome is known."""
    out: list[dict[str, Any]] = []
    for r in eval_rows:
        if r["series"] not in series or r["y"] is None or not r["tip_verified"]:
            continue
        if r["entry"] not in STUDY_ENTRIES:
            continue
        for side in ("yes", "no"):
            f = r[side]
            if f.get("fill") != "FILLED" or "net_pnl" not in f:
                continue
            mid = r.get("mid")
            out.append(
                {
                    "cluster": r["cluster"], "ticker": r["ticker"], "series": r["series"],
                    "entry": r["entry"], "side": side, "price": f["price"],
                    "net": f["net_pnl"], "gross": f["gross_pnl"], "cost": f["total_cost"],
                    "won": (r["y"] == 1) == (side == "yes"), "mid": mid,
                    "spread": r.get("spread"), "hours": r.get("hours_before_ref"),
                    "tip": tips.get(r["ticker"]) or "",
                    "subject_is_favorite": None if mid is None else mid >= 0.5,
                }
            )  # fmt: skip
    return out


def _ratio(items: list[tuple[str, float, float]], rng: random.Random) -> dict[str, Any]:
    by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for k, a, b in items:
        by[k][0] += a
        by[k][1] += b
    vals = list(by.values())
    den = sum(b for _, b in vals)
    if not vals or not den:
        return {"roi": None, "lo": None, "hi": None, "p_le_zero": None, "games": len(vals)}
    est = sum(a for a, _ in vals) / den
    draws = []
    for _ in range(BOOT):
        s = rng.choices(vals, k=len(vals))
        d = sum(b for _, b in s)
        if d:
            draws.append(sum(a for a, _ in s) / d)
    draws.sort()
    n = len(draws)
    return {
        "roi": est, "games": len(vals),
        "lo": draws[int(0.05 * n)] if n > 20 else None,
        "hi": draws[int(0.95 * n) - 1] if n > 20 else None,
        "p_le_zero": sum(1 for x in draws if x <= 0.0) / n if n else None,
    }  # fmt: skip


def summarize(rows: list[dict[str, Any]], rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random.Random(SEED)
    net = _ratio([(r["cluster"], r["net"], r["cost"]) for r in rows], rng)
    gross = _ratio([(r["cluster"], r["gross"], r["price"]) for r in rows], rng)
    n = len(rows)
    return {
        "contracts": n, "games": net["games"],
        "net_roi": net["roi"], "net_lo": net["lo"], "net_hi": net["hi"], "p_le_zero": net["p_le_zero"],
        "gross_roi": gross["roi"],
        "hit_rate": sum(1 for r in rows if r["won"]) / n if n else None,
        "mean_price": sum(r["price"] for r in rows) / n if n else None,
    }  # fmt: skip


def concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How dependent is the result on a handful of games? (leave-one-game-out + top-game share)."""
    by: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        by[r["cluster"]][0] += r["net"]
        by[r["cluster"]][1] += r["cost"]
    if len(by) < 3:
        return {"games": len(by), "note": "too_few_games"}
    tot_net = sum(v[0] for v in by.values())
    tot_cost = sum(v[1] for v in by.values())
    loo = [(tot_net - v[0]) / (tot_cost - v[1]) for v in by.values() if tot_cost - v[1] > 0]
    pos = sorted((v[0] for v in by.values() if v[0] > 0), reverse=True)
    return {
        "games": len(by), "roi": tot_net / tot_cost if tot_cost else None,
        "leave_one_game_out_min": min(loo), "leave_one_game_out_max": max(loo),
        "top3_share_of_positive_pnl": (sum(pos[:3]) / sum(pos)) if pos else None,
        "sign_flips_if_top_game_removed": bool(loo and (min(loo) <= 0 < (tot_net / tot_cost))),
    }  # fmt: skip


def chrono_split(rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """(discovery clusters, holdout clusters) by tip time; games without a tip are excluded."""
    tip: dict[str, str] = {}
    for r in rows:
        if r["tip"]:
            tip[r["cluster"]] = min(tip.get(r["cluster"], r["tip"]), r["tip"])
    ordered = sorted(tip, key=lambda c: (tip[c], c))
    k = int(len(ordered) * DISCOVERY_SHARE)
    return set(ordered[:k]), set(ordered[k:])


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values (family-wise error control across every slice looked at)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def _bucket(v: float | None, lo: float, hi: float) -> bool:
    return v is not None and lo <= v < hi


def slices_for(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The fixed slice grid for one family (declared here, not tuned on results)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in STUDY_ENTRIES:
        for side in ("yes", "no"):
            base = [r for r in rows if r["entry"] == entry and r["side"] == side]
            out[f"{entry}|{side}|all"] = base
            for lo, hi in PRICE_BUCKETS:
                out[f"{entry}|{side}|price[{lo:.1f},{min(hi, 1.0):.1f})"] = [
                    r for r in base if _bucket(r["price"], lo, hi)
                ]
            for name, lo, hi in SPREAD_BUCKETS:
                out[f"{entry}|{side}|spread{name}"] = [
                    r for r in base if _bucket(r["spread"], lo, hi)
                ]
            for role, flag in (("subject_favorite", True), ("subject_underdog", False)):
                out[f"{entry}|{side}|{role}"] = [
                    r for r in base if r["subject_is_favorite"] is flag
                ]
    return out


def study_family(name: str, rows: list[dict[str, Any]], min_games: int = 8) -> dict[str, Any]:
    rng = random.Random(SEED)
    disc, hold = chrono_split(rows)
    table: dict[str, Any] = {}
    pvals: dict[str, float] = {}
    for key, sl in slices_for(rows).items():
        if len({r["cluster"] for r in sl}) < min_games:
            continue
        s = summarize(sl, rng)
        d = summarize([r for r in sl if r["cluster"] in disc], rng)
        h = summarize([r for r in sl if r["cluster"] in hold], rng)
        s["discovery"], s["holdout"] = d, h
        s["concentration"] = concentration(sl)
        table[key] = s
        if s["p_le_zero"] is not None:
            pvals[key] = s["p_le_zero"]
    adj = holm(pvals)
    for k, p in adj.items():
        table[k]["holm_p"] = p
    ranked = sorted(
        (k for k in table if table[k]["net_roi"] is not None),
        key=lambda k: -(table[k]["net_roi"] or -9),
    )
    return {
        "family": name, "games_total": len({r["cluster"] for r in rows}),
        "discovery_games": len(disc), "holdout_games": len(hold),
        "slices_tested": len(table), "slices": table, "ranked": ranked,
        "label": "EXPLORATORY",
        "note": "retrospective slices cannot be VALIDATED; Holm p-values count every slice shown",
    }  # fmt: skip


def calibration_by_price(rows: list[dict[str, Any]], entry: str = "H1") -> list[dict[str, Any]]:
    """Market calibration: YES-contract midpoint vs realized YES frequency (one row per contract)."""
    seen: set[str] = set()
    pts: list[tuple[float, int, str]] = []
    for r in rows:
        if r["entry"] != entry or r["side"] != "yes" or r["mid"] is None or r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        pts.append((r["mid"], 1 if r["won"] else 0, r["cluster"]))
    out = []
    for lo, hi in PRICE_BUCKETS:
        b = [p for p in pts if lo <= p[0] < hi]
        if b:
            out.append(
                {"bucket": f"[{lo:.1f},{min(hi, 1.0):.1f})", "contracts": len(b),
                 "games": len({p[2] for p in b}), "mean_mid": sum(p[0] for p in b) / len(b),
                 "yes_frequency": sum(p[1] for p in b) / len(b)}
            )  # fmt: skip
    return out


def run_study(eval_rows: list[dict[str, Any]], tips: dict[str, str]) -> dict[str, Any]:
    fam: dict[str, Any] = {}
    for name, series in SERIES_SETS.items():
        rows = side_rows(eval_rows, tips, series)
        if not rows:
            continue
        fam[name] = study_family(name, rows)
        fam[name]["market_calibration_h1"] = calibration_by_price(rows)
    return {
        "schema_version": "cbb-side-study-v1",
        "design": {
            "unit": "game cluster",
            "discovery_share": DISCOVERY_SHARE,
            "bootstrap": BOOT,
            "seed": SEED,
            "entries": list(STUDY_ENTRIES),
            "multiple_comparisons": "Holm across all slices shown per family",
            "labels": "EXPLORATORY only; VALIDATED requires prospective shadow results",
        },  # fmt: skip
        "families": fam,
        "game_level": strategy_table(eval_rows, tips),
    }


# ------------------------------------------------------------------ one bet per game strategies
MIN_EDGES = (0.0, 0.02, 0.05)
MODEL_VERSIONS = ("pure-0.5.0", "pure-0.5.0+roster")


def _candidates(rows: list[dict[str, Any]], version: str | None) -> dict[str, list[dict[str, Any]]]:
    """Fillable (contract, side) candidates per game at one entry, with model EV when available."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["cluster"]].append(r)
    return by


def one_bet_per_game(
    eval_rows: list[dict[str, Any]],
    tips: dict[str, str],
    series: tuple[str, ...],
    entry: str,
    version: str,
    min_edge: float,
) -> list[dict[str, Any]]:
    """Model-value rule: per game, the single fillable (contract, side) with the highest model net EV,
    bet only if EV >= ``min_edge``. One bet per game => games are the independent samples."""
    best: dict[str, dict[str, Any]] = {}
    for r in eval_rows:
        if (
            r["series"] not in series or r["entry"] != entry or r["y"] is None
            or not r["tip_verified"]
        ):  # fmt: skip
            continue
        m = (r.get("model") or {}).get(version)
        if not m:
            continue
        for side in ("yes", "no"):
            f = r[side]
            ev = m.get(f"ev_{side}")
            if f.get("fill") != "FILLED" or "net_pnl" not in f or ev is None:
                continue
            cur = best.get(r["cluster"])
            if cur is None or ev > cur["ev"]:
                best[r["cluster"]] = {
                    "cluster": r["cluster"], "ticker": r["ticker"], "series": r["series"],
                    "entry": entry, "side": side, "price": f["price"], "net": f["net_pnl"],
                    "gross": f["gross_pnl"], "cost": f["total_cost"], "ev": ev,
                    "won": (r["y"] == 1) == (side == "yes"), "mid": r.get("mid"),
                    "model_p": m["p"], "tip": tips.get(r["ticker"]) or "", "t": r["t"],
                }  # fmt: skip
    return [b for b in best.values() if b["ev"] >= min_edge]


def moneyline_baselines(
    eval_rows: list[dict[str, Any]], tips: dict[str, str], entry: str
) -> dict[str, list[dict[str, Any]]]:
    """Directional game-winner baselines, one bet per game, best executable way to take the side:
    FAVORITE / UNDERDOG (by YES midpoint). NO on contract A == YES on contract B, so both are
    considered and the cheaper fillable one is taken."""
    games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in eval_rows:
        if (
            r["series"] == "KXNCAAMBGAME" and r["entry"] == entry and r["y"] is not None
            and r["tip_verified"] and r.get("mid") is not None
        ):  # fmt: skip
            games[r["cluster"]].append(r)
    out: dict[str, list[dict[str, Any]]] = {"FAVORITE": [], "UNDERDOG": []}
    for cl, rs in games.items():
        if len(rs) != 2:
            continue
        fav, dog = sorted(rs, key=lambda r: -r["mid"])
        for name, yes_c, no_c in (("FAVORITE", fav, dog), ("UNDERDOG", dog, fav)):
            opts = []
            if yes_c["yes"].get("fill") == "FILLED" and "net_pnl" in yes_c["yes"]:
                opts.append((yes_c["yes"], yes_c))
            if no_c["no"].get("fill") == "FILLED" and "net_pnl" in no_c["no"]:
                opts.append((no_c["no"], no_c))
            if not opts:
                continue
            f, c = min(opts, key=lambda o: o[0]["price"])
            subject_won = yes_c["y"] == 1
            out[name].append(
                {
                    "cluster": cl,
                    "ticker": c["ticker"],
                    "series": c["series"],
                    "entry": entry,
                    "side": "yes" if f is yes_c["yes"] else "no",
                    "price": f["price"],
                    "net": f["net_pnl"],
                    "gross": f["gross_pnl"],
                    "cost": f["total_cost"],
                    "won": subject_won,
                    "mid": yes_c["mid"],
                    "tip": tips.get(c["ticker"]) or "",
                    "t": yes_c["t"],
                }  # fmt: skip
            )
    return out


def strategy_table(
    eval_rows: list[dict[str, Any]], tips: dict[str, str], min_games: int = 10
) -> dict[str, Any]:
    """Fixed strategy grid; every row is counted in the Holm correction."""
    rng = random.Random(SEED)
    table: dict[str, Any] = {}
    pvals: dict[str, float] = {}

    def add(key: str, bets: list[dict[str, Any]]) -> None:
        if len({b["cluster"] for b in bets}) < min_games:
            return
        disc, hold = chrono_split(bets)
        s = summarize(bets, rng)
        s["discovery"] = summarize([b for b in bets if b["cluster"] in disc], rng)
        s["holdout"] = summarize([b for b in bets if b["cluster"] in hold], rng)
        s["concentration"] = concentration(bets)
        s["mean_model_edge"] = (
            sum(b["ev"] for b in bets) / len(bets) if bets and "ev" in bets[0] else None
        )
        table[key] = s
        if s["p_le_zero"] is not None:
            pvals[key] = s["p_le_zero"]

    for entry in STUDY_ENTRIES:
        for name, bets in moneyline_baselines(eval_rows, tips, entry).items():
            add(f"baseline|GAME_WINNER|{name}|{entry}", bets)
        for fam, series in SERIES_SETS.items():
            if fam == "FIRST_HALF":
                continue
            for ver in MODEL_VERSIONS:
                for me in MIN_EDGES:
                    add(
                        f"model_value|{fam}|{ver}|{entry}|edge>={me:.2f}",
                        one_bet_per_game(eval_rows, tips, series, entry, ver, me),
                    )
    for k, p in holm(pvals).items():
        table[k]["holm_p"] = p
    return {"strategies": table, "tested": len(table), "label": "EXPLORATORY"}
