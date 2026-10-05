"""Competitiveness-weighted team efficiency (B13): garbage-time possessions down-weighted.

Uses the game's own NCAA possession data (``is_garbage_time`` flag from the play-by-play
possession files). That information exists only after the game is final — the same
timestamp as the box score it replaces — so the walk-forward information set is
unchanged (timestamp-safe).
"""

from __future__ import annotations

import pandas as pd

from cbb_edge.players.stints import stints_path

GARBAGE_WEIGHT = 0.3  # same fixed constant as the wave-2 RAPM (not tuned)


def garbage_weighted_tg(
    tg: pd.DataFrame, games: pd.DataFrame, w: float = GARBAGE_WEIGHT
) -> pd.DataFrame:
    """Team-game points per possession with garbage-time possessions down-weighted.

    Uses the game's own NCAA possession data (flag ``is_garbage_time``), available only
    after the game — the same timestamp as the box score it replaces. Applied when the
    stint possessions match the box-score possession estimate within 15%; otherwise
    the raw box value is kept.
    """
    parts = []
    for s in sorted(tg["season"].unique()):
        p = stints_path(int(s))
        if not p.exists():
            continue
        st = pd.read_parquet(p, columns=["game_id", "off_home", "poss", "pts", "garbage"])
        g = st.groupby(["game_id", "off_home"]).agg(
            poss=("poss", "sum"), pts=("pts", "sum"), garb=("garbage", "sum")
        )
        # points in garbage time: stint points pro rata to garbage possessions
        st["gpts"] = st["pts"] * st["garbage"] / st["poss"].clip(lower=1)
        g["gpts"] = st.groupby(["game_id", "off_home"])["gpts"].sum()
        parts.append(g.reset_index())
    if not parts:
        return tg
    g = pd.concat(parts)
    g["ppp_c"] = (g["pts"] - (1 - w) * g["gpts"]) / (g["poss"] - (1 - w) * g["garb"]).clip(lower=1)
    hm = games[["game_id", "home_espn_id"]]
    out = tg.merge(hm, on="game_id", how="left")
    out["off_home"] = out["team_espn_id"] == out["home_espn_id"]
    own = g[["game_id", "off_home", "ppp_c", "poss"]].rename(columns={"poss": "st_poss"})
    out = out.merge(own, on=["game_id", "off_home"], how="left")
    opp = g[["game_id", "off_home", "ppp_c"]].rename(columns={"ppp_c": "opp_ppp_c"})
    opp["off_home"] = ~opp["off_home"]
    out = out.merge(opp, on=["game_id", "off_home"], how="left")
    ok = out["ppp_c"].notna() & out["opp_ppp_c"].notna()
    ok &= (out["st_poss"] / out["poss"]).between(0.85, 1.15)
    out.loc[ok, "ppp"] = out.loc[ok, "ppp_c"]
    out.loc[ok, "opp_ppp"] = out.loc[ok, "opp_ppp_c"]
    print(f"  garbage weighting applied to {ok.mean():.1%} of team-games", flush=True)
    return out.drop(columns=["home_espn_id", "off_home", "ppp_c", "opp_ppp_c", "st_poss"])
