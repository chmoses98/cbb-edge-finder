# Wave 5: live/research parity and the player-level possession model

Preregistration: `research/hypotheses/WAVE5.md`, commit 03792ea, written before any
Wave 5 result. Reference: B20 = `pure-0.4.0`. Evaluation: blocked rolling-origin
folds F1–F5 (2015–2024), a day-clustered bootstrap, and the gates fixed in the
preregistration. Cost: Odds API 0, CBBD 0, $0 (cost audit OK). No market quantity
enters any PURE feature, prior, label, hyperparameter or calibration.

## A. Verdict

* **Priority 0 is solved.** Live and research are now the same computation. Every
  model input and the projected margin/total agree to ≤ 1e-8 (pure-0.2.0) and ≤ 3e-14
  (pure-0.3.0, pure-0.4.0, pure-0.5.0) on 2025-12-06 and 2026-02-14 of 2025–26.
  Opening day 2025-11-03 is exact too, with one documented exception: a single
  pure-0.4.0 game, explained in section B.
  * The old ~0.26-point difference came from three sources:
    * coefficients (0.12–0.16): a refit through 2026;
    * the information set: `as_of`;
    * reconstruction (0.005–0.011): a short warm-up on the runner.
  * Live now replays only the current season from content-hashed season-boundary
    checkpoints of the research replay.
* **The player-level possession model works, mostly through Nov–Dec and first games.**
  * All four component arms passed the component gate.
  * The combined arm **B25 = B20 + B23 + B24 passed every freeze gate**:
    * margin RMSE Δ −0.0158;
    * 5/5 blocks and 10/10 seasons better;
    * bootstrap P(better) = 1.00, 90% CI [−0.0212, −0.0107];
    * Nov–Dec −0.021, Jan–Mar −0.012;
    * log loss −0.0007;
    * total RMSE −0.012;
    * every preregistered subgroup better (first game −0.046);
    * 2024–26 −0.0055.
* B25 is frozen as **`pure-0.5.0`, SHADOW challenger only**
  (sha256 `c4600f62351b26c159f1eaf9153d5a78a0c07e0c77fe20ed8bbc47e8e9ac0a19`).
  * The incumbent stays `pure-0.2.0`.
  * The prospective promotion rule frozen in Wave 4 alone decides promotion, after the
    2026–27 season.
* **Answer to the overriding question: yes, partly.** Expected possessions described
  from the players who will create them improve the margin forecast beyond team-level
  ratings.
  * Taken alone, the player-derived component forecasts are WORSE than the engine's
    opponent-adjusted team ratings for eFG%, TO%, ORB% and FT rate.
  * They are better only for the shot MIX: rim share and 3PA share.
  * The gain comes from combining the two. Player histories carry information before a
    team has played (game 1 −0.046), and team ratings dominate later.

## B. Live / research parity

| check | pure-0.2.0 | pure-0.3.0 | pure-0.4.0 | pure-0.5.0 |
|---|---|---|---|---|
| 2025-12-06, mean / max \|Δ margin\| | 1.3e-9 / 3.5e-9 | 3e-14 / 1e-13 | 2e-14 / 1e-13 | 6e-15 / 3e-14 |
| 2026-02-14 | 3e-10 / 1.7e-9 | 0 / 0 | 0 / 0 | 1e-15 / 7e-15 |
| 2025-11-03 (opening day) | 2e-9 / 1.1e-8 | 0 / 0 | 0.0011 / 0.119 (1 game)\* | 2e-15 / 1.4e-14 |
| before the fix, 2025-12-06 (warm-up rebuild) | 0.005 / 0.022 | 0.011 / 0.042 | 0.011 / 0.039 | – |

\* The one game is the opening game of a brand-new D-I program (New Haven), which has
no earlier D-I shooting history.
* pure-0.4.0's frozen B17 block fills that gap with the mean of the RESEARCH frame,
  which a live run cannot reproduce.
* The artifact is immutable, so this is documented and pinned in
  `tests/test_parity.py`.
* pure-0.5.0 uses fixed DEV constants instead (`shooting_fill`).

**Method** (`scripts/research/parity_diagnostics.py`):
* same games, same as-of (the day's first tip − 1 s), same artifact;
* feature by feature, every final input of the margin and total specs;
* `team_hca` is season-indexed, so it is injected from research (documented).

**Root cause:** reconstruction from a short warm-up, specifically:
* RAPM chains started 4 seasons back;
* the engine warm-up of 8 seasons;
* the P(return) model and career shooting trained on the runner's window.

**Fix** (`cbb_edge/app/checkpoints.py`, `scripts/research/build_checkpoints.py`):
* `models/pure/checkpoints/<version>/boundary_<B>/` stores the research replay's exact
  end-of-season state. Files are content-hashed and pinned; a checkpoint is written
  once and never modified.
  * `build_checkpoints.py` re-runs the research replays. Base, b15 and b16b engines,
    and the rot and b12 chains, reproduce the cached research outputs with max |Δ| = 0
    (the base chain to 5e-5, in pre-2025 seasons only).
* Contents:
  * engine fits;
  * RAPM chains;
  * base finals;
  * the preseason table;
  * shooting careers;
  * for pure-0.5.0, the possession-model state.
* `feature_frame(reconstruction="auto")` replays only season B+1.
* Every record carries `prospective.reconstruction = {mode, boundary, sha256}`.

**What remains for a PAST game** is coefficients only
(`research/wave5/parity_coefficients.json`):
* the artifact was fitted on 2012–2026, the OOS stack for season s on 2012..s−1;
* 0.12 / 0.16 mean |Δ| on 2025–26, mostly an intercept shift of −0.10 / −0.15;
* for the 2026–27 target season the artifact IS the research fit for s = 2027.

**Bugs found by the parity work, all fixed before publication:**
* An opening-day crash of the live B17 block. With no completed game in the season it
  had no rows.
* A game-1 fallback mismatch in live shooting features.
* Games without PBP got a defensive excess of 0 instead of the defender's running
  state. That affected 10% of rows, mostly 2012–2014. Re-evaluated; verdicts unchanged.
* **Leak.** The B24 top-5 interaction features (rim protector, ORB size) could include
  zero-weight players: players not yet seen with the team, who appear later in the
  season. Fixed, re-evaluated and re-frozen.
  * A first local pure-0.5.0 freeze (sha 46f888a4…) was discarded unpublished.
  * Its gate results were essentially identical (−0.0158).

## C. Model state

| version | role | arm | notes |
|---|---|---|---|
| pure-0.2.0 | **incumbent** | B9 | unchanged |
| pure-0.3.0 | shadow | B15 | unchanged |
| pure-0.4.0 | shadow | B20 | unchanged artifact; live now exact via checkpoints |
| pure-0.5.0 | shadow (new) | B25 = B20 + B23 + B24 | `requires_checkpoint`; current-season PBP in the daily runner |

* `models/pure/active.json`: challengers are [0.3.0, 0.4.0, 0.5.0].
* Every artifact hash and checkpoint hash is pinned in CI.

## D. Player shot quality (PBP shot zones)

* **Data.** Free SportsDataverse ESPN play-by-play, 2010–2026. 2010–2014 were downloaded
  for this wave so that DEV and the early training seasons have histories. Only
  basketball columns are read.
* **Coverage.**
  * 3.4–3.9k games per season in 2010–2013, against 5.0–6.3k from 2014.
  * Shooter id = box id ("P" + ESPN athlete id), matched for 99.3–100% of shots, exact
    only.
  * PBP FGA equal the box score exactly in 96–99% of player-games, 3PA in 98–99.5%.
  * Unmatched rows are almost all non-D-I opponents (team id missing by design). For
    example, 56 D-I player-games in 2024.
* **Format-robust zones.** League shares by season are in
  `data/silver/pbp_player_shots.coverage.json`.
  * Rim 0.33–0.36 up to 2025, then **0.387 in 2025–26**: the ESPN text format changed
    (TipShot ×10, no "Three Point Jump Shot" type).
  * Rim and tip are pooled. Shares enter only as deviations from the league's
    season-to-date mean.
  * Corner vs above-the-break 3: infeasible. Coordinates exist for only 6–27% of shots
    before 2026.
  * Assisted share rises over time (0.44 → 0.52), so it is centred.
  * Putback ≈ 6–9% and transition ≈ 12–17% of FGA.

## E. Finishing skill (heavily shrunk, DEV-fitted κ)

* Beta-binomial career posteriors (all teams, transfers carried) toward G/F/C positional
  means. Chosen on DEV 2011–2014 by next-game log-likelihood
  (`research/wave5/player_prior.json`):

  | rate | κ |
  |---|---|
  | rim | 100 |
  | j2 | 200 |
  | 3P | 200 |
  | FT | 25 (the B17 constant) |

* Positional means: rim 0.57 (G) / 0.63 (F) / 0.64 (C).
* Unseen players get the positional prior. Recruiting reputation is never used.
* **Shot-making vs shot selection** (validation 2015–2024, per offence side):

  | component | player-derived | engine (team, opp-adjusted) |
  |---|---|---|
  | 3P% | RMSE 0.1095, corr 0.112 | RMSE 0.1113, corr 0.132 |
  | 2P% | 0.0913 | 0.0883 |
  | eFG (x_pps / 2) | 0.0832 | 0.0810 |

  * Player skills are over-shrunk for prediction: calibration slopes are 1.3–1.5.
  * Shot-making is mostly unpredictable at game level (3P% corr ≈ 0.1 for every
    method).

## F. Expected shot mix

* x_mix_z = Σ w·u·s_z / Σ w·u. Weights w are EWMA minute shares (half-life 4). Before
  game 1: last season's weights × P(return), plus a vacancy at the unseen prior.
* Selection τ = 20 (DEV), usage τ_u = 100 min (fixed).
* Against a team-level baseline (own season-to-date share shrunk to the league,
  n/(n + 200)):

  | target | player-derived MAE / corr | team-level MAE / corr |
  |---|---|---|
  | rim share | 0.0761 / 0.431 | 0.0794 / 0.339 |
  | 3PA share | 0.0655 / 0.527 | 0.0679 / 0.470 |

* 2025–26 has the same ranking. The player-derived mix is better at every games-seen
  bucket except game 1 for 3PA share.
* The player-derived expected shooting component is reported next to the existing one
  and does not replace it.

## G. Defensive shot quality

* Defenders are not identified in PBP, so these are team-level stable quantities.
* Allowed excess = opponents' actual rim share, 3PA share, FT rate and rim FG% minus the
  same opponents' own player-based expectations. Season-to-date, shrunk n/(n + k_def).
* k_def = 250 attempts (DEV grid {250, 500, 1000}, edge of the grid).
* DEV error of the opponents' shot mix falls 9.5% against offence-only expectations.
* Opponent 3P% allowed is not used.

## H. Player possession components (B22)

* Shrunk per-opportunity priors, all with κ ≥ 50 opportunities (DEV):

  | rate | κ |
  |---|---|
  | TO / own usage | 50 |
  | AST / teammate FGM on court | 50 |
  | ORB / chances | 100 |
  | DRB / chances | 100 |
  | STL / opponent possessions | 400 |
  | BLK / opponent 2PA | 100 |
  | PF / min | 100 |
  | FTA / FGA | 50 |

* Alone they forecast worse than the engine (validation RMSE):

  | rate | player-derived | engine |
  |---|---|---|
  | TO% | 0.0563 (bias +0.020) | 0.0498 |
  | ORB% | 0.0864 | 0.0838 |
  | FT rate | 0.1436 | 0.1419 |

* As stack inputs: **B22 −0.0056 (5/5 blocks, P 0.998, Nov–Dec −0.007)**.

## I. Expected team profile (B24 = B21 + B22 + 5 interactions)

* Interactions:
  * spacing;
  * ball-handler scarcity;
  * rim protector;
  * ORB size;
  * usage HHI.
* **B24: −0.0125**, 5/5 blocks, 10/10 seasons, P 1.00, Nov–Dec −0.019.
* That is more than B21 (−0.0030) plus B22 (−0.0056).
* **Control:** shuffling the B23 + B24 features within season makes the stack WORSE
  (+0.0075). The gain is signal, not a stacking artifact.

## J. Player impact scale

* **Absence stretches.** A regular (min share ≥ 0.4, ≥ 1,500 rated possessions) misses
  ≥ 3 consecutive games mid-season. That gives 148 stretches and 535 games.
  * Predicted change = −net rating × minute share × possessions / 100.
  * Actual change = the margin against pregame ratings frozen at the stretch start.
  * **Slope 0.65, 90% CI [0.27, 1.03].** No evidence that ratings are compressed; if
    anything, they are inflated or replacement is above zero.
  * Intercept −1.47 points: an absence of a regular costs more than his own rating
    implies (disruption or thin bench).
* Persistence (same team, year to year): corr 0.77, slope 0.90.
* Transfers: corr 0.71, slope 0.82. This matches Wave 3 (k ≈ 0.7).
* No sportsbook move is used.
* **B23** (absence-driven part of the player signal as its own stack input): −0.0029,
  5/5 blocks, P 0.98, so useful. 2024–26 is +0.0004 (neutral).

## K. First-game diagnostics (validation, team-games at games seen 0)

* RMSE B20 12.97 → **B25 12.90**, against 10.90 at games ≥ 10.
* By quintile:

  | factor | Q1 → Q5 | B25 mean error Q1 → Q5 |
  |---|---|---|
  | newcomers | 2.2 → 7.9 | **+1.9 → −1.9** |
  | rotation share with earlier D-I seasons | 0.50 → 0.97 | **−2.3 → +2.1** |
  | transfer-in minute share | 0 → 0.40 | −1.0 → +1.3 |

  * Mean error is actual − projected, so +1.9 means the projection was too low:
    teams with many newcomers are over-rated in game 1 and experienced rotations
    under-rated.
  * Returning minutes, returning impact, prior strength and PBP coverage show no
    monotone bias.
* Rotation composition is the realised one. From 2026–27 on, the roster archive
  supplies it before tip, so this is a Wave 6 candidate. It was not used here (no
  retro-fixing).
* Returning coach: unavailable (no free, timestamped source).

## L. Preseason uncertainty index (preregistered, not fitted)

* Spearman ρ with |error| in games 1–5 = **0.003 (p 0.66)**. No decile pattern.
* Rejected as specified. Equal weights on these five inputs carry no variance
  information.

## M. Component error decomposition (B25, validation, per offence side)

* Team-points error SD 10.09. The regression on component errors explains R² 0.91.
* Share of error variance:

  | component | share |
  |---|---|
  | **shot making (eFG)** | **51%** |
  | pace | 22% |
  | turnovers | 10% |
  | off. rebounds | 4.5% |
  | free throws | 2.4% |

* Engine component forecasts (validation, MAE / RMSE / bias / calibration slope):

  | component | MAE | RMSE | bias | slope |
  |---|---|---|---|---|
  | possessions | 3.80 | 4.96 | −0.17 | 0.87 |
  | PPP | 0.106 | 0.133 | +0.009 | 0.89 |
  | eFG | 0.064 | 0.081 | +0.004 | 0.75 |
  | 3P% | 0.088 | 0.111 | +0.003 | **0.40** |
  | TO% | 0.040 | 0.050 | −0.005 | 0.81 |
  | ORB% | 0.067 | 0.084 | −0.006 | 0.80 |
  | FT rate | 0.111 | 0.142 | +0.002 | 0.76 |
  | team points (B25) | 7.99 | 10.09 | −0.17 | 0.99 |

  * Reliability by games seen is in `research/wave5/diagnostics_components.json`.
* Home vs away offence points-error RMSE: 10.19 vs 9.99.

## N. Full historical table (margin RMSE; `research/wave5/full_table.csv`)

| season | B15 | B20 | B21 | B22 | B23 | B24 | **B25** |
|---|---|---|---|---|---|---|---|
| 2015 | 10.682 | 10.653 | 10.650 | 10.641 | 10.648 | 10.647 | **10.641** |
| 2016 | 10.899 | 10.884 | 10.885 | 10.876 | 10.878 | 10.880 | **10.872** |
| 2017 | 11.101 | 11.097 | 11.093 | 11.091 | 11.095 | 11.080 | **11.077** |
| 2018 | 11.228 | 11.215 | 11.217 | 11.209 | 11.208 | 11.212 | **11.205** |
| 2019 | 11.251 | 11.240 | 11.240 | 11.233 | 11.241 | 11.223 | **11.223** |
| 2020 | 11.312 | 11.291 | 11.289 | 11.291 | 11.289 | 11.286 | **11.285** |
| 2021 | 11.818 | 11.797 | 11.802 | 11.797 | 11.792 | 11.795 | **11.789** |
| 2022 | 11.197 | 11.188 | 11.181 | 11.187 | 11.186 | 11.165 | **11.163** |
| 2023 | 11.236 | 11.210 | 11.199 | 11.200 | 11.208 | 11.182 | **11.181** |
| 2024 | 11.276 | 11.266 | 11.257 | 11.262 | 11.266 | 11.250 | **11.250** |
| 2015–24 | 11.185 | 11.169 | 11.166 | 11.163 | 11.166 | 11.156 | **11.153** |
| 2024–25 (evidence) | 11.384 | 11.357 | 11.350 | 11.356 | 11.359 | 11.350 | **11.351** |
| 2025–26 (evidence) | 11.449 | 11.439 | 11.439 | 11.435 | 11.438 | 11.437 | **11.434** |

**Blocked results (Δ vs B20):**

| arm | Δ | F1 | F2 | F3 | F4 | F5 | seasons < 0 | P(better) | Nov–Dec | Jan–Mar | log loss | total | 2024–26 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B21 | −0.0030 | −0.0009 | −0.0009 | −0.0013 | −0.0017 | −0.0095 | 7 | 0.993 | −0.0020 | −0.0036 | −0.0001 | −0.0034 | −0.0036 | useful |
| B22 | −0.0056 | −0.0104 | −0.0061 | −0.0038 | −0.0003 | −0.0069 | 8 | 0.998 | −0.0074 | −0.0045 | −0.0004 | −0.0015 | −0.0027 | useful |
| B23 | −0.0029 | −0.0059 | −0.0048 | −0.0006 | −0.0031 | −0.0004 | 8 | 0.983 | −0.0018 | −0.0036 | −0.0001 | −0.0021 | +0.0004 | useful |
| B24 | −0.0125 | −0.0052 | −0.0101 | −0.0115 | −0.0138 | −0.0215 | 10 | 1.000 | −0.0191 | −0.0083 | −0.0006 | −0.0088 | −0.0044 | useful |
| **B25** | **−0.0158** | −0.0122 | −0.0150 | −0.0119 | −0.0177 | −0.0223 | **10** | **1.000** | **−0.0213** | **−0.0124** | **−0.0007** | **−0.0124** | **−0.0055** | **FREEZE** |

* B25 by subgroup (Δ):

  | subgroup | Δ |
  |---|---|
  | first game | −0.046 |
  | games 2–10 | −0.014 |
  | conference | −0.012 |
  | non-conference | −0.021 |
  | neutral site | −0.006 |
  | \|margin_an\| > 15 | −0.021 |
  | top pace decile | −0.013 |

* B25 composition rule: B24 supersedes B21/B22, plus B23. It was recorded in
  `research/wave5/b25_components.json` before B25 was run, and re-derived (unchanged)
  after the defensive-state fix.

## O. Market gap (ESPN closing lines; benchmark only, never an input)

* Validation 2015–2024 (n = 25,256 lined games):

  | slice | B20 gap | B25 gap |
  |---|---|---|
  | all | +0.113 | **+0.097** |
  | game 1 | +0.585 | **+0.501** |
  | games 2–3 | +0.279 | +0.258 |
  | games 11+ | +0.067 | +0.052 |
  | Nov | +0.237 | +0.198 |
  | Jan–Mar | +0.077 | +0.061 |

* 2025–26 (n = 4,760): +0.062 → +0.060.
* The game-20 bump excess for B25 is +0.021, 90% CI [−0.034, +0.078]. Still not
  structural.
* Files: `research/wave5/market_scorecard.csv`, `research/wave5/market.json`.

## P. Distributional totals and OT

The regulation × OT mixture (seasons 2017–2024, parameters fitted on 2015..s−1):
* regulation Normal(a + b·total, σ(pace));
* P(OT) = P(regulation margin = 0) under Normal(margin, σ_reg);
* geometric extra OTs;
* each OT adds a Normal with mean 5/40-scaled.

Compared with a single Normal(total, σ):

| metric | single Normal | mixture |
|---|---|---|
| CRPS | 9.382 | **9.374** |
| log score | 4.2745 | **4.2709** |
| 50 / 80 / 95% coverage | 0.514 / 0.809 / 0.950 | 0.506 / 0.802 / 0.948 |
| P(y > q95) / P(y < q05) | 0.050 / 0.045 | 0.058 / 0.040 |
| fast top decile, CRPS | 10.051 | 10.052 |
| \|margin\| > 15, CRPS | 9.283 | 9.316 |

* The gain is tiny, and the mixture is slightly worse in mismatches and in the upper
  tail.
* **P(OT) is badly under-predicted:** 2.7% predicted vs 6.0% actual. In the top
  decile, 3.6% vs 8.0%.
  * The Normal margin density misses the endgame clustering at a tie (fouling and
    late 3PA).
  * Next step: an empirical P(tie | projected margin, σ), fitted in-window.
* Market pricing is never used to tune distributions. Not promoted; research
  foundation only.

## Q. Roster archive (`roster-archive` branch; audit `research/wave5/roster_audit.json`)

* First snapshot 2026-10-05T12:26Z: 5,341 players, 365 teams, all ESPN ids mapped.
* Daily change checks Sep–Nov, weekly Dec–Apr, append-only. Nothing is ever
  backfilled.
* Missing fields: class 0.4%, height 0.6%, weight 5.2%.
* **Staleness:**
  * 69 teams are still labelled 2025-26;
  * 941 players are listed as FR with an earlier D-I season;
  * transfer-ins are only 340 against 3,211 "returning" among teams labelled 2026-27,
    implausibly low for the portal era.
* Exact-id classification against history at capture time: returning 4,176, newcomer
  673, transfer-in 350, returning after a gap 142.
* ESPN preseason rosters must prove themselves over October–November. The archive
  records every change with its timestamp.

## R. Availability archive (`availability-archive` branch)

* Capturing: one capture plus the raw league injury feed so far. There are no games in
  October, so coverage (% games with status, % true missed regulars announced, lead
  time, false positives, late changes) can only be measured once games begin.
* Capture runs every 30 minutes Nov–Apr. The coverage measurement is a pending task
  for the first weeks of the season; it needs games.
* College coverage must prove itself. P-AVAIL stays an overlay (`+avail` records) and
  never enters a frozen model.

## S. Prospective models

* All four versions run daily from checkpoints.
* Opening-day simulation for 2026-11-02, with 54 games in the window:
  * every model in checkpoint mode;
  * pure-0.5.0 vs pure-0.4.0: corr 0.9975, mean |Δ margin| 0.73;
  * pure-0.5.0 vs pure-0.2.0: mean |Δ margin| 1.57.
* The daily runner downloads the CURRENT-season PBP release asset (free) when an active
  model needs it. History comes from the checkpoint.
* The off-season run (no games in the window) is clean for all versions.

## T. Market independence

* `tests/test_market_independence.py` now also checks every input of every frozen
  artifact (0.2.0–0.5.0) against the market-column guard.
* `pbp_shots` reads an explicit basketball column list. The PBP files' spread and
  `pregame_home_prob` columns are never read.
* Market data appears only in `wave5_market.py`, which runs downstream.

## U. Cost audit

* `python -m cbb_edge.data.cost_policy audit`: OK.
* Odds API lifetime requests 0, CBBD 0, paid spend $0.
* New data: SportsDataverse GitHub release assets only (FREE_BULK).

## V. Rejected / negative results (preserved)

* **Preseason uncertainty index (equal weights):** ρ = 0.003, rejected.
* **Regulation × OT mixture for totals:** negligible gain; P(OT) under-predicted 2×.
  Not adopted.
* **Player-derived component forecasts as replacements** for the engine's TO% / ORB% /
  FT rate / eFG%: worse alone. Kept only as complementary inputs.
* **Player-impact recalibration by absence stretches:** no compression found (slope
  0.65 [0.27, 1.03]). No rescaling.
* **Corner vs above-the-break 3:** infeasible (coordinates on 6–27% of shots).
* **Discarded freeze:** a first local pure-0.5.0 (sha 46f888a4…) was discarded before
  publication, because the parity check found the zero-weight top-5 leak (section B).
* **Count discrepancy:** the preregistration said "12 features" for B21 and B22. The
  enumerated lists (14 and 11) were implemented exactly as written.

## W. Next research (not done here)

* **First-game composition.** Newcomer count and experience of the rotation, from the
  preseason roster archive (known before tip). The bias is ±2 points (section K).
* **Empirical P(OT | projected margin)** fitted in-window, and a late-game term.
* **Over-shrunk player skills** (calibration slopes 1.3–1.5). Test lower κ with
  hierarchical previous-season priors, on DEV only.
* **Boundary-2027 checkpoints** after the 2026–27 season
  (`build_checkpoints.py engine|chain|write 2027`).
