"""Render research/wave2/{metrics,market_benchmark}.json -> research/reports/WAVE2.md."""

from __future__ import annotations

import json
from pathlib import Path

M = Path("research/wave2/metrics.json")
MB = Path("research/wave2/market_benchmark.json")
OUT = Path("research/reports/WAVE2.md")

ARMS = {
    "B3": ("PR #1 best: adjusted efficiency + Four Factors + shot rates (team level)", "low"),
    "B6": ("B3 + player impact (walk-forward RAPM, NCAA stints) on expected rotation", "high"),
    "B7": ("B3 + opponent-adjusted shot profile (rim/mid/assisted) + matchup terms", "medium"),
    "B8": ("B3 + context: rest, season phase, team-specific home court (shrunk)", "low"),
    "B9": ("B3 + B6 + B7 + B8 blocks combined", "high"),
}


def f(x, nd=3):
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def main() -> None:
    m = json.loads(M.read_text())
    mb = json.loads(MB.read_text()) if MB.exists() else {}
    L = [
        "# Wave 2 — independent PURE_BASKETBALL engine",
        "",
        f"Model version `{m['model_version']}`. All arms are **PURE_BASKETBALL** (market inputs: "
        "NONE). Training window for every stacked arm starts in "
        f"{m['first_train']} (expanding, walk-forward); validation {m['validation'][0]}–"
        f"{m['validation'][-1]}; historical {m['historical']} (the PR #1 holdout — already "
        "observed, reported as evidence only); the clean test is the 2026-27 prospective "
        "archive.",
        "",
        "Promotion rule (fixed before results): validation margin RMSE below B3, better in ≥ 7 "
        "of 10 validation seasons, and log loss not worse.",
        "",
    ]
    val_mb = mb.get("validation", {})
    hist_mb = mb.get("historical", {})
    L += [
        "## Arms",
        "",
        "| Arm | Description | Pure | Val N | Val margin RMSE | Val MAE | Val total RMSE | "
        "Val total MAE | Val log loss | Val Brier | Δ RMSE vs B3 | Seasons better | Hist margin "
        "RMSE | Hist total RMSE | market_gap val | market_gap hist | Complexity | Verdict |",
        "|" + "---|" * 18,
    ]
    for a, (desc, cx) in ARMS.items():
        r = m["arms"].get(a)
        if not r:
            continue
        v, h = r["validation"], r["historical"]
        vs = r.get("vs_B3", {})
        verdict = vs.get("verdict", "BASELINE")
        if a == m.get("production_arm"):
            verdict += " (production)"
        L.append(
            f"| {a} | {desc} | YES | {v['n']} | {f(v['margin']['rmse'])} | {f(v['margin']['mae'])} | "
            f"{f(v['total']['rmse'])} | {f(v['total']['mae'])} | {f(v['wp']['log_loss'], 4)} | "
            f"{f(v['wp']['brier'], 4)} | {f(vs.get('d_margin_rmse'))} | "
            f"{vs.get('seasons_better', '—')}/10 | {f(h['margin']['rmse'])} | {f(h['total']['rmse'])} | "
            f"{f(val_mb.get(a, {}).get('market_gap_margin_rmse'))} | "
            f"{f(hist_mb.get(a, {}).get('market_gap_margin_rmse'))} | {cx} | {verdict} |"
        )
    L += [
        "",
        "market_gap = PURE margin RMSE − MARKET (free closing line) margin RMSE on games "
        "with a usable line (validation lines: 2018–2023; historical: 2026). Lower is better; "
        "0 = as accurate as the closing market using basketball data alone.",
        "",
    ]
    # by season
    L += [
        "## Margin RMSE by season (all D-I games, common sample)",
        "",
        "| Season | " + " | ".join(ARMS) + " |",
        "|---|" + "---|" * len(ARMS),
    ]
    seasons = sorted(
        set(m["arms"]["B3"]["validation"]["by_season"])
        | set(m["arms"]["B3"]["historical"]["by_season"]),
        key=int,
    )
    for s in seasons:
        row = []
        for a in ARMS:
            r = m["arms"].get(a, {})
            bs = r.get("validation", {}).get("by_season", {}).get(s) or r.get("historical", {}).get(
                "by_season", {}
            ).get(s)
            row.append(f(bs["margin_rmse"]) if bs else "—")
        L.append(f"| {s} | " + " | ".join(row) + " |")
    # scores
    L += [
        "",
        "## Team score error (validation)",
        "",
        "| Arm | Home pts MAE | Away pts MAE | Home pts bias | Away pts bias |",
        "|---|---|---|---|---|",
    ]
    for a in ARMS:
        r = m["arms"].get(a)
        if r:
            v = r["validation"]
            L.append(
                f"| {a} | {f(v['home_pts']['mae'])} | {f(v['away_pts']['mae'])} | "
                f"{f(v['home_pts']['bias'])} | {f(v['away_pts']['bias'])} |"
            )
    # early season
    L += [
        "",
        "## Early season (November–December)",
        "",
        "| Arm | Split | N | Margin RMSE | Total RMSE | Log loss |",
        "|---|---|---|---|---|---|",
    ]
    for a in ARMS:
        r = m["arms"].get(a)
        if r:
            for split in ("validation", "historical"):
                e = r[split]["nov_dec"]
                L.append(
                    f"| {a} | {split} | {e['n']} | {f(e['margin']['rmse'])} | "
                    f"{f(e['total']['rmse'])} | {f(e['wp']['log_loss'], 4)} |"
                )
    # possession models
    L += [
        "",
        "## Possession model",
        "",
        "| Model | Split | N | MAE | RMSE | Bias |",
        "|---|---|---|---|---|---|",
    ]
    for k, v in m["possession_models"].items():
        name, split = k.split("|")
        L.append(
            f"| {name} | {split} | {v.get('n')} | {f(v.get('mae'))} | {f(v.get('rmse'))} | "
            f"{f(v.get('bias'))} |"
        )
    # uncertainty
    u = m["uncertainty"]
    L += [
        "",
        f"## Uncertainty (arm {u['arm']})",
        "",
        "| Split | Win-prob method | Log loss | Brier |",
        "|---|---|---|---|",
    ]
    for split in ("validation", "historical"):
        for meth in ("logistic_wp", "bucket_sd_normal_wp", "hetero_normal_wp"):
            x = u[split][meth]
            L.append(f"| {split} | {meth} | {f(x['log_loss'], 4)} | {f(x['brier'], 4)} |")
    L += [
        "",
        "| Split | Margin interval coverage (hetero) | (bucket SD) | PIT dev hetero | PIT dev "
        "bucket | Total coverage (hetero) | σ_margin 5–95% |",
        "|---|---|---|---|---|---|---|",
    ]
    for split in ("validation", "historical"):
        x = u[split]
        L.append(
            f"| {split} | {x['margin_coverage_hetero']} | {x['margin_coverage_bucket']} | "
            f"{f(x['margin_pit_dev_hetero'], 4)} | {f(x['margin_pit_dev_bucket'], 4)} | "
            f"{x['total_coverage_hetero']} | {f(x['sigma_margin_range'][0], 1)}–"
            f"{f(x['sigma_margin_range'][1], 1)} |"
        )
    # error decomposition
    L += ["", "## Error decomposition (best arm, validation)", ""]
    ed = m["error_decomposition"]["validation"]
    tv = ed["total_err_var"]
    L += [
        f"* Total-points error variance {f(tv, 1)} (RMSE {f(ed['total_rmse'], 2)}). Pace component "
        f"variance {f(ed['pace_component_var'], 1)} ({f(100 * ed['pace_component_var'] / tv, 1)}%), "
        f"efficiency component {f(ed['efficiency_component_var'], 1)} "
        f"({f(100 * ed['efficiency_component_var'] / tv, 1)}%), covariance term "
        f"{f(ed['pace_eff_cov'], 1)}.",
        f"* Possession MAE {f(ed['poss_mae'], 2)}, bias {f(ed['poss_bias'], 2)}.",
        f"* Per-side PPP error attributed to factors (linear PPP map R² "
        f"{f(ed['ppp_factor_r2'], 3)}): "
        + ", ".join(
            f"{k} var {f(ed.get(f'ppp_err_from_{k}_var'), 4)}" for k in ("efg", "to", "orb", "ftr")
        ),
        "",
    ]
    # slices
    L += ["## Residual slices (best arm, validation)", ""]
    for name, rows in m["residual_slices_validation"].items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        L += [f"**{name}**", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            L.append(
                "| "
                + " | ".join(f(r[c], 2) if c != cols[0] and c != "n" else str(r[c]) for c in cols)
                + " |"
            )
        L.append("")
    # market benchmark by season
    if val_mb:
        L += [
            "## Market benchmark (downstream only)",
            "",
            "| Split | Season | N | MARKET | " + " | ".join(ARMS) + " |",
            "|---|---|---|---|" + "---|" * len(ARMS),
        ]
        for split, blk in (("validation", val_mb), ("historical", hist_mb)):
            for s, r in blk.get("by_season_margin_rmse", {}).items():
                L.append(
                    f"| {split} | {s} | {r['n']} | {f(r['MARKET'])} | "
                    + " | ".join(f(r.get(a)) for a in ARMS)
                    + " |"
                )
        for split, blk in (("validation", val_mb), ("historical", hist_mb)):
            e = blk.get("MARKET_ENSEMBLE_diagnostic")
            if e:
                L.append(
                    f"\nMARKET_ENSEMBLE diagnostic ({split}, {e['pure_arm']} + market, "
                    f"n={e['n']}): margin RMSE {f(e['margin'].get('rmse'))} — diagnostic only, "
                    "never the default projection."
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
