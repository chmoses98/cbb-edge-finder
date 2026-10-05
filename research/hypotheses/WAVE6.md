# Wave 6 preregistration (2026-10-05, before any Wave 6 arm was evaluated)

**Question.** Before either team has played, can PURE identify who will actually play,
how good those players are, and therefore how good the team should be, without asking
the market?

**Reference.** B25 = `pure-0.5.0` (frozen; shadow challenger). The incumbent stays
`pure-0.2.0`. The Wave 4 prospective promotion rule is unchanged and alone decides any
promotion after the 2026–27 season. No challenger is promoted early.

**PURE_BASKETBALL rules (unchanged).** No spread, total, moneyline, Kalshi price,
consensus or line movement enters any feature, prior, label, hyperparameter, roster
decision, minutes estimate or adjustment. Roster membership and injuries are never
inferred from the market. Cost: Odds API 0, CBBD 0, $0.

## What was looked at before writing this (Priority 7 diagnostics, B25 errors only)

These diagnostics motivate the hypotheses below. They do not change the gates.

* **The game-1 player block ignores who left.** Before a team's first game,
  `player_team_features` uses the previous season's full minute shares, departed
  players included (`rapm._prev_shares`). There is no return probability in that block;
  the engine hook's preseason S and the B24 possession weights do use P(return).
* **Departed VALUE does not explain the error; departed SHARE does.** Validation
  2015–2024, team-side first games (n = 3,549):
  * Σ departed min-share × (rating − newcomer level): corr −0.03.
  * Realized departed minute share: corr −0.10. B25 error runs +2.03 → −1.81 points
    from the lowest to the highest quintile.
  * The same quantity from P(return) (known preseason): corr 0.001.
  * P(return)-expected and realized departure shares correlate only 0.40.
* **The effect persists after game 1.** The slope of team error on realized departure
  share is −6.9 (game 1), −6.1 (2), −5.3 (3–4), −2.6 (5–7), −1.4 (12–21) and −0.5
  (22+).
* **Development proxies do not explain it.** P(return)-weighted youth, experience and
  sophomore/junior share of expected returners all have |corr| ≤ 0.02 with the game-1
  error.

**Reading.** The ±2-point newcomer/experience residual is mostly roster truth that
P(return) cannot foresee (portal-era departures and arrivals). Historically, realized
membership is post-hoc. So the only historically eligible handles are:
1. better use of preseason-known continuity (B27);
2. development (B26);
3. continuity REVEALED by the games already played (B28, from game 2).

True preseason roster knowledge is PROSPECTIVE_ONLY (P-ROSTER-1).

## HISTORICAL_ELIGIBLE vs PROSPECTIVE_ONLY

* **HISTORICAL_ELIGIBLE:**
  * anything computable from data timestamped before T: box-score history, P(return)
    from earlier seasons, and players who have APPEARED in this season's completed
    games;
  * conditional models trained on past seasons that take roster membership as an
    INPUT, e.g. P(minutes | on roster). The membership itself is not claimed known
    historically.
* **PROSPECTIVE_ONLY:**
  * timestamped 2026–27 roster truth (`cbb_edge/rosters/truth.py`) and everything built
    on preseason membership: P-ROSTER-1 and its game-1 rotation.
  * Evaluated only on 2026–27 games.
* **ORACLE (diagnostic, never eligible, never frozen):** realized membership (players
  who appear in a team's first five games) treated as known at game 1. It is reported
  ONLY as an upper bound on what roster truth could be worth. It is not a backtest.

## Roster-truth precedence (fixed now, before any model effect is measured)

Implemented in `cbb_edge/rosters/truth.py` and documented in
`docs/ROSTER_SOURCE_AUDIT.md`:

1. **Freshness** is determined per source per team:
   * a native season label older than the target season → stale;
   * an ESPN-family list identical to the team's previous-season ESPN core list → stale
     (a copy, not yet updated);
   * an older capture of a feed whose latest capture is stale → stale;
   * official sources (stats.ncaa.org, school athletics sites) are fresh when their
     season label is current.
2. **Independence groups:**
   * ESPN family: site roster, core season athletes, SportsDataverse copy;
   * NCAA;
   * school site.

   Within a group, the latest capture supersedes older ones (a player who moved).
3. **Player status:**
   * CONFIRMED = ≥ 2 independent fresh groups, or an official group;
   * LIKELY = one fresh group;
   * CONFLICTED = fresh sources disagree on the team; it is never silently resolved,
     and every team is kept and flagged;
   * STALE = stale evidence only;
   * UNKNOWN = no usable identity.
4. **Identity:**
   * ESPN athlete id is canonical;
   * official rows match only by exact normalized name, unique within the same team;
   * nothing is fuzzy-matched.
5. **Experience** comes from observed D-I participation before the season (seasons,
   games, minutes, previous team). Class strings are kept but never decide newcomer
   status.

Model effects are never used to choose between sources.

## Hypotheses and arms (historical, vs B25, blocked folds F1–F5)

### H-W6-DEV (B26): player development priors

* **Construction.** Returning and transfer players' season-start priors in the B19h
  player chain get an additive development offset by
  (D-I seasons completed ∈ {1, 2, 3, 4+}) × (previous minute share < 0.3 / ≥ 0.3),
  separately for offence and defence.
* **Fit, DEV only** (player pairs whose later season ≤ 2014):
  * offset = mean of (next weak-RAPM − 0.95 × combined prior);
  * cells with n < 200 pool to their experience row;
  * shrunk ×0.5, because survivor selection inflates development.
* **Expected.** A small gain concentrated in Nov–Dec, or none: the proxies above have
  |corr| ≤ 0.02.

### H-W6-CARRY (B27): continuity-dependent carryover (preseason-known continuity)

* **Construction.** Stack features per side:

  ```
  carry_s = prev_net_s × (1 − ret_min_s) × d(gs)
  cont_s  = ret_min_s × d(gs)
  d(gs)   = 1 / (1 + gs / 3)
  ```

  * prev_net = the team's previous-season final net rating (B9 finals);
  * ret_min = P(return)-expected returning minute share (the preseason table);
  * gs = games seen.
* **Expected.** ≈ 0, because expected continuity carried no error signal (corr 0.001).

### H-W6-REVEAL (B28): continuity revealed by the games already played

* **Construction.** For games seen ≥ 1, from player-games of this season before T:
  * rev_cont = Σ_{last season's players who have appeared for the team} prev minute
    share / Σ prev minute share;
  * rev_new = share of this season's minutes so far played by players with no prior
    D-I minutes;
  * rev_tr = share played by transfers-in;
  * features per side: rev_cont × d(gs), rev_new × d(gs), rev_tr × d(gs),
    prev_net × (1 − rev_cont) × d(gs);
  * at gs = 0, every one of these equals its preseason expectation (P(return) for
    rev_cont; 0 for the others).
* **Expected.** Gains in games 2–10 (the slope −6.1 → −2.6 above). None at game 1.

### B29: combined

* B29 = B25 + the union of the useful components among B26, B27 and B28. The list is
  recorded in `research/wave6/b29_components.json` before B29 is run.

## Gates (fixed; never lowered)

**Component (B26–B28) "useful"** if all of these hold vs B25 on 2015–2024:

* pooled Δ < 0;
* ≥ 4/5 blocks < 0, and no block > +0.005;
* bootstrap P(Δ < 0) ≥ 0.90;
* log loss Δ ≤ 0;
* Nov–Dec Δ ≤ +0.005 and Jan–Mar Δ ≤ +0.005.

**B29 freeze** (as another SHADOW challenger, `pure-0.6.0`) only if ALL of these hold:

1. margin RMSE Δ ≤ −0.008 vs B25;
2. Δ < 0 in ≥ 4/5 blocks;
3. Δ < 0 in ≥ 8/10 seasons;
4. bootstrap P(better) ≥ 0.95;
5. first-game RMSE Δ ≤ −0.03;
6. games 2–5 Δ ≤ 0;
7. Nov–Dec Δ < 0;
8. Jan–Mar Δ ≤ +0.005;
9. log loss Δ ≤ 0;
10. total RMSE Δ ≤ +0.010;
11. 2025–26 Δ ≤ +0.010;
12. market-independence tests pass.

Gate 5 is deliberately hard. The diagnostics say the game-1 bias needs roster truth,
so B29 is expected NOT to freeze, and that is an acceptable outcome.

## Expected rotation (conditional model; HISTORICAL_ELIGIBLE as a conditional model)

* **Target:** each roster player's share of team minutes over the team's first five
  games (sum = 5 on-court units).
* **Membership (training only):** players appearing in those games.
* **Features** (all from before the season):
  * previous-season minute share, start rate, usage share and net rating, all at the
    previous team;
  * D-I seasons played;
  * position (G/F/C);
  * transfer flag, and origin-team net for transfers;
  * first-D-I flag;
  * same-position depth = Σ the other roster players' previous minute shares at that
    position.
* **Model:** sklearn HistGradientBoostingRegressor (max_depth 3, 200 iterations,
  learning rate 0.05), trained on seasons < s. Predictions are normalised per team to 5.
* **Accuracy** (validation 2015–2024): minutes MAE, top-5 / top-8 identification,
  starter accuracy (top-5 by minutes), rotation precision/recall (share ≥ 0.25).
* The model never sees future starting lineups.

## P-ROSTER-1 (PROSPECTIVE_ONLY overlay, never a frozen version)

* `pure-0.5.0+roster` = the frozen pure-0.5.0 projection plus two recorded components:
  * **(a) input substitution.** Before a team's first game, the player block's minute
    shares come from the expected-rotation model over the roster-truth players, with
    their frozen season-start priors (the pure-0.5.0 provider, transfers translated)
    instead of last season's full roster. The pure-0.5.0 artifact is then applied
    unchanged.
  * **(b) continuity correction.** A ridge (α = 10) on B25 team-side residuals for games
    seen ≤ 10, with inputs (truth − expected) returning share, transfer
    previous-minute share and first-D-I count, each × d(gs).
    * Fit on 2015–2026 with ORACLE membership (players appearing in the first five
      games), which is the only available proxy for preseason truth.
    * Reported historically ONLY as an expanding-window oracle upper bound.
    * Its real test is 2026–27.
* **Per game, archived as a separate version** (`pure-0.5.0+roster`; base records
  untouched):
  * roster snapshot timestamp and confidence;
  * returning / transfer / unseen projected minutes;
  * expected rotation (top 8);
  * roster offence / defence strength;
  * (a) and (b) adjustments, the total adjustment and its uncertainty;
  * the raw evidence ids.
* **Snapshots for game 1:** T−7d, T−72h, T−24h, T−6h and latest pregame. Each is
  archived; none is ever rewritten. Game-1 results never alter archived game-1 records.
* **Prospective metrics** (preregistered; 2026–27; no historical promotion gate):
  1. game-1 rotation accuracy (top-5 / top-8, minutes MAE, starters, precision/recall);
  2. game-1 margin RMSE, base vs +roster;
  3. games 2–3 RMSE;
  4. market gap, as a benchmark only;
  5. whether roster confidence is associated with smaller |error| (Spearman).

  Reported weekly alongside every frozen model.

## Diagnostics (not eligible)

* **First-game error decomposition** of B25 by input layer:
  * previous-team carryover (hook prior);
  * player prior (player block);
  * expected-returner / transfer / unseen contributions;
  * home court;
  * conference anchor;
  * opponent uncertainty.
* **Player development** by component: offence, defence, shooting, TO, rebounding and
  usage persistence, DEV only.
* **Head-coach continuity:** audit whether a free, timestamp-safe historical source
  exists. If none does, it is reported as unavailable and not modelled.
* **Rapid game-1 → game-2 update:** is B28 enough, or does a faster EWMA after game 1
  help games 2–3? Reported as exploratory unless B28 already covers it.

## Amendment A1 (2026-10-05 ~17:10Z, after the first live roster-truth run; before any prospective game)

The first live run (roster-capture run 37342501100, snapshot `20261005T164553Z`) showed
three data-integrity defects in the precedence rules above. These were found by
reading the archived records. No model outcome had been observed: no 2026-27 game has
been played. The P-ROSTER-1 spec (`models/overlays/p-roster-1.json`, coefficients and
hash) is unchanged. The fixes only tighten the rules.

1. **Team-level same-feed supersession.** For each (independence group, team), the
   source with the latest fresh capture defines that group's listing. A player who is
   listed only by an older capture of the same feed is `STALE`, with
   `superseded_only`. Example: a September SDV copy listed 5 players whom the October
   ESPN core list for the same team no longer had; before this fix they were `LIKELY`.
2. **An official listing defines membership.** If a team has a fresh official roster,
   an ESPN-only player that the roster omits is `STALE`, with `absent_from_official`.
   Such players are logged in the conflict log (kind `absent_from_official_roster`),
   never dropped silently. Players dropped under rules 1 or 2 count as departures,
   not as unconfirmed listings, in the team's 80% coverage test.
3. **Identity is required for classification.** An official name that matches no ESPN
   id is classified `unknown`. Before this fix it defaulted to `first_d1`, so an
   unmatched graduate transfer was counted as a newcomer. Unmatched names are logged
   (kind `unmatched_official_name`).
   If fewer than 80% of a team's fresh official listing match an ESPN id, the team's
   roster confidence is `UNKNOWN` (`official_roster_unidentified`), and P-ROSTER-1
   applies neither component. In the live snapshot, one official roster matched 5 of
   16 names but was rated `CONFIRMED`. Its expected rotation held 5 players, and its
   transfer inputs were zero.
