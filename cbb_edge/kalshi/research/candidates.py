"""Preregistered candidate signals and their prospective shadow evaluation (RESEARCH ONLY).

A candidate is a FROZEN rule: its configuration is hashed and committed BEFORE any game it is scored on
is played. Rules for status:

* ``PREREGISTERED``    registered, no settled prospective bet yet;
* ``SHADOW_VALIDATING``at least one settled prospective game, evidence still insufficient;
* ``VALIDATED``        prospective sample >= min_games AND lower confidence bound of net ROI > 0 AND
                       Bonferroni-adjusted p-value < alpha AND the fee schedule is verified official;
* ``REJECTED``         prospective sample >= min_games and the upper confidence bound < 0, or a
                       sample of 2 x min_games whose lower bound is still <= 0.
* ``EXPLORATORY``      never assigned to a registered candidate; used only for unregistered slices.

Retrospective (discovery) performance is reported separately and can NEVER move a candidate to VALIDATED.
Prospective = bets whose entry quote was observed at/after ``registered_at`` AND whose game tips after it.
Nothing here places orders: a VALIDATED candidate still has no betting authority (RESEARCH_ONLY).
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cbb_edge.kalshi.research import progress as sample_progress
from cbb_edge.kalshi.research import study
from cbb_edge.kalshi.research.matrix import cluster_ratio

REGISTRY_DIR = Path("research/candidates")
SCHEMA = "cbb-candidate-v1"
ORDER_CONTRACTS = 25  # the engine's fill assumption; part of every candidate's frozen config


def canonical(config: dict[str, Any]) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(config).encode()).hexdigest()


def register(config: dict[str, Any], discovery: dict[str, Any], now: datetime | None = None,
             directory: Path = REGISTRY_DIR) -> Path:  # fmt: skip
    """Write an immutable registration file; refuses to overwrite an existing candidate id."""
    now = now or datetime.now(UTC)
    path = directory / f"{config['id']}.json"
    if path.exists():
        raise FileExistsError(f"candidate already registered: {config['id']}")
    directory.mkdir(parents=True, exist_ok=True)
    reg = {
        "schema_version": SCHEMA,
        "registered_at": now.isoformat(),
        "config": config,
        "config_sha256": config_hash(config),
        "discovery_at_registration": discovery,
    }
    reg["registration_sha256"] = hashlib.sha256(
        (str(reg["config_sha256"]) + str(reg["registered_at"])).encode()
    ).hexdigest()
    path.write_text(json.dumps(reg, indent=1, sort_keys=True) + "\n")
    return path


def load_registry(directory: Path = REGISTRY_DIR) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]


def verify_registry(directory: Path = REGISTRY_DIR) -> list[str]:
    """Hash check: any edit to a registered config or timestamp is reported as a violation."""
    bad: list[str] = []
    for reg in load_registry(directory):
        cid = reg.get("config", {}).get("id")
        if config_hash(reg["config"]) != reg.get("config_sha256"):
            bad.append(f"{cid}: config changed after registration")
        want = hashlib.sha256((reg["config_sha256"] + reg["registered_at"]).encode()).hexdigest()
        if want != reg.get("registration_sha256"):
            bad.append(f"{cid}: registration timestamp/hash changed")
    return bad


def apply_rule(
    cfg: dict[str, Any], eval_rows: list[dict[str, Any]], tips: dict[str, str]
) -> list[dict[str, Any]]:
    """The frozen rule -> one bet per game."""
    rule = cfg["rule"]
    entry = cfg["entry"]
    if rule["type"] == "baseline_underdog":
        return study.moneyline_baselines(eval_rows, tips, entry)["UNDERDOG"]
    if rule["type"] == "baseline_favorite":
        return study.moneyline_baselines(eval_rows, tips, entry)["FAVORITE"]
    if rule["type"] == "model_value":
        return study.one_bet_per_game(
            eval_rows, tips, tuple(cfg["series"]), entry, rule["model_version"], rule["min_edge"]
        )
    raise ValueError(f"unknown rule type {rule['type']}")


def _status(
    prosp: dict[str, Any], cfg: dict[str, Any], n_candidates: int, fee_verified: bool
) -> str:
    crit = cfg["success"]
    n = prosp["games"]
    if n == 0:
        return "PREREGISTERED"
    lo, hi, p = prosp["net_lo"], prosp["net_hi"], prosp["p_le_zero"]
    alpha = crit["alpha_family"] / max(n_candidates, 1)  # Bonferroni over the registered family
    if n >= crit["min_games"] and hi is not None and hi < 0:
        return "REJECTED"
    if n >= 2 * crit["min_games"] and lo is not None and lo <= 0:
        return "REJECTED"
    if (
        n >= crit["min_games"] and lo is not None and lo > 0
        and p is not None and p < alpha and fee_verified
    ):  # fmt: skip
        return "VALIDATED"
    return "SHADOW_VALIDATING"


def evaluate(
    eval_rows: list[dict[str, Any]],
    tips: dict[str, str],
    registry: list[dict[str, Any]],
    fee_verified: bool = False,
) -> dict[str, Any]:
    rng = random.Random(study.SEED)
    out: list[dict[str, Any]] = []
    for reg in registry:
        cfg = reg["config"]
        reg_at = reg["registered_at"]
        bets = apply_rule(cfg, eval_rows, tips)
        prosp = [b for b in bets if sample_progress.prospective_bet(b, reg_at)]
        retro = [b for b in bets if not sample_progress.prospective_bet(b, reg_at)]
        ps, rs = study.summarize(prosp, rng), study.summarize(retro, rng)
        ps["clv"] = None  # CLV needs the closing quote per bet; reported by the matrix, not here
        status = _status(ps, cfg, len(registry), fee_verified)
        milestone_progress = sample_progress.progress(ps["games"], cfg["success"]["min_games"], status)
        funnel = sample_progress.eligibility_funnel(cfg, reg_at, eval_rows, tips, prosp)
        out.append(
            {
                "id": cfg["id"], "hypothesis": cfg["hypothesis"], "family": cfg["family"],
                "side_rule": cfg["rule"], "entry": cfg["entry"], "registered_at": reg_at,
                "config_sha256": reg["config_sha256"],
                "status": status,
                "prospective": ps, "discovery_retrospective": rs,
                "sample_progress": milestone_progress, "eligibility_funnel": funnel,
                "discovery_at_registration": reg.get("discovery_at_registration"),
                "success_criteria": cfg["success"],
                "fee_schedule_verified": fee_verified,
                "authority": "RESEARCH_ONLY",
            }
        )  # fmt: skip
    out.sort(key=lambda c: (c["prospective"]["net_lo"] is None, -(c["prospective"]["net_lo"] or 0)))
    return {"candidates": out, "registry_violations": [], "n_registered": len(registry)}


def default_candidates() -> list[dict[str, Any]]:
    """The initial registered family (kept small: Bonferroni over 5)."""
    succ = {"min_games": 300, "alpha_family": 0.05, "ci": 0.90,
            "primary_metric": "net ROI (cluster-bootstrap, fee-inclusive cash cost)"}  # fmt: skip
    base = {"order_contracts": ORDER_CONTRACTS, "fill": "displayed top-of-book size must cover",
            "horizon": "settled by final score", "exclusions": ["tip not verified", "no fill"]}  # fmt: skip
    return [
        {
            "id": "cbb-gw-underdog-h1-v1",
            "family": "GAME_WINNER",
            "entry": "H1",
            "series": ["KXNCAAMBGAME"],
            "hypothesis": "Underdogs are underpriced on game-winner moneylines one hour before tip "
            "(favorite-longshot asymmetry); a one-bet-per-game underdog rule has positive net ROI.",
            "rule": {"type": "baseline_underdog"},
            "success": succ,
            **base,
        },
        {
            "id": "cbb-gw-favorite-h1-v1",
            "family": "GAME_WINNER",
            "entry": "H1",
            "series": ["KXNCAAMBGAME"],
            "hypothesis": "CONTROL: favorites at the ask lose to fees and overround (expected negative).",
            "rule": {"type": "baseline_favorite"},
            "success": succ,
            **base,
        },
        {
            "id": "cbb-gw-modelvalue-h1-v1",
            "family": "GAME_WINNER",
            "entry": "H1",
            "series": ["KXNCAAMBGAME"],
            "hypothesis": "Where frozen pure-0.5.0 win probability exceeds the fee-inclusive ask, the best "
            "single side per game has positive net ROI.",
            "rule": {"type": "model_value", "model_version": "pure-0.5.0", "min_edge": 0.02},
            "success": succ,
            **base,
        },
        {
            "id": "cbb-spread-modelvalue-h1-v1",
            "family": "SPREAD",
            "entry": "H1",
            "series": ["KXNCAAMBSPREAD"],
            "hypothesis": "Frozen pure-0.5.0 spread-cover probabilities find executable value (expected "
            "negative: the model trails the market on spreads).",
            "rule": {"type": "model_value", "model_version": "pure-0.5.0", "min_edge": 0.02},
            "success": succ,
            **base,
        },
        {
            "id": "cbb-total-modelvalue-h1-v1",
            "family": "TOTAL",
            "entry": "H1",
            "series": ["KXNCAAMBTOTAL"],
            "hypothesis": "Frozen pure-0.5.0 total probabilities find executable value (expected negative).",
            "rule": {"type": "model_value", "model_version": "pure-0.5.0", "min_edge": 0.02},
            "success": succ,
            **base,
        },
    ]


__all__ = [
    "register",
    "load_registry",
    "verify_registry",
    "evaluate",
    "default_candidates",
    "cluster_ratio",
]


def main() -> None:
    import argparse
    import gzip

    ap = argparse.ArgumentParser(description="register the default candidate family (once)")
    ap.add_argument("--evaluations", type=Path, required=True)
    ap.add_argument("--universe", type=Path, required=True)
    ap.add_argument("--dir", type=Path, default=REGISTRY_DIR)
    a = ap.parse_args()

    def read(path: Path) -> list[dict[str, Any]]:
        with gzip.open(path, "rt") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    rows = read(a.evaluations)
    uni = read(a.universe)
    tips = {u["ticker"]: u["game_start"] for u in uni if u["game_start"]}
    rng = random.Random(study.SEED)
    for cfg in default_candidates():
        if (a.dir / f"{cfg['id']}.json").exists():
            print("exists", cfg["id"])
            continue
        disc = study.summarize(apply_rule(cfg, rows, tips), rng)
        disc["note"] = "discovery only: seen before registration; cannot validate"
        print("registered", register(config=cfg, discovery=disc, directory=a.dir))


if __name__ == "__main__":
    main()
