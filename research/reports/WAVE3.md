# Wave 3 — early-season team strength

Question: *how much can we improve our estimate of team strength before the season has
provided enough games to tell us the answer?*

All arms are PURE_BASKETBALL (no spreads, totals, moneylines, Kalshi prices or market
movement as inputs; CI-enforced). Seasons: DEV ≤ 2014 (every new prior component fitted
here, or walk-forward on strictly earlier seasons), VALIDATION 2015–2024 (promotion
decisions, thresholds preregistered in `research/hypotheses/WAVE3.md` before any
result), HISTORICAL 2025–2026 (evidence only — already observed; nothing tuned on it).
The market is read only by the downstream benchmark step (`scripts/research/wave3_market.py`).

**Outcome:** B15 passes every preregistered B15 threshold and is frozen as
`pure-0.3.0`. It runs as a **shadow challenger** beside the unchanged incumbent
`pure-0.2.0` in the 2026–27 prospective archive.

## Headline

| | B9 (`pure-0.2.0`) | B15 (`pure-0.3.0`) | Δ |
|---|---|---|---|
| validation margin RMSE | 11.2234 | 11.1845 | −0.0389 (10/10 seasons) |
| validation Nov–Dec RMSE | — | — | −0.0826 |
| validation Jan–Mar RMSE | — | — | −0.0109 |
| validation log loss | — | — | −0.0018 |
| historical 2025–26 RMSE | 11.4820 | 11.4162 | −0.0658 (Nov–Dec −0.125) |
| market_gap (validation, games with a line) | +0.153 | +0.128 | −0.025 |
| market_gap November (validation) | +0.343 | +0.258 | −0.085 |
| market_gap first game (validation) | +0.708 | +0.577 | −0.131 |

B15 beats B9 in every season 2015–2026 (by 0.022–0.067).

## What B15 is

1. **Roster-anchored team prior in the rating solve (B10r):** each team's eff prior on day
   D = c0 + c_base·0.9·last-season rating + c_S·S(D) + c_conf·C. S(D) is the
   *observed rotation × season-start player ratings*: EW minute shares of the players who
   have actually appeared (before D's first tip), each valued at his preseason RAPM
   (carry 0.95; generic newcomer prior). Before a team's first game S is the
   probabilistic preseason estimate: P(return) × carried value, with vacated minutes
   filled at the newcomer level. No in-season performance enters S, so it does not
   double-count results the solve already sees. (The in-season version, B10, failed:
   +0.002.)
2. **Conference anchor (B14):** C = last season's mean final rating of the other members
   of the team's current conference (leave-one-out). Early-season networks are sparse,
   and this ties each team's level to its conference's. Fitted jointly with S on DEV
   2012–2014: offense c_base 0.58–0.61, c_S 0.36–0.40, c_conf 0.24–0.25; defense c_base
   0.65–0.67, c_S 0.25–0.32, c_conf 0.29 (pre-first-game / observed states).
3. **Box-score-informed player features (B12):** walk-forward RAPM whose priors are the
   DEV-tuned carry, plus a transfer translation from the player's first appearance for
   a new team (k ≈ 0.66–0.70 of returner persistence in 2020–2026 fits, +0.07 off / −0.08 def per point of
   team-strength change, fitted on earlier seasons only). During the season the prior is
   blended toward an SPM of the player's season-to-date box line, with weight
   minutes/(minutes+400).
4. **Extreme-mismatch block:** piecewise extension of the analytic margin beyond ±15.
   B9 under-projected favourites by +1.13 pts when the projection was ≥ 25.
5. Everything else is unchanged from B9 (base / player / shot / context blocks, the same
   expanding-window stacked ridge and logistic WP).

## All arms (Δ vs B9)

| arm | val RMSE | Δ | Δ Nov–Dec | Δ Jan–Mar | Δ log loss | seasons better | verdict | hist Δ | hist Δ Nov–Dec |
|---|---|---|---|---|---|---|---|---|---|
| B10 | 11.2171 | -0.0063 | -0.0108 | -0.0034 | -0.0003 | 7/10 | PROMOTE | +0.0097 | +0.0208 |
| B10_engine_only | 11.2255 | +0.0021 | +0.0077 | -0.0015 | +0.0001 | 4/10 | REJECT | -0.0025 | -0.0084 |
| B10d | 11.2669 | +0.0435 | +0.0517 | +0.0382 | +0.0015 | 0/10 | REJECT | +0.0412 | +0.0377 |
| B10r ¹ | 11.2058 | -0.0176 | -0.0322 | -0.0082 | -0.0008 | 9/10 | PROMOTE | -0.0013 | +0.0078 |
| B10r_engine_only ¹ | 11.2132 | -0.0102 | -0.0161 | -0.0064 | -0.0005 | 10/10 | PROMOTE | -0.0162 | -0.0270 |
| B11 | 11.2240 | +0.0007 | +0.0009 | +0.0005 | +0.0001 | 4/10 | REJECT | +0.0096 | +0.0150 |
| B12 ¹ | 11.2154 | -0.0080 | -0.0180 | -0.0015 | -0.0006 | 9/10 | PROMOTE | -0.0058 | -0.0109 |
| B13 | 11.2298 | +0.0064 | +0.0062 | +0.0066 | +0.0003 | 3/10 | REJECT | +0.0026 | -0.0173 |
| B13_garbage_only | 11.2327 | +0.0093 | +0.0117 | +0.0078 | +0.0004 | 1/10 | REJECT | +0.0109 | +0.0003 |
| B13_mismatch_only | 11.2202 | -0.0032 | -0.0063 | -0.0012 | -0.0001 | 7/10 | PROMOTE | -0.0077 | -0.0164 |
| B14 | 11.2049 | -0.0185 | -0.0438 | -0.0021 | -0.0007 | 10/10 | PROMOTE | -0.0290 | -0.0565 |
| B14v | 11.2238 | +0.0005 | -0.0018 | +0.0019 | +0.0001 | 6/10 | REJECT | +0.0032 | +0.0025 |
| **B15** | **11.1845** | **-0.0389** | **-0.0826** | **-0.0109** | **-0.0018** | **10/10** | **PROMOTE** | **-0.0658** | **-0.1253** |
| B15_with_preseason ² | 11.1802 | -0.0432 | -0.0918 | -0.0120 | -0.0020 | 10/10 | not eligible | -0.0549 | -0.1006 |

N = 53,778 validation / 11,516 historical games, identical for every arm. B9
recomputed here = 11.2234, which reproduces Wave 2.
¹ Post-hoc variants (specified after first results; see the preregistration addendum),
so weaker evidence. B15's composition was fixed in writing before B15 was run.
² Adds the preseason roster stacking block. Within validation the block helps in
2015–2020 but hurts in 3 of 4 portal seasons (2021–24); it is also worse on 2025–26. It
was excluded from B15 before B15 ran.

### B9 vs B15 by season (margin RMSE)

| season | n | B9 | B15 | Δ |
|---|---|---|---|---|
| 2015 | 5499 | 10.732 | 10.682 | -0.050 |
| 2016 | 5469 | 10.943 | 10.899 | -0.044 |
| 2017 | 5521 | 11.154 | 11.101 | -0.053 |
| 2018 | 5540 | 11.255 | 11.228 | -0.027 |
| 2019 | 5603 | 11.282 | 11.251 | -0.031 |
| 2020 | 5328 | 11.350 | 11.312 | -0.038 |
| 2021 | 3868 | 11.869 | 11.817 | -0.051 |
| 2022 | 5503 | 11.221 | 11.197 | -0.024 |
| 2023 | 5721 | 11.258 | 11.236 | -0.022 |
| 2024 | 5726 | 11.328 | 11.276 | -0.052 |
| 2025 (hist) | 5764 | 11.450 | 11.383 | -0.067 |
| 2026 (hist) | 5752 | 11.514 | 11.449 | -0.065 |

Totals (not the focus; the rejected pace model stays rejected): total RMSE 17.052 → 17.039.

## Early-season scorecard (MARKET = free ESPN closing line; benchmark only)

| split | slice | n | B9 RMSE | B15 RMSE | B9 MAE | B15 MAE | B9 LL | B15 LL | MARKET RMSE | B9 gap | B15 gap |
|---|---|---|---|---|---|---|---|---|---|---|---|
| validation | all | 25256 | 11.315 | 11.290 | 8.925 | 8.904 | 0.5323 | 0.5306 | 11.162 | +0.153 | +0.128 |
| validation | Nov | 4525 | 12.072 | 11.987 | 9.541 | 9.469 | 0.4682 | 0.4632 | 11.729 | +0.343 | +0.258 |
| validation | Dec | 4843 | 11.591 | 11.553 | 9.151 | 9.126 | 0.4903 | 0.4877 | 11.415 | +0.176 | +0.139 |
| validation | Jan-Mar | 15888 | 11.004 | 11.001 | 8.681 | 8.676 | 0.5634 | 0.5629 | 10.916 | +0.087 | +0.084 |
| validation | game 1 | 1051 | 13.062 | 12.931 | 10.264 | 10.129 | 0.4226 | 0.4163 | 12.355 | +0.708 | +0.577 |
| validation | games 2-3 | 1901 | 12.126 | 12.017 | 9.606 | 9.508 | 0.4685 | 0.4608 | 11.726 | +0.400 | +0.292 |
| validation | games 4-5 | 1755 | 11.638 | 11.584 | 9.255 | 9.224 | 0.4986 | 0.4959 | 11.398 | +0.240 | +0.186 |
| validation | games 6-10 | 4487 | 11.450 | 11.442 | 9.022 | 9.018 | 0.5017 | 0.5005 | 11.352 | +0.097 | +0.089 |
| validation | games 11+ | 16062 | 11.015 | 11.007 | 8.693 | 8.686 | 0.5593 | 0.5586 | 10.930 | +0.086 | +0.078 |
| historical | all | 4760 | 11.281 | 11.232 | 8.908 | 8.876 | 0.5461 | 0.5446 | 11.168 | +0.113 | +0.064 |
| historical | Nov | 262 | 12.376 | 12.229 | 9.630 | 9.510 | 0.5042 | 0.5003 | 12.392 | -0.016 | -0.163 |
| historical | Dec | 960 | 11.726 | 11.632 | 9.156 | 9.104 | 0.4477 | 0.4448 | 11.464 | +0.262 | +0.168 |
| historical | Jan-Mar | 3538 | 11.071 | 11.043 | 8.787 | 8.768 | 0.5759 | 0.5749 | 10.990 | +0.081 | +0.053 |
| historical | games 6-10 | 862 | 11.846 | 11.718 | 9.216 | 9.123 | 0.4808 | 0.4768 | 11.619 | +0.227 | +0.099 |
| historical | games 11+ | 3812 | 11.118 | 11.089 | 8.815 | 8.798 | 0.5609 | 0.5599 | 11.029 | +0.089 | +0.060 |

"Game n" = games played before tip by the *less-informed* team, + 1. Historical
free lines are sparse before game 6 (n ≤ 82), so those slices are omitted; the
historical November slice (n = 262) is small.

## Convergence curve and time to market parity

Gap = PURE RMSE − MARKET RMSE, pooled ±1 game, validation:

| games seen | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 8 | 10 | 12 | 15 | 20 | 25 | 30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| n | 2019 | 2952 | 2766 | 2688 | 2621 | 2672 | 2699 | 2705 | 2475 | 2370 | 2399 | 2246 | 2155 | 1265 |
| B9 | +0.607 | +0.514 | +0.376 | +0.262 | +0.159 | +0.122 | +0.090 | +0.092 | +0.091 | +0.062 | +0.080 | +0.166 | +0.108 | +0.073 |
| B15 | +0.488 | +0.397 | +0.279 | +0.188 | +0.120 | +0.098 | +0.078 | +0.090 | +0.067 | +0.037 | +0.061 | +0.165 | +0.090 | +0.090 |

Games seen until the gap first reaches the threshold (validation; points with n ≥ 200):

| arm | +0.50 | +0.25 | +0.15 | +0.10 | +0.05 |
|---|---|---|---|---|---|
| B9 | 2 | 4 | 5 | 6 | 22 |
| B15 | 0 | 3 | 4 | 5 | 11 |

The *sustained* definition (gap stays below for every later k) is 21 games for +0.15
for both arms, because of a bump around game 20 (conference-play onset, gap ≈ 0.165 for
both). The late-season plateau of ≈ +0.06 to +0.09 is not an early-season problem.
B15 removes about one game of convergence time early: B15 at game k ≈ B9 at game k+1
for k ≤ 4.

## Roster graph, returning production, rotation prior

* **Roster graph** (`cbb_edge/players/roster_graph.py`): ~101k player-seasons 2006–2026,
  identity = ESPN athlete id only (no name matching here). Status flags: returning,
  transfer_in (any earlier different D-I team, handling pre-2021 sit-out years),
  first_observed, seasons_prior. Rotation transfers rose from ~4.5% (2008) to 38%
  (2026); rotation returners fell from 64% to 33%. RAPM matched 93–97% of rotation
  players (2011+); unmatched players stay unmatched (logged by stints.py), never
  fuzzy-matched.
* **Returning production** (preseason, probabilistic; `cbb_edge/players/preseason.py`):
  returning minutes / usage / starts / rotation count, returning ast/orb/drb/stl/blk/pts
  shares, carried impact, lost impact, top-1 / top-3 returning impact. Correlations with
  the change in team net rating: returning minutes +0.22, usage +0.24, points +0.24,
  rotation count +0.23, lost impact −0.24, returning impact −0.20 (regression to the
  mean of strong teams). B9's Nov–Dec residual is monotone in the home−away
  returning-minutes gap: −0.83, −0.21, +0.17, +0.65, +1.08 pts by quintile. That is the
  signal B10/B10r recover.
* **Rotation prior accuracy:** preseason expected returning minutes vs the realized
  share of last season's minutes that returned: corr 0.42, RMSE 0.16 (2012–2020); corr
  0.30, RMSE 0.22 (2021–2026). P(return) is calibrated for rotation players (bins 0.55 →
  0.53, 0.69 → 0.69, 0.82 → 0.80) but weak at the team level in the portal era:
  incoming transfers are unknowable preseason in historical data.
* **New-player priors:** players with no D-I history get the DEV-tuned generic
  newcomer prior (−0.8 off, +0.4 def per 100). No recruiting data is used: there is no
  free, leakage-safe historical source. Players with history but no RAPM match use 0.95
  × their box-score SPM.

## Transfer model (B11)

Fitted walk-forward on earlier seasons only, through the origin (relative quantities
only). Next-season targets exist only for players who kept playing (survivor
selection), so intercepts and absolute slopes are biased. The first free-intercept
version was worse on DEV early games and is recorded as rejected. Persistence of
transfers relative to returners: k = 0.70 (2020 fit), 0.66 (2026 fit); team-strength
change: +0.07 offense / −0.08 defense per point of (new − old) team net. In DEV-era fits
(≤ 121 transfers) offensive persistence is ≈ 0, which is noise. **Alone (B11) it adds
nothing in the full stack** (+0.0007, 4/10) and is worse on 2025–26. It survives only
inside B12, together with the in-season box update.

## Box-score prior (B12)

SPM = ridge of same-season weak-prior RAPM on per-40 box (pts, ast, orb, drb, stl, blk,
tov, pf, fga, fta), TS%, 3PA rate and listed position, fitted on earlier seasons. DEV
comparison of the player layer alone (OLS of margin on player-implied margin, DEV
2013–14; `research/wave3/player_prior_dev.csv`):

| variant | RMSE | games 0–5 | games 6+ |
|---|---|---|---|
| RAPM carry (`pure-0.2.0`) | 11.429 | 12.420 | 11.181 |
| + transfer translation (B11) | 11.378 | 12.326 | 11.141 |
| box+RAPM season-start prior, no in-season box | 11.444 | 12.764 | 11.106 |
| box+RAPM season-start prior + in-season box | 11.405 | 12.710 | 11.072 |
| box only + in-season box | 11.439 | 12.831 | 11.082 |
| **RAPM carry + translation + in-season box (B12)** | **11.281** | **12.213** | **11.047** |

So RAPM carry is the better *season-start* prior. Box score is valuable as the *in-season*
prior that sparse RAPM shrinks toward.

## Prior decay (B10d)

The per-component DEV study (`research/wave3/stat_decay_dev.csv`) found every component's
one-step error minimized at a stronger prior than the shared tuned scale: tempo / to /
eff / rim / mid_rate / ast ×2; efg / fg2 / orb / ftr ×4; fg3 / mid_pct ≥ ×8 (grid edge);
fg3a_rate ×1. Applied together (B10d) they make game projections clearly worse (+0.044,
0/10). Component-level one-step error is a poor proxy for game-level error; the stacked
layer wants less-shrunk component features. Rejected.

## Early-season opponent adjustment and network

* The roster and conference terms enter the ridge solve itself (priors in the
  network), not a post-hoc blend.
* Network diagnostics: 99% of November and 86% of December D-I games are
  cross-conference. Nov–Dec cross-conference games whose two conferences had *no*
  earlier link that season: RMSE 12.13, vs 11.74 (1–2 links), 11.46 (3–5), 11.39 (> 10).
  The conference anchor (B14) alone is −0.0185 (10/10), Nov–Dec −0.044.

## Extreme mismatches

| projected margin | n | favourite's mean residual | RMSE |
|---|---|---|---|
| 0–5 | 22259 | −0.06 | 11.03 |
| 5–10 | 15853 | −0.23 | 11.05 |
| 10–15 | 8635 | −0.41 | 11.25 |
| 15–20 | 4032 | +0.13 | 11.66 |
| 20–25 | 1826 | +0.53 | 12.54 |
| 25–30 | 748 | +0.91 | 13.06 |
| 30+ | 425 | +1.53 | 13.39 |

Projections ≥ 25: n = 1,173, the favourite beats the projection by +1.13 (Nov–Dec
+1.35; 89–94% of these games are in Nov–Dec). The piecewise block fixes part of it:
−0.003 alone (7/10), and it is in B15.

## Garbage time

Garbage-time possessions (NCAA PBP flag) down-weighted to 0.3 in team efficiency
(applied to 52% of all team-games, where stint possessions matched the box estimate
within 15%; timestamp-safe because it uses only the finished game's own data):
+0.009 (1/10). **Rejected.** Points scored in garbage time still carry information
about team strength.

## Neutral sites, strong team × venue

Classified from venue city/state vs each team's modal home venue over the previous
three seasons (measurable, prior seasons only), with B9 residuals:

| class | n | mean residual (designated home) |
|---|---|---|
| true neutral | 5058 | +0.01 |
| venue in home team's state | 643 | +0.86 |
| venue in home team's city | 161 | +0.78 |
| venue in away team's state | 417 | +0.20 |
| venue in away team's city | 97 | −1.30 |

The residual means are real, but the semi-home block adds nothing out of sample
(B14v +0.0005, 6/10). Rejected. Strong home teams (top tercile of net rating) have mean
home residual +0.52 (weak −0.19), i.e. home court is larger for strong teams. Most of
this overlaps the mismatch nonlinearity; the venue × strength interaction did not help.

## Prospective archive

* `pure-0.2.0` is unchanged: the artifact hash is pinned in CI and its records keep
  their path.
* `pure-0.3.0` is frozen at `models/pure/pure-0.3.0.json` (sha256 6a58fb50…). It is
  trained on 2012–2026 with the DEV-fitted hook coefficients and the walk-forward
  player-prior fits, including the one for 2027 (fitted on pairs ≤ 2026).
* `models/pure/active.json`: incumbent `pure-0.2.0`, challenger `pure-0.3.0` (shadow).
  Both are projected on every run and archived append-only, the challenger under
  `projections/pure-0.3.0/…`.
* Live/research parity on 2025-12-06 (127 games): corr 0.9993 / 0.9994; mean
  |Δ margin| 0.30 / 0.27 pts. The residual comes from the full-history coefficient
  refit and the shorter live RAPM chain.
* Free ESPN pre-tip line snapshots (T-24h, T-6h, T-90m, T-30m, latest) are captured by
  a new workflow for future convergence benchmarking. They are downstream only.

## Cost audit

Wave 3 made **0 network requests**; all work used the cached free bulk data. Odds API
requests 0, CBBD requests 0, paid cost $0. Lifetime ledger: 226 sportsdataverse
releases (FREE_BULK), 40,615 raw.githubusercontent (FREE_RATE_LIMITED). The cost-policy
CI tests are unchanged and passing.

## Rejected / negative results

B10 engine-only (in-season roster strength double-counts), B10d (per-stat decay), B11
alone (translation), first-version B11/B12 fits (survivor-biased intercepts), box-score
season-start priors, B13 garbage weighting, B14v venue block, preseason roster stacking
block in the portal era.

## Next research

1. Measure 2026–27 prospectively: `pure-0.3.0` vs `pure-0.2.0` vs market at the
   captured horizons. This is the clean test; no further tuning on 2025–26.
2. Portal-era preseason information: incoming-transfer rosters are knowable before the
   season *now* (free roster pages, captured with timestamps), but not historically.
   Start a timestamped preseason roster capture so a future wave can test it honestly.
3. Conference-play onset bump (gap ≈ +0.165 around game 20): look at conference-specific
   home court and the re-weighting of the network when conference play starts.
4. Late-season plateau (+0.06–0.09 vs market): injuries and availability (no free
   source yet), and a variance model for blowouts.
5. Shot-accuracy components want very strong priors (≥ ×8 one-step): try a *separate*
   heavily shrunk accuracy feature beside the current ones, instead of re-shrinking the
   whole engine.
