# WAVE 15 — margin calibration challengers A1 `mstretch-0.5.0-v1` and A2 `hsd-0.5.0-v1` (REGISTRATION)

RESEARCH_ONLY. Registered 2026-11-13, before any record in the eligibility window exists. The window opens on 2026-11-15T00:00Z.
No frozen projection, production model, default, candidate, promotion gate, schedule, runner or permission is changed.
`models/pure/active.json` is untouched and nothing is promoted. The immutable spec is `research/wave15/spec.json`; a test asserts code == spec.
Wave 15 is separate from Wave 14: it has its own code, spec, window, outputs and verdicts, and changes no Wave 14 file or rule.

## 1. Hypotheses (from the exploratory 468-game diagnostics, `research/reports/PROJECTION_DIAGNOSTICS_20261113.md`)

Base `pure-0.5.0` margins look about 8% too compressed: the OLS slope of actual on projected margin is 1.08 [1.05, 1.13].
The margin SD also does not scale with |margin|. The z-SD is 0.82 where |m| < 8 and 1.13 where |m| ≥ 16.
These are two different claims, so they are two separate challengers with separate primary metrics.
Neither is assumed to imply the other.

* **H15-A1 (magnitude):** stretching the projected margin by a walk-forward factor `s` lowers margin MAE versus pure-0.5.0.
* **H15-A2 (uncertainty):** a margin-dependent predictive SD improves the Gaussian log score of the actual margin versus
  pure-0.5.0's `N(margin, margin_sd)`.

## 2. Challengers

Both use the same walk-forward history. That history is every game whose latest pre-tip pure-0.5.0 record exists and whose orientation-verified final
was first observed (`available_at`) at or before the target record's `as_of`.
The history therefore uses no outcome at or after the prediction's information cutoff.
`k = 30` pseudo-games, `m_ref = 15` points, `min_games = 30`.

* **A1:** `s = (Σ m·y + k·m_ref²) / (Σ m² + k·m_ref²)` is a ridge slope shrunk toward 1. `margin' = s·margin`.
  The total and `margin_sd` are unchanged. The probability moves along the frozen production link:
  `p' = σ(logit(p_frozen) + 0.161365·(margin' − margin))`.
  The link is `logit(p) = 0.161365·margin + 0.007782` for model sha `c4600f62…`, verified on every archive record to 1e-12.
* **A2:** ridge-regress `z² = ((y − m)/margin_sd)²` on `[1, |m|/m_ref]`, with `k` pseudo-observations per coefficient pulling
  `(c0, c1)` toward `(1, 0)`. Then `margin_sd' = margin_sd·sqrt(max(0.25, c0 + c1·|m|/m_ref))`.
  The margin is unchanged, and `p' = Φ(margin / margin_sd')`.
  A link-matched comparator `Φ(margin / margin_sd)` is reported descriptively. It separates A2's SD effect from the switch away
  from the production logistic link.

## 3. Fail closed / eligibility (identical games for every forecaster)

A game is eligible only if all of the following hold:
* The latest pure-0.5.0 record with `as_of < tip` has `as_of ≥ 2026-11-15T00:00Z`.
* The tip is on an ET date ≤ 2026-12-20.
* The record's `model_sha256` equals the registered sha. If production changes model mid-window, later games are excluded and
  nothing is refit.
* The game has an orientation-verified archived final.
* The record's manifest has **verified freeze provenance**, rebuilt by `cbb_edge.research.freeze_provenance` from GitHub
  Actions job records, with `pushed_by < tip`.
* There are at least 30 finished training games.

One row per game, so no game is counted twice. Records before the window are never eligible, though they may train.

## 4. Evaluation and decision rule (fixed now)

* **Fixed window, single analysis.** The window is fixed and is analysed once, at or after 2026-12-22T12:00Z.
  Before then the only status is **COLLECTING / INSUFFICIENT EVIDENCE**, whatever interim numbers show. There is no optional stopping.
* **Floor.** The floor is ≥ 300 eligible games on ≥ 10 ET dates. If the closed window falls short, the status is INSUFFICIENT EVIDENCE.
* **Bootstrap.** Matched-game differences (challenger − pure-0.5.0) are bootstrapped over whole ET dates, with 10 000 replicates
  and seed 20261113.
* **Multiplicity.** Waves 15–16 form one family of three primary tests (A1, A2, B). Each is tested one-sided at
  α = 0.05/3 (Bonferroni), so the primary bound is the 98.33% upper quantile. Guards use the 95% one-sided bound.
* **A1 — IMPROVED:** the margin-MAE upper bound is < 0, the log-loss bound is ≤ +0.005 and the Brier bound is ≤ +0.002.
  **NOT IMPROVED:** the MAE point difference is ≥ 0, or its lower bound is > 0, or a guard's lower bound exceeds its tolerance.
  Anything else is INSUFFICIENT EVIDENCE.
* **A2:** the same rule, with the primary metric being the margin Gaussian NLL. The guards are again log loss ≤ +0.005 and
  Brier ≤ +0.002 versus the frozen production probability.
* **Always reported:** margin bias, 80% interval coverage, z-SD by |margin| band (0–8, 8–16, ≥16) and win-probability
  reliability by quintile.

Even IMPROVED is research evidence only. Promotion remains governed by `research/hypotheses/WAVE4.md`. Market data is never
an input, and profitability is never an objective.

## 5. Disclosure of exploratory development (historical; NOT evidence)

Parameters `k`, `m_ref`, `min_games` and `var_floor` mirror Waves 12/14 conventions and were fixed before the run below. They were not tuned.
The walk-forward run used only records frozen before the Wave 14 boundary: 347 games on 10 ET dates, in
`research/wave15/wave15_exploratory_historical.json`. These games are never eligible here.
Results, as point estimates with 90% date-clustered intervals:
* **A1:** margin MAE −0.042 [−0.082, −0.005] and bias +0.47 → −0.12, **but** log loss +0.0020 [+0.0000, +0.0043] through the
  production link. A larger margin is not the same as a better probability.
* **A2:** margin NLL −0.0094 [−0.0152, −0.0021], and the ≥16 band's z-SD goes from 1.15 to 1.08.
  Log loss is −0.0032 versus the production probability, but **+0.0009 versus the link-matched** Φ comparator. The apparent
  probability gain comes from the link, not the SD model.

These numbers motivated the hypotheses and are not evidence for them. The historical sample is early season, with many mismatches.

## 6. Known limitations

* **Not a separately frozen stream.** Challenger predictions are not frozen as separate files. They are a deterministic function of frozen production
  records, the code and parameters at this registration commit, and finals observed before each record's `as_of`.
  Freezing a separate challenger stream would need a workflow that writes to an archive, which needs owner approval and is not done here.
* **Single provider.** The ESPN schedule archive is the only source of finals. Graded finals are re-checked later from the same provider by
  `cbb_edge.research.outcome_recheck`.
* **Overlap with Wave 14.** Wave 14 evaluates totals on an overlapping set of games. Its hypothesis, forecaster and metric are different, and
  neither wave's result enters the other's decision.

## 7. Tooling

`python scripts/research/prospective_wave15.py --projections <arch> --schedule <sched> --provenance research/wave14/freeze_provenance.json --out research/wave15 --report research/reports/WAVE15_MARGIN_CALIBRATION.md --exploratory`

The CI regrade job runs it on every research-wave PR, manual dispatch and push to main. It reuses the archives and the provenance
verified in that same run.
