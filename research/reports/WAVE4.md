# Wave 4: availability, conference transition, shooting skill, nonlinearity

Reference: **B15 = `pure-0.3.0`** (11.1844 validation margin RMSE; reproduced
exactly). Protocol, gates and the prospective promotion rule were preregistered in
`research/hypotheses/WAVE4.md` (commit 99405e4) before any Wave 4 arm was evaluated.

Evaluation method:
* Validation seasons 2015–2024 in five blocks: F1 2015–16, F2 2017–18, F3 2019–20,
  F4 2021–22, F5 2023–24.
* Each season is predicted by an expanding-window model.
* 2,000-resample game-day-clustered bootstrap, stratified by block.
* 2025–26 is evidence only.

Every arm is PURE_BASKETBALL. Market data appears only in the downstream benchmark.

## Verdict

**B20 = B15 + B17 (player shooting skill) + B19h (absence-persistence rotation) + B16b
(dynamic conference anchor) passes every preregistered freeze gate and is frozen as
`pure-0.4.0`**, a second shadow challenger. `pure-0.2.0` stays the incumbent;
`pure-0.2.0` and `pure-0.3.0` are unchanged (hashes pinned in CI).

| | B15 (`pure-0.3.0`) | B20 (`pure-0.4.0`) |
|---|---|---|
| validation margin RMSE | 11.1844 | **11.1688** (−0.0156) |
| blocks better (F1..F5) | — | **5 / 5** (−0.022, −0.008, −0.016, −0.014, −0.018) |
| seasons better | — | **10 / 10** |
| bootstrap P(Δ < 0); 90% CI | — | 1.000; [−0.020, −0.011] |
| Δ Nov–Dec / Jan–Mar | — | −0.021 / −0.012 |
| Δ log loss / Δ total RMSE | — | −0.0007 / −0.023 |
| 2025–26 evidence | — | −0.018 (Nov–Dec −0.042) |
| market_gap, validation (benchmark only) | +0.128 | **+0.113** |

Almost all of the gain is **shooting skill** (B17: −0.0145 alone). The availability and
dynamic-conference components pass the gates, but they are small.

## Full historical results (Δ vs B15)

| arm | val RMSE | Δ | F1 | F2 | F3 | F4 | F5 | P(Δ<0) | Δ Nov–Dec | Δ Jan–Mar | Δ log loss | Δ total | 2025–26 Δ | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B16a rematch | 11.1845 | +0.0001 | +0.0018 | −0.0030 | +0.0004 | +0.0004 | +0.0008 | 0.478 | +0.0004 | −0.0002 | +0.0000 | −0.0056 | −0.0003 | not useful |
| B16b dynamic conf. | 11.1841 | −0.0004 | +0.0000 | −0.0002 | −0.0014 | −0.0000 | −0.0001 | 0.990 | −0.0005 | −0.0002 | −0.0000 | −0.0003 | −0.0017 | useful (tiny) |
| **B17 shooting skill** | 11.1700 | **−0.0145** | −0.0198 | −0.0071 | −0.0137 | −0.0154 | −0.0166 | 1.000 | −0.0199 | −0.0110 | −0.0006 | −0.0240 | −0.0153 | **useful** |
| B18 nonlinear calibration | 11.1894 | +0.0049 | +0.0075 | −0.0025 | +0.0003 | +0.0170 | +0.0041 | 0.028 | +0.0093 | +0.0022 | +0.0001 | +0.0000 | +0.0005 | not useful |
| B18r regulation target | 11.1847 | +0.0002 | −0.0003 | +0.0007 | +0.0006 | −0.0019 | +0.0017 | 0.267 | +0.0011 | −0.0003 | +0.0000 | +0.0000 | −0.0004 | not useful |
| B18t closeness → totals ¹ | 11.1845 | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 | 0 | +0.0007 | 0 | exploratory, no gain |
| B19h availability (historical) | 11.1832 | −0.0013 | −0.0025 | −0.0013 | −0.0015 | +0.0012 | −0.0021 | 0.993 | −0.0016 | −0.0011 | −0.0001 | +0.0011 | −0.0011 | useful |
| B19oracle ² | 11.1805 | −0.0039 | −0.0028 | −0.0019 | −0.0062 | −0.0029 | −0.0057 | 1.000 | −0.0047 | −0.0035 | −0.0002 | +0.0022 | −0.0019 | diagnostic |
| **B20 combined** | **11.1688** | **−0.0156** | −0.0217 | −0.0083 | −0.0160 | −0.0139 | −0.0183 | 1.000 | −0.0212 | −0.0121 | −0.0007 | −0.0229 | −0.0181 | **FREEZE** |

¹ Post-hoc, preregistered as exploratory before it was run; not eligible.
² Upper bound, NOT a model: the game's own box score reveals which pregame regulars did
not play. The first version also used *who else* appeared. Deep-bench players appear
in blowouts, so that leaked the outcome and gave a spurious −0.042. It is preserved as
`pf_b19oracle_leaky` and documented as a flawed diagnostic.

## Player availability (Priority 1)

* **Free sources.** All ESPN public endpoints:
  * team roster (`status`, `injuries[]`, class, position, height): works now;
  * league `/injuries`: responds, empty in October;
  * core team injuries: responds, empty;
  * game summary: injuries section if published, and post-game `starter` /
    `didNotPlay`.

  College injury coverage cannot be measured before games begin. Raw text is archived
  so it can be measured honestly. No paid feed, no CBBD, no Odds API.
* **Capture.**
  * `availability-capture` runs every 30 minutes Nov–Apr and writes to the
    `availability-archive` branch. Checkpoints: T-24h, T-6h, T-90m, T-30m, latest.
  * Each row carries canonical and ESPN ids, team, game, timestamp, canonical status,
    P(plays), source, native text, confidence and changed-since-last-capture. The
    expected-minutes adjustment is filled by the replacement model at projection time.
  * Snapshots are append-only (`docs/AVAILABILITY.md`).
* **Absence study (2011–26, actual minutes):**
  * a regular's *first surprise absence* happens in ~2% of his games (21,904 cases);
  * after one missed game only **49%** of regulars play the next; after two, **34%**;
  * the pure-0.3.0 rotation still kept ~84% of the share after one miss;
  * first surprise absences are not claimed knowable historically.
* **Replacement minutes.**
  * Δshare_B ∝ cond_share_B^γ × (1 + β·same_position), water-filled so no player
    exceeds 40 minutes.
  * DEV choice γ = 0.5, β = 1.0: next-game share RMSE 0.1630 vs 0.1686 for plain
    proportional redistribution. Both values are at the edge of the preregistered grid.
  * Absent minutes spread more evenly than proportionally, and preferentially to the
    same position.
* **B19h** applies persistence + replacement through player impact (B12 ratings). It
  is useful but small (−0.0013).
* **Value of perfect regular-absence information** (corrected oracle): −0.0039 overall,
  and only −0.016 even on the 16,495 validation games where a regular was out. In this
  architecture, availability reaches the projection through the stacked player layer,
  and team ratings already absorb persistent absences.
* **P-AVAIL overlay (PROSPECTIVE_ONLY).**
  * Challengers' games with reported statuses are re-projected through the replacement
    model and archived as `<version>+avail`, with base margin, total and every changed
    share.
  * Mechanics check (2025-12-06, top-minutes player of 12 home teams set "out"): the
    margin moves −0.20 on average (max −0.43). That is a small effect, consistent with
    the oracle. The 2026–27 archive will show whether real reports do better.

## Conference transition (Priority 2): root cause of the "game-20 bump"

**There is no structural bump.**
* B15's own RMSE falls smoothly through games 15–28 (10.90 → 10.74 → 10.83 → 10.92).
* The Wave 3 spike (+0.165 at game 20) was a single convergence-curve point. Its
  neighbours were 0.105 and 0.084.
* The preregistered test (benchmark only) compares the gap at games 18–22 with games
  12–17 and 23–28: excess **+0.010, 90% CI [−0.043, +0.067]** for B15 (B20: +0.017,
  [−0.035, +0.072]).
* At games 15–25, first conference meetings and rematches have the same gap (0.083 vs
  0.080).

B15 residuals by game type (validation, regular season):

| slice | n | RMSE | margin bias | total bias | poss bias | home / away pts bias |
|---|---|---|---|---|---|---|
| non-conference | 18,606 | 11.66 | +0.16 | −0.34 | −0.12 | −0.09 / −0.25 |
| conference, first meeting | 18,048 | 10.95 | −0.08 | −0.25 | −0.29 | −0.16 / −0.09 |
| conference rematch | 13,282 | 10.85 | −0.01 | +0.00 | −0.08 | −0.00 / +0.00 |

Smaller patterns are noted but not modeled:
* quick rematches (≤ 14 days, n = 2,364) total −0.84;
* same-venue second meetings (n = 676) total −1.49;
* late-season games (26+) total +0.95.

## Rematch effects (B16a)

* The first meeting's residual does not predict the second meeting's: correlation
  −0.025 for margin, +0.020 for total, +0.025 for possessions.
* As features (B16a) they add nothing: +0.0001, bootstrap P(better) 0.48. The engine
  already absorbs the first result.

## Conference anchor (B16b)

* The dynamic version moves from last season's conference strength to conference-mates'
  current ratings as cross-conference games accumulate: w = n_c / (n_c + k).
* On DEV it is indistinguishable from the static anchor: k ∈ {25, 100, 400} →
  10.7642 / 10.7638 / 10.7635 vs 10.7634 static. k = 400 was chosen per the
  preregistration.
* Full run: −0.0004 (P(better) 0.99). It passes the gate but is negligible, because the
  solve already pools conference-mates once networks connect.
* Deviation from the preregistration: the hook coefficients were kept at B15's
  DEV-fitted values, not refitted with the dynamic C. Refitting needs the engine's own
  path.

## Shooting skill vs shooting luck (Priority 3)

* **Luck** (split-half reliability, validation):

  | percentage | attempts for reliability 0.5 |
  |---|---|
  | team 3P% | ~700 (≈ a full season) |
  | opponent 3P% | ~1,370 (≈ two seasons; mostly luck) |
  | 2P% | ~380 |
  | opponent 2P% | ~460 |
  | FT% | ~230 |

  Recent 3P% should be regressed very hard, and opponent 3P% almost entirely.
* **Skill** (B17).
  * Player beta-binomial posteriors over the whole D-I career (transfers keep their
    history). Fitted on DEV 2008–14: κ = 200 attempts for 3P, 100 for 2P, 25 for FT.
  * Position means: 3P G .349 / F .333 / C .324; FT G .730 / F .653 / C .620.
  * The 3P prior also leans on FT skill (b = 0.25).
  * Each team's expectation is weighted by EW attempt shares from earlier games only.
* The team skill estimate predicts a game's 3P% better than the engine's
  opponent-adjusted 3P%: correlation 0.131 vs 0.119, in every games-played bucket.
* In the stack: **−0.0145, 5/5 blocks, Nov–Dec −0.020, totals −0.024**. This is the
  largest single gain of the wave.

## Strength nonlinearity (B18)

* B15 is not compressed. Calibration slope of realized on projected margin: 0.99
  overall, 0.96 for the top 5% of home strength. Projected-margin bins have residuals
  within ±0.3, except the 30 games beyond −25.
* Strong home vs weak (n = 321): −1.80. Weak home vs strong: only n = 10.
* Wave 3's mismatch block already took the generalizable part. The spline calibration
  (B18) is worse: +0.0049, F4 +0.017.

## Extreme pace (Priority 4)

* The fastest projected-pace decile has total RMSE 18.1 vs 16.0 for the slowest. Total
  bias stays near 0 in every decile.
* Projected possessions are too dispersed: +0.76 in the slowest decile, −1.02 in the
  fastest. The stacked total already absorbs this.
* Squared total error splits roughly 37% possession error and 72% PPP error, with a
  small negative interaction (correlation −0.08). OT share is flat (5.7–6.7%) across
  deciles.
* Root cause: more possessions mean more variance, not bias. No fix was warranted. The
  rejected richer possession model stays rejected.

## Regulation vs overtime

* 6.0% of games go to overtime.
* Margin variance: 202.4 regulation vs 203.7 final. RMSE: 11.172 against the regulation
  margin vs 11.200 against the final margin.
* OT games: total RMSE 25.9 vs 16.0 otherwise; on average they add 24.3 points.
* Training the margin on a regulation target (B18r) does nothing (+0.0002). Overtime
  matters for totals, not margins.
* Late-game fouling is real: 12–13 points in the last two minutes when the margin at
  2:00 is 3–10, vs 7.3 in blowouts. But the closeness feature for totals (B18t) added
  nothing (+0.0007).

## Market gap (benchmark only, ESPN closing lines)

| slice | n | B15 gap | B20 gap |
|---|---|---|---|
| validation all | 25,256 | +0.128 | **+0.113** |
| November | 4,525 | +0.258 | +0.237 |
| December | 4,843 | +0.139 | +0.108 |
| January–March | 15,888 | +0.084 | +0.077 |
| game 1 | 1,051 | +0.577 | +0.585 |
| games 2–3 | 1,901 | +0.292 | +0.279 |
| games 4–5 | 1,755 | +0.186 | +0.130 |
| games 6–10 | 4,487 | +0.089 | +0.071 |
| games 11+ | 16,062 | +0.078 | +0.067 |
| 2025–26 all | 4,760 | +0.064 | +0.062 |

## Future market alignment, Kalshi, availability impact (prospective, downstream)

* `cbb_edge/market/stages.py` + `scripts/benchmark/prospective_benchmark.py` +
  weekly `prospective-benchmark` workflow (to the `benchmark-reports` branch).
* **Stage benchmark.** PURE vs market vs result at T-24h, T-6h, T-90m, T-30m and
  latest. Each stage uses the latest PURE record archived at or before that line
  capture.
* **future_market_alignment.** For PURE at stage s vs the market's later line:
  * sign agreement of (PURE_s − M_s) with (M_latest − M_s);
  * correlation of those two;
  * RMSE of PURE_s vs M_latest.

  This is a neutral diagnostic, not an edge claim.
* **Kalshi.** For each projection snapshot × mapped game-winner market: PURE
  probability, Kalshi mid at that time, later mid, final pre-tip mid, outcome.
* **Availability impact.** Projected margin and total change from a status update,
  minutes changed, the game error, and the market move AFTERWARDS.
* None of these feed PURE. All archives are empty until games start, so there are no
  prospective numbers yet.

## Prospective archives

* **Projections.** Incumbent `pure-0.2.0` plus challengers `pure-0.3.0` and
  `pure-0.4.0`, each from its frozen artifact. A `+avail` overlay is added for
  challengers once captures exist.
* **Live/research parity** on 2025-12-06:

  | model | correlation | mean \|Δ\| (pts) |
  |---|---|---|
  | `pure-0.4.0` | 0.9995 | 0.26 |
  | `pure-0.3.0` | 0.9993 | 0.30 |
  | `pure-0.2.0` | 0.9994 | 0.27 |

* **Workflows.**
  * Kalshi (every 6 hours off-season, 30 minutes in season): verified, branch updated.
  * ESPN lines: verified; branch created by a dispatched run.
  * Projections: in-season cron only; the dispatched run found no games in October.
  * Availability and rosters: new; they start after merge.
* **Promotion rule.** Fixed before the season in `WAVE4.md` and implemented in
  `cbb_edge/research/promotion.py`:
  * evaluated once, after the 2027 title game;
  * ≥ 4,000 games;
  * day-clustered bootstrap P(Δ RMSE < 0) ≥ 0.95;
  * MAE, total, log loss, calibration, market_gap, by-month and subgroup guards;
  * challenger better in ≥ 60% of 14-day blocks.

## Rejected / negative results (preserved)

* B16a rematch features.
* B18 spline calibration.
* B18r regulation-margin target.
* B18t closeness feature for totals (exploratory).
* The leaky first oracle (deep-bench participation reveals blowouts).
* The game-20 bump as a structural effect (not significant).
* A "direct" availability coefficient. With the leaky oracle, the player-impact change
  had slope ≈ 0 against residuals on DEV, so no direct variant was registered.

## Next research

1. **Score 2026–27 prospectively** with the fixed rule. The P-AVAIL overlay and roster
   archive are the first truly new information sources. Measure ESPN college injury
   coverage in November.
2. **Why player-level availability moves projections so little.**
   * RAPM player values may be too compressed for individual swaps.
   * Test calibration of Δ player strength vs realized results on reported absences
     once captures exist.
3. **Shooting skill was the big win.** Extend it to opponent-adjusted shot quality
   (rim and mid finishing per player from PBP shot coordinates, 2015+) and to
   free-throw rate.
4. **First-game gap is unchanged (+0.58).** The remaining early-season gap needs
   preseason information the market has: incoming transfers, freshmen. The roster
   archive starts that dataset.
5. **Totals.** Overtime and late fouling are real but were not captured by simple
   features. Revisit with a distributional (regulation + OT) total model once the
   margin work plateaus.
