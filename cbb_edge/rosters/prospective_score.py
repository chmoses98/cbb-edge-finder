"""Prospective scorer for P-ROSTER-1 (Wave 8). Deterministic, read-only, append-only output.

Scores ``pure-0.5.0+roster`` against the frozen ``pure-0.5.0`` base under the LOCKED
Wave 7 protocol (``research/hypotheses/WAVE7.md`` section 7). The incumbent
``pure-0.2.0`` is carried as a reference column. Nothing here can change an archived
projection, a P-ROSTER-1 rule, the rotation algorithm or the continuity formula: all
inputs are archived records read after the fact.

Inputs (all local, already fetched):

* projection records from the ``projections-archive`` checkout (every file is hashed;
  the scored record of each version is its latest record with ``as_of`` < tip);
* results: espn_game_id, result_margin, result_total (completed games only);
* optional market: espn_game_id, mkt_margin (benchmark only; the market gap is a
  preregistered downstream metric; this module never imports market code: the CLI
  ``scripts/prospective/score_proster.py`` builds the column);
* the ``roster-archive`` checkout (truth snapshots, P-ROSTER states);
* optional box scores (played and DNP rows) for rotation validation and realized
  false inclusion;
* ``models/rosters/history_2026.parquet``.

Outputs (``score(...)`` returns frames; ``write(...)`` writes them sorted, so two runs
over the same inputs are byte-identical):

* ``paired_games.csv``  one row per game with base, roster and incumbent pregame
  records: projections, errors (signed, absolute, squared), log loss, paired
  differences, the frozen component split (a) / (b), snapshot provenance and hashes;
* ``team_games.csv``    one row per (game, side): team game number (games seen + 1),
  team-perspective errors, confidence, turnover inputs, freshness, disagreement,
  opponent quality, site;
* ``summary.json`` + ``dashboard.md``  PRIMARY = preregistered slices (game 1 = min
  games seen 0, games 2-3 = min games seen 1-2); DIAGNOSTIC = team game number 1 / 2 / 3
  (not pooled), strata, continuity-tail buckets, newcomer quantiles. Sample size first.

Error sign convention: error = actual - projected home margin (team view: the side's
own margin). Paired difference d = |e_roster| - |e_base| (negative = roster better).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE, ROSTER, INCUMBENT = "pure-0.5.0", "pure-0.5.0+roster", "pure-0.2.0"
VERSIONS = {"base": BASE, "roster": ROSTER, "incumbent": INCUMBENT}
PRIMARY_SLICES = {"game_1": (0, 0), "games_2_3": (1, 2)}  # WAVE7.md 7, min(games seen)
TEAM_GAME_NUMBERS = (1, 2, 3)  # Wave 8 diagnostic, never pooled
ADJ_BUCKETS = [(0, 2, "<2"), (2, 4, "2-4"), (4, 6, "4-6"), (6, np.inf, ">=6")]
APPEAR_SHARE = 0.10  # P-ROSTER-1's "expected to play" threshold (overlay.APPEAR_SHARE)
BOOT_REPS, BOOT_SEED = 2000, 20261106
MIN_N_CI, MIN_DAYS_CI = 20, 10  # WAVE8 D2 + Wave 9 amendment (a cluster bootstrap needs clusters)
HEADLINE_GAMES = {"game_1": (0, 0), "game_2": (1, 1), "game_3": (2, 2)}  # min games seen
REPO = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------- inputs
def load_records(root: Path, season: int) -> list[dict[str, Any]]:
    """Every projection record of ``season`` under ``root``, with its path and sha256."""
    out = []
    for f in sorted(Path(root).rglob("*.json")):
        b = f.read_bytes()
        try:
            r = json.loads(b)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("game", {}).get("season") != season:
            continue
        r["_path"] = str(f.relative_to(root))
        r["_sha256"] = hashlib.sha256(b).hexdigest()
        out.append(r)
    return out


def _ts(x: object) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def evidence_files(roster_archive: Path, stamp: str | None) -> dict[str, Path]:
    if not stamp or roster_archive is None:
        return {}
    day = f"{stamp[:4]}/{stamp[4:6]}/{stamp[6:8]}"
    t, o = roster_archive / "truth" / day, roster_archive / "official" / day
    out = {f"truth_{k}": t / f"{stamp}_{k}.{e}" for k, e in (
        ("records", "jsonl"), ("teams", "json"), ("proster_state", "json"),
        ("freshness", "jsonl"), ("conflicts", "jsonl"))}  # fmt: skip
    out |= {f"official_{k}": o / f"{stamp}_{k}.{e}" for k, e in (
        ("rows", "jsonl"), ("pages", "jsonl"), ("discovery", "json"))}  # fmt: skip
    return out


# --------------------------------------------------------------------------- pregame
def pregame(
    recs: list[dict[str, Any]], tips: dict[int, pd.Timestamp] | None = None
) -> pd.DataFrame:
    """The scored record of each (version, game): latest ``as_of`` strictly before tip.
    ``tips``: the ACTUAL tip times from the schedule (Wave 9). A rescheduled game is
    judged against when it really started, never the tip stored in the record."""
    rows = []
    for r in recs:
        v = r.get("model", {}).get("version")
        if v not in VERSIONS.values():
            continue
        g, p, f, pr = r["game"], r["projection"], r.get("freshness", {}), r.get("prospective", {})
        gid = int(g["espn_game_id"])
        tip = _ts((tips or {}).get(gid, g["start_time_utc"]))
        asof = _ts(pr.get("as_of"))
        if asof >= tip:
            continue
        ro = r.get("roster") or {}
        row = {
            "version": v, "espn_game_id": int(g["espn_game_id"]), "tip": tip, "as_of": asof,
            "home_team_id": r["home"]["team_id"], "away_team_id": r["away"]["team_id"],
            "site": g.get("site"), "gs_home": int(f.get("home_games_seen", 0)),
            "gs_away": int(f.get("away_games_seen", 0)), "margin": float(p["margin"]),
            "total": float(p["total"]), "home_wp": float(p["home_win_prob"]),
            "margin_sd": p.get("margin_sd"), "path": r["_path"], "sha256": r["_sha256"],
            "as_of_raw": str(pr.get("as_of")),
            "truth_files_sha256": ro.get("truth_files_sha256"),
            "code_version": pr.get("code_version"), "code_sha": pr.get("code_sha"),
            "model_sha256": pr.get("model_sha256"),
            "home_adj_off": (r.get("ratings") or {}).get("home", {}).get("adj_off"),
            "home_adj_def": (r.get("ratings") or {}).get("home", {}).get("adj_def"),
            "away_adj_off": (r.get("ratings") or {}).get("away", {}).get("adj_off"),
            "away_adj_def": (r.get("ratings") or {}).get("away", {}).get("adj_def"),
            "truth_snapshot": ro.get("truth_snapshot"),
            "truth_archive_commit": ro.get("truth_archive_commit"),
            "spec_sha256": ro.get("spec_sha256"),
            "margin_base_in_record": ro.get("margin_base"),
            "adj_a": ro.get("adjustment_a_input_substitution"),
            "adj_b": ro.get("adjustment_b_continuity"),
        }  # fmt: skip
        for side in ("home", "away"):
            s = (ro.get("sides") or {}).get(side) or {}
            for k in ("roster_confidence", "overlay_applied", "continuity_correction_applied",
                      "truth_cont", "expected_returning_share", "tr_prev", "first_d1",
                      "proj_min_returning", "proj_min_transfer", "proj_min_unseen"):  # fmt: skip
                row[f"{side}_{k}"] = s.get(k)
            row[f"{side}_rotation"] = [(e["player_id"], e["share"]) for e in
                                       s.get("expected_rotation") or []]  # fmt: skip
        rows.append(row)
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d = d.sort_values(["version", "espn_game_id", "as_of", "path"])
    return d.groupby(["version", "espn_game_id"], as_index=False).tail(1).reset_index(drop=True)


# ----------------------------------------------------------------------------- pairing
def _ll(wp: pd.Series, y: pd.Series) -> pd.Series:
    q = wp.clip(1e-4, 1 - 1e-4)
    return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def git_first_commit_times(root: Path | None) -> dict[str, pd.Timestamp]:
    """Path (relative to the checkout root) -> committer time of the commit that ADDED it.
    Needs a full-history checkout; an archive branch is append-only, so this is when the
    evidence was pushed (independent of the ``as_of`` the record states)."""
    import subprocess

    if root is None or not (Path(root) / ".git").exists():
        return {}
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--reverse", "--diff-filter=A", "--format=@%cI",
             "--name-only", "--no-renames"], capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return {}
    times: dict[str, pd.Timestamp] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("@"):
            cur = _ts(line[1:])
        elif line and cur is not None:
            times.setdefault(line, cur)
    return times


def paired_games(pre: pd.DataFrame, res: pd.DataFrame, mkt: pd.DataFrame | None = None,
                 roster_archive: Path | None = None,
                 committed: dict[str, pd.Timestamp] | None = None,
                 committed_roster: dict[str, pd.Timestamp] | None = None) -> pd.DataFrame:  # fmt: skip
    """One row per settled game with both base and roster pregame records.
    ``committed`` / ``committed_roster``: first-commit times of the projection files and
    of the roster-archive files (``git_first_commit_times``), for the integrity check."""
    if pre.empty or res.empty:
        return pd.DataFrame()
    piv = {k: pre[pre["version"] == v].set_index("espn_game_id") for k, v in VERSIONS.items()}
    ids = sorted(set(piv["base"].index) & set(piv["roster"].index) & set(res["espn_game_id"]))
    r = res.set_index("espn_game_id")
    m = mkt.set_index("espn_game_id")["mkt_margin"] if mkt is not None and len(mkt) else None
    rows = []
    for gid in ids:
        b, ro = piv["base"].loc[gid], piv["roster"].loc[gid]
        inc = piv["incumbent"].loc[gid] if gid in piv["incumbent"].index else None
        y = float(r.loc[gid, "result_margin"])
        row = {
            "espn_game_id": gid, "tip": b["tip"], "home_team_id": b["home_team_id"],
            "away_team_id": b["away_team_id"], "site": b["site"], "gs_home": b["gs_home"],
            "gs_away": b["gs_away"], "min_gs": min(b["gs_home"], b["gs_away"]),
            "result_margin": y, "result_total": float(r.loc[gid, "result_total"])
            if "result_total" in r.columns else np.nan,
            "mkt_margin": float(m.get(gid, np.nan)) if m is not None else np.nan,
        }  # fmt: skip
        for k, x in (("base", b), ("roster", ro), ("incumbent", inc)):
            if x is None:
                continue
            e = y - x["margin"]
            row |= {f"{k}_margin": x["margin"], f"{k}_err": e, f"{k}_abs": abs(e),
                    f"{k}_sq": e * e, f"{k}_wp": x["home_wp"], f"{k}_as_of": x["as_of"],
                    f"{k}_age_h": (b["tip"] - x["as_of"]).total_seconds() / 3600,
                    f"{k}_path": x["path"], f"{k}_sha256": x["sha256"],
                    f"{k}_code_sha": x["code_sha"], f"{k}_as_of_raw": x["as_of_raw"]}  # fmt: skip
            if committed is not None:
                c = committed.get(x["path"])
                row[f"{k}_committed_at"] = c
                row[f"{k}_committed_before_tip"] = None if c is None else bool(c < b["tip"])
            if "result_total" in r.columns:
                row[f"{k}_total_err"] = float(r.loc[gid, "result_total"]) - x["total"]
        yb = float(y > 0)
        for k in ("base", "roster", "incumbent"):
            if f"{k}_wp" in row:
                row[f"{k}_logloss"] = float(_ll(pd.Series([row[f"{k}_wp"]]), pd.Series([yb]))[0])
        # frozen component split recorded by P-ROSTER-1 itself (no new ablation):
        # (a) input substitution only = base + adj_a; full = base + adj_a + adj_b
        a_ = ro["adj_a"] if pd.notna(ro["adj_a"]) else 0.0
        b_ = ro["adj_b"] if pd.notna(ro["adj_b"]) else 0.0
        row |= {"adj_a": a_, "adj_b": b_, "abs_adj_b": abs(b_),
                "a_only_err": y - (b["margin"] + a_)}  # fmt: skip
        row["a_only_abs"] = abs(row["a_only_err"])
        row["d_abs"] = row["roster_abs"] - row["base_abs"]
        row["d_sq"] = row["roster_sq"] - row["base_sq"]
        row["d_abs_from_a"] = row["a_only_abs"] - row["base_abs"]
        row["d_abs_from_b"] = row["roster_abs"] - row["a_only_abs"]  # signed effect of (b)
        row["roster_margin_base"] = ro["margin_base_in_record"]
        row["roster_adj_a_raw"], row["roster_adj_b_raw"] = ro["adj_a"], ro["adj_b"]
        row["margin_base_consistent"] = ro["margin_base_in_record"] is None or bool(
            np.isclose(ro["margin_base_in_record"], b["margin"])
        )
        row["same_run"] = bool(ro["as_of"] == b["as_of"])
        row["truth_snapshot"] = ro["truth_snapshot"]
        row["truth_files_sha256"] = ro["truth_files_sha256"]
        row["truth_archive_commit"] = ro["truth_archive_commit"]
        row["spec_sha256"] = ro["spec_sha256"]
        tf = evidence_files(roster_archive, ro["truth_snapshot"]) if roster_archive else {}
        for k, p in tf.items():
            row[f"{k}_sha256"] = _sha(p)
        row["evidence_complete"] = bool(tf) and all(
            row[f"{k}_sha256"] is not None for k in ("truth_records", "truth_teams",
                                                     "truth_proster_state"))  # fmt: skip
        if committed_roster is not None and tf:
            rel = str(tf["truth_records"].relative_to(roster_archive))
            c = committed_roster.get(rel)
            row["truth_committed_at"] = c
            row["truth_committed_before_tip"] = None if c is None else bool(c < b["tip"])
        row["truth_before_as_of"] = (
            ro["truth_snapshot"] is None or _ts(ro["truth_snapshot"]) < ro["as_of"]
        )
        for side in ("home", "away"):
            for k in ("roster_confidence", "overlay_applied", "continuity_correction_applied",
                      "truth_cont", "expected_returning_share", "tr_prev", "first_d1",
                      "proj_min_returning", "proj_min_transfer", "proj_min_unseen"):  # fmt: skip
                row[f"{side}_{k}"] = ro[f"{side}_{k}"]
            row[f"{side}_rotation"] = ro[f"{side}_rotation"]
            row[f"{side}_net"] = (
                b[f"{side}_adj_off"] - b[f"{side}_adj_def"]
                if pd.notna(b[f"{side}_adj_off"]) and pd.notna(b[f"{side}_adj_def"]) else np.nan
            )  # fmt: skip
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- team-side view
def _state_index(roster_archive: Path | None) -> dict[str, dict[str, dict]]:
    """truth stamp -> team -> P-ROSTER state, plus teams.json / page freshness rows."""
    out: dict[str, dict[str, dict]] = {}
    if roster_archive is None:
        return out
    for f in sorted((roster_archive / "truth").rglob("*_proster_state.json")):
        stamp = f.name.split("_")[0]
        try:
            st = {s["team_id"]: s for s in json.loads(f.read_text())}
        except ValueError:
            continue
        tj = f.with_name(f"{stamp}_teams.json")
        if tj.exists():
            for t in json.loads(tj.read_text()):
                st.setdefault(t["team_id"], {})["_team"] = t
        fj = f.with_name(f"{stamp}_freshness.jsonl")
        fr = pd.read_json(fj, lines=True) if fj.exists() and fj.stat().st_size else pd.DataFrame()
        if {"team_id", "source", "fresh"} <= set(fr.columns):
            for t, x in fr.groupby("team_id"):
                st.setdefault(t, {})["_fresh"] = {
                    s: bool(v) for s, v in zip(x["source"], x["fresh"], strict=True)
                }
        out[stamp] = st
    return out


def team_games(pg: pd.DataFrame, roster_archive: Path | None = None,
               d1_teams: set[str] | None = None) -> pd.DataFrame:  # fmt: skip
    """One row per (game, side) for the diagnostic team-game-number view. ``d1_teams``:
    the season's canonical D-I membership (``cbb_edge.rosters.membership``)."""
    if pg.empty:
        return pd.DataFrame()
    states = _state_index(roster_archive)
    rows = []
    for g in pg.itertuples(index=False):
        for side, opp, sign in (("home", "away", 1.0), ("away", "home", -1.0)):
            st = states.get(g.truth_snapshot or "", {}).get(getattr(g, f"{side}_team_id"), {})
            rot = st.get("expected_rotation") or []
            cls = pd.Series([e.get("class") for e in rot if e.get("share", 0) >= APPEAR_SHARE])
            team = st.get("_team", {})
            fresh = st.get("_fresh", {})
            site = "neutral" if g.site == "neutral" else side
            # the archived record's rotation (top 8) must be the snapshot's own rotation
            arch = [(e["player_id"], round(float(e["share"]), 4)) for e in
                    sorted(rot, key=lambda e: -e["share"])[:8]]  # fmt: skip
            used = [(p, round(float(v), 4)) for p, v in getattr(g, f"{side}_rotation")]
            match = None if not used else sorted(used) == sorted(arch)
            rows.append({
                "espn_game_id": g.espn_game_id, "tip": g.tip, "side": side,
                "team_id": getattr(g, f"{side}_team_id"),
                "opponent_id": getattr(g, f"{opp}_team_id"), "site": site,
                "team_game_number": int(getattr(g, f"gs_{side}")) + 1,
                "opp_game_number": int(getattr(g, f"gs_{opp}")) + 1,
                "base_err": sign * g.base_err, "roster_err": sign * g.roster_err,
                "base_abs": g.base_abs, "roster_abs": g.roster_abs, "d_abs": g.d_abs,
                "a_only_abs": g.a_only_abs, "adj_b_game": g.adj_b,
                "roster_confidence": getattr(g, f"{side}_roster_confidence"),
                "opp_roster_confidence": getattr(g, f"{opp}_roster_confidence"),
                "overlay_applied": getattr(g, f"{side}_overlay_applied"),
                "continuity_correction_applied": getattr(g, f"{side}_continuity_correction_applied"),
                "truth_cont": getattr(g, f"{side}_truth_cont"),
                "expected_returning_share": getattr(g, f"{side}_expected_returning_share"),
                "tr_prev": getattr(g, f"{side}_tr_prev"),
                "first_d1_expected": getattr(g, f"{side}_first_d1"),
                "returning_minutes_share": (getattr(g, f"{side}_proj_min_returning") or 0) / 200
                if getattr(g, f"{side}_proj_min_returning") is not None else np.nan,
                "n_transfer_expected": int((cls == "transfer").sum()),
                "n_first_d1_expected": int((cls == "first_d1").sum()),
                "n_newcomers_expected": int(cls.isin(["transfer", "first_d1"]).sum()),
                "fresh_groups": ",".join(team.get("fresh_groups") or []),
                "confidence_reason": team.get("confidence_reason"),
                "official_identity_coverage": team.get("official_identity_coverage"),
                "n_conflicted": team.get("n_conflicted"), "n_dropped": team.get("n_dropped"),
                "espn_site_fresh": fresh.get("espn_site"), "school_site_fresh": fresh.get("school_site"),
                "opp_net": getattr(g, f"{opp}_net"), "own_net": getattr(g, f"{side}_net"),
                "rotation_matches_snapshot": match,
                "opponent_d1": None if d1_teams is None
                else getattr(g, f"{opp}_team_id") in d1_teams,
            })  # fmt: skip
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------- summaries
def _boot_ci(d: np.ndarray, groups: np.ndarray) -> list[float] | None:
    """Day-clustered bootstrap 90% interval of the mean paired difference: only with
    N >= 20 games on >= 10 distinct days (fewer clusters make the interval meaningless)."""
    if len(d) < MIN_N_CI or len(np.unique(groups)) < MIN_DAYS_CI:
        return None
    rng = np.random.default_rng(BOOT_SEED)
    u = np.unique(groups)
    idx = {k: np.flatnonzero(groups == k) for k in u}
    means = []
    for _ in range(BOOT_REPS):
        pick = rng.choice(u, size=len(u), replace=True)
        rows = np.concatenate([idx[k] for k in pick])
        means.append(d[rows].mean())
    return [float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))]


def table(x: pd.DataFrame, fi: pd.DataFrame | None = None) -> dict[str, Any]:
    """Headline paired metrics for one slice (sample size first)."""
    out: dict[str, Any] = {"N": int(len(x))}
    if x.empty:
        return out
    for k in ("base", "roster", "incumbent"):
        if f"{k}_err" not in x or x[f"{k}_err"].isna().all():
            continue
        e = x[f"{k}_err"].dropna()
        out[k] = {"MAE": float(e.abs().mean()), "RMSE": float(np.sqrt((e**2).mean())),
                  "bias": float(e.mean()), "log_loss": float(x[f"{k}_logloss"].mean())}  # fmt: skip
    out["delta_MAE"] = out["roster"]["MAE"] - out["base"]["MAE"]
    out["delta_RMSE"] = out["roster"]["RMSE"] - out["base"]["RMSE"]
    out["pct_games_improved"] = float((x["d_abs"] < 0).mean())
    out["pct_games_tied"] = float((x["d_abs"] == 0).mean())
    out["mean_paired_abs_change"] = float(x["d_abs"].mean())
    out["mean_paired_sq_change"] = float(x["d_sq"].mean())
    days = pd.to_datetime(x["tip"], utc=True).dt.tz_convert("America/New_York").dt.date.astype(str)
    out["paired_abs_change_ci90_day_bootstrap"] = _boot_ci(x["d_abs"].to_numpy(), days.to_numpy())
    out["component_split"] = {
        "mean_abs_change_from_a": float(x["d_abs_from_a"].mean()),
        "mean_abs_change_from_b": float(x["d_abs_from_b"].mean()),
    }
    if x["mkt_margin"].notna().sum() > 2:
        mm = x[x["mkt_margin"].notna()]
        mk = np.sqrt(((mm["result_margin"] - mm["mkt_margin"]) ** 2).mean())
        out["market_gap"] = {k: float(np.sqrt((mm[f"{k}_err"] ** 2).mean()) - mk)
                             for k in ("base", "roster")}  # fmt: skip
        out["N_market"] = int(len(mm))
    return out


CONF_ORDER = ["UNKNOWN", "STALE", "CONFLICTED", "LIKELY", "CONFIRMED"]


def overlay_confidence(pg: pd.DataFrame) -> pd.Series:
    """WAVE7.md 7: the roster confidence of the side(s) that triggered the overlay (the
    lower one when both did); ``none`` when neither side's overlay applied."""
    out = []
    for g in pg.itertuples(index=False):
        c = [getattr(g, f"{s}_roster_confidence") for s in ("home", "away")
             if bool(getattr(g, f"{s}_overlay_applied"))]  # fmt: skip
        c = [x if x in CONF_ORDER else "UNKNOWN" for x in c]
        out.append(min(c, key=CONF_ORDER.index) if c else "none")
    return pd.Series(out, index=pg.index)


def rotation_summary(rs: pd.DataFrame | None, fi: pd.DataFrame | None) -> dict[str, Any]:
    """WAVE7.md 7 intermediate metrics by snapshot offset (team means)."""
    out: dict[str, Any] = {}
    if rs is not None and len(rs):
        cols = ["top5", "top8", "starters", "minutes_mae", "rotation_precision", "rotation_recall"]
        for lab, x in rs.groupby("snapshot"):
            out[lab] = {"teams": int(len(x)), **{c: float(x[c].mean()) for c in cols}}
    if fi is not None and len(fi):
        r = fi[fi["rotation"] == "ROSTER"]
        for lab, x in r.groupby("snapshot"):
            out.setdefault(lab, {})["false_inclusion_rate"] = float((x["false_players"] > 0).mean())
            out[lab]["current_player_omission"] = float(x["omitted_minutes_share"].mean())
        b = fi[fi["rotation"] == "BASE"]
        if len(b):
            out["BASE"] = {"teams": int(len(b)),
                           "false_inclusion_rate": float((b["false_players"] > 0).mean()),
                           "current_player_omission": float(b["omitted_minutes_share"].mean())}  # fmt: skip
    return out


def summarize(pg: pd.DataFrame, tg: pd.DataFrame, fi_real: pd.DataFrame | None = None,
              fi_est: pd.DataFrame | None = None,
              rot: pd.DataFrame | None = None) -> dict[str, Any]:  # fmt: skip
    s: dict[str, Any] = {
        "protocol": "research/hypotheses/WAVE7.md section 7 (locked); Wave 8 diagnostics in "
        "research/hypotheses/WAVE8.md",
        "versions": VERSIONS,
        "settled_paired_games": int(len(pg)),
    }
    if pg.empty:
        s["note"] = "no settled game with both base and P-ROSTER-1 pregame records yet"
        return s
    s["primary"] = {k: table(pg[pg["min_gs"].between(lo, hi)])
                    for k, (lo, hi) in PRIMARY_SLICES.items()}  # fmt: skip
    s["headline"] = {k: table(pg[pg["min_gs"].between(lo, hi)])
                     for k, (lo, hi) in HEADLINE_GAMES.items()}  # fmt: skip
    if fi_real is not None and len(fi_real):
        g1 = set(pg.loc[pg["min_gs"] == 0, "espn_game_id"])
        f1 = fi_real[fi_real["espn_game_id"].isin(g1)]
        if len(f1):
            b = f1[f1["rotation"] == "BASE"]
            r = f1[(f1["rotation"] == "ROSTER") & (f1["snapshot"] == "latest")]
            s["headline"]["game_1"]["false_inclusion"] = {
                "teams": int(len(b)),
                "base_false_minutes": float(b["false_minutes"].mean()) if len(b) else None,
                "roster_false_minutes": float(r["false_minutes"].mean()) if len(r) else None,
            }
    oc = overlay_confidence(pg)
    s["primary_by_overlay_confidence"] = {
        f"{k} / {c}": table(pg[pg["min_gs"].between(lo, hi) & (oc == c)])
        for k, (lo, hi) in PRIMARY_SLICES.items() for c in ["none", *CONF_ORDER[::-1]]
        if (pg["min_gs"].between(lo, hi) & (oc == c)).any()
    }  # fmt: skip
    if rot is not None or fi_real is not None:
        s["intermediate_rotation"] = rotation_summary(rot, fi_real)
    diag: dict[str, Any] = {}
    for n in TEAM_GAME_NUMBERS:
        ids = tg.loc[tg["team_game_number"] == n, "espn_game_id"].unique()
        diag[f"team_game_{n}"] = table(pg[pg["espn_game_id"].isin(ids)])
    s["diagnostic_team_game_number"] = diag
    g1 = pg[pg["min_gs"] == 0]
    s["diagnostic_game1_adj_b_buckets"] = {
        lab: table(g1[(g1["abs_adj_b"] >= lo) & (g1["abs_adj_b"] < hi)])
        for lo, hi, lab in ADJ_BUCKETS
    }
    t1 = tg[tg["team_game_number"] == 1]
    if len(t1):
        conf = {}
        for c, x in t1.groupby(t1["roster_confidence"].fillna("NONE")):
            conf[c] = table(pg[pg["espn_game_id"].isin(x["espn_game_id"].unique())])
        s["diagnostic_team_game1_by_confidence"] = conf
        q = t1["n_newcomers_expected"]
        if q.nunique() > 1:
            bins = pd.qcut(q.rank(method="first"), q=min(4, q.nunique()), labels=False)
            s["diagnostic_team_game1_newcomer_quartiles"] = {
                f"q{int(b) + 1} ({int(q[bins == b].min())}-{int(q[bins == b].max())} newcomers)":
                table(pg[pg["espn_game_id"].isin(t1.loc[bins == b, "espn_game_id"].unique())])
                for b in sorted(bins.unique())
            }  # fmt: skip
    if fi_real is not None and len(fi_real):
        s["false_inclusion_realized"] = fi_summary(fi_real)
    if fi_est is not None and len(fi_est) and fi_real is not None and len(fi_real):
        rb = fi_real[fi_real["rotation"] == "BASE"][["team_id", "false_minutes"]]
        j = fi_est.merge(rb, on="team_id", suffixes=("_est", "_real"))
        if len(j):
            s["false_inclusion_estimate_vs_realized"] = {
                "teams": int(len(j)),
                "mean_est_minus_real": float((j["false_minutes_est"] - j["false_minutes_real"]).mean()),
                "corr": float(j["false_minutes_est"].corr(j["false_minutes_real"]))
                if len(j) > 2 else None,
            }  # fmt: skip
    if fi_est is not None and len(fi_est):
        s["false_inclusion_estimated_pretip"] = {
            "teams": int(len(fi_est)),
            "base_false_minutes_mean": float(fi_est["false_minutes"].mean()),
            "base_false_players_mean": float(fi_est["false_players"].mean()),
        }
    s["integrity"] = {
        "games_scored": int(len(pg)),
        "truth_snapshot_before_as_of": int(pg["truth_before_as_of"].sum()),
        "base_and_roster_same_run": int(pg["same_run"].sum()),
        "margin_base_consistent": int(pg["margin_base_consistent"].sum()),
        "roster_records_with_code_sha": int(pg["roster_code_sha"].notna().sum()),
        "truth_evidence_complete": int(pg["evidence_complete"].sum())
        if "evidence_complete" in pg
        else 0,
    }
    for k in ("base", "roster", "truth"):
        c = f"{k}_committed_before_tip"
        if c in pg:
            s["integrity"][c] = int(pg[c].eq(True).sum())
            s["integrity"][f"{k}_commit_unknown"] = int(pg[c].isna().sum())
    return s


def fi_summary(fi: pd.DataFrame) -> dict[str, Any]:
    out = {}
    for (rot, snap), x in fi.groupby([fi["rotation"], fi["snapshot"].fillna("-")]):
        out[f"{rot}@{snap}"] = {"teams": int(len(x)),
                                "false_players_mean": float(x["false_players"].mean()),
                                "false_minutes_mean": float(x["false_minutes"].mean()),
                                "omitted_minutes_share_mean": float(x["omitted_minutes_share"].mean())}  # fmt: skip
    return out


def estimated_false_inclusion(roster_archive: Path, history: pd.DataFrame, season: int,
                              first_games: pd.DataFrame) -> pd.DataFrame:  # fmt: skip
    """PRE-TIP estimate (kept separate from the realized metric): BASE minutes on players
    the latest truth snapshot before each team's first tip does not place on the team."""
    snaps = sorted((roster_archive / "truth").rglob("*_records.jsonl"))
    last = history[history["role_season"] == season - 1]
    rows = []
    cache: dict[str, set] = {}
    for g in first_games.itertuples(index=False):
        prior = [f for f in snaps if _ts(f.name.split("_")[0]) < g.tip]
        if not prior:
            continue
        f = prior[-1]
        if f.name not in cache:
            r = pd.read_json(f, lines=True, dtype={"player_id": str})
            on = r[r["status"].isin(["CONFIRMED", "LIKELY"])]
            cache[f.name] = set(zip(on["player_id"], on["team_id"], strict=True))
        b = last[last["role_team"] == g.team_id]
        keep = np.array([(p, g.team_id) not in cache[f.name] for p in b["player_id"]], dtype=bool)
        gone = b.loc[keep]
        rows.append({"team_id": g.team_id, "espn_game_id": g.espn_game_id,
                     "truth_snapshot": f.name.split("_")[0], "false_players": int(len(gone)),
                     "false_minutes": float(40 * gone["min_share"].sum())})  # fmt: skip
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- rotation (diag)
def rotation_validation(roster_archive: Path, first_games: pd.DataFrame,
                        box5: pd.DataFrame) -> pd.DataFrame:  # fmt: skip
    """Exploratory rotation metrics vs actual first-five-game participation (not tuning):
    minute-weighted overlap, actual minutes on the predicted rotation, predicted minutes
    on players who did not play (DNP or unlisted), top-5 / top-8, starters."""
    from cbb_edge.rosters import scorecard

    states = scorecard._states(roster_archive)
    rows = []
    for g in first_games.itertuples(index=False):
        b = box5[box5["team_id"] == g.team_id]
        if b.empty:
            continue
        n_games = max(b["espn_game_id"].nunique(), 1)
        act = b.groupby("player_id")["minutes"].sum().astype(float) / n_games
        g1 = b[b["espn_game_id"] == g.espn_game_id]
        starters = (
            set(g1.loc[g1["starter"].astype(bool), "player_id"]) if "starter" in g1 else set()
        )
        snap = [s for s in states if s[0] < g.tip]
        if not snap:
            continue
        ts, st = snap[-1]
        team = next((t for t in st if t["team_id"] == g.team_id), None)
        if team is None or not team.get("expected_rotation"):
            continue
        pr = pd.Series({e["player_id"]: 40 * e["share"] for e in team["expected_rotation"]})
        idx = act.index.union(pr.index)
        a_, p_ = act.reindex(idx).fillna(0), pr.reindex(idx).fillna(0)
        played = set(act[act > 0].index)
        rows.append({
            "team_id": g.team_id, "espn_game_id": g.espn_game_id, "snapshot_ts": ts.isoformat(),
            "roster_confidence": team.get("roster_confidence"),
            "minute_weighted_overlap": float(np.minimum(a_, p_).sum() / max(a_.sum(), 1e-9)),
            "actual_minutes_on_predicted_rotation": float(a_[p_ > 0].sum() / max(a_.sum(), 1e-9)),
            "predicted_minutes_on_non_players": float(p_[~p_.index.isin(played)].sum()),
            "top5": len(set(a_.nlargest(5).index) & set(p_.nlargest(5).index)) / 5,
            "top8": len(set(a_.nlargest(8).index) & set(p_.nlargest(8).index)) / 8,
            "starters_game1": len(starters & set(p_.nlargest(5).index)) / 5
            if len(starters) == 5 else np.nan,
            "minutes_mae_first5": float((a_ - p_).abs().mean()),
        })  # fmt: skip
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------- dashboard
def _fmt(v: object, nd: int = 2) -> str:
    return "–" if v is None or (isinstance(v, float) and not np.isfinite(v)) else (
        f"{v:.{nd}f}" if isinstance(v, float) else str(v))  # fmt: skip


def dashboard(s: dict[str, Any], stamp: str, banner: str | None = None) -> str:
    L = [f"# P-ROSTER-1 prospective scoreboard — {stamp}", ""]
    if banner:
        L += [f"> **{banner}**", ""]
    g = (s.get("gate") or {}).get("counts", {})
    h1 = (s.get("headline") or {}).get("game_1", {})
    n1 = h1.get("N", 0)
    L += ["Locked protocol: `research/hypotheses/WAVE7.md` §7. Base = `pure-0.5.0` (frozen), "
          "P-ROSTER-1 = `pure-0.5.0+roster`, incumbent `pure-0.2.0` shown for reference. "
          "error = actual − projected home margin; paired Δ = |e_roster| − |e_base| (negative "
          "= P-ROSTER-1 better). Only games whose whole evidence chain passed the pre-tip "
          "gate are counted.", "",
          f"## Sample size first: **game 1 N = {n1}**",
          "",
          f"Pre-tip gate: VALID {g.get('VALID', 0)} · INVALID {g.get('INVALID', 0)} · "
          f"UNSCORABLE {g.get('UNSCORABLE', 0)} · PENDING {g.get('PENDING', 0)} "
          "(INVALID / UNSCORABLE games are never scored and never reconstructed; see "
          "`integrity_gate.csv`).", ""]  # fmt: skip
    if n1 == 0:
        L += ["**NO DATA. Nothing can be concluded.**", ""]
    elif n1 < MIN_N_CI:
        L += [f"**INSUFFICIENT SAMPLE (N = {n1} < {MIN_N_CI}): descriptive only, no interval, "
              "no conclusion.**", ""]  # fmt: skip
    else:
        L += [f"Intervals need N ≥ {MIN_N_CI} games on ≥ {MIN_DAYS_CI} distinct days; until "
              "then they are suppressed. **No table here decides anything during 2026–27.**", ""]  # fmt: skip
    if not s.get("primary"):
        return "\n".join(L + [s.get("note", ""), ""])
    fi = h1.get("false_inclusion") or {}
    L += ["## HEADLINE — Game 1 (each version's latest pre-tip record; min games seen = 0)", "",
          "| N | Base MAE | P-ROSTER-1 MAE | Δ MAE | Base RMSE | P-ROSTER-1 RMSE | Δ RMSE | "
          "Base bias | P-ROSTER-1 bias | % improved | paired mean \\|e\\| diff | departed-player "
          "false minutes (Base → P-ROSTER-1) |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    if n1:
        L.append(
            f"| **{n1}** | {_fmt(h1['base']['MAE'])} | {_fmt(h1['roster']['MAE'])} | "
            f"{_fmt(h1['delta_MAE'])} | {_fmt(h1['base']['RMSE'])} | {_fmt(h1['roster']['RMSE'])} | "
            f"{_fmt(h1['delta_RMSE'])} | {_fmt(h1['base']['bias'])} | {_fmt(h1['roster']['bias'])} | "
            f"{_fmt(100 * h1['pct_games_improved'], 0)}% | {_fmt(h1['mean_paired_abs_change'])} | "
            + (f"{_fmt(fi.get('base_false_minutes'), 1)} → {_fmt(fi.get('roster_false_minutes'), 1)}"
               f" ({fi.get('teams')} teams)" if fi else "box scores pending") + " |"
        )  # fmt: skip
    else:
        L.append("| **0** | | | | | | | | | | | |")
    L.append("")

    def rows(title: str, d: dict[str, dict]) -> list[str]:
        out = [f"## {title}", "", "| slice | N | base MAE | roster MAE | Δ MAE | base RMSE | "
               "roster RMSE | Δ RMSE | base bias | roster bias | % improved | mean paired Δ | "
               "90% CI (day bootstrap) |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for k, t in d.items():
            if t.get("N", 0) == 0:
                out.append(f"| {k} | 0 | | | | | | | | | | | |")
                continue
            ci = t.get("paired_abs_change_ci90_day_bootstrap")
            out.append(
                f"| {k} | **{t['N']}** | {_fmt(t['base']['MAE'])} | {_fmt(t['roster']['MAE'])} | "
                f"{_fmt(t['delta_MAE'])} | {_fmt(t['base']['RMSE'])} | {_fmt(t['roster']['RMSE'])} | "
                f"{_fmt(t['delta_RMSE'])} | {_fmt(t['base']['bias'])} | {_fmt(t['roster']['bias'])} | "
                f"{_fmt(100 * t['pct_games_improved'], 0)}% | {_fmt(t['mean_paired_abs_change'])} | "
                f"{'suppressed (N<20 or <10 days)' if ci is None else f'[{ci[0]:.2f}, {ci[1]:.2f}]'} |"
            )
        return out + [""]

    L += rows("Game 2 and Game 3, separately (never pooled into the game-1 headline)",
              {k: v for k, v in s["headline"].items() if k != "game_1"})  # fmt: skip
    L += rows("PRIMARY (preregistered WAVE7 §7 slices): game 1 = min(games seen) 0; "
              "games 2–3 = 1–2", s["primary"])  # fmt: skip
    if s.get("primary_by_overlay_confidence"):
        L += rows("PRIMARY by confidence of the side(s) that triggered the overlay",
                  s["primary_by_overlay_confidence"])  # fmt: skip
    if s.get("intermediate_rotation"):
        L += ["## Intermediate (each team's first game, by archived snapshot)", "",
              "| snapshot | teams | top-5 | top-8 | starters | minutes MAE | precision | "
              "recall | false-inclusion rate | omission |", "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for k, v in s["intermediate_rotation"].items():
            L.append(f"| {k} | {v.get('teams', '')} | " + " | ".join(
                _fmt(v.get(c)) for c in ("top5", "top8", "starters", "minutes_mae",
                                         "rotation_precision", "rotation_recall",
                                         "false_inclusion_rate", "current_player_omission")
            ) + " |")  # fmt: skip
        L.append("")
    L += rows("Diagnostic: team game number (not pooled)", s["diagnostic_team_game_number"])
    L += rows(
        "Diagnostic: game-1 |continuity adjustment| buckets", s["diagnostic_game1_adj_b_buckets"]
    )
    if "diagnostic_team_game1_by_confidence" in s:
        L += rows(
            "Diagnostic: team game 1 by roster confidence", s["diagnostic_team_game1_by_confidence"]
        )
    if "diagnostic_team_game1_newcomer_quartiles" in s:
        L += rows("Diagnostic: team game 1 by expected-newcomer quartile",
                  s["diagnostic_team_game1_newcomer_quartiles"])  # fmt: skip
    if "false_inclusion_realized" in s:
        L += ["## Departed-player false inclusion (realized, locked definition)", "",
              "| rotation @ snapshot | teams | false players | false minutes | omitted share |",
              "|---|---|---|---|---|"]  # fmt: skip
        for k, v in s["false_inclusion_realized"].items():
            L.append(f"| {k} | {v['teams']} | {_fmt(v['false_players_mean'])} | "
                     f"{_fmt(v['false_minutes_mean'], 1)} | {_fmt(v['omitted_minutes_share_mean'])} |")  # fmt: skip
        L.append("")
    if "false_inclusion_estimated_pretip" in s:
        e = s["false_inclusion_estimated_pretip"]
        L += [f"Pre-tip ESTIMATE (separate): BASE {e['base_false_minutes_mean']:.1f} false "
              f"minutes / {e['base_false_players_mean']:.1f} players per team over {e['teams']} "
              "teams.", ""]  # fmt: skip
    i = s.get("integrity", {})
    L += ["## Snapshot integrity", "", *[f"* {k}: {v}" for k, v in i.items()], ""]
    return "\n".join(L)


def write(out: Path, frames: dict[str, pd.DataFrame], s: dict[str, Any], stamp: str,
          banner: str | None = None) -> None:  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    for name, f in frames.items():
        if f is None or f.empty:
            continue
        keys = [c for c in ("espn_game_id", "side", "team_id", "rotation", "snapshot") if c in f]
        f.sort_values(keys).to_csv(out / f"{name}.csv", index=False)
    (out / "summary.json").write_text(json.dumps(s, indent=1, sort_keys=True, default=str))
    (out / "dashboard.md").write_text(dashboard(s, stamp, banner))


# ------------------------------------------------------------------------------- run
def score(recs: list[dict], res: pd.DataFrame, mkt: pd.DataFrame | None = None,
          roster_archive: Path | None = None, box: pd.DataFrame | None = None,
          games: pd.DataFrame | None = None, season: int = 2027,
          d1_teams: set[str] | None = None,
          committed: dict[str, pd.Timestamp] | None = None,
          committed_roster: dict[str, pd.Timestamp] | None = None,
          projections_root: Path | None = None, expected: pd.DataFrame | None = None,
          enforce_gate: bool = True) -> tuple[dict, dict]:  # fmt: skip
    """``games``: espn_game_id, home_team_id, away_team_id, tip (the season schedule; for
    each team's first five games). ``box``: espn_game_id, team_id, player_id, minutes,
    starter (played and DNP rows). ``expected``: the D-I games (espn_game_id) that tipped
    before this run; settled ones without a VALID pair are reported, never dropped.

    ``enforce_gate`` (always on in production): only games that pass the pre-tip
    evidence gate (``pretip_gate``) enter any metric; ``False`` only for unit tests of
    the arithmetic."""
    from cbb_edge.rosters import pretip_gate

    tips = None
    if games is not None and len(games) and "tip" in games:
        tips = {int(k): _ts(v) for k, v in zip(games["espn_game_id"], games["tip"], strict=True)}
    pre = pregame(recs, tips)
    pg_all = paired_games(pre, res, mkt, roster_archive, committed, committed_roster)
    tg_all = team_games(pg_all, roster_archive, d1_teams)
    gate = pretip_gate.classify(
        pre, pg_all, res, expected, tg_all, roster_archive=roster_archive,
        manifests=pretip_gate.manifest_index(projections_root), committed=committed,
        committed_roster=committed_roster,
        mutated=pretip_gate.git_mutated_paths(projections_root),
        mutated_roster=pretip_gate.git_mutated_paths(roster_archive),
        dups=pretip_gate.duplicates(recs),
    )  # fmt: skip
    if len(pg_all):
        gi = gate.set_index("espn_game_id")
        pg_all["gate_status"] = pg_all["espn_game_id"].map(gi["status"])
        pg_all["gate_reasons"] = pg_all["espn_game_id"].map(gi["reasons"])
    if enforce_gate and len(pg_all):
        pg = pg_all[pg_all["gate_status"] == pretip_gate.VALID].reset_index(drop=True)
    else:
        pg = pg_all
    tg = tg_all[tg_all["espn_game_id"].isin(set(pg["espn_game_id"]))] if len(tg_all) else tg_all
    frames: dict[str, pd.DataFrame] = {"paired_games": pg_all, "team_games": tg_all,
                                       "integrity_gate": gate}  # fmt: skip
    fi_real = fi_est = None
    if games is not None and len(games) and roster_archive is not None:
        from cbb_edge.rosters import scorecard

        sides = pd.concat([
            games[["espn_game_id", "home_team_id", "tip"]].rename(columns={"home_team_id": "team_id"}),
            games[["espn_game_id", "away_team_id", "tip"]].rename(columns={"away_team_id": "team_id"}),
        ]).dropna().sort_values(["tip", "espn_game_id"])  # fmt: skip
        first = sides.groupby("team_id").head(1)
        hist = pd.read_parquet(REPO / "models" / "rosters" / "history_2026.parquet")
        fi_est = estimated_false_inclusion(roster_archive, hist, season, first)
        frames["false_inclusion_estimated"] = fi_est
        if box is not None and len(box):
            g5 = sides.groupby("team_id").head(5)[["espn_game_id", "team_id"]]
            box5 = box.merge(g5, on=["espn_game_id", "team_id"])
            done = set(box["espn_game_id"])
            first_done = first[first["espn_game_id"].isin(done)]
            fi_real = scorecard.false_inclusion(roster_archive, first_done, box5, hist, season)
            frames["false_inclusion_realized"] = fi_real
            frames["rotation_scorecard"] = scorecard.rotation_scorecard(
                roster_archive, first_done, box
            )
            frames["rotation_validation"] = rotation_validation(roster_archive, first_done, box5)
    if len(pg):
        frames["continuity_tail"] = pg[pg["min_gs"] == 0][[
            "espn_game_id", "tip", "home_team_id", "away_team_id", "adj_a", "adj_b",
            "abs_adj_b", "base_err", "a_only_err", "roster_err", "d_abs_from_a",
            "d_abs_from_b", "home_truth_cont", "home_expected_returning_share",
            "home_first_d1", "home_tr_prev", "away_truth_cont",
            "away_expected_returning_share", "away_first_d1", "away_tr_prev",
            "home_roster_confidence", "away_roster_confidence"]]  # fmt: skip
    s = summarize(pg, tg, fi_real, fi_est, frames.get("rotation_scorecard"))
    s["gate"] = {
        "enforced": bool(enforce_gate),
        "counts": gate["status"].value_counts().to_dict() if len(gate) else {},
        "reasons": pd.Series([x for r in gate["reasons"] for x in r.split(";") if x])
        .value_counts().to_dict() if len(gate) else {},
    }  # fmt: skip
    return frames, s
