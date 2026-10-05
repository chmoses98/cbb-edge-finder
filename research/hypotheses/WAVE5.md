# Wave 5 preregistration (2026-10-05, before any Wave 5 model result was computed)

Theme: **player-level possession modelling.** Can we describe the expected possessions
more accurately from the players who will create them, instead of mostly from team
averages?

Reference model: **B20 = `pure-0.4.0`** (frozen, sha256 pinned). Its inputs are the
B16b-hooked engine states, the B19h player features, the B17 shooting block and the
mismatch block. Every Wave 5 arm is B20 plus one block. Every arm is PURE_BASKETBALL. No
spread, total, moneyline, Kalshi price, consensus, line movement or market-implied
quantity enters any feature, prior, label, hyperparameter or calibration. Availability
is never inferred from line movement.

The incumbent stays `pure-0.2.0`. `pure-0.2.0`, `pure-0.3.0` and `pure-0.4.0` are not
modified. **No Wave 5 result can change the incumbent.** Even a passing B25 is frozen
only as another shadow challenger (`pure-0.5.0`). The prospective promotion rule frozen
in Wave 4 (`cbb_edge/research/promotion.py`) is unchanged, and it alone decides
promotion after the 2026–27 season.

## Priority 0 is done first: live / research parity

This was fixed before any experiment below (commit 8e4b390, `docs/PROSPECTIVE.md`).
The live runner replays only the current season from research season-boundary
checkpoints. Live and research features now agree to ≤ 4e-9 (0.2.0) and ≤ 1e-13
(0.3.0 / 0.4.0). The old ~0.26 gap was coefficients (0.12–0.16, a refit through 2026)
plus information-set mismatch. Reconstruction contributed 0.005–0.011. A Wave 5 model,
if frozen, gets the same checkpoint treatment before it is archived prospectively.

## Protocol (unchanged from Wave 4)

* Blocked rolling-origin evaluation: F1 2015–16, F2 2017–18, F3 2019–20, F4 2021–22,
  F5 2023–24. Inside a block, each season is predicted by the expanding-window stack
  trained on 2012..s−1 (ridge α = 10, logistic WP).
* Day-clustered bootstrap: 2,000 resamples of game days, stratified by block.
* No tuning on 2015–2024. Every new constant is fixed here, fitted on DEV (≤ 2014), or
  fitted inside the predicted season's own training window.
* 2025–26 is evidence only. It acts as a veto only for B25 (worse than B20 by more
  than +0.010).
* No retro-fixing: nothing is added or changed because it fixes a known 2025–26 miss.
* Rejected and exploratory arms are reported, never hidden.

## Data (free only; cost unchanged: Odds API 0, CBBD 0, $0)

* **ESPN play-by-play, 2010–2026**, SportsDataverse public GitHub release assets
  (FREE_BULK). 2010–2014 were downloaded for this wave so that DEV and the 2012–2014
  training seasons have shot histories.
  * Coverage: 3,4xx–3,9xx games per season in 2010–2013, against 5,0xx–6,2xx from 2014.
  * Shooter id equals the box-score player id (`"P" + ESPN athlete id`). The id is
    found in that season's player-games table for 99.3% (2011) to 100% of shots.
  * PBP per-player FGA match the box score exactly in 96–99% of player-games, and
    3PA in 98–99.5%.
  * Only exact ids are used. Unmatched shots are counted and dropped. Nobody is
    fuzzy-matched.
  * Only basketball columns are read. The PBP files also carry spread columns, which
    are never read.
* Shot coordinates exist for only 6–27% of shots before 2026, so corner vs
  above-the-break threes are NOT modelled historically (reported as infeasible).
* The ESPN text format changed in 2025–26 (no "Three Point Jump Shot" type, many more
  "TipShot" rows). Zone rules are therefore format-robust:
  * **FT** = free-throw type.
  * **3** = text contains "three point" (any case), or a made shot worth 3.
  * **rim** = layup / dunk / tip / alley-oop / putback type or text, and not a 3.
  * **j2** = every other two.
  * Rim and tip are pooled so the 2026 reclassification stays inside one zone.
  * Zone shares enter the model only as deviations from the league's season-to-date
    mean (information before the day).
  * League zone shares by season are reported as a definition-break diagnostic.
* **Assisted** = a made FG with `athlete_id_2` present. Recording rates rise over time
  (≈ 0.28 → 0.52), so assisted shares are season-centred like the zones.
* **Putback** = an FG attempt by the same team ≤ 4 s of game clock after that team's
  offensive rebound.
* **Transition** = an FG attempt ≤ 8 s after the same team's defensive rebound or steal.
* Box scores (2006–2026) carry per-player TO, AST, ORB, DRB, STL, BLK, PF, FTA.

All player-level priors use only games tipped before T. A player's history follows his
player id across teams (transfers). Recruiting reputation is never used.

## Hypotheses and arms

### H-W5-SHOT (B21): player shot selection × finishing skill × opponent suppression

* **Rationale.** A team's expected points per shot depends on WHO shoots (selection)
  and how well they finish in each zone (skill). Team-level shot rates mix both and are
  noisy early in the season. Players' career histories exist before game 1.
* **Finishing skill** for zones z ∈ {rim, j2, 3, FT}.
  * Beta-binomial empirical Bayes: skill_pz = (makes_pz + κ_z·m_z,pos) /
    (att_pz + κ_z). Career attempts before T, all teams.
  * m_z,pos = DEV positional mean (G / F / C). κ_z is chosen on DEV 2011–2014 from
    {25, 50, 100, 200, 400, 800} by next-game predictive log-likelihood.
  * For 3: m_3 also moves with FT skill, b3 = 0.25 (the B17 constant, not refitted).
  * Unseen players get the positional prior.
* **Shot selection.**
  * Per player: shrunk zone shares of his FGA, s_pz = (att_pz + τ·q_z,pos) /
    (FGA_p + τ).
  * Usage u_p = (FGA + 0.44·FTA + TO) per minute, shrunk toward the positional mean
    with τ_u = 100 minutes.
  * FT rate f_p = (FTA + τ_f·ftr_pos) / (FGA + τ_f).
  * τ, τ_f ∈ {20, 50, 100, 200} chosen on DEV by next-game multinomial log-likelihood.
* **Team expected offence** before T.
  * Weights w_p = EWMA of each player's minute share in the team's earlier games this
    season, half-life 4 games (the B17 weighting). Game 1 uses last season's final
    weights for returning players, renormalised, plus the positional prior for the
    vacancy.
  * x_mix_z = Σ w_p u_p s_pz / Σ w_p u_p.
  * x_pps = Σ_z x_mix_z · skill_z,team · pts_z, where skill_z,team is the
    attempt-weighted skill.
  * x_ftr = Σ w_p u_p f_p / Σ w_p u_p.
  * x_ast = expected assisted share of makes, from the player shrunk assisted share
    (τ = 50 makes).
* **Defensive shot quality**, from stable quantities only. PBP does not identify
  defenders, so these are team-level.
  * Each team's allowed excess: opponents' actual rim share, 3PA share and FT rate
    minus the same opponents' player-based expected values.
  * Allowed rim FG% excess and block rate, shrunk n/(n + k) with k_def ∈ {250, 500,
    1000} attempts chosen on DEV.
  * Opponent 3P% allowed is NOT used.
* **Matchup expected mix** (home side shown): h_mix_z = x_mix_z,h + def_excess_z,a,
  then renormalised.
* **Block features (12).**
  * Per side: x_pps, x_rim, x_3r, x_ftr.
  * Matchup: d_xpps_poss = poss/100·(h_xpps − a_xpps) and s_xpps_poss for totals.
  * Defence: h_def_rim_pct_ex, a_def_rim_pct_ex.
  * Two season-centred shares: rim and 3 for both sides combined.
* **Separate evaluation (diagnostic).** Predicted vs actual game shot mix (rim / j2 / 3
  share, FT rate) and eFG%, scored by MAE and calibration slope. Compared with the
  existing team-level expectation (engine `rim_rate` / `efg` adjusted ratings). The
  player-derived expected shooting component is reported next to the existing one and
  does NOT replace it automatically.
* **Expected failure mode.** Most of the information is already in the engine's
  adjusted eFG and in B17, so the gain is ≤ 0.005.

### H-W5-POSS (B22): player possession-component profile

* **Rationale.** Turnovers, offensive rebounds and free throws are partly player
  skills, and those skills travel with the player.
* **Player priors** (box score, all earlier games, carried across transfers; same Beta
  / Gamma shrinkage; κ per stat ∈ {50, 100, 200, 400, 800} opportunities, DEV-chosen).
  Each rate uses its own opportunity denominator:
  * TO per own usage possession (FGA + 0.44·FTA + TO);
  * AST per teammate made FG while on court ≈ (min share·team FGM − own FGM);
  * ORB per offensive-rebound chance ≈ min share·(team missed FG);
  * DRB per defensive-rebound chance ≈ min share·(opp missed FG);
  * STL per opponent possession on court;
  * BLK per opponent 2PA on court;
  * PF per 40 minutes;
  * FTA per FGA.
  * Regression is aggressive by construction: κ is at least 50 opportunities, and
    unseen players get the positional mean.
* **Expected team profile** with the B21 minute weights:
  * x_to (usage-weighted), x_orb, x_drb, x_stl, x_blk, x_pf, x_ftr_box, x_ast.
* **Block features (12).**
  * Per side: x_to, x_orb, x_drb.
  * Matchup: orb_edge = h_x_orb − a_x_drb (and the reverse), to_edge = h_x_to +
    a_x_stl (and the reverse), foul_edge = a_x_pf − h_x_pf.
* **Expected failure mode.** The engine's opponent-adjusted TO/ORB/FTR ratings already
  carry this from game ~5 on, so the gain concentrates in Nov–Dec and is small overall.

### H-W5-SCALE (B23): are player ratings compressed?

* **Diagnostic** (not an arm, never tuned on 2015–2024 outcomes):
  * absence stretches (a regular, minute share ≥ 0.4, misses ≥ 3 consecutive games):
    predicted change in team strength from the player ratings vs the actual change in
    opponent-adjusted margin residual. Slope with a day-clustered CI;
  * year-to-year persistence of the ratings;
  * transfer performance: prior rating vs the next season's rating at the new team;
  * lineup-RAPM consistency.
* **Arm B23** = B20 + `avail_delta` (the B19h − B12 player-margin difference: the
  absence-driven part of the player signal) and its total analogue. The stack can then
  scale absences separately from the full-strength player signal. The scale is learned
  in-window by the ridge. No sportsbook move is used anywhere.
* **Expected failure mode.** Persistence-based absence deltas are small and rare, so
  the coefficient is noisy and Δ ≈ 0.

### H-W5-PROFILE (B24): combined player-derived expected team profile

* B20 + the B21 and B22 blocks + five preregistered interactions, standardised like
  every other feature (ridge α = 10):
  * spacing: expected-minute share of players with 3P skill ≥ 0.35 and 3PA share
    ≥ 0.30;
  * ball-handler scarcity: expected minutes of players with AST rate ≥ 0.20, below 1.0;
  * rim protector: the largest expected-minute-weighted block rate in the top-5 by
    expected minutes;
  * ORB size: the sum of the top-2 expected ORB rates;
  * usage concentration: Herfindahl index of expected usage shares.
* **Expected failure mode.** The interactions overfit and the gain is ≤ B21 + B22.

### B25: combined Wave 5 challenger

* B25 = B20 + the union of the useful components among B21, B22, B23 and B24 (if B24
  is useful it supersedes B21 and B22). The list is recorded in
  `research/wave5/b25_components.json` before B25 is run.
* If no component is useful, B25 is not built and nothing is frozen. pure-0.4.0 may
  remain the best model, and that is an acceptable outcome.

## Gates (fixed; never lowered)

**Component arm (B21–B24) is "useful"** if all of these hold vs B20 on 2015–2024:

1. pooled margin RMSE Δ < 0;
2. Δ < 0 in ≥ 4 of 5 blocks, and no block worse than +0.005;
3. bootstrap P(Δ < 0) ≥ 0.90;
4. log loss Δ ≤ 0;
5. Nov–Dec Δ ≤ +0.005 and Jan–Mar Δ ≤ +0.005.

**B25 is frozen (as shadow challenger `pure-0.5.0`)** only if ALL hold vs B20:

1. pooled margin RMSE Δ ≤ −0.008;
2. Δ < 0 in ≥ 4 of 5 blocks;
3. Δ < 0 in ≥ 8 of 10 seasons;
4. bootstrap P(Δ < 0) ≥ 0.95;
5. Nov–Dec Δ ≤ 0 (not worse);
6. Jan–Mar Δ ≤ +0.005;
7. log loss Δ ≤ 0;
8. total RMSE Δ ≤ +0.010 (not materially worse);
9. no major subgroup regression. Subgroups: first game (min games seen ≤ 1), games
   seen 2–10, conference, non-conference, neutral site, |margin_an| > 15, top pace
   decile. Each must have Δ ≤ +0.030 (each has n ≥ 1,000);
10. 2025–26 Δ ≤ +0.010 (veto);
11. market-independence CI tests pass.

## Diagnostics (reported, not eligible, never tuned on outcomes 2015–2024)

* **First-game problem** (the Wave 4 gap of +0.585 vs market at games seen 0).
  * Error and |error| of B20 in each team's first game, by returning minutes,
    returning impact, transfer count, share of the rotation with earlier D-I history,
    prior team strength, conference, newcomers and previous-season coverage.
  * Returning coach is reported as unavailable: there is no free, timestamped coach
    source in the lake.
* **Preseason uncertainty index** (basketball only, preregistered and NOT fitted).
  Equal-weight mean of z-scores of:
  1. 1 − returning minutes;
  2. transfer-in minute share;
  3. newcomer count;
  4. 1 − share of expected rotation with ≥ 1 earlier D-I season;
  5. 1 − previous-season PBP coverage.

  It is tested for whether it predicts |error| in games 1–5 (Spearman ρ and decile
  table, 2015–2024). It may inform variance, not the mean.
* **Component error decomposition.**
  * Home / away offence and defence. The shot-making, turnover, ORB, FT and pace
    contributions to margin error, via the four-factor identity on actual vs expected
    factors.
  * Component forecast metrics for possessions, eFG%, 2P%, 3P%, zone shares, TO%, ORB%,
    FT rate, PPP and team points: MAE, RMSE, bias, calibration slope, and reliability
    by games seen.
* **Distributional totals.**
  * total = regulation (possessions × PPP, Normal with game-specific σ from pace) +
    late-game/foul term + OT mixture.
  * P(OT) comes from the margin distribution (P(regulation margin = 0) under the
    discretised Normal).
  * Each OT period adds a Normal with mean = 5/40 of the expected regulation total.
  * Scored against the single Normal(total, σ_total) by CRPS, log score, 50/80/95%
    interval coverage, PIT histogram, tail calibration (top / bottom 5%), and by
    mismatch and fast-pace subgroups.
  * σ parameters are fitted on DEV or inside the training window. Market pricing is
    never used to tune distributions.
* **Archives.** Roster archive staleness and coverage; ESPN availability coverage once
  games begin (% games with status, % true missed regulars announced, median lead
  time, false positives, late changes). College coverage must prove itself.

## Market

The market stays a downstream benchmark only (MARKET_BENCHMARK, stage table, Kalshi
table, `future_market_alignment`). Nothing is optimised for it.
