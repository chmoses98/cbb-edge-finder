"""Coherent full-game score distribution from a frozen projection (SHADOW / RESEARCH ONLY).

One bivariate normal over (home score, away score) is built from the four numbers every frozen record
carries - ``margin``, ``total``, ``margin_sd``, ``total_sd`` - under the stated assumption that the
total and the margin errors are uncorrelated:

    mean_h = (T + M) / 2,  mean_a = (T - M) / 2
    var_h = var_a = (sd_T^2 + sd_M^2) / 4,   cov_ha = (sd_T^2 - sd_M^2) / 4

so by construction E[h] + E[a] = total, E[h] - E[a] = margin, Var(h + a) = sd_T^2, Var(h - a) = sd_M^2,
and every market (moneyline, spread ladders, total ladders, team totals) is priced from the SAME
distribution - they cannot contradict each other. The covariance matrix is positive semidefinite for
all non-negative SDs. The uncorrelatedness assumption and the team-score SDs it implies are checked
against realised results in ``research/reports/WAVE13_...`` before anything may rely on them; team-total
outputs are labelled ``SHADOW_UNVALIDATED`` and nothing here authorises a wager.

NOT modelled (explicit, never fabricated): halves and other periods (the first-half share forecast
``period_forecast`` is a mean only, with no variance), overtime/race markets, player props. They return
``Unmodeled`` with the reason so a contract table keeps them in the universe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

STATUS = "SHADOW_UNVALIDATED"


@dataclass(frozen=True)
class Unmodeled:
    reason: str
    status: str = "UNMODELED"


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class ScoreDistribution:
    mean_home: float
    mean_away: float
    sd_margin: float
    sd_total: float

    @classmethod
    def from_projection(cls, p: dict[str, Any]) -> ScoreDistribution | Unmodeled:
        try:
            m, t = float(p["margin"]), float(p["total"])
            sm, st = float(p["margin_sd"]), float(p["total_sd"])
        except (KeyError, TypeError, ValueError):
            return Unmodeled("projection_missing_margin_total_or_sd")
        if not all(math.isfinite(x) for x in (m, t, sm, st)) or sm <= 0 or st <= 0:
            return Unmodeled("projection_not_finite_or_sd_not_positive")
        return cls((t + m) / 2.0, (t - m) / 2.0, sm, st)

    # ---- moments (coherent by construction)
    @property
    def total(self) -> float:
        return self.mean_home + self.mean_away

    @property
    def margin(self) -> float:
        return self.mean_home - self.mean_away

    @property
    def var_team(self) -> float:
        return (self.sd_total**2 + self.sd_margin**2) / 4.0

    @property
    def cov_home_away(self) -> float:
        return (self.sd_total**2 - self.sd_margin**2) / 4.0

    @property
    def sd_team(self) -> float:
        return math.sqrt(self.var_team)

    # ---- probabilities (strict ">" on integer scores via the .5 convention callers already use)
    def p_home_win(self) -> float:
        return _cdf(self.margin / self.sd_margin)

    def p_margin_gt(self, side: str, strike: float) -> float:
        mu = self.margin if side == "home" else -self.margin
        return _cdf((mu - strike) / self.sd_margin)

    def p_total_gt(self, strike: float) -> float:
        return _cdf((self.total - strike) / self.sd_total)

    def p_team_total_gt(self, side: str, strike: float) -> float:
        mu = self.mean_home if side == "home" else self.mean_away
        return _cdf((mu - strike) / self.sd_team)

    def period(self, period: str) -> Unmodeled:
        return Unmodeled(f"no_{period}_distribution: frozen model has no period variance")

    def player(self) -> Unmodeled:
        return Unmodeled("no_player_distribution_in_frozen_team_projection")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": STATUS, "mean_home": self.mean_home, "mean_away": self.mean_away,
            "sd_margin": self.sd_margin, "sd_total": self.sd_total, "sd_team": self.sd_team,
            "cov_home_away": self.cov_home_away,
            "assumption": "total and margin errors uncorrelated (checked against realised results)",
        }  # fmt: skip
