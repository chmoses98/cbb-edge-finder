# Research Registry

Every experiment is registered here **before** its validation result is viewed.
Status values: `registered` → `run` → `accepted` / `rejected`. A rejected idea stays
listed. Results live in `research/baseline/metrics.json` and `research/reports/`.

## Season roles (fixed 2026-10-04, before any validation result)

| Role | Seasons | Use |
|---|---|---|
| Seed | 2006 | builds priors only; never evaluated |
| DEV | 2007–2014 | hyperparameter tuning (`scripts/research/tune_dev.py`, `roster_prior_dev.py`) |
| VALIDATION | 2015–2024 | arm comparison, walk-forward, expanding-window fitted layers |
| HOLDOUT | 2025–2026 | opened once per frozen configuration; any later change must be re-registered |

2021 (COVID season) is kept but flagged; results are reported with and without it in
future reports.

## Primary metrics (decided in advance)

1. Margin RMSE and MAE (lower is better); 2. total RMSE/MAE; 3. win-probability log
loss and Brier; 4. calibration (ECE). ROI is a secondary diagnostic only, never a
selection criterion. An arm is "better" only if it improves validation margin RMSE
AND does not worsen log loss, on the common sample of games every arm projects.

## Arms

| ID | Description | Status |
|---|---|---|
| B0 | home court + league total (prior seasons) | run |
| B1 | raw rolling efficiency + tempo, same shrinkage engine, opponent adjustment off | run |
| B2 | opponent-adjusted efficiency + tempo, analytic projection | run |
| B3 | B2 + opponent-adjusted Four Factors / shot profile via expanding-window ridge | run |
| B4 | B3 with roster-continuity priors (returning-minutes share, leakage-safe) | run |
| B5 | B4 + preregistered matchup interactions (H-B5) | run |
| B6 | B3 + player impact (walk-forward RAPM, NCAA stints 2011–2026) on expected rotation | **accepted** (wave 2) |
| B7 | B3 + opponent-adjusted shot profile (rim/mid/assisted) + rim matchup | **accepted** (wave 2) |
| B8 | B3 + rest, season phase, shrunk team-specific home court | **accepted** (wave 2) |
| B9 | B3 + B6 + B7 + B8 — **PURE production arm `pure-0.2.0`** | **accepted** (wave 2) |
| B10 | B9 + roster hook (in-season player strength) + preseason roster block | passed (fragile; worse 2025–26) |
| B10r | B9 + roster hook (observed rotation × season-start ratings) [+ preseason block] | passed (post-hoc variant) |
| B10d | B9 with per-stat prior strengths from DEV one-step error | rejected |
| B11 | B9 player features with transfer translation priors | rejected |
| B12 | B9 player features with transfer translation + in-season box-score (SPM) prior | passed |
| B13 | B9 + garbage-time weighted efficiency + mismatch block | rejected (mismatch sub-arm passed) |
| B14 | B9 + conference anchor in the opponent network prior | passed |
| B14v | B9 + neutral-site / semi-home venue block | rejected |
| B15 | B10r hook + B14 anchor (joint) + B12 player features + mismatch block — **`pure-0.3.0`** | **promoted** (shadow challenger) |
| B16a | B15 + earlier-meeting (rematch) residual features | rejected (wave 4) |
| B16b | B15 with dynamic conference anchor (w = n/(n+k), k=400) | useful, tiny (wave 4) |
| B17 | B15 + heavily shrunk player shooting skill (3P/FT/2P) | **useful** (wave 4) |
| B18 / B18r / B18t | spline calibration / regulation-margin target / closeness for totals | rejected / rejected / exploratory no gain |
| B19h | B15 with absence-persistence + replacement-minutes rotation | useful, small (wave 4) |
| B19oracle | perfect regular-absence information (diagnostic upper bound) | diagnostic: −0.0039 |
| B20 | B15 + B16b + B17 + B19h — **`pure-0.4.0`** | **frozen** (shadow challenger #2) |
| ELO | points-based Elo dynamic benchmark | run |
| MARKET | free historical closing line (ESPN pickcenter) | run |
| ENSEMBLE | B3 + market prior, expanding-window ridge | run |
| ESPN | ESPN published pregame win probability (benchmark only) | run |

## Hypotheses

* H-B1-1 Opponent adjustment improves projections: B2 margin RMSE < B1. — `research/hypotheses/H-B1.md`
* H-B3-1 Adjusted Four Factors add information beyond adjusted efficiency. — `H-B3.md`
* H-B4-1 Returning-minutes continuity improves early-season projections. — `H-B4.md`
* H-B5-1..6 Matchup interactions. — `H-B5.md`
* H-PRIOR-1 Prior decay rate (prior strength λ, carry-over ρ) — tuned on DEV only. — `H-PRIOR.md`
* H-MKT-1 Model anticipates open→close movement (exploratory on 2026; prospective test registered) — `H-MKT.md`

## Wave 2 outcomes (see research/reports/WAVE2.md; preregistration research/hypotheses/WAVE2.md)

| Hypothesis | Result | Status |
|---|---|---|
| H-B6-1 player impact | val RMSE −0.006 vs B3 (7/10 seasons), larger in 2024–26 (−0.03 to −0.04) | accepted (weak) |
| H-B6-2 RAPM tuning (DEV) | λ = 800 poss (interior optimum), carry 0.95, new-player prior (−0.8, +0.4) | done |
| H-B7-1 shot profile | val RMSE −0.006 (9/10) | accepted (weak) |
| H-B8-1 context | val RMSE −0.010 (9/10) | accepted |
| H-B9-1 combined | val RMSE −0.025 (10/10); historical −0.060 | accepted → production |
| H-PACE-1 ridge possession model | possession MAE 3.749 vs 3.752 (calibrated additive) | rejected (no meaningful gain) |
| H-UNC-1 heteroscedastic σ | log loss 0.5303 vs 0.5303 (bucket SD); PIT deviation slightly worse | rejected (no gain) |
| H-B4 roster continuity (PR #1) | superseded by B6 (player identity carries over) | rejected |
| H-B5 matchup interactions (PR #1) | no gain | rejected |

## Wave 3 outcomes (see research/reports/WAVE3.md; preregistration research/hypotheses/WAVE3.md)

| Hypothesis | Result | Status |
|---|---|---|
| H-W3-DECAY per-stat prior decay | DEV one-step optimum is stronger priors (×2–×8); as an arm (B10d) val RMSE +0.044, 0/10 | rejected |
| H-W3-ROSTER player-built preseason prior | in-season version (B10 engine) +0.002; rotation × season-start ratings (B10r engine) −0.010 (10/10) | accepted (B10r form) |
| H-W3-RET returning production predictive | corr with Δ team net 0.22–0.24; B9 Nov–Dec residual monotone in returning-minutes gap (−0.8 → +1.1 pts); preseason block helps 2015–20, hurts 2021–24 | accepted pre-portal; not used in B15 |
| H-W3-TRANSFER translation | transfers persist at k≈0.66–0.70 of returners, +0.07 off / −0.08 def per point of team-strength change; arm B11 +0.0007 (4/10) | rejected alone (kept inside B12) |
| H-W3-BOX box-score prior | box SPM at season start hurts early games on DEV; in-season box update + RAPM carry (B12) −0.008 (9/10), Nov–Dec −0.018 | accepted |
| H-W3-GARBAGE competitiveness weighting | +0.009 (1/10) | rejected |
| H-W3-NEUTRAL semi-home | B9 residual +0.86 (home-state "neutral", n=643), but block adds nothing (+0.0005) | rejected |
| H-W3-NET network sparsity | Nov–Dec cross-conference RMSE 12.13 with 0 prior bridge games vs 11.39 with >10; conference anchor (B14) −0.0185 (10/10), Nov–Dec −0.044 | accepted |
| Extreme mismatches | favourites projected ≥25 beat projection by +1.13 (Nov–Dec +1.35); piecewise block −0.003 (7/10) | accepted (in B15) |
| B15 combined | val −0.0389 (10/10), Nov–Dec −0.083, Jan–Mar −0.011, log loss −0.0018; 2025–26 −0.066 | **promoted → `pure-0.3.0` (shadow)** |

## Wave 4 outcomes (see research/reports/WAVE4.md; preregistration research/hypotheses/WAVE4.md)

| Hypothesis | Result (validation, blocked CV, Δ vs B15) | Status |
|---|---|---|
| H-W4-REMATCH (B16a) | +0.0001, P(better) 0.48; first-meeting residual corr with second −0.025 | rejected |
| H-W4-CONFDYN (B16b) | −0.0004 (P 0.99); DEV k-search flat | accepted (negligible) |
| H-W4-SHOOT (B17) | −0.0145, 5/5 blocks, Nov–Dec −0.020, totals −0.024; κ3P=200, κ2P=100, κFT=25 | **accepted** |
| H-W4-NONLIN (B18, B18r) | +0.0049 / +0.0002; calibration slope already 0.99 | rejected |
| H-W4-AVAIL (B19h) | −0.0013 (P 0.99); oracle bound −0.0039 | accepted (small) |
| Game-20 bump | excess gap +0.010, 90% CI [−0.043, +0.067] | not a structural effect |
| B20 combined | −0.0156, 5/5 blocks, 10/10 seasons, P 1.00; 2025–26 −0.018 | **frozen → `pure-0.4.0` (shadow)** |

## Wave 5 outcomes (see research/reports/WAVE5.md; preregistration research/hypotheses/WAVE5.md)

| Hypothesis | Result (validation, blocked CV, Δ vs B20) | Status |
|---|---|---|
| Priority 0 live/research parity | warm-up rebuild 0.005–0.011 mean \|Δ\| → checkpoint replay ≤ 1e-8 (0.2.0), ≤ 3e-14 (0.3.0–0.5.0); old 0.26 = coefficients + as-of | **fixed** |
| H-W5-SHOT (B21) player shot zones × finishing × defence | −0.0030, 5/5 blocks, P 0.99; player mix beats team-level for rim / 3PA share | accepted (inside B24) |
| H-W5-POSS (B22) player possession components | −0.0056, 5/5, P 0.998, Nov–Dec −0.007 | accepted (inside B24) |
| H-W5-SCALE (B23) absence-driven player signal | −0.0029, 5/5, P 0.98; absence-stretch slope 0.65 [0.27, 1.03], no compression | accepted (arm); no rescaling |
| H-W5-PROFILE (B24) combined profile + 5 interactions | −0.0125, 5/5, 10/10, P 1.00; shuffled control +0.0075 | accepted |
| Preseason uncertainty index | Spearman 0.003 with \|error\| games 1–5 | rejected |
| Regulation × OT totals mixture | CRPS 9.374 vs 9.382; P(OT) 2.7% predicted vs 6.0% actual | not adopted |
| B25 combined (B20 + B23 + B24) | −0.0158, 5/5, 10/10, P 1.00, Nov–Dec −0.021, first game −0.046; 2024–26 −0.0055 | **frozen → `pure-0.5.0` (shadow)** |

## Wave 6 outcomes (see research/reports/WAVE6.md; preregistration research/hypotheses/WAVE6.md)

| Hypothesis | Result (validation, blocked CV, Δ vs B25) | Status |
|---|---|---|
| First-game bias origin | realized departed share corr −0.10 (+2.0 → −1.8 pts); P(return) expectation corr 0.001; departed value corr −0.03 | missing roster truth |
| H-W6-DEV (B26) development priors | −0.0007, P 0.83 | rejected |
| H-W6-CARRY (B27) continuity from P(return) | −0.0016, F4/F5 worse | rejected |
| H-W6-REVEAL (B28) revealed continuity | −0.0257, 5/5, games 2–5 −0.089; reverses in 2024–26 (g2–5 +0.014 / +0.044) | useful (not frozen) |
| B29 = B25 + B28 | first game −0.010 vs gate −0.03 | **rejected (no freeze)** |
| ORACLE roster truth (not eligible) | first game −0.19 for (a) substitution and (b) continuity each | upper bound only |
| Expected rotation model | top-5 82%, starters 78%, minutes MAE 7.4 (naive 10.6) | adopted for P-ROSTER-1 |
| ESPN preseason rosters | 82% continuity listed vs 42% actual; 183/296 list ≥ 2 exhausted players | stale; CONFIRMED rule |
| P-ROSTER-1 overlay | deployed PROSPECTIVE_ONLY on pure-0.5.0 | evaluated on 2026–27 |

## Wave 7 outcomes (see research/reports/WAVE7.md; preregistration research/hypotheses/WAVE7.md)

| Item | Result (live snapshot 20261005T215634Z) | Status |
|---|---|---|
| NCAA Membership Directory (public memberList JSON) | 365 D-I MBB members; 364 verified athletics domains | authority for universe and domains |
| Universe reconciliation | 257 exact + 107 verified alias; Saint Francis out; West Florida new (unmapped) | done |
| Official roster discovery + parsers (SIDEARM / WMT / table) | 349 / 364 pages; 342 CURRENT or PROBABLY_CURRENT | deployed (daily) |
| Identity (exact only, A2/A4) | 97.2% of official names; 98.6% of ≥ 10-min rotation players have an ESPN id | deployed |
| Team confidence | CONFIRMED 320, LIKELY 3, CONFLICTED 20, STALE 18, UNKNOWN 4 | 88.5% vs 90% target |
| Departed-player exposure, pre-tip | BASE 147 / 200 game-1 minutes on departed players; ROSTER 0 | scored after games |
| Positional rotation bounds | top-5 0.816 → 0.802 | rejected |
| Water-filled rotation (A3) | same ranking; exactly 200 minutes | adopted |
| Continuity correction audit | mean −0.67; \|adj\| p95 5.3, max 8.4; explained by measured turnover (truth continuity 0.263 vs expected 0.472) | uncapped; prospective test |
| Historical freeze | none | by design |

## Wave 8 outcomes (see research/reports/WAVE8.md; preregistration research/hypotheses/WAVE8.md)

| Item | Result (2026-10-06, no 2026–27 game played) | Status |
|---|---|---|
| Freeze audit after PR #7 merge (9b0fbae) | all model / spec / prereg hashes unchanged; main CI green | done |
| Prospective P-ROSTER-1 scorer (WAVE7 §7 + WAVE8 D1–D8) | daily `prospective-scores` workflow, deterministic, integrity-linked | deployed; no results yet |
| Season-aware D-I membership | 2006–2026 from frozen pipeline, 2026–27 NCAA; Saint Francis kept, West Florida ESPN 2697 (no canonical id) | deployed |
| Coverage C1 (linked official host) | ASU: 13 players, 2026–27 (probe) | adopted |
| Coverage C4 (www. 404 → bare host) | Missouri: 15 players, 2026–27 (probe) | adopted |
| Alabama / LSU / Jacksonville / LIU | official pages published without (full) player lists | not a parser gap |
| Unresolved identity impact | ≤ 39.5 of 72,800 rotation minutes | exact-only kept |
| P-ROSTER-1 game-1 result | — | pending games |

## Wave 9 outcomes (see research/reports/WAVE9.md; rules research/hypotheses/WAVE9.md)

| Item | Result (2026-10-06, no 2026–27 game played) | Status |
|---|---|---|
| PR #8 merge (824c9db) + freeze audit | all frozen hashes unchanged; main CI green; scores workflow ran from main | done |
| West Florida T0374 (ESPN 2697, from 2026–27 only) | silver 2006–2026 identical old vs new; projections byte-identical for common games | adopted (infrastructure) |
| End-to-end dry run (production code, simulated clock) | 54 / 54 opening-window games VALID; all operational scenarios pass | done |
| Pre-tip evidence gate | VALID / INVALID / UNSCORABLE / PENDING; 10 fail-closed checks | deployed |
| Catch-up cadence (hourly ticks) | crashed slot recovered: 54 VALID vs 12 without catch-up | deployed |
| Readiness / observability / alerts (ops-watch) | Nov 2–9 preview: 142 teams, 0 unscorable, 0 CRITICAL | deployed |
| Presentation amendment A1 | intervals need N >= 20 on >= 10 days | adopted (pre-results) |
| Roster coverage after first merged capture | CONFIRMED 329 (Missouri, ASU now CONFIRMED); 355 / 364 pages | live |
| Model / P-ROSTER-1 change | none | by design |

## Wave 10 outcomes (see research/reports/WAVE10.md; rules research/hypotheses/WAVE10.md)

| Item | Result (2026-10-06, no 2026–27 game played) | Status |
|---|---|---|
| PR #9 merge (6c60608) + freeze audit | all frozen hashes unchanged; CI, scores, ops-watch, roster-capture green on main; West Florida CONFIRMED | done |
| ESPN tip-time semantics | `timeValid=false` ⇔ 00:00 ET ⇔ "TBD" (1,520 / 1,629); 0 midnight listings in 18,866 completed games | documented |
| TBD-safe projection (R1/R2) | passed-placeholder games projected only on live "pre" evidence; started / postponed / cancelled never projected | deployed |
| Tip-time history | append-only `schedule-archive` (changes + gate evidence) | deployed |
| TBD scoring (R5) | never-announced tip: provable lower bound; unprovable → UNSCORABLE `tbd_start_unprovable` | deployed |
| TBD failure simulations | 17 tests, all fail closed | done |
| Opening week Nov 1–9 | 356 D-I games (262 TBD); **249 missing from the SDV schedule** (SDV lag) | alerted; owner decision |
| T0333 Utah Valley "Tanner Davis" | blocked by an NAIA namesake in the frozen identity pool (pool includes 38,169 never-D-I players) | documented; owner decision |
| Model / P-ROSTER-1 / scoring change | none | by design |

## Wave 11 outcomes (see research/reports/WAVE11.md; rules research/hypotheses/WAVE11.md)

| Item | Result (2026-10-06, no 2026–27 game played) | Status |
|---|---|---|
| PR #10 merge (6165438) + freeze audit | all frozen hashes unchanged; CI, scores, ops-watch, roster-capture green on main | done |
| ESPN-vs-SDV overlap (completed 2025–26, 1,391 games) | every pipeline field identical; only display / venue names differ | validated |
| ESPN fallback (SDV first, ESPN only when absent) | 2026–27: 1,629 SDV + 4,158 fallback rows; 55 bracket placeholders excluded | deployed |
| Historical safety | silver 2006–2027 byte-identical to main without fallback | proven |
| Nov 1–9 readiness (pre-A1, UTC window; superseded) | 356 D-I games: 107 SDV + 249 fallback; 0 absent from both; 0 at risk | superseded by A1 |
| Full-window dry run (pre-A1, synthetic; superseded) | 357 / 357 projected, P-ROSTER-1, settled, VALID; catch-up 8 games, 0 mutations, 0 post-tip records | superseded by A1 |
| Gate rule G1 (tightening) | schedule identity changed → UNSCORABLE | adopted (pre-results) |
| Amendment A1: field-level reconciliation of shared games | 1,625 shared: 1,371 exact, 254 reconciled to ESPN (tip 204, venue 41, notes 37, teams 35, conference 18, tournament 8, neutral 4); 0 unresolved, 0 ambiguous | adopted (pre-results, owner) |
| A1 historical invariance | silver 2006–2027 byte-identical to main without a completion file | re-proven |
| A1 rest days | 639 SDV-native games change: 452 from new fallback games, 187 from reconciled tips, 0 unexplained; formula unchanged | approved consequence |
| A1 canonical ET universe (356 vs 357) | 401920686 (UConn–Wagner, Nov 9 7 PM ET) was dropped by the old UTC window; canonical Nov 1–9 = 357 | fixed + regression test |
| A1 Nov 1–9 readiness (frozen snapshot) | 357 = canonical: 107 SDV + 250 fallback; 0 absent, 0 at risk; 0 CRITICAL, 16 WARNING (all reconciled) | target met |
| A1 full dry run (synthetic) | 357 projected/settled; 356 VALID + 1 designed UNSCORABLE (matchup changed after last pre-tip record); duplicate run 0 written | passed |
| Model / P-ROSTER-1 / scoring change | none | by design |
