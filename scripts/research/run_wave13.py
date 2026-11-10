"""Wave 13 reproducible comparison (RESEARCH ONLY; protocol research/hypotheses/WAVE13.md).

Reuses the Wave 12 loaders / scorers (`cbb_edge.research.wave1`) and adds orientation-safe finals, the
hierarchical level challenger and the game-number slices. Writes NEW files only.

    python scripts/research/run_wave13.py --projections P --schedule S --espn E --out research/wave13
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from cbb_edge.model import level_adapt as la
from cbb_edge.model import level_hier as lh
from cbb_edge.research import wave1 as w
from cbb_edge.research import wave13 as w13

W13, W12L = lh.VERSION, "wf-level-only"
FORECASTERS = [
    "pure-0.2.0",
    "pure-0.5.0",
    "pure-0.5.0_roster",
    W12L,
    W13,
    "wf13-independent",
    "wf13r",
    "market",
]
LABEL = {
    "pure-0.2.0": "pure-0.2.0 (incumbent)", "pure-0.5.0": "pure-0.5.0", "pure-0.5.0_roster": "pure-0.5.0+roster",
    W12L: "Wave 12 level-only", W13: "Wave 13 hierarchical", "wf13-independent": "ablation: independent groups",
    "wf13r": "Wave 13 on roster base", "market": "ESPN line (benchmark)",
}  # fmt: skip


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


def attach(rows: list[dict[str, Any]], frozen: dict, finals: dict) -> dict[str, Any]:
    rows_by = {r["game_id"]: r for r in rows}
    base_games = sorted(frozen["pure-0.5.0"].values(), key=lambda g: g["as_of"])
    roster_games = sorted(frozen["pure-0.5.0_roster"].values(), key=lambda g: g["as_of"])
    st12 = la.walk_forward(base_games, finals, la.Params(sd=False))
    sth = {
        W13: lh.walk_forward(base_games, finals, lh.Params()),
        "wf13-independent": lh.walk_forward(base_games, finals, lh.Params(hierarchical=False)),
        "wf13r": lh.walk_forward(roster_games, finals, lh.Params()),
    }
    src = {W13: "pure-0.5.0", "wf13-independent": "pure-0.5.0", "wf13r": "pure-0.5.0_roster"}
    last: dict[str, Any] = {}
    for r in rows:
        r["adapted"] = {W12L: None, W13: None, "wf13-independent": None, "wf13r": None}
        s12 = st12.get(r["game_id"])
        if s12:
            r["adapted"][W12L] = la.adapt(r["proj"]["pure-0.5.0"], s12)
        grp = lh.group_of(r["min_gs"])
        for name, states in sth.items():
            s = states.get(r["game_id"])
            if s:
                r["adapted"][name] = lh.adapt(r["proj"][src[name]], s, grp)
                if name == W13:
                    last[r["game_id"]] = s
    ordered = sorted(last.values(), key=lambda s: s["n_games"])
    return {"state_first": ordered[0] if ordered else None, "state_last": ordered[-1] if ordered else None,
            "rows": len(rows_by)}  # fmt: skip


def coherence(elig: list[dict[str, Any]], name: str = "pure-0.5.0") -> dict[str, Any]:
    """Does the implied score distribution (module score_distribution) match realised errors?"""
    import numpy as np

    from cbb_edge.model.score_distribution import ScoreDistribution

    he, ae, te, me, imp_var, cover = [], [], [], [], [], []
    for r in elig:
        p = r["proj"][name]
        d = ScoreDistribution.from_projection(p)
        he.append(r["home"] - d.mean_home)
        ae.append(r["away"] - d.mean_away)
        te.append(r["total"] - p["total"])
        me.append(r["margin"] - p["margin"])
        imp_var.append(d.var_team)
        cover += [abs(he[-1]) <= 1.645 * d.sd_team, abs(ae[-1]) <= 1.645 * d.sd_team]
    he, ae, te, me = map(np.array, (he, ae, te, me))
    n = len(he)
    rng = np.random.default_rng(20261110)
    boots = [np.corrcoef(te[i], me[i])[0, 1] for i in (rng.integers(0, n, n) for _ in range(2000))]
    return {
        "n_games": n,
        "implied_team_score_sd_mean": float(np.sqrt(np.mean(imp_var))),
        "empirical_home_score_sd": float(he.std(ddof=1)), "empirical_away_score_sd": float(ae.std(ddof=1)),
        "empirical_corr_home_away_errors": float(np.corrcoef(he, ae)[0, 1]),
        "implied_corr_home_away_errors": float(np.mean([ScoreDistribution.from_projection(r["proj"][name]).cov_home_away
                                                        / ScoreDistribution.from_projection(r["proj"][name]).var_team for r in elig])),
        "corr_total_err_margin_err": float(np.corrcoef(te, me)[0, 1]),
        "corr_total_err_margin_err_ci90": [float(np.percentile(boots, 5)), float(np.percentile(boots, 95))],
        "team_score_90pct_interval_coverage": float(np.mean(cover)),
        "verdict_inputs": "uncorrelated-total-margin assumption is supported iff the CI contains 0",
    }  # fmt: skip


def decision(res: dict[str, Any]) -> dict[str, Any]:
    ex, pr = res["exploratory"], res["prospective"]
    p5, p12 = ex["paired_vs_pure-0.5.0"], ex["paired_vs_wave12_level_only"]
    harm = (
        p5["margin_abs"]["lo"] > 0
        or p5.get("logloss", {}).get("lo", -1) > 0
        or p5["total_abs"]["diff"] > 0
    )
    not_better_than_w12 = p12["total_abs"]["diff"] >= 0
    rules = {
        "prospective_games_ge_150": pr["n"] >= 150, "prospective_dates_ge_5": len(pr["dates"]) >= 5,
        "total_mae_lower_vs_0.5.0_ci_excludes_0": (pr.get("vs_0.5.0") or {}).get("total_abs", {}).get("hi", 1) < 0,
        "no_worse_than_wave12_level_only": (pr.get("vs_w12") or {}).get("total_abs", {}).get("hi", 1) <= 0.05,
    }  # fmt: skip
    if all(rules.values()):
        label = "IMPROVED"
    elif not_better_than_w12 or harm:
        label = "NOT IMPROVED"
    else:
        label = "INSUFFICIENT EVIDENCE"
    return {"label": label, "rules": rules, "exploratory_total_mae_diff_vs_wave12": p12["total_abs"]["diff"],
            "evidence_class": f"EXPLORATORY_HISTORICAL; prospective games: {pr['n']}"}  # fmt: skip


def evaluate(rows: list[dict[str, Any]], elig: list[dict[str, Any]]) -> dict[str, Any]:
    tab = {n: {"point": w.score_forecaster(elig, n), "n": len(elig)} for n in FORECASTERS}
    for n in FORECASTERS:
        if n != "market":
            tab[n]["p_normal"] = w.score_forecaster(elig, n, "p_normal")
    out: dict[str, Any] = {
        "n": len(elig), "dates": dict(sorted(Counter(r["date"] for r in elig).items())),
        "table": tab,
        "paired_vs_pure-0.5.0": w.paired_vs(elig, W13, "pure-0.5.0"),
        "paired_vs_wave12_level_only": w.paired_vs(elig, W13, W12L),
        "paired_vs_roster": w.paired_vs(elig, W13, "pure-0.5.0_roster"),
        "paired_vs_incumbent": w.paired_vs(elig, W13, "pure-0.2.0"),
        "paired_vs_market": w.paired_vs(elig, W13, "market"),
        "wave12_level_only_vs_pure-0.5.0": w.paired_vs(elig, W12L, "pure-0.5.0"),
        "independent_vs_hierarchical": w.paired_vs(elig, "wf13-independent", W13),
        "wave13r_vs_roster": w.paired_vs(elig, "wf13r", "pure-0.5.0_roster"),
    }  # fmt: skip
    slices: dict[str, Any] = {}
    for label, fn in (("by_date", lambda r: r["date"]),
                      ("by_team_game_number", lambda r: f"team_game_{min(r['min_gs'], 2) + 1}{'+' if r['min_gs'] >= 2 else ''}")):  # fmt: skip
        slices[label] = {
            k: {"n": len(v), **{n: w.score_forecaster(v, n) for n in ("pure-0.5.0", W12L, W13, "market")},
                "paired_total_abs_w13_vs_0.5.0": w.paired_bootstrap(
                    [abs(r["total"] - r["adapted"][W13]["total"]) for r in v],
                    [abs(r["total"] - r["proj"]["pure-0.5.0"]["total"]) for r in v])}
            for k, v in sorted(w.bucket(elig, fn).items())
        }  # fmt: skip
    out["slices"] = slices
    out["calibration"] = {n: w.calibration_bins(elig, n) for n in ("pure-0.5.0", W13)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for k in ("projections", "schedule", "espn", "out"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    ap.add_argument("--prospective-from", default=w13.PROSPECTIVE_FROM)
    a = ap.parse_args()

    frozen = {v: w.load_frozen(a.projections, v) for v in w.VERSION_DIRS}
    finals, audit = w13.load_finals_oriented(a.schedule, frozen["pure-0.5.0"])
    market, mk_audit = w13.orient_market(w.load_espn_lines(a.espn), frozen["pure-0.5.0"])
    ids, _ = w.eligible_games(frozen, finals)  # finals carry no names: no heuristic exclusion
    rows = w.build_table(frozen, finals, {}, market, ids)
    state = attach(rows, frozen, finals)
    elig = [r for r in rows if "mkt_margin" in r and all(r["adapted"][k] for k in r["adapted"])]
    pf = w.parse_ts(a.prospective_from)
    prosp = [r for r in elig if r["tip"] >= pf]
    # prospective = tip after registration AND the same eligibility; may be empty today
    res: dict[str, Any] = {
        "protocol": "research/hypotheses/WAVE13.md",
        "orientation_audit": audit,
        "market_orientation_audit": mk_audit,
        "scored_games_total": len(rows),
        "state_first_last": state,
        "exploratory": evaluate(rows, elig),
        "score_distribution_coherence": coherence(elig),
        "prospective": {
            "from": a.prospective_from,
            "n": len(prosp),
            "dates": dict(sorted(Counter(r["date"] for r in prosp).items())),
        },
    }
    if prosp:
        res["prospective"]["vs_0.5.0"] = w.paired_vs(prosp, W13, "pure-0.5.0")
        res["prospective"]["vs_w12"] = w.paired_vs(prosp, W13, W12L)
        res["prospective"]["table"] = {n: w.score_forecaster(prosp, n) for n in FORECASTERS}
    res["decision"] = decision(res)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "wave13_results.json").write_text(
        json.dumps(_jsonable(res), indent=1, sort_keys=True) + "\n"
    )
    print(json.dumps(_jsonable(res["decision"]), indent=1))
    print(
        "eligible",
        len(elig),
        "scored",
        len(rows),
        "prospective",
        len(prosp),
        "orientation",
        audit["status"],
    )


if __name__ == "__main__":
    main()
