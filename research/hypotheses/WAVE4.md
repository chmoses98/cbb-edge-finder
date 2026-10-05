# Wave 4 preregistration (2026-10-05, before any Wave 4 model result was computed)

Reference model: **B15 = `pure-0.3.0`** (frozen; sha256 pinned in CI). `pure-0.2.0` is
the incumbent and is also frozen. Every Wave 4 arm is B15 plus one component. All arms
are PURE_BASKETBALL: no spread, total, moneyline, Kalshi price, line movement or
market-implied quantity enters any feature, prior, label or hyperparameter.

## Why the protocol is stricter

The 2015–2024 seasons have been reused for three research waves. From Wave 4 on:

* **Blocked rolling-origin evaluation.** Five blocks of two seasons: F1 2015–16,
  F2 2017–18, F3 2019–20, F4 2021–22, F5 2023–24. Inside each block every season is
  predicted by the expanding-window stack trained on 2012..s−1 (unchanged machinery).
  An improvement has to appear in most blocks, not just in the pooled number.
* **Day-clustered bootstrap.** Δ RMSE uncertainty comes from 2,000 resamples of
  game *days* (games on the same day share information), stratified by block.
* **No tuning on 2015–2024.** Every new constant is either fixed below, fitted on DEV
  (≤ 2014), or fitted inside each predicted season's own training window
  (seasons < s). Grids are written here and evaluated on DEV only.
* **2025–26 is evidence only.** It is reported. It acts as a veto only for the
  combined arm: B20 is not frozen if it is worse than B15 on 2025–26 by more than
  0.010.
* **No retro-fixing.** No feature may be added or changed because it fixes a known
  2025–26 miss.

## Gates

**Component arm (B16x–B19x) is "useful"** only if ALL of these hold versus B15 on
2015–2024:

1. pooled margin RMSE Δ < 0;
2. Δ < 0 in ≥ 4 of 5 blocks, and no block worse than +0.005;
3. bootstrap P(Δ < 0) ≥ 0.90;
4. log loss not worse (Δ ≤ 0);
5. Nov–Dec Δ ≤ +0.005 and Jan–Mar Δ ≤ +0.005.

**Combined arm B20** (= B15 + only the useful components, fitted together) is frozen as
`pure-0.4.0` only if ALL of these hold:

1. pooled Δ ≤ −0.005;
2. Δ < 0 in 5 of 5 blocks and in ≥ 8 of 10 seasons;
3. bootstrap P(Δ < 0) ≥ 0.975;
4. log loss ≤ B15;
5. Nov–Dec Δ ≤ +0.003 and Jan–Mar Δ ≤ +0.003;
6. 2025–26 Δ ≤ +0.010 (veto above);
7. market-independence CI tests pass.

If no component is useful, B20 is not built and nothing new is frozen.

## Hypotheses

### H-W4-REMATCH (B16a): earlier meetings this season inform the rematch

* **Rationale.** Conference opponents usually meet twice. The first meeting is legitimate
  prior basketball information about this specific matchup: style clash, pace, shot
  profile. It is already inside both teams' ratings, but only diluted across all
  opponents.
* **Features.** Built only from meetings with tip < current tip, same season. Each
  is 0 when there is no earlier meeting:
  `rm_flag`; `rm_margin_resid` (earlier meeting's actual margin − its B15 projected
  margin, oriented to the current home team); `rm_total_resid`;
  `rm_poss_resid` (actual − projected possessions); `rm_venue_swap`
  (1 if the earlier meeting was at the other team's home); `rm_n` (number of
  earlier meetings, capped at 2).
* **Training / evaluation.** Added to the B15 stack (ridge α = 10, as always),
  expanding window, blocked evaluation as above.
* **Primary metric.** Pooled margin RMSE Δ vs B15 (component gate).
* **Expected failure mode.** The earlier meeting's residual is mostly noise (σ ≈ 11),
  so its coefficient goes to ≈ 0 and Δ ≈ 0.

### H-W4-CONFDYN (B16b): the conference anchor should update with network evidence

* **Rationale.** The B14 anchor uses LAST season's conference strength, with a fixed
  weight. As cross-conference games accumulate, current-season conference strength
  becomes measurable.
* **Construction.** In the hook,
  C_t(D) = (1 − w)·C_last + w·C_cur(D), with w = n_c / (n_c + k).
  * C_cur(D) = leave-one-out mean of conference-mates' current pregame engine ratings
    (from the previous day's fits, so information < D).
  * n_c = number of cross-conference D-I games played so far by the conference's
    members.
  * k is chosen on DEV 2012–2014 from {25, 100, 400} by DEV one-step margin RMSE of
    the B15 engine.
  * The hook coefficients are refitted on DEV with the dynamic C.
* **Primary metric.** Component gate.
* **Expected failure mode.** Conference-mates' current ratings are already pooled by
  the solve, so this double-counts them. Gain ≈ 0, or worse in Nov.

### H-W4-SHOOT (B17): heavily shrunk player shooting skill beats realized shooting

* **Rationale.** 3P% is mostly noise at team-season sample sizes. A player's career
  shooting, with FT% as a skill proxy, should predict future shooting better than
  recent percentages.
* **Construction.**
  * **Player skill.** Beta-binomial empirical Bayes per shot type (3P, FT, 2P).
    skill = (makes + κ·m) / (attempts + κ), using all of the player's earlier D-I
    attempts: previous seasons plus current-season games tipped before T. Transfers
    keep their history.
  * **Prior mean m.** By listed position (G / F / C). For 3P, m also includes a
    linear FT-skill term.
  * **Fitting.** κ and the m coefficients are fitted on DEV seasons (2007–2014) by
    maximizing next-observation binomial log-likelihood.
  * **New players.** They get the position mean with the same κ, i.e. heavy
    regression.
  * **Team expectation for game T.**
    * Weights: each player's EW share of the team's 3PA (or FTA, 2PA) in its earlier
      games this season, falling back to last season's shares before game 1.
    * Team skill = Σ weight × player skill.
  * **Stack features (h and a):**
    * `sk3`, `skft`, `sk2`;
    * expected 3P points per 100 FGA = 3 × 3PA rate × `sk3`;
    * `luck3` = engine opponent-adjusted fg3 − `sk3` (lets the ridge discount
      realized 3P%).
* **Luck study (diagnostic, no gate).**
  * Split-half (odd vs even games) reliability of team 3P%, opponent 3P%, FT% and
    2P% by attempts.
  * κ* where reliability reaches 0.5.
  * Persistence of each from season to season.
* **Primary metric.** Component gate.
* **Expected failure mode.** The engine's shrunk fg3 component already captures most
  of this.

### H-W4-NONLIN (B18): elite and terrible teams are compressed by the shrinkage

* **Rationale.** Wave 3 found favourites projected by 25+ beat the projection by
  +1.1, even after the mismatch block.
* **Construction (B18).**
  * Second-stage calibration of B15's out-of-sample stacked margin: ridge (α = 10) on
    a linear spline basis with knots at ±5, ±10, ±15, ±20, ±25.
  * Fitted on all earlier predicted seasons' out-of-sample predictions (expanding).
  * 2015 has no earlier out-of-sample season, so it is left unchanged (Δ = 0 by
    construction).
* **Construction (B18r, regulation target).**
  * Train the stack's margin target on the REGULATION margin: 0 for overtime games,
    the final margin otherwise. This removes overtime noise from the target.
  * Evaluate against the full-game margin. Totals are unchanged.
* **Diagnostics (no gate).**
  * Rating compression by strength tier (top/bottom 5% and 10%): regress
    out-of-sample realized margin on projected margin within tiers.
  * Strong-vs-weak and weak-vs-strong slices.
* **Primary metric.** Component gate (for each sub-arm separately).
* **Expected failure mode.** The mismatch block already took the part that
  generalizes; the rest is variance, not bias.

### H-W4-AVAIL (B19): who is going to play tonight

* **B19h (historical, legitimate information only).**
  * **Absence persistence.** For each player in the pregame rotation, estimate
    P(plays) from his run of consecutive zero-minute games just before T
    (0, 1, 2, 3+), his share, and whether he played last game. This is a logistic
    model fitted on earlier seasons only (expanding).
  * **Expected share.** P(plays) × EW share.
  * **Removed minutes.** Redistributed by the replacement model below.
  * **Team strength.** Player features are recomputed with these shares (B12 ratings).
* **Replacement model (also used prospectively).**
  * When rotation player A is out, teammate B's share rises by
    Δ_B ∝ share_B^γ × (1 + β·same_position(A, B)), scaled so the team still sums to 5,
    with each player capped at 1.0 (40 minutes).
  * γ and β are chosen on DEV absences (2012–2014) from γ ∈ {0.5, 1, 1.5},
    β ∈ {0, 0.5, 1}, by squared error of next-game minutes shares.
* **Absence backtest (diagnostic, no gate).**
  * A "regular" has pregame EW share ≥ 0.35 and played in ≥ 3 of the team's last 5
    games.
  * Classify each regular's game as: first surprise absence (played last game, 0
    minutes now), 2nd consecutive absence, 3rd+ consecutive absence, return from
    absence, or normal.
  * For each class report frequency, P(absence continues), and B15 margin RMSE.
  * **Oracle bound (labelled as NOT a model).** Rerun the player layer with the
    game's actual absentees removed, to show what perfect pregame availability
    information would be worth. This is the upper bound on the value of prospective
    injury capture.
  * The first surprise absence is NOT claimed to be knowable historically: no source
    recorded it.
* **Primary metric.** Component gate for B19h.
* **Expected failure mode.** The EW shares (missed games count 0, half-life 4 games)
  already capture most of the persistence.

### PROSPECTIVE_ONLY components (no historical backtest is possible; none is faked)

* **P-AVAIL.** ESPN public injury / status fields (team roster `injuries[]`,
  `status`, league `/injuries`, pregame summary) captured at T-24h / T-6h / T-90m /
  T-30m / latest. The fixed status → P(plays) map is:
  `out` / `suspended` / `inactive` 0.0, `doubtful` 0.25, `questionable` 0.5,
  `probable` / `day-to-day` 0.85, active / no report 1.0 (or the B19h persistence
  value if he missed recent games). Applied through the replacement model to the
  challenger's player features, and archived as an availability-impact diagnostic.
  The map is not changed during 2026–27.
* **P-ROSTER.** Timestamped preseason roster snapshots (incoming transfers known before
  tip). Archived from now on, to be evaluated as a preseason prior in a future wave
  once at least two seasons exist.

## Diagnostics (no gate; inform future waves)

* Conference-play transition, decomposed by: conference vs non-conference; first
  meeting vs rematch; conference game number; season game number; days since the
  previous meeting; venue; current-season conference-network links.
  * Each slice gets margin bias, total/pace bias, home and away points bias, and RMSE
    of B15.
* Extreme pace: total error split into possession error × PPP, PPP error ×
  possessions, interaction, overtime, and last-two-minutes scoring.
* Overtime audit: how much overtime inflates target variance and what a regulation
  target changes.

## Prospective promotion rule (fixed before the first 2026–27 game)

A challenger (`pure-0.3.0`, or `pure-0.4.0` if frozen) replaces the incumbent
`pure-0.2.0` **from the 2027–28 season** only if ALL of the following hold on the
2026–27 prospective archive.

**Comparison set.** For each completed D-I game, use the latest pre-tip archived record
of each model from the same run.

**Timing.** The evaluation runs once, after the national championship game. Earlier
looks are monitoring only and cannot promote.

1. **Sample.** ≥ 4,000 completed games with both records.
   * Paired squared-error difference SD ≈ 18.9 per game (B9 vs B15, 2012–2026).
   * Game-day clustering design effect ≈ 1.85.
   * So 4,000 games detect Δ RMSE ≈ −0.045 at 80% power; a full season (~5,500)
     detects ≈ −0.038.
2. **Margin RMSE.** Challenger < incumbent, with day-clustered bootstrap
   P(Δ < 0) ≥ 0.95 (10,000 resamples of game days).
3. **Margin MAE.** Challenger ≤ incumbent + 0.01.
4. **Total RMSE.** Challenger ≤ incumbent + 0.05.
5. **Log loss.** Challenger ≤ incumbent + 0.0005.
6. **Calibration.** 10-bin ECE ≤ 0.020 and ≤ incumbent + 0.005.
7. **market_gap.** Against the latest captured pre-tip ESPN line, downstream only:
   challenger gap ≤ incumbent gap.
8. **By month.** In every month with ≥ 300 games (Nov, Dec, Jan, Feb, Mar), challenger
   RMSE ≤ incumbent + 0.05.
9. **No catastrophic subgroup.** Δ RMSE ≤ +0.10 in each pre-declared subgroup:
   * conference games / non-conference games;
   * neutral / true home;
   * |projected margin| ≥ 15;
   * less-informed team ≤ 5 games played;
   * both teams in the same conference tier (high-major / mid-major / low-major,
     defined by 2025–26 final conference mean rating terciles).
10. **Consistency.** Challenger better in ≥ 60% of consecutive 14-day blocks.

Further rules:
* If several challengers pass, the one with the lowest margin RMSE is promoted.
* The old incumbent keeps being projected and archived for one more season as a
  challenger.
* No archived record of any version is ever modified.
* If none pass, `pure-0.2.0` stays incumbent and every challenger stays in shadow.
