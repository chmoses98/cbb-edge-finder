"""Constrained expected-rotation allocation (Wave 7).

The rotation model (``overlay._rotation_model``) predicts each roster player's share of
a team's first-five-games minutes independently. ``allocate`` turns those raw
predictions into a coherent rotation:

* team total = 200 regulation minutes (shares sum to 5);
* no player above 40 minutes (share <= 1), by water-filling (players at the cap keep
  it, the rest are rescaled; never a post-hoc cut of one player);
* position plausibility was TESTED and REJECTED: rescaling guard / forward / center
  minute totals into the [p05, p95] range of real rotations (bounds from seasons <=
  2014, ``POSITION_BOUNDS``) lowered 2015-2026 top-5 identification 0.816 -> 0.802 and
  raised minutes MAE 8.04 -> 8.54 (listed positions are too coarse); a "<= 3 starters
  per position" rule lowered starter accuracy 0.777 -> 0.769. Position competition
  enters only through the model's ``depth_same_pos`` feature.

Water-filling leaves the 2015-2026 ranking identical to Wave 6 (top-5 0.816, top-8
0.880) and makes the documented contract (shares sum to exactly 5) hold for every team.
Per player: expected minutes, P(rotation) (>= 10 minutes; calibration table from seasons
<= 2014), expected starter (top five by expected minutes) and a usage role from last
season's usage share (``first_d1`` players: "unknown").
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TEAM_SHARE = 5.0
CAP = 1.0
# share of the 5.0 team share per position group, [p05, p95], seasons <= 2014
POSITION_BOUNDS = {"G": (0.87, 3.15), "F": (0.46, 2.35), "C": (0.0, 0.88)}
# P(>= 10 minutes in game 1) by expected-share bin (upper edges), seasons <= 2014
P_ROT_EDGES = (0.05, 0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 1.01)
P_ROT = (0.02, 0.06, 0.16, 0.40, 0.64, 0.84, 0.92, 0.96)


def pos_group(pos_g: float, pos_c: float) -> str:
    return "G" if pos_g > 0 else ("C" if pos_c > 0 else "F")


def waterfill(w: np.ndarray, total: float, cap: float = CAP) -> np.ndarray:
    """Shares proportional to ``w`` summing to ``total`` with each <= ``cap``."""
    w = np.clip(np.asarray(w, dtype=float), 0.0, None)
    if w.sum() <= 0 or total <= 0:
        return np.zeros_like(w)
    total = min(total, cap * (w > 0).sum())
    s = np.zeros_like(w)
    free = w > 0
    rem = total
    for _ in range(len(w) + 1):
        f = rem / w[free].sum()
        s[free] = w[free] * f
        over = free & (s > cap)
        if not over.any():
            break
        s[over] = cap
        free &= ~over
        rem = total - s[~free].sum()
        if not free.any() or rem <= 0:
            break
    return s


def allocate_team(raw: np.ndarray, groups: np.ndarray | None = None) -> np.ndarray:
    """200 minutes, <= 40 per player (``groups`` kept for the record; position bounds
    were tested and rejected, see module docstring)."""
    return waterfill(raw, TEAM_SHARE)


def allocate(df: pd.DataFrame, raw_col: str = "share_raw") -> pd.DataFrame:
    """``df``: team_id, pos_g, pos_c, ``raw_col`` (+ prev_usage, first_d1). Adds share,
    minutes, p_rotation, p_start (expected starter flag as probability 0/1 from the
    rank rule), usage_role."""
    out = df.copy()
    out["pos_group"] = [pos_group(g, c) for g, c in zip(out["pos_g"], out["pos_c"], strict=True)]
    out["share"] = 0.0
    for _t, idx in out.groupby("team_id").groups.items():
        x = out.loc[idx]
        out.loc[idx, "share"] = allocate_team(x[raw_col].to_numpy(), x["pos_group"].to_numpy())
    out["minutes"] = 40.0 * out["share"]
    out["p_rotation"] = np.array(P_ROT)[np.searchsorted(P_ROT_EDGES, out["share"].to_numpy())
                                         .clip(0, len(P_ROT) - 1)]  # fmt: skip
    rank = out.groupby("team_id")["share"].rank(method="first", ascending=False)
    out["expected_starter"] = rank <= 5
    u = out.get("prev_usage", pd.Series(0.0, index=out.index)).fillna(0.0)
    fd = out.get("first_d1", pd.Series(0.0, index=out.index)) > 0
    out["usage_role"] = np.select(
        [fd, u >= 0.055, u >= 0.035, u > 0], ["unknown", "primary", "secondary", "role"], "minimal"
    )
    return out


def sanity(rot: pd.DataFrame, departed: set[str] | None = None,
           exhausted: set[str] | None = None) -> pd.DataFrame:  # fmt: skip
    """Per-team structural checks of an allocated rotation (before any game)."""
    rows = []
    for t, x in rot.groupby("team_id"):
        rows.append({
            "team_id": t,
            "minutes_total": float(x["minutes"].sum()),
            "max_minutes": float(x["minutes"].max()),
            "n_players": int(len(x)),
            "n_rotation_10min": int((x["minutes"] >= 10).sum()),
            "duplicates": int(x["player_id"].duplicated().sum()),
            "departed_listed": int(x["player_id"].isin(departed or set()).sum()),
            "exhausted_listed": int(x["player_id"].isin(exhausted or set()).sum()),
            "starters": int(x["expected_starter"].sum()),
        })  # fmt: skip
    s = pd.DataFrame(rows)
    if len(s):
        s["ok"] = (
            s["minutes_total"].between(199.0, 201.0) & (s["max_minutes"] <= 40.0 + 1e-6)
            & (s["duplicates"] == 0) & (s["departed_listed"] == 0) & (s["starters"] == 5)
            & (s["n_players"] >= 5)
        )  # fmt: skip
    return s
