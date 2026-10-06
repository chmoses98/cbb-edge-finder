"""Immutable prospective PURE_BASKETBALL projection archive (2026-27 onward).

Each run:
1. refreshes the free bulk inputs (SportsDataverse current-season files are re-downloaded
   into dated, immutable bronze paths; earlier seasons come from the permanent cache);
2. rebuilds silver and computes pregame states with information available before
   ``as_of`` only;
3. applies the frozen PURE model artifact (``models/pure/<version>.json``) to every D-I
   game starting within the horizon;
4. writes one JSON record per (game, run) to the archive — never overwriting.

No market data is read anywhere in this module (CI-enforced). Kalshi/lines are joined
later by the downstream comparison step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from cbb_edge import __version__
from cbb_edge.app.sift import (
    Freshness,
    GameRef,
    ModelRef,
    Projection,
    SiftProjection,
    TeamRatings,
    TeamRef,
    validate,
)
from cbb_edge.app.wave3_live import checkpoint_inputs, wave3_inputs
from cbb_edge.backtest.walkforward import EngineConfig, run
from cbb_edge.data.http import data_dir
from cbb_edge.data.ids.teams import _registry
from cbb_edge.features.context import rest_days, season_phase
from cbb_edge.features.shot_profile import enrich_team_games
from cbb_edge.model.arms import FACTORS, attach_games
from cbb_edge.model.families import assert_pure_frame
from cbb_edge.model.pure import load_pure_silver
from cbb_edge.players.rapm import RapmConfig, player_team_features
from cbb_edge.research import blocks

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "models" / "pure"


class ArchiveOverwriteError(FileExistsError):
    """An archive record for this (game, run) already exists — archives are append-only."""


LEGACY_LAYOUT_VERSION = "pure-0.2.0"  # archived at <root>/<season>/... (no version dir)


def active_models() -> dict[str, Any]:
    """``models/pure/active.json``: the incumbent and any shadow challengers. Every
    active model is projected and archived on every run (challengers in shadow)."""
    p = MODEL_DIR / "active.json"
    if not p.exists():
        return {"incumbent": LEGACY_LAYOUT_VERSION, "challengers": []}
    return json.loads(p.read_text())


def load_model(version: str | None = None) -> dict[str, Any]:
    """Frozen artifact by version; default = the active INCUMBENT (never 'latest file')."""
    version = version or active_models()["incumbent"]
    path = MODEL_DIR / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"no frozen PURE model {version} in {MODEL_DIR}")
    return json.loads(path.read_text())


def apply_linear(X: pd.DataFrame, spec: dict[str, Any]) -> np.ndarray:
    cols = spec["features"]
    mu = np.array(spec["mean"])
    sd = np.array(spec["sd"])
    Z = (X[cols].to_numpy(dtype=float) - mu) / sd
    return Z @ np.array(spec["coef"]) + float(spec["intercept"])


def feature_frame(
    model: dict[str, Any],
    season: int,
    as_of: pd.Timestamp,
    warmup: int = 8,
    share_adjust: Any = None,
    reconstruction: str = "auto",
    preseason_shares: dict | None = None,
) -> pd.DataFrame:
    """Pregame states + PURE feature blocks for every game of ``season`` (info < as_of).

    ``reconstruction``: ``auto`` replays only ``season`` from the research
    season-boundary checkpoint when one exists (canonical, exact), else rebuilds from a
    ``warmup``-season replay; ``checkpoint`` requires a checkpoint; ``warmup`` forces
    the old path (diagnostics)."""
    games, tg = load_pure_silver()
    tg = tg[tg["available_at"] < as_of]
    games_info = games.copy()
    late = games_info["available_at"] >= as_of
    games_info.loc[late, ["home_score", "away_score"]] = pd.NA
    games_info.loc[late, "completed"] = False
    tg_e = enrich_team_games(tg)
    ec = model["engine_config"]
    cfg = EngineConfig(
        lam=ec["lam"],
        prior_regress=ec["prior_regress"],
        recency_tau_days=ec["recency_tau_days"],
        stats=tuple(ec["stats"]),
    )
    seasons = list(range(season - warmup, season + 1))
    wave3 = "team_prior_hook" in model
    ck = _checkpoint(model, season) if reconstruction != "warmup" else None
    if (reconstruction == "checkpoint" or model.get("requires_checkpoint")) and ck is None:
        raise FileNotFoundError(f"no checkpoint for {model['version']} boundary {season - 1}")
    if wave3 and ck is not None:  # canonical: replay season from the research boundary
        st, pf3 = checkpoint_inputs(
            model,
            ck,
            season,
            games_info,
            tg_e,
            as_of,
            cfg,
            share_adjust=share_adjust,
            unadjusted="avail_delta" in model.get("extra_blocks", []),
            preseason_shares=preseason_shares,
        )
        pf12 = checkpoint_inputs.unadjusted  # type: ignore[attr-defined]
    elif wave3:  # pure-0.3.0+: roster/conference-anchored engine + provider player features
        st, pf3 = wave3_inputs(
            model, season, games_info, tg_e, as_of, cfg, warmup, share_adjust=share_adjust
        )
    elif ck is not None:
        from cbb_edge.data.ids.teams import _registry

        st = run(
            games_info,
            tg_e,
            [season],
            cfg,
            verbose=False,
            initial_end=ck.engine(sorted(_registry()["team_id"].tolist())),
        )
    else:
        st = run(games_info, tg_e, seasons, cfg, verbose=False)
    df = attach_games(st[st["season"] == season], games_info)
    parts = [blocks.base_block(df)]
    feats = set(model["margin"]["features"]) | set(model["total"]["features"])
    if wave3:
        df = df.merge(pf3.drop(columns=["season"]), on="game_id", how="left")
        parts = [blocks.base_block(df), blocks.player_block(df)]
    elif any(f.startswith(("p_", "depth_", "roster_known")) for f in feats):
        pg = pd.read_parquet(
            data_dir() / "silver" / "player_games.parquet",
            columns=["season", "game_id", "team_id", "player_id", "min", "available_at"],
        )
        pg = pg[pg["available_at"] < as_of].drop(columns=["available_at"])
        rc = RapmConfig(**model["rapm_config"])
        if ck is not None:
            pf = player_team_features(
                [season],
                games_info,
                pg,
                rc,
                verbose=False,
                initial_prev=ck.rapm("base", season - 1),
            )
        else:
            pf = player_team_features(
                list(range(season - 4, season + 1)), games_info, pg, rc, verbose=False
            )
        df = df.merge(pf.drop(columns=["season"]), on="game_id", how="left")
        parts = [blocks.base_block(df), blocks.player_block(df)]
    if any(f.startswith(("rim_", "mid_", "ast_share")) for f in feats):
        parts.append(blocks.shot_block(df))
    if any(
        f.startswith(("h_rest", "a_rest", "rest_diff", "h_b2b", "a_b2b", "ph_", "team_hca"))
        for f in feats
    ):
        df = df.merge(rest_days(games), on="game_id", how="left")
        ctx = pd.concat(
            [df[["h_rest", "a_rest", "rest_diff", "h_b2b", "a_b2b"]].fillna(7.0), season_phase(df)],
            axis=1,
        )
        hca = model.get("team_hca", {})
        ctx["team_hca"] = np.where(df["L"] == 1, df["home_team_id"].map(hca).fillna(0.0), 0.0)
        parts.append(blocks.context_block(df, ctx))
    if "mismatch" in model.get("extra_blocks", []):
        parts.append(blocks.mismatch_block(df))
    if "shooting" in model.get("extra_blocks", []):  # pure-0.4.0+: B17 shooting skill
        from cbb_edge.players import shooting

        pgs = pd.read_parquet(data_dir() / "silver" / "player_games.parquet")
        pgs = pgs[pgs["team_id"].notna() & (pgs["available_at"] < as_of)]
        sp = shooting.ShootingPrior(**model["shooting_prior"])
        if ck is not None:
            xs = shooting.player_games(pgs[pgs["season"] == season])
            sf = shooting.live_features(
                xs, games_info, sp, season, ck.shooting_careers(), ck.shooting_prev_team()
            )
        else:
            sf = shooting.live_features(shooting.player_games(pgs), games_info, sp, season)
        parts.append(blocks.shooting_block(df, sf, model.get("shooting_fill")))
    if "avail_delta" in model.get("extra_blocks", []):  # pure-0.5.0+: B23
        df12 = attach_games(st[st["season"] == season], games_info)
        df12 = df12.merge(pf12.drop(columns=["season"]), on="game_id", how="left")
        parts.append(blocks.b23_block(df, df12))
    if "possession" in model.get("extra_blocks", []):  # pure-0.5.0+: B24
        from cbb_edge.app.possession_live import possession_frame

        if "game_date_et" not in df:
            df["game_date_et"] = df["game_id"].map(games.set_index("game_id")["game_date_et"])
        pfr = possession_frame(model, ck, season, as_of, games_info, df)
        parts.append(blocks.b24_block(df, pfr))
    X = blocks.combine(*parts)
    assert_pure_frame(X, "prospective features")
    out = pd.concat(
        [df.reset_index(drop=True), X.reset_index(drop=True).loc[:, ~X.columns.isin(df.columns)]],
        axis=1,
    )
    out.attrs["reconstruction"] = (
        {"mode": "checkpoint", "boundary": season - 1, "sha256": ck.manifest["sha256"]}
        if ck is not None
        else {"mode": "warmup", "warmup_seasons": warmup}
    )
    return out


def _checkpoint(model: dict[str, Any], season: int) -> Any:
    from cbb_edge.app import checkpoints

    if checkpoints.Checkpoint.exists(model["version"], season - 1):
        return checkpoints.Checkpoint(model["version"], season - 1)
    return None


def availability_overlay(
    season: int,
    as_of: pd.Timestamp,
    model: dict[str, Any],
    base: list[dict[str, Any]],
    overrides: dict[tuple[int, str], float],
    captured: dict[int, str],
    horizon_h: float = 30.0,
) -> list[dict[str, Any]]:
    """P-AVAIL (PROSPECTIVE_ONLY): re-project games that have reported player statuses,
    with the status P(plays) applied through the replacement model to the player
    features. Written as version ``<version>+avail``; base records are untouched."""
    from cbb_edge.app.wave3_live import availability_adjuster

    if "team_prior_hook" not in model or not overrides or not base:
        return []
    adj = availability_adjuster(model, overrides)
    recs = project_window(season, as_of, horizon_h, model=model, share_adjust=adj)
    by_game = {r["game"]["espn_game_id"]: r for r in base}
    out = []
    for r in recs:
        gid = r["game"]["espn_game_id"]
        changes = [c for (g, _t), lst in adj.log.items() if g == gid for c in lst]
        b = by_game.get(gid)
        if not changes or b is None:
            continue
        r["model"]["version"] = f"{model['version']}+avail"
        r["availability"] = {
            "component": "P-AVAIL (PROSPECTIVE_ONLY)",
            "status_map": "cbb_edge.availability.espn.P_PLAY (preregistered WAVE4.md)",
            "capture_as_of": captured.get(gid),
            "margin_base": b["projection"]["margin"],
            "total_base": b["projection"]["total"],
            "players": changes,
        }
        out.append(r)
    return out


# Wave 10 window override (operations only; None = the frozen rule exactly). Set by
# ``window_override`` around a production run so every caller of ``project_window`` in
# that run (incumbent, challengers, the P-ROSTER-1 and availability overlays) sees the
# same game set without any change to their code:
# * ``extra``   games whose LISTED tip has passed but whose time is not announced (ESPN
#               "TBD" placeholder) and whose live game state, observed after ``as_of``,
#               is still "pre" (cbb_edge/ops/schedule_state.py);
# * ``exclude`` games whose live state shows they have started, been postponed or been
#               cancelled: never projected, whatever their listed tip says.
_WINDOW: dict[str, frozenset[int]] = {}


class window_override:  # noqa: N801  (context manager)
    def __init__(self, extra: set[int] | None = None, exclude: set[int] | None = None):
        self.new = {"extra": frozenset(extra or ()), "exclude": frozenset(exclude or ())}

    def __enter__(self) -> window_override:
        self.old = dict(_WINDOW)
        _WINDOW.clear()
        _WINDOW.update(self.new)
        return self

    def __exit__(self, *exc: object) -> None:
        _WINDOW.clear()
        _WINDOW.update(self.old)


def select_window(df: pd.DataFrame, as_of: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """The frozen rule (listed tip in (as_of, end]) plus the Wave 10 override."""
    keep = (df["start_time_utc"] > as_of) & (df["start_time_utc"] <= end)
    if _WINDOW:
        gid = df["game_id"].astype("int64")
        keep = (keep | gid.isin(_WINDOW.get("extra", frozenset()))) & ~gid.isin(
            _WINDOW.get("exclude", frozenset())
        )
    return df[keep]


def project_window(
    season: int,
    as_of: pd.Timestamp,
    horizon_h: float = 30.0,
    model: dict[str, Any] | None = None,
    share_adjust: Any = None,
    preseason_shares: dict | None = None,
) -> list[dict[str, Any]]:
    model = model or load_model()
    df = feature_frame(
        model, season, as_of, share_adjust=share_adjust, preseason_shares=preseason_shares
    )
    recon = df.attrs.get("reconstruction")
    end = as_of + pd.Timedelta(hours=horizon_h)
    win = select_window(df, as_of, end)
    if win.empty:
        return []
    margin = apply_linear(win, model["margin"])
    total = apply_linear(win, model["total"])
    a, b = model["wp_logit"]
    wp = 1 / (1 + np.exp(-(a + b * margin)))
    sig_m = np.array(
        [
            model["sigma_margin_by_games"].get(str(min(int(g), 11)), model["sigma_margin"])
            for g in np.minimum(win["h_games_seen"], win["a_games_seen"])
        ]
    )
    sig_t = model["sigma_total"]
    reg = _registry().set_index("team_id")
    out = []
    for i, (_, r) in enumerate(win.iterrows()):
        poss = float(r["mu_tempo"] + r["h_off_tempo"] + r["a_off_tempo"])
        hs, as_ = (total[i] + margin[i]) / 2, (total[i] - margin[i]) / 2

        def team(tid: str, espn: Any) -> TeamRef:
            row = reg.loc[tid]
            conf = row.conference_latest if isinstance(row.conference_latest, str) else None
            return TeamRef(
                tid, int(espn) if pd.notna(espn) else None, str(row.espn_display_name), conf
            )

        def ratings(side: str, r: pd.Series = r) -> TeamRatings:
            return TeamRatings(
                adj_off=float(r["mu_eff"] + r[f"{side}_off_eff"]),
                adj_def=float(r["mu_eff"] + r[f"{side}_def_eff"]),
                adj_tempo=float(r["mu_tempo"] + 2 * r[f"{side}_off_tempo"]),
                four_factors={
                    f"{x}_{k}": float(r[f"mu_{x}"] + r[f"{side}_{k}_{x}"])
                    for x in FACTORS
                    for k in ("off", "def")
                },
            )

        player_ctx = None
        if "h_p_off" in r:
            player_ctx = {
                side: {
                    "player_off": float(r[f"{side}_p_off"]),
                    "player_def": float(r[f"{side}_p_def"]),
                    "rotation_known": bool(r[f"{side}_roster_known"]),
                    "games_seen": int(r[f"{side}_games_seen_p"]),
                }
                for side in ("h", "a")
            }
        rec = SiftProjection(
            game=GameRef(
                f"G{int(r['game_id'])}",
                int(r["game_id"]),
                season,
                pd.Timestamp(r["start_time_utc"]).isoformat(),
                "neutral" if r["neutral_site"] else "home",
            ),
            home=team(r["home_team_id"], None),
            away=team(r["away_team_id"], None),
            projection=Projection(
                poss,
                float((total[i] + margin[i]) / 2 / poss),
                float((total[i] - margin[i]) / 2 / poss),
                float(hs),
                float(as_),
                float(margin[i]),
                float(total[i]),
                float(np.clip(wp[i], 1e-4, 1 - 1e-4)),
                float(sig_m[i]),
                float(sig_t),
            ),
            model=ModelRef(model["name"], model["version"], model["arm"], "research"),
            freshness=Freshness(
                as_of.isoformat(),
                int(r["info_rows"]),
                int(r["h_games_seen"]),
                int(r["a_games_seen"]),
                model.get("sources", []),
            ),
            ratings={"home": ratings("h"), "away": ratings("a")},
            player_context=player_ctx,
            market=None,  # joined downstream only
        ).to_dict()
        rec["prospective"] = {
            "as_of": as_of.isoformat(),
            "code_version": __version__,
            "model_sha256": model.get("sha256"),
            "reconstruction": recon,
            "spread_cover_prob_fn": "Phi((margin - line) / margin_sd)",
            "home_win_prob_normal": float(norm.cdf(margin[i] / sig_m[i])),
        }
        validate(rec)
        out.append(rec)
    return out


def write_archive(records: list[dict[str, Any]], root: Path) -> dict[str, int]:
    """Append-only: one file per (game, run). Refuses to overwrite an existing record."""
    written = 0
    for rec in records:
        gid = rec["game"]["game_id"]
        date = rec["game"]["start_time_utc"][:10]
        stamp = rec["prospective"]["as_of"].replace(":", "").replace("+0000", "Z")
        version = rec.get("model", {}).get("version", LEGACY_LAYOUT_VERSION)
        base = (
            root
            if version in (LEGACY_LAYOUT_VERSION, "0.2.0")
            else root / version.replace("+", "_")
        )
        path = base / str(rec["game"]["season"]) / date / gid / f"{stamp}.json"
        blob = json.dumps(rec, sort_keys=True, allow_nan=False)
        if path.exists():
            if (
                hashlib.sha256(path.read_bytes()).hexdigest()
                != hashlib.sha256(blob.encode()).hexdigest()
            ):
                raise ArchiveOverwriteError(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blob)
        written += 1
    return {"records": len(records), "written": written}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--as-of", default=None, help="UTC timestamp; default now")
    ap.add_argument("--horizon-h", type=float, default=30.0)
    ap.add_argument("--out", default="projections_out")
    a = ap.parse_args()
    as_of = pd.Timestamp(a.as_of) if a.as_of else pd.Timestamp(datetime.now(UTC))
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    recs = project_window(a.season, as_of, a.horizon_h)
    res = write_archive(recs, Path(a.out))
    print(json.dumps({"as_of": as_of.isoformat(), **res}))


if __name__ == "__main__":
    main()
