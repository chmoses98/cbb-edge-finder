"""Wave 1 reproducible comparison: reproduce -> diagnose -> challenger -> evaluate (RESEARCH ONLY).

Reads the immutable archives (projections, schedule, ESPN lines, free ESPN team box scores) from
local checkouts and writes NEW files under ``--out``; it never edits an archive.

    python scripts/research/run_wave1.py --projections P --schedule S --espn E \
        --team-box team_box_2027.parquet --out research/wave12

Archive checkouts: ``git archive origin/<branch> | tar -x -C <dir>`` for ``projections-archive``,
``schedule-archive`` and ``espn-lines-archive``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from cbb_edge.model import level_adapt as la
from cbb_edge.research import wave1 as w

PRIMARY = la.VERSION
FORECASTERS = [
    "pure-0.2.0", "pure-0.3.0", "pure-0.4.0", "pure-0.5.0", "pure-0.5.0_roster",
    PRIMARY, "market",
]  # fmt: skip


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_jsonable(v) for v in x]
    if hasattr(x, "isoformat"):
        return x.isoformat()
    if isinstance(x, float) and x != x:
        return None
    return x


def attach_challengers(rows: list[dict[str, Any]], frozen: dict, finals: dict) -> dict[str, Any]:
    """Populate ``row['adapted']`` for the primary challenger, ablations and the roster-base
    variant. Returns per-variant state summaries."""
    variants = {
        PRIMARY: ("pure-0.5.0", la.Params()),
        "wf-level-only": ("pure-0.5.0", la.Params(sd=False)),
        "wf-sd-only": ("pure-0.5.0", la.Params(level=False)),
        "wf-level-0.5.0r": ("pure-0.5.0_roster", la.Params()),
    }
    summary: dict[str, Any] = {}
    for name, (base, params) in variants.items():
        games = sorted(frozen[base].values(), key=lambda g: g["as_of"])
        states = la.walk_forward(games, finals, params)
        summary[name] = {"base": base, "params": params.__dict__}
        for r in rows:
            st = states.get(r["game_id"])
            r.setdefault("adapted", {})[name] = (
                la.adapt(r["proj"][base], st) if st is not None else None
            )
            r.setdefault("state", {})[name] = st
        r_states = [r["state"][name] for r in rows if r["state"][name]]
        summary[name]["games_with_state"] = len(r_states)
        if r_states:
            summary[name]["lambda_per_poss_first"] = r_states[0]["lambda_per_poss"]
            summary[name]["lambda_per_poss_last"] = r_states[-1]["lambda_per_poss"]
    return summary


def phase1(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_games": len(rows), "versions": {}}
    for v in w.VERSION_DIRS:
        out["versions"][v] = {
            "published_p": w.score_forecaster(rows, v, "p_published"),
            "normal_p": w.score_forecaster(rows, v, "p_normal"),
        }
    out["market_point"] = w.score_forecaster([r for r in rows if "mkt_margin" in r], "market")
    # scoreboard-style slice: every game that is a team's first game (min games seen == 0)
    g1 = [r for r in rows if r["min_gs"] == 0]
    out["game1"] = {
        v: w.score_forecaster(g1, v, "p_published") for v in ("pure-0.2.0", "pure-0.5.0")
    }
    out["game1"]["pure-0.5.0_roster"] = w.score_forecaster(g1, "pure-0.5.0_roster", "p_published")
    out["game1"]["n"] = len(g1)
    # exact decomposition, per version (ppp = projected score / projected possessions)
    dec: dict[str, Any] = {}
    for v in w.VERSION_DIRS:
        acc: dict[str, list[float]] = {}
        for r in rows:
            if "act_poss" not in r:
                continue
            p = r["proj"][v]
            q = {
                "poss": p["poss"], "home_ppp": p["home_score"] / p["poss"],
                "away_ppp": p["away_score"] / p["poss"],
            }  # fmt: skip
            d = w.decompose(
                q, {"poss": r["act_poss"], "home_pts": r["home"], "away_pts": r["away"]}
            )
            for k, x in d.items():
                acc.setdefault(k, []).append(x)
        dec[v] = {k: {"mean": w.mean(xs), "se": w.sd(xs) / len(xs) ** 0.5} for k, xs in acc.items()}
        dec[v]["n"] = len(acc["poss_err"])
    out["decomposition"] = dec
    return out


def segments(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure-0.5.0 error segments: date, team game number, projected pace, |margin|, opponent quality."""
    b = "pure-0.5.0"

    def stats(rs: list[dict[str, Any]]) -> dict[str, float]:
        d = [w.decompose(
                {"poss": r["proj"][b]["poss"], "home_ppp": r["proj"][b]["home_ppp"],
                 "away_ppp": r["proj"][b]["away_ppp"]},
                {"poss": r["act_poss"], "home_pts": r["home"], "away_pts": r["away"]},
            ) for r in rs if "act_poss" in r]  # fmt: skip
        m = [r for r in rs if "mkt_margin" in r]
        f = [w.forecast_of(r, b) for r in rs]
        zm = [(r["margin"] - x["margin"]) / x["margin_sd"] for r, x in zip(rs, f, strict=True)]
        return {
            "n": len(rs),
            "total_bias": w.mean([r["total"] - r["proj"][b]["total"] for r in rs]),
            "pace_term": w.mean([x["total_pace_term"] for x in d]),
            "eff_term": w.mean([x["total_eff_term"] for x in d]),
            "margin_bias": w.mean([r["margin"] - r["proj"][b]["margin"] for r in rs]),
            "margin_mae": w.mean([abs(r["margin"] - r["proj"][b]["margin"]) for r in rs]),
            "margin_z_sd": w.sd(zm),
            "market_total_bias": w.mean([r["total"] - r["mkt_total"] for r in m]),
            "market_margin_mae": w.mean([abs(r["margin"] - r["mkt_margin"]) for r in m]),
            "model_margin_mae_same_games": w.mean([abs(r["margin"] - r["proj"][b]["margin"]) for r in m]),
        }  # fmt: skip

    def terc(key: str, labels: tuple[str, str, str]):
        c1, c2 = w.tercile_labels([key_fn[key](r) for r in rows])
        return lambda r: (
            labels[0] if key_fn[key](r) < c1 else labels[1] if key_fn[key](r) < c2 else labels[2]
        )

    key_fn = {
        "pace": lambda r: r["proj"][b]["poss"],
        "spread": lambda r: abs(r["proj"][b]["margin"]),
        "quality": lambda r: r["quality"],
        "ptotal": lambda r: r["proj"][b]["total"],
    }
    defs = {
        "date": lambda r: r["date"],
        "team_game_number": lambda r: f"min_games_seen={min(r['min_gs'], 2)}",
        "projected_pace_tercile": terc("pace", ("slow", "mid", "fast")),
        "projected_margin_size_tercile": terc("spread", ("close", "mid", "lopsided")),
        "opponent_quality_tercile": terc("quality", ("weak", "mid", "strong")),
        "projected_total_tercile": terc("ptotal", ("low", "mid", "high")),
    }
    out = {}
    for name, fn in defs.items():
        out[name] = {k: stats(v) for k, v in sorted(w.bucket(rows, fn).items())}

    # roster continuity: only the roster-overlay records carry it
    def cont(r: dict[str, Any]) -> str | None:
        ro = r["proj"]["pure-0.5.0_roster"].get("roster") or {}
        adj = ro.get("adjustment_b_continuity")
        if adj is None:
            return None
        return "no_continuity_adj" if abs(adj) < 0.05 else "|adj|<3" if abs(adj) < 3 else "|adj|>=3"

    out["roster_continuity_adjustment"] = {
        k: stats(v) for k, v in sorted(w.bucket(rows, cont).items())
    }
    # regression of realised on projected possessions / total (pace shrinkage evidence)
    import numpy as np

    rr = [r for r in rows if "act_poss" in r]
    pp = np.array([r["proj"][b]["poss"] for r in rr])
    ap = np.array([r["act_poss"] for r in rr])
    pt = np.array([r["proj"][b]["total"] for r in rr])
    at = np.array([r["total"] for r in rr])
    rng = np.random.default_rng(20261110)

    def slope(x: Any, y: Any) -> dict[str, float]:
        s = float(np.polyfit(x, y, 1)[0])
        bs = [
            np.polyfit(x[i], y[i], 1)[0]
            for i in (rng.integers(0, len(x), len(x)) for _ in range(2000))
        ]
        return {
            "slope": s,
            "lo90": float(np.percentile(bs, 5)),
            "hi90": float(np.percentile(bs, 95)),
        }

    out["pace_and_total_slopes"] = {
        "realised_vs_projected_possessions": slope(pp, ap),
        "realised_vs_projected_total": slope(pt, at),
        "projected_poss_sd": float(pp.std()), "realised_poss_sd": float(ap.std()),
        "mean_projected_poss": float(pp.mean()), "mean_realised_poss": float(ap.mean()),
    }  # fmt: skip

    # largest misses (pure-0.5.0), including 2026-11-06
    def miss(r: dict[str, Any]) -> dict[str, Any]:
        p = r["proj"][b]
        d = w.decompose(
            {"poss": p["poss"], "home_ppp": p["home_ppp"], "away_ppp": p["away_ppp"]},
            {"poss": r["act_poss"], "home_pts": r["home"], "away_pts": r["away"]},
        )
        return {
            "game_id": r["game_id"], "date": r["date"], "game": f"{r['away_name']} @ {r['home_name']}",
            "projected": f"{p['home_score']:.1f}-{p['away_score']:.1f} (poss {p['poss']:.1f})",
            "final": f"{r['home']}-{r['away']} (poss {r['act_poss']:.1f})",
            "margin_err": r["margin"] - p["margin"], "total_err": r["total"] - p["total"],
            "poss_err": d["poss_err"], "home_ppp_err": d["home_ppp_err"],
            "away_ppp_err": d["away_ppp_err"], "mkt_margin_err": r["margin"] - r.get("mkt_margin", float("nan")),
            "mkt_total_err": r["total"] - r.get("mkt_total", float("nan")),
            "std_margin_err": (r["margin"] - p["margin"]) / p["margin_sd"],
        }  # fmt: skip

    ra = [r for r in rows if "act_poss" in r]
    out["largest_margin_misses"] = [
        miss(r) for r in sorted(ra, key=lambda r: -abs(r["margin"] - r["proj"][b]["margin"]))[:12]
    ]
    out["largest_total_misses"] = [
        miss(r) for r in sorted(ra, key=lambda r: -abs(r["total"] - r["proj"][b]["total"]))[:12]
    ]
    nov6 = [r for r in ra if r["date"] == "2026-11-06"]
    out["nov6_largest_misses"] = [
        miss(r) for r in sorted(nov6, key=lambda r: -abs(r["margin"] - r["proj"][b]["margin"]))[:8]
    ]
    return out


def phase3(
    rows: list[dict[str, Any]], all_rows: list[dict[str, Any]], frozen: dict, finals: dict
) -> dict[str, Any]:
    """Identical-game comparison on ``rows`` (all forecasters defined)."""
    out: dict[str, Any] = {
        "n_eligible": len(rows), "n_scored_games": len(all_rows),
        "dates": dict(sorted(Counter(r["date"] for r in rows).items())),
        "first_eligible_tip": min(r["tip"] for r in rows).isoformat(),
        "table": {}, "calibration": {}, "paired_vs_pure-0.5.0": {}, "paired_vs_pure-0.2.0": {},
        "paired_vs_roster": {}, "paired_vs_market": {},
    }  # fmt: skip
    for name in FORECASTERS:
        kinds = ["p_published", "p_normal"] if name.startswith("pure") else ["p_normal"]
        if name == "market":
            kinds = []
        out["table"][name] = {"point": w.score_forecaster(rows, name)}
        for k in kinds:
            out["table"][name][k] = w.score_forecaster(rows, name, k)
            out["calibration"][f"{name}:{k}"] = w.calibration_bins(rows, name, k)
    for extra in ("wf-level-only", "wf-sd-only", "wf-level-0.5.0r"):
        rr = [r for r in rows if r["adapted"][extra] is not None]
        out["table"][extra] = {"point": w.score_forecaster(rr, extra), "n": len(rr)}
    out["paired_vs_pure-0.5.0"] = w.paired_vs(rows, PRIMARY, "pure-0.5.0")
    out["paired_vs_pure-0.2.0"] = w.paired_vs(rows, PRIMARY, "pure-0.2.0")
    out["paired_vs_roster"] = w.paired_vs(rows, PRIMARY, "pure-0.5.0_roster")
    out["paired_vs_market"] = w.paired_vs([r for r in rows if "mkt_margin" in r], PRIMARY, "market")
    out["pure-0.5.0_vs_pure-0.2.0"] = w.paired_vs(rows, "pure-0.5.0", "pure-0.2.0")
    out["roster_vs_pure-0.5.0"] = w.paired_vs(rows, "pure-0.5.0_roster", "pure-0.5.0")
    # by date and team game number for the headline forecasters
    for label, fn in (
        ("by_date", lambda r: r["date"]),
        ("by_team_game_number", lambda r: f"min_games_seen={min(r['min_gs'], 2)}"),
    ):
        out[label] = {
            k: {
                n: w.score_forecaster(v, n) for n in ("pure-0.2.0", "pure-0.5.0", PRIMARY, "market")
            }
            | {"n": len(v)}
            for k, v in sorted(w.bucket(rows, fn).items())
        }
    # sensitivity (reported only; never used to select the primary)
    sens = {}
    for tag, params in {
        "k_level=15": la.Params(k_level=15), "k_level=60": la.Params(k_level=60),
        "k_level=120": la.Params(k_level=120), "k_sd=20": la.Params(k_sd=20),
        "k_sd=80": la.Params(k_sd=80), "min_games=20": la.Params(min_games=20),
        "min_games=60": la.Params(min_games=60),
    }.items():  # fmt: skip
        sens[tag] = _sensitivity(rows, frozen, finals, params)
    out["sensitivity"] = sens
    return out


def _sensitivity(
    rows: list[dict[str, Any]], frozen: dict, finals: dict, params: la.Params
) -> dict[str, Any]:
    """Primary-eligible games re-scored under other hyperparameters (REPORTED, never selected on).
    Games whose state is undefined under ``params`` are skipped and counted."""
    games = sorted(frozen["pure-0.5.0"].values(), key=lambda g: g["as_of"])
    states = la.walk_forward(games, finals, params)
    sub, tmp = [], []
    for r in rows:
        st = states.get(r["game_id"])
        if st is None:
            continue
        r2 = dict(r)
        r2["adapted"] = {"tmp": la.adapt(r["proj"]["pure-0.5.0"], st)}
        sub.append(r2)
        tmp.append(r2)
    m = w.score_forecaster(sub, "tmp")
    b = w.score_forecaster(sub, "pure-0.5.0", "p_normal")
    pv = w.paired_vs(sub, "tmp", "pure-0.5.0")
    return {
        "n": len(sub), "skipped": len(rows) - len(sub),
        "total_mae": m["total_mae"], "base_total_mae": b["total_mae"],
        "total_bias": m["total_bias"], "logloss": m.get("logloss"), "base_logloss": b.get("logloss"),
        "total_mae_diff": pv["total_abs"], "logloss_diff": pv.get("logloss"),
    }  # fmt: skip


def decision(p3: dict[str, Any]) -> dict[str, Any]:
    pv = p3["paired_vs_pure-0.5.0"]
    tab = p3["table"]
    cha, base = tab[PRIMARY]["point"], tab["pure-0.5.0"]["point"]
    ll = pv.get("logloss", {})
    n, dates = p3["n_eligible"], len(p3["dates"])
    rules = {
        "total_mae_lower_ci_excludes_0": pv["total_abs"]["hi"] < 0,
        "abs_total_bias_lower": abs(cha["total_bias"]) < abs(base["total_bias"]),
        "margin_mae_not_worse": pv["margin_abs"]["hi"] <= 0.10,
        "margin_rmse_not_worse": (pv["margin_sq"]["hi"] <= 0.10 * 2 * base["margin_rmse"]),
        "logloss_not_worse": ll.get("hi", 1.0) <= 0.005,
        "n_ge_150": n >= 150, "dates_ge_5": dates >= 5,
    }  # fmt: skip
    worse = (
        pv["margin_abs"]["lo"] > 0 or pv["logloss"]["lo"] > 0 or pv["margin_sq"]["lo"] > 0
        if "logloss" in pv
        else False
    )
    if all(rules.values()):
        label = "IMPROVED"
    elif pv["total_abs"]["diff"] >= 0 or worse:
        label = "NOT IMPROVED"
    else:
        label = "INSUFFICIENT EVIDENCE"
    return {"label": label, "rules": rules, "evidence_class": "EXPLORATORY_HISTORICAL"}


def _phase4(a: argparse.Namespace, eligible: list[dict[str, Any]], res: dict[str, Any]) -> None:
    import csv
    import gzip

    from cbb_edge.research import wave1_market as wm

    dists = {
        "pure-0.2.0": "pure-0.2.0", "pure-0.5.0": "pure-0.5.0",
        "pure-0.5.0+roster": "pure-0.5.0_roster", PRIMARY: PRIMARY,
    }  # fmt: skip
    recs, info = wm.contract_table(a.panel, eligible, dists)
    labels = list(dists)
    # demo game: the eligible game with the most modelled FULL-game contracts
    counts = Counter(r["game_id"] for r in recs if r["model_status"] == "MODELLED")
    demo_game = counts.most_common(1)[0][0] if counts else None
    market = {
        "note": wm.RESEARCH_ONLY, "info": info, "universe_newest_partition": wm.universe_tally(a.panel),
        "evaluation": wm.evaluate_contracts(recs, labels),
        "evaluation_base_vs_challenger_only": wm.evaluate_contracts(recs, ["pure-0.5.0", PRIMARY]),
        "ladder_demo_game_id": demo_game,
        "ladder_demo": wm.ladder_demo(recs, demo_game, labels) if demo_game else [],
        "fee_schedule": {"version": wm.fees.FEE_SCHEDULE_VERSION, "taker_rate": wm.fees.TAKER_RATE,
                         "note": "assumed default unless the series API carried fee fields"},
    }  # fmt: skip
    (a.out / "wave12_market.json").write_text(
        json.dumps(_jsonable(market), indent=1, sort_keys=True) + "\n"
    )
    cols = sorted({k for r in recs for k in r})
    with gzip.open(a.out / "wave12_contracts.csv.gz", "wt", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(_jsonable(recs))
    res["phase4"] = {"n_contracts": len(recs), "modelled": market["evaluation"]["universe"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--projections", type=Path, required=True)
    ap.add_argument("--schedule", type=Path, required=True)
    ap.add_argument("--espn", type=Path, required=True)
    ap.add_argument("--team-box", type=Path, required=True)
    ap.add_argument("--panel", type=Path, default=None, help="kalshi-panel-archive checkout")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    frozen = {v: w.load_frozen(a.projections, v) for v in w.VERSION_DIRS}
    finals = w.load_finals(a.schedule)
    actuals = w.load_team_box_actuals(a.team_box)
    market = w.load_espn_lines(a.espn)
    ids_all, swapped = w.eligible_games(frozen, finals)
    ids = [g for g in ids_all if g in actuals]
    rows = w.build_table(frozen, finals, actuals, market, ids)
    summary = attach_challengers(rows, frozen, finals)

    eligible = [r for r in rows if r["adapted"][PRIMARY] and "mkt_margin" in r
                and all(r["adapted"][v] for v in ("wf-level-only", "wf-sd-only"))]  # fmt: skip
    res = {
        "protocol": "research/hypotheses/WAVE12.md",
        "evidence_class": "EXPLORATORY_HISTORICAL (hypothesis formed on this window; not prospective)",
        "cutoff_tip_utc": w.CUTOFF_TIP_UTC,
        "excluded_orientation_swapped_game_ids": swapped,
        "n_without_team_box": len(ids_all) - len(ids),
        "challenger_summary": summary,
        "phase1": phase1(rows),
        "segments": segments(rows),
        "phase3": phase3(eligible, rows, frozen, finals),
    }
    res["decision"] = decision(res["phase3"])
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "wave12_results.json").write_text(
        json.dumps(_jsonable(res), indent=1, sort_keys=True) + "\n"
    )
    import csv

    with (a.out / "wave12_game_table.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["game_id", "tip_utc", "et_date", "min_games_seen", "home_final", "away_final",
                     "act_poss", "mkt_margin", "mkt_total", "pure050_margin", "pure050_total",
                     "pure050_poss", "challenger_total", "challenger_total_sd", "challenger_margin_sd",
                     "base_total_sd", "base_margin_sd"])  # fmt: skip
        for r in rows:
            p = r["proj"]["pure-0.5.0"]
            c = r["adapted"][PRIMARY] or {}
            wr.writerow([r["game_id"], r["tip"].isoformat(), r["date"], r["min_gs"], r["home"],
                         r["away"], r.get("act_poss"), r.get("mkt_margin"), r.get("mkt_total"),
                         p["margin"], p["total"], p["poss"], c.get("total"), c.get("total_sd"),
                         c.get("margin_sd"), p["total_sd"], p["margin_sd"]])  # fmt: skip
    if a.panel is not None:
        _phase4(a, eligible, res)
    print(json.dumps(_jsonable(res["decision"]), indent=1))
    print("eligible games:", len(eligible), "of", len(rows))


if __name__ == "__main__":
    main()
