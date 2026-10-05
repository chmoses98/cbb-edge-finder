# Wave 3 preregistration (2026-10-05, before any Wave 3 result was computed)

Focus: early-season (November/December) independent projection error. `pure-0.2.0`
(B9) stays frozen; every Wave 3 arm is a challenger built beside it.

## Protocol (unchanged from Wave 2)

* Expanding-window stacked ridge, training seasons 2012..s-1 for every arm (B9 refit on
  the same window is the reference); validation 2015–2024; 2025–2026 historical evidence
  only; 2026–27 prospective archive = clean test.
* Any hyperparameter (prior strengths, decay rates, persistence, translation, box-prior
  weights) is fitted on DEV seasons only (≤ 2014) or by expanding windows over seasons
  strictly before the predicted season. Nothing is tuned on 2025–2026.
* No market inputs. Market RMSE / market_gap computed downstream only.

## Promotion thresholds (fixed now)

Individual arm (B10–B14) — promote only if ALL hold on validation 2015–2024:
1. margin RMSE below B9;
2. better than B9 in ≥ 7 of 10 seasons;
3. November–December margin RMSE improves vs B9 (any amount > 0);
4. January–March margin RMSE not worse than B9 by more than 0.005;
5. log loss not worse than B9;
6. market-independence CI tests pass.

Combined arm B15 (candidate `pure-0.3.0`) — promote only if ALL hold:
1. validation margin RMSE ≤ B9 − 0.010;
2. better than B9 in ≥ 8 of 10 validation seasons;
3. November–December validation margin RMSE ≤ B9 − 0.030;
4. January–March validation margin RMSE ≤ B9 + 0.005;
5. validation log loss ≤ B9;
6. market-independence CI tests pass.

If B15 fails, nothing is promoted; `pure-0.2.0` remains production and the results are
recorded as negative evidence.

## Hypotheses

| ID | Hypothesis | Arm |
|---|---|---|
| H-W3-DECAY | Each opponent-adjusted component stabilizes at its own rate; per-stat prior strengths fitted on DEV (one-step-ahead component error) beat the single shared scale. | B10 engine |
| H-W3-ROSTER | A preseason team prior built from players (probabilistic return × carried player value + generic new-player fill) improves November/December projections vs. 0.9 × last-season team rating. | B10 |
| H-W3-RET | Returning production measured by player impact (not just minutes) is predictive of season-over-season team change. | B10 diagnostics |
| H-W3-TRANSFER | Transfer player value translates with season-to-season persistence below returners and depends on old vs. new team strength; a fitted translation prior improves player features after a transfer's first game. | B11 |
| H-W3-BOX | A box-score-informed (SPM) prior improves sparse RAPM estimates, especially early season, transfers and partially matched players. | B12 |
| H-W3-GARBAGE | Competitiveness-weighted team efficiency (garbage-time possessions down-weighted) improves projections, especially for extreme mismatches. | B13 |
| H-W3-NEUTRAL | "Neutral" games in a participant's home state behave like partial home games. | B14 context |
| H-W3-NET | Early-season network sparsity (few cross-conference links) explains part of November error; diagnostics only unless a fix is preregistered. | diagnostics |

## Addendum (2026-10-05, recorded during the wave — read before the results)

Specified after the table above was committed, with the same promotion thresholds:

* **B14 network fix (conference anchor)** — specified and coded *before* any B14 result
  was computed: each team's eff prior also regresses toward last season's mean
  end-of-season rating of the other members of its current conference (leave-one-out),
  coefficients fitted on DEV 2012–2014. The neutral-site / semi-home context of
  H-W3-NEUTRAL is tested as a separate sub-arm, **B14v**.
* **B10d** — the per-stat decay of H-W3-DECAY run as its own arm (engine λ only), so its
  effect is not confounded with the roster prior.
* **Post-hoc variants (added after seeing first results; weaker evidence if they pass):**
  - **B10r**: roster hook whose observed-roster strength is the observed rotation ×
    season-start player ratings (no in-season RAPM), added after B10's engine-only hook
    failed — the in-season version double-counts results the team solve already sees.
  - **B11 / B12 refit scheme**: the first player-prior fit (free intercepts and slopes
    vs next-season weak RAPM) was worse on DEV early games because next-season targets
    exist only for players who kept playing (survivor selection). The rerun fits only
    relative weights through the origin and keeps the DEV-tuned wave-2 carry scale.
    Both versions are reported.

### B15 composition (fixed before B15 was run)

Rule: include each component whose own arm passed the individual thresholds, fitted
jointly where they touch the same prior; exclude components that failed.

* included — roster prior via observed rotation × season-start player ratings (B10r
  hook), conference anchor (B14; fitted jointly with the roster term in one hook on DEV
  2012–2014), extreme-mismatch block (B13 mismatch sub-arm), and the player-prior
  provider (B11 or B12, whichever has the better validation result; recorded below);
* excluded — garbage-time weighting (failed), per-stat decay B10d (failed), venue block
  B14v (failed);
* preseason roster stacking block — EXCLUDED from B15 although B10/B10r passed with it:
  within validation its contribution is negative in 2015–2020 but positive (harmful) in
  3 of 4 transfer-portal seasons 2021–2024 (mean +0.009), consistent with returning
  production being measured without incoming transfers. The B15 variant *with* the
  block is reported as **B15_with_preseason** (not eligible for promotion).
* Recorded as the arms finished: B11 failed in the full stack (validation +0.0007,
  4/10), so transfer translation is NOT used anywhere in B15 — the roster-strength
  series is B10r's (`rot`, no translation); the player block uses B12's features if
  B12 passes, otherwise wave-2's.
