"""Build season-boundary checkpoints from the RESEARCH replays (Wave 5, Priority 0).

    python scripts/research/build_checkpoints.py engine <base|b15|b16b>
    python scripts/research/build_checkpoints.py chain <base|rot|b12>
    python scripts/research/build_checkpoints.py write [boundary ...]   # default 2025 2026

``engine`` / ``chain`` re-run the exact research replays (same code, same inputs),
capture every season's end state, and VERIFY that the re-run reproduces the cached
research outputs (states_shot / states_b15 / states_b16b, player_features / pf_rot /
pf_b12). ``write`` assembles per-version checkpoint directories under
models/pure/checkpoints/<version>/boundary_<B>/ with a content-hash manifest.
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pandas as pd

from cbb_edge.app import checkpoints as ck
from cbb_edge.backtest.walkforward import run
from cbb_edge.data.http import data_dir
from cbb_edge.players import box_prior, preseason, shooting
from cbb_edge.players.rapm import player_team_features

sys.path.insert(0, str(Path(__file__).parent))
import run_wave2 as w2  # noqa: E402
import run_wave3 as w3  # noqa: E402
import run_wave4 as w4  # noqa: E402

RAW = data_dir() / "research" / "wave5" / "ckpt_raw"
OUT = Path("research/wave5")


def _cmp(new: pd.DataFrame, old: pd.DataFrame, key: str = "game_id") -> float:
    a = new.set_index(key)
    b = old.set_index(key)
    ids = a.index.intersection(b.index)
    cols = [
        c
        for c in a.columns
        if c in b.columns and pd.api.types.is_numeric_dtype(a[c]) and c != "season"
    ]
    d = (a.loc[ids, cols] - b.loc[ids, cols]).abs().max().max()
    return float(d)


def engine_stage(name: str) -> None:
    ctx = w3.Ctx()
    hook = None
    if name == "b15":
        from cbb_edge.players import team_prior as tp

        eng = json.loads((w3.OUT / "engine_b15.json").read_text())["coefs"]
        coefs = tp.PriorCoefficients(
            components=tuple(eng["components"]), pre=eng["pre"], obs=eng["obs"], n=eng["n"]
        )
        strength = tp.team_day_strength(w3.pf_variant(ctx, "rot"), ctx.games)
        ca = tp.conference_anchor(ctx.finals9, ctx.games)
        hook = tp.TeamPriorHook(coefs, strength, ctx.pre(), ca)
        ref = w3.WORK / "states_b15.parquet"
    elif name == "b16b":
        hook = w4.b16b_hook(ctx, 400.0)
        ref = w4.WORK / "states_b16b.parquet"
    else:
        ref = w2.WORK / "states_shot.parquet"
    ends: dict = {}
    st = run(
        ctx.games, ctx.tg_e, w2.SEASONS, ctx.cfg, verbose=False, prior_hook=hook, end_fits_out=ends
    )
    diff = _cmp(st, pd.read_parquet(ref))
    RAW.mkdir(parents=True, exist_ok=True)
    with open(RAW / f"engine_{name}.pkl", "wb") as fh:
        pickle.dump(ends, fh)
    rep = {"engine": name, "max_abs_diff_vs_cached_research_states": diff}
    print(rep, flush=True)
    (RAW / f"engine_{name}.json").write_text(json.dumps(rep))


def chain_stage(name: str) -> None:
    ctx = w3.Ctx()
    pg = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
    pg = pg[pg["team_id"].notna() & (pg["min"].fillna(0) > 0)]
    pg_min = pg[["season", "game_id", "team_id", "player_id", "min"]]
    ends: dict = {}
    if name == "base":
        pf = player_team_features(
            list(range(2011, 2027)),
            ctx.games,
            pg_min,
            w2.rapm_cfg(),
            verbose=False,
            end_ratings=ends,
        )
        ref = w2.WORK / "player_features.parquet"
    elif name == "rot":
        pf = player_team_features(
            list(range(2011, 2027)),
            ctx.games,
            pg_min,
            w2.rapm_cfg(),
            verbose=False,
            update_ratings=False,
            end_ratings=ends,
        )
        ref = w3.WORK / "pf_rot.parquet"
    else:
        prov = box_prior.PlayerPriorProvider(
            ctx.ps, pg, ctx.team_net, **w3.PF_VARIANTS["b12"]["provider"]
        )
        pf = player_team_features(
            list(range(2011, 2027)),
            ctx.games,
            pg_min,
            w2.rapm_cfg(),
            verbose=False,
            prior_provider=prov,
            end_ratings=ends,
        )
        ref = w3.WORK / "pf_b12.parquet"
    diff = _cmp(pf, pd.read_parquet(ref))
    RAW.mkdir(parents=True, exist_ok=True)
    with open(RAW / f"chain_{name}.pkl", "wb") as fh:
        pickle.dump(ends, fh)
    rep = {"chain": name, "max_abs_diff_vs_cached_research_pf": diff}
    print(rep, flush=True)
    (RAW / f"chain_{name}.json").write_text(json.dumps(rep))


NEEDS = {
    "pure-0.2.0": {"engine": "base", "chains": {"base": [0]}},
    "pure-0.3.0": {
        "engine": "b15",
        "chains": {"rot": [0], "b12": [-1, 0]},
        "finals": True,
        "preseason": True,
    },
    "pure-0.4.0": {
        "engine": "b16b",
        "chains": {"rot": [0], "b12": [-1, 0]},
        "finals": True,
        "preseason": True,
        "shooting": True,
    },
    "pure-0.5.0": {
        "engine": "b16b",
        "chains": {"rot": [0], "b12": [-1, 0]},
        "finals": True,
        "preseason": True,
        "shooting": True,
        "possession": True,
    },
}


def possession_state(boundaries: list[int]) -> dict:
    """Research player possession-model state at each boundary (run_wave5 inputs)."""
    import run_wave5 as w5

    from cbb_edge.players import possession as pos

    pr = w5.load_prior()
    x, tg, shots = w5.load_rows()
    ctx = w3.Ctx()
    x = x[x["season"] <= max(boundaries)]
    pret = w5.p_return(ctx.ps, list(range(w5.FIRST, max(boundaries) + 2)))
    pos.team_profiles(x, pr, ctx.games, pret)
    ev = pos.team_profiles.end_values  # type: ignore[attr-defined]
    ew = pos.team_profiles.end_weights  # type: ignore[attr-defined]
    act = pd.read_parquet(w5.WORK / "team_actuals.parquet")
    lg = act[act["pbp_fga"].fillna(0) > 0].groupby("season")[["rim_a", "t3_a", "pbp_fga"]].sum()
    out = {}
    for b in boundaries:
        vals = [(p_, s_, v_) for (p_, s_), v_ in ev.items() if b - 2 <= s_ <= b]
        evt = pd.DataFrame([v_ for *_, v_ in vals], columns=list(pos.RATES))
        evt.insert(0, "season", [s_ for _, s_, _ in vals])
        evt.insert(0, "player_id", [p_ for p_, *_ in vals])
        ewt = pd.DataFrame(
            [(t_, s_, q, w) for (t_, s_), d in ew.items() if s_ == b for q, w in d.items()],
            columns=["team_id", "season", "player_id", "w"],
        )
        prt = pd.DataFrame(
            [(q, t_, s_, v_) for (q, t_, s_), v_ in pret.items() if s_ == b + 1],
            columns=["player_id", "team_id", "season", "p"],
        )
        r = lg.loc[b]
        out[b] = {
            "careers": pos.career_totals(x, b),
            "end_values": evt,
            "end_weights": ewt,
            "p_ret": prt,
            "league": {str(b): [float(r.rim_a / r.pbp_fga), float(r.t3_a / r.pbp_fga)]},
        }
    return out


def write_stage(boundaries: list[int]) -> None:
    from cbb_edge.data.ids.teams import _registry

    ctx = w3.Ctx()
    team_ids = sorted(_registry()["team_id"].tolist())
    sx = None
    poss = None
    for v, need in NEEDS.items():
        for b in boundaries:
            d = ck.path_for(v, b)
            if (d / "manifest.json").exists():
                print(f"{d} exists: checkpoints are immutable, skipping", flush=True)
                continue
            d.mkdir(parents=True, exist_ok=True)
            with open(RAW / f"engine_{need['engine']}.pkl", "rb") as fh:
                ck.save_engine(pickle.load(fh)[b], team_ids, d / "engine_end.npz")
            for chain, offs in need["chains"].items():
                with open(RAW / f"chain_{chain}.pkl", "rb") as fh:
                    ends = pickle.load(fh)
                for o in offs:
                    ck.save_rapm(ends[b + o], d / f"rapm_{chain}_{b + o}.parquet")
            if need.get("finals"):
                ctx.finals9[ctx.finals9["season"] <= b].to_parquet(
                    d / "finals.parquet", index=False
                )
            if need.get("preseason"):
                pre = preseason.preseason_team_features(ctx.ps, b + 1)
                pre.to_parquet(d / "preseason.parquet", index=False)
            if need.get("shooting"):
                if sx is None:
                    pgs = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
                    sx = shooting.player_games(pgs[pgs["team_id"].notna()])
                    sp = shooting.ShootingPrior(
                        **{
                            k: v_
                            for k, v_ in json.loads(
                                (w4.OUT / "shooting_prior.json").read_text()
                            ).items()
                            if k != "fit"
                        }
                    )
                    shooting.team_features(sx[sx["season"] <= max(boundaries)], ctx.games, sp)
                    prev_all = shooting.team_features.prev_team  # type: ignore[attr-defined]
                shooting.career_totals(sx, b).to_parquet(
                    d / "shooting_careers.parquet", index=False
                )
                rows = [
                    {"team_id": t, "season": s_, "typ": k, "value": val}
                    for (t, s_), dd in prev_all.items()
                    if s_ == b
                    for k, val in dd.items()
                ]
                pd.DataFrame(rows).to_parquet(d / "shooting_prev_team.parquet", index=False)
            if need.get("possession"):
                if poss is None:
                    poss = possession_state(boundaries)
                st = poss[b]
                st["careers"].to_parquet(d / "poss_careers.parquet", index=False)
                st["end_values"].to_parquet(d / "poss_end_values.parquet", index=False)
                st["end_weights"].to_parquet(d / "poss_end_weights.parquet", index=False)
                st["p_ret"].to_parquet(d / "poss_p_ret.parquet", index=False)
                (d / "poss_league.json").write_text(json.dumps(st["league"]))
            verif = {
                k: json.loads((RAW / f"{k}.json").read_text())
                for k in [f"engine_{need['engine']}", *[f"chain_{c}" for c in need["chains"]]]
            }
            man = ck.write_manifest(
                d,
                {
                    "version": v,
                    "boundary_season": b,
                    "target_season": b + 1,
                    "source": "research replays (build_checkpoints.py)",
                    "verification": verif,
                },
            )
            print(v, b, man["sha256"], flush=True)


if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "engine":
        engine_stage(sys.argv[2])
    elif stage == "chain":
        chain_stage(sys.argv[2])
    else:
        write_stage([int(x) for x in sys.argv[2:]] or [2025, 2026])
