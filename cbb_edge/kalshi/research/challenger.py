"""Shadow challenger: a calibration layer on the FROZEN pure-0.5.0 projections (RESEARCH ONLY).

Diagnosis (2026-11-04, 121 finished games): totals are under-predicted by ~3.6 points (interval excludes
zero) and the margin error is ~15% wider than ``margin_sd`` claims (standardised-error SD 1.15). The
challenger therefore changes only two things, both fitted on the EARLIEST 60% of games by tip time:

* ``total_bias``       added to the projected total;
* ``margin_sd_scale``, ``total_sd_scale``  multiplied into the projected standard deviations.

It never edits an archived projection: it derives a probability from the frozen row's own inputs and is
published as an extra model version. Its probabilities exist ONLY for games tipping after
``fit_window_end`` (out of sample); earlier games get an explicit gap, so no in-sample number can leak
into a comparison. The champion remains the incumbent; nothing is promoted by this module.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics as st
from pathlib import Path
from typing import Any

BASE_VERSION = "pure-0.5.0"
CHALLENGER_VERSION = "calib-0.5.0-v1"
FIT_SHARE = 0.6
MIN_FIT_GAMES = 30


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fit(games: list[dict[str, Any]]) -> dict[str, Any]:
    """``games``: {game_id, tip(ISO), margin, margin_sd, total, total_sd, home, away} per finished game.
    Fits on the earliest FIT_SHARE by tip; everything later is out of sample by construction."""
    ordered = sorted((g for g in games if g.get("tip")), key=lambda g: (g["tip"], g["game_id"]))
    k = int(len(ordered) * FIT_SHARE)
    train = ordered[:k]
    if len(train) < MIN_FIT_GAMES:
        raise ValueError(f"need >= {MIN_FIT_GAMES} fit games, have {len(train)}")
    t_err = [(g["home"] + g["away"]) - g["total"] for g in train]
    zt = [e / g["total_sd"] for e, g in zip(t_err, train, strict=True)]
    zm = [((g["home"] - g["away"]) - g["margin"]) / g["margin_sd"] for g in train]
    bias = st.mean(t_err)
    # total z-scores are measured after removing the fitted bias
    zt_adj = [(e - bias) / g["total_sd"] for e, g in zip(t_err, train, strict=True)]
    return {
        "schema_version": "cbb-challenger-v1",
        "version": CHALLENGER_VERSION,
        "base_version": BASE_VERSION,
        "total_bias": bias,
        "margin_sd_scale": st.pstdev(zm),
        "total_sd_scale": st.pstdev(zt_adj),
        "fit_games": len(train),
        "fit_window_end": train[-1]["tip"],
        "fit_share": FIT_SHARE,
        "diagnostics_before": {"total_bias": bias, "margin_z_sd": st.pstdev(zm), "total_z_sd": st.pstdev(zt)},
        "note": "calibration layer on frozen projections; probabilities exist only for games tipping "
        "after fit_window_end; never promoted automatically",
    }  # fmt: skip


def probability(
    parsed: dict[str, Any], proj: dict[str, Any], params: dict[str, Any]
) -> float | None:
    """Challenger probability for a parsed FULL-period WINNER / MARGIN / TOTAL contract, else None."""
    if parsed.get("status") != "parsed" or parsed.get("period") != "FULL":
        return None
    t = parsed.get("market_type")
    side = parsed.get("subject_side")
    try:
        if t == "TOTAL":
            tot, sd = proj.get("total"), proj.get("total_sd")
            if tot is None or not sd or float(sd) <= 0:
                return None
            mean = float(tot) + params["total_bias"]
            return _cdf((mean - float(parsed["strike"])) / (float(sd) * params["total_sd_scale"]))
        if t in ("MARGIN", "WINNER") and side in ("home", "away"):
            m, sd = proj.get("margin"), proj.get("margin_sd")
            if m is None or not sd or float(sd) <= 0:
                return None
            mean = float(m) if side == "home" else -float(m)
            strike = float(parsed["strike"]) if t == "MARGIN" else 0.0
            return _cdf((mean - strike) / (float(sd) * params["margin_sd_scale"]))
    except (TypeError, ValueError, KeyError):
        return None
    return None


def build_games(panel_root: Path, scores: dict[int, tuple[int, int]]) -> list[dict[str, Any]]:
    """Latest PRETIP frozen projection (base version) per finished game, joined to its final score."""
    latest: dict[int, dict[str, Any]] = {}
    for p in sorted(panel_root.glob("panels/**/*.panel.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                g = r.get("espn_game_id")
                if g is None or int(g) not in scores or r.get("market_phase") != "PRETIP":
                    continue
                v = ((r.get("models_as_of_capture") or {}).get("versions") or {}).get(BASE_VERSION)
                if v and v.get("margin") is not None and v.get("total") is not None:
                    latest[int(g)] = {
                        "game_id": int(g), "tip": r.get("game_start_utc"), "margin": v["margin"],
                        "margin_sd": v["margin_sd"], "total": v["total"], "total_sd": v["total_sd"],
                        "home": scores[int(g)][0], "away": scores[int(g)][1],
                    }  # fmt: skip
    return list(latest.values())


def main() -> None:
    ap = argparse.ArgumentParser(
        description="fit the calibration challenger (writes a frozen params file)"
    )
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--schedule", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from cbb_edge.kalshi.research.universe import load_scores

    params = fit(build_games(a.panel, load_scores(a.schedule)))
    if a.out.exists():
        raise FileExistsError(f"{a.out} exists: challenger parameters are frozen once written")
    a.out.write_text(json.dumps(params, indent=1, sort_keys=True) + "\n")
    print(json.dumps(params, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
