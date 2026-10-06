"""Wave 8 pre-tip diagnostics over one archived roster-truth snapshot (no outcomes).

    python scripts/prospective/pretip_diagnostics.py --rosters <roster-archive> [--stamp S]

Reports, for the snapshot (default: the newest):

* coverage by confidence over the season's canonical D-I members (non-members apart);
* unresolved-identity impact: names left without a player id, and an UPPER BOUND on the
  expected-rotation minutes they could represent (same normalized name among 2025-26 D-I
  players not on any roster in the snapshot, at their 2025-26 minutes). Never used to
  link anyone;
* estimated BASE false inclusion per team (pre-tip; separate from the realized metric);
* the continuity-correction tail (|adj| buckets) and expected-newcomer distribution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cbb_edge.rosters import membership
from cbb_edge.rosters.truth import norm_name

REPO = Path(__file__).resolve().parents[2]


def snapshot(root: Path, stamp: str | None) -> tuple[str, Path]:
    files = sorted((root / "truth").rglob("*_records.jsonl"))
    if stamp:
        files = [f for f in files if f.name.startswith(stamp)]
    f = files[-1]
    return f.name.split("_")[0], f.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rosters", type=Path, required=True)
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    stamp, d = snapshot(a.rosters, a.stamp)
    recs = pd.read_json(d / f"{stamp}_records.jsonl", lines=True, dtype={"player_id": str})
    teams = pd.read_json(d / f"{stamp}_teams.json")
    state = json.loads((d / f"{stamp}_proster_state.json").read_text())
    audit = json.loads((d / f"{stamp}_continuity_audit.json").read_text())
    mem = membership.members(a.season)
    ids = set(mem["team_id"].dropna())
    out: dict = {"snapshot": stamp, "members": int(len(mem)),
                 "members_without_canonical_id": mem.loc[mem["team_id"].isna(), "school"].tolist()}  # fmt: skip
    t = teams[teams["team_id"].isin(ids)]
    out["not_members_in_snapshot"] = sorted(set(teams["team_id"]) - ids)
    out["confidence_over_members"] = t["roster_confidence"].value_counts().to_dict()
    out["members_without_truth_row"] = sorted(ids - set(teams["team_id"]))

    # unresolved identity impact (upper bound; diagnostic only)
    idt = pd.read_parquet(REPO / "models" / "rosters" / "player_identity_2026.parquet")
    names = idt[["player_id", "last_season", "names_seen"]].explode("names_seen")
    names["k"] = names["names_seen"].map(norm_name)
    hist = pd.read_parquet(REPO / "models" / "rosters" / "history_2026.parquet")
    last = hist[hist["role_season"] == a.season - 1].groupby("player_id")["min_share"].max()
    claimed = set(recs["player_id"].dropna())
    u = recs[recs["player_id"].isna() & recs["team_id"].isin(ids)]
    rows = []
    for x in u.itertuples(index=False):
        c = names[(names["k"] == norm_name(x.name)) & (names["last_season"] == a.season - 1)]
        free = c[~c["player_id"].isin(claimed)].drop_duplicates("player_id")
        m = 40 * free["player_id"].map(last).fillna(0.0)
        rows.append({"team_id": x.team_id, "identity": x.identity,
                     "unclaimed_d1_candidates": int(len(free)),
                     "max_minutes_at_stake": float(m.max()) if len(m) else 0.0})  # fmt: skip
    ui = pd.DataFrame(rows)
    rot_total = 200.0 * len(state)
    out["identity_impact"] = {
        "unresolved_names": int(len(ui)),
        "teams": int(ui["team_id"].nunique()) if len(ui) else 0,
        "by_identity": ui["identity"].value_counts().to_dict() if len(ui) else {},
        "names_with_unclaimed_2025_26_candidate": int((ui["unclaimed_d1_candidates"] > 0).sum())
        if len(ui) else 0,
        "minutes_at_stake_upper_bound": float(ui["max_minutes_at_stake"].sum()) if len(ui) else 0.0,
        "share_of_all_rotation_minutes": float(ui["max_minutes_at_stake"].sum() / rot_total)
        if len(ui) and rot_total else 0.0,
        "teams_over_10_minutes": sorted(ui.groupby("team_id")["max_minutes_at_stake"].sum()
                                        .loc[lambda s: s > 10].index.tolist()) if len(ui) else [],
    }  # fmt: skip

    # estimated BASE false inclusion (pre-tip)
    on = recs[recs["status"].isin(["CONFIRMED", "LIKELY"])]
    on = set(zip(on["player_id"], on["team_id"], strict=True))
    lt = hist[hist["role_season"] == a.season - 1]
    fi = []
    for tid, b in lt[lt["role_team"].isin(set(t["team_id"]))].groupby("role_team"):
        gone = b[[(p, tid) not in on for p in b["player_id"]]]
        fi.append({"team_id": tid, "false_players": len(gone),
                   "false_minutes": 40 * float(gone["min_share"].sum())})  # fmt: skip
    fi = pd.DataFrame(fi)
    conf = t.set_index("team_id")["roster_confidence"]
    fi["confidence"] = fi["team_id"].map(conf)
    out["estimated_base_false_inclusion"] = {
        "teams": int(len(fi)),
        "false_minutes_mean": float(fi["false_minutes"].mean()),
        "false_players_mean": float(fi["false_players"].mean()),
        "by_confidence": fi.groupby("confidence")["false_minutes"].mean().round(1).to_dict(),
    }

    # continuity tail and newcomers (CONFIRMED teams, frozen formula as archived)
    out["continuity_audit"] = {k: v for k, v in audit.items() if k not in ("large", "all")}
    rows = []
    for s in state:
        r = s.get("expected_rotation") or []
        n_new = sum(
            1 for e in r if e.get("class") in ("transfer", "first_d1") and e["share"] >= 0.10
        )
        rows.append({"team_id": s["team_id"], "confidence": s.get("roster_confidence"),
                     "n_newcomers": n_new})  # fmt: skip
    nc = pd.DataFrame(rows)
    nc = nc[nc["team_id"].isin(ids)]
    out["expected_newcomers"] = {
        "quantiles": {str(q): float(nc["n_newcomers"].quantile(q)) for q in (0.25, 0.5, 0.75, 0.9)},
        "mean": float(nc["n_newcomers"].mean()),
    }
    allc = pd.DataFrame(audit.get("all") or audit.get("large", []))
    if len(allc):
        adj = allc["adjustment"].abs()
        out["continuity_tail_buckets"] = {
            lab: int(((adj >= lo) & (adj < hi)).sum())
            for lo, hi, lab in [(0, 2, "<2"), (2, 4, "2-4"), (4, 6, "4-6"), (6, np.inf, ">=6")]
        }
    txt = json.dumps(out, indent=1, default=str)
    if a.out:
        a.out.write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
