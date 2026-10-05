"""Availability-aware expected rotation: absence persistence + replacement minutes (B19).

Historical data has no injury labels, only actual minutes. So:

* ``absence_table`` lists, for every team game, every player who already appeared for
  the team earlier that season, with pregame information only: EW share (missed games
  = 0), conditional share when playing (EW over games he played), consecutive missed
  games just before this one, games played in the last 5, and position. The outcome
  is whether he played (minutes > 0) and his actual share.
* ``fit_persistence`` is a logistic P(plays) from the consecutive-miss run (0 / 1 / 2 /
  3+), conditional share and recent participation. Fitted on earlier seasons only.
* ``fit_replacement`` handles a player's removed minutes, which go to available
  teammates in proportion to cond_share^γ × (1 + β·same_position). γ and β are chosen
  on DEV absences from the preregistered grid by squared error of next-game shares.
* ``AvailabilityAdjuster`` plugs into ``rapm.player_team_features(share_adjust=...)``:
  expected share_B = P_B·cond_B + Σ_A (1−P_A)·cond_A·weight_AB (capped at 1.0,
  normalized to 5). It takes ``p_override`` per game, e.g. prospective injury-report
  P(plays) or the labelled-oracle diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

HALFLIFE = 4.0
POS = {
    "G": "G",
    "PG": "G",
    "SG": "G",
    "F": "F",
    "SF": "F",
    "PF": "F",
    "C": "C",
    "G-F": "G",
    "F-C": "F",
    "F-G": "F",
    "C-F": "C",
}


def _pos(x: object) -> str:
    return POS.get(str(x).upper(), "F")


def _trailing_zeros(S: np.ndarray, appeared: np.ndarray) -> np.ndarray:
    """Per row r: consecutive zero-share games immediately before r (only after the
    player's first appearance)."""
    k, n = S.shape
    out = np.zeros((k, n), dtype=int)
    run = np.zeros(n, dtype=int)
    for r in range(k):
        out[r] = np.where(appeared[r], run, 0)
        run = np.where(S[r] > 0, 0, run + 1)
    return out


def pregame_stats(S: np.ndarray) -> dict[str, np.ndarray]:
    """For each row r of a team-season share matrix (games in tip order), statistics
    from rows < r only: EW share (missed = 0), conditional share when playing, trailing
    consecutive missed games, games played in the previous 5, appeared-before flag."""
    k, n = S.shape
    played = S > 0
    first = np.where(played.any(axis=0), played.argmax(axis=0), k)
    appeared = np.arange(k)[:, None] > first[None, :]
    decay = 0.5 ** (1.0 / HALFLIFE)
    ew, cond, last5 = np.zeros((k, n)), np.zeros((k, n)), np.zeros((k, n))
    num, den, cn, cd = np.zeros(n), 0.0, np.zeros(n), np.zeros(n)
    for r in range(k):
        ew[r] = num / den if den > 0 else 0.0
        cond[r] = np.where(cd > 0, cn / np.where(cd > 0, cd, 1), 0.0)
        last5[r] = played[max(0, r - 5) : r].sum(axis=0)
        num = decay * num + S[r]
        den = decay * den + 1.0
        cn = np.where(played[r], decay * cn + S[r], cn)
        cd = np.where(played[r], decay * cd + 1.0, cd)
    return {
        "ew": ew,
        "cond": cond,
        "miss": _trailing_zeros(S, appeared),
        "last5": last5,
        "appeared": appeared,
    }


def team_panel(x: pd.DataFrame) -> dict[str, np.ndarray]:
    """Shares matrix for one team-season (rows = games in tip order) + pregame stats."""
    piv = x.pivot_table(
        index="game_id", columns="player_id", values="min", aggfunc="sum", fill_value=0.0
    )
    order = x.drop_duplicates("game_id").set_index("game_id")["start_time_utc"]
    piv = piv.loc[order.loc[piv.index].sort_values().index]
    tot = piv.sum(axis=1).replace(0, np.nan)
    S = piv.div(tot / 5.0, axis=0).clip(upper=1.0).fillna(0.0).to_numpy()
    return {
        "S": S,
        **pregame_stats(S),
        "game_ids": np.array(piv.index),
        "players": np.array(piv.columns),
    }


def absence_table(pg: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """One row per (team game, player who appeared earlier that season)."""
    pos = pg.drop_duplicates(["player_id", "season"], keep="last").set_index(
        ["player_id", "season"]
    )["position"]
    rows = []
    for (s, team), x in pg[pg["season"].isin(seasons)].groupby(["season", "team_id"]):
        p = team_panel(x)
        r, c = np.nonzero(p["appeared"])
        if not len(r):
            continue
        rows.append(
            pd.DataFrame(
                {
                    "season": s,
                    "team_id": team,
                    "game_id": p["game_ids"][r],
                    "game_no": r,
                    "player_id": p["players"][c],
                    "ew_share": p["ew"][r, c],
                    "cond_share": p["cond"][r, c],
                    "miss_run": p["miss"][r, c],
                    "played_last5": p["last5"][r, c],
                    "share": p["S"][r, c],
                    "played": p["S"][r, c] > 0,
                }
            )
        )
    out = pd.concat(rows, ignore_index=True)
    out["pos"] = [
        _pos(pos.get((a, b))) for a, b in zip(out["player_id"], out["season"], strict=True)
    ]
    out["regular"] = (out["ew_share"] >= 0.35) & (out["played_last5"] >= 3)
    return out


def absence_class(t: pd.DataFrame) -> pd.Series:
    """first_surprise / second / third_plus / return / normal for regulars' games."""
    c = pd.Series("normal", index=t.index)
    out = ~t["played"]
    c[out & (t["miss_run"] == 0)] = "first_surprise_absence"
    c[out & (t["miss_run"] == 1)] = "second_consecutive_absence"
    c[out & (t["miss_run"] >= 2)] = "third_plus_absence"
    c[t["played"] & (t["miss_run"] >= 1)] = "return_from_absence"
    return c


def _px(t: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=t.index)
    for k in (1, 2, 3):
        X[f"miss{k}"] = (t["miss_run"].clip(upper=3) == k).astype(float)
    X["cond"] = t["cond_share"].clip(0, 1)
    X["last5"] = t["played_last5"] / 5.0
    X["miss_x_cond"] = X[["miss1", "miss2", "miss3"]].sum(axis=1) * X["cond"]
    return X


@dataclass
class Persistence:
    coef: list[float] = field(default_factory=list)
    intercept: float = 0.0
    columns: list[str] = field(default_factory=list)

    def p_play(self, miss_run: np.ndarray, cond: np.ndarray, last5: np.ndarray) -> np.ndarray:
        t = pd.DataFrame({"miss_run": miss_run, "cond_share": cond, "played_last5": last5})
        z = _px(t)[self.columns].to_numpy() @ np.asarray(self.coef) + self.intercept
        return 1 / (1 + np.exp(-z))


def fit_persistence(t: pd.DataFrame) -> Persistence:
    x = t[t["cond_share"] >= 0.1]
    X = _px(x)
    m = LogisticRegression(C=1.0, max_iter=1000).fit(X, x["played"].astype(int))
    return Persistence(list(map(float, m.coef_[0])), float(m.intercept_[0]), list(X.columns))


def redistribute(
    cond: np.ndarray, p: np.ndarray, pos: np.ndarray, gamma: float, beta: float
) -> np.ndarray:
    """Expected shares given P(plays): playing share + removed minutes to teammates."""
    base = p * cond
    out = base.copy()
    lost = (1 - p) * cond
    for a in np.nonzero(lost > 1e-9)[0]:
        w = p * np.power(np.clip(cond, 0, None), gamma) * (1 + beta * (pos == pos[a]))
        w[a] = 0.0
        if w.sum() > 0:
            out += lost[a] * w / w.sum()
    out = np.minimum(out, 1.0)
    tot = out.sum()
    return out * (5.0 / tot) if tot > 0 else out


def fit_replacement(
    t: pd.DataFrame, grid_gamma=(0.5, 1.0, 1.5), grid_beta=(0.0, 0.5, 1.0)
) -> tuple[float, float, pd.DataFrame]:
    """Choose (γ, β) on games where >= 1 regular was absent (outcome known), predicting
    the actual shares of the players who played from the pregame conditional shares."""
    t = t.assign(cls=absence_class(t))
    games = t.loc[t["regular"] & ~t["played"], ["team_id", "game_id"]].drop_duplicates()
    sub = t.merge(games, on=["team_id", "game_id"])
    res = []
    for g in grid_gamma:
        for b in grid_beta:
            se, n = 0.0, 0
            for _, x in sub.groupby(["team_id", "game_id"]):
                p = x["played"].to_numpy(float)  # actual availability (fit only)
                pred = redistribute(x["cond_share"].to_numpy(), p, x["pos"].to_numpy(), g, b)
                m = p > 0
                se += float(((pred[m] - x["share"].to_numpy()[m]) ** 2).sum())
                n += int(m.sum())
            res.append({"gamma": g, "beta": b, "rmse_share": (se / max(n, 1)) ** 0.5, "n": n})
    r = pd.DataFrame(res).sort_values("rmse_share")
    return float(r.iloc[0]["gamma"]), float(r.iloc[0]["beta"]), r


class AvailabilityAdjuster:
    """``share_adjust`` for ``rapm.player_team_features``.

    mode ``persistence``: P(plays) from the fitted persistence model (pregame info only).
    mode ``oracle``: P = 1 if the player actually played, else 0 (DIAGNOSTIC upper bound,
    uses the game's own box score; never a model input).
    ``p_override``: {(game_id, player_id): P} from prospective status reports.
    """

    def __init__(
        self,
        models: dict[int, Persistence],
        positions: dict[str, str],
        gamma: float,
        beta: float,
        mode: str = "persistence",
        actual: dict[int, set[str]] | None = None,
        p_override: dict[tuple[object, str], float] | None = None,
    ):
        self.models = models
        self.positions = positions
        self.gamma, self.beta = gamma, beta
        self.mode = mode
        self.actual = actual or {}
        self.p_override = p_override or {}
        self._cache: dict[tuple[str, int], dict[str, np.ndarray]] = {}

    def _panel(self, ts, team: str, season: int) -> dict[str, np.ndarray]:
        key = (team, season)
        if key not in self._cache:
            # one extra all-zero row: row m = state before the team's (m+1)-th game
            ext = np.vstack([ts.S, np.zeros((1, ts.S.shape[1]))])
            st = pregame_stats(ext)
            st["idx"] = {p: i for i, p in enumerate(ts.players)}
            self._cache[key] = st
        return self._cache[key]

    def __call__(self, team, season, ts, m, pids, s, game_id) -> np.ndarray:
        pan = self._panel(ts, team, season)
        idx = np.array([pan["idx"][p] for p in pids])
        cond = pan["cond"][m][idx]
        cond = np.where(cond > 0, cond, s)
        if self.mode == "oracle":
            act = self.actual.get(game_id)
            if act is None:
                return s
            p = np.array([1.0 if q in act else 0.0 for q in pids])
        else:
            model = self.models.get(season)
            if model is None:
                return s
            p = model.p_play(pan["miss"][m][idx], cond, pan["last5"][m][idx])
        for i, q in enumerate(pids):
            o = self.p_override.get((game_id, q))
            if o is not None:
                p[i] = o
        pos = np.array([self.positions.get(q, "F") for q in pids])
        return redistribute(cond, p, pos, self.gamma, self.beta)
