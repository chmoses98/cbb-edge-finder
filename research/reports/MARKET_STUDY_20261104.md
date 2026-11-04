# CBB market study, 2026-11-04 (discovery only: nothing here is validated)

Data: Kalshi men's CBB captures joined to frozen pregame projections, settled games through 2026-11-04.
Unit of inference: the GAME (contracts of one game are never independent). 137 games with settled
single-game contracts (82 discovery / 55 holdout by tip time). Fills: 25 contracts at the displayed best
price, fee-inclusive cash cost, displayed size must cover. Fee schedule: coefficients are the assumed 0.07 /
0.0175 with Kalshi-API series fee types (official PDF not yet archived; see `fee-schedule-probe`).
Reproduce: `python -m cbb_edge.kalshi.research.run ... --candidates research/candidates` ->
`latest/study_sides.json`.

## What was examined (everything is counted in the multiple-comparison correction)
* 303 pre-declared side x entry x (price bucket | spread tier | favorite/underdog role) slices across
  game winner, spread, total and first-half markets.
* 59 one-bet-per-game strategies: favorite / underdog baselines and a model-value rule (best fillable
  side per game by frozen-model net EV, three minimum-edge levels, two model versions).

## Findings
1. **No slice and no strategy survives Holm correction (0 of 362 with adjusted p < 0.10).** The smallest
   unadjusted p-values (about 0.02-0.04, e.g. game winner at 24h, price 0.20-0.40, about 16 games) become 1.00
   after correction, and their holdouts rest on 5-6 games.
2. **The exploratory game-winner BUY NO result is noise.** At 1h before tip: +0.9% net, 90% interval
   [-1.7%, +4.0%], unadjusted p = 0.30, discovery +2.3% (82 games) vs holdout -1.3% (55 games), and removing one
   game flips its sign. It was also not independent evidence: NO on one team's contract is the same bet as YES on
   the opponent's, so pooling "all contracts" mostly measures the book's overround.
3. **One-bet-per-game results, 1h before tip (net of fees):** favorite -6.9% (110 games), underdog +17.2% with
   interval [-10.5%, +47.8%] (discovery +29.6%, holdout -13.9%), model-value game winner +5.7% [-6.9%, +18.1%]
   (holdout -5.7%), spread -4.0%, total -7.0%. Every positive discovery estimate weakens or reverses in the holdout.
4. **The market is well calibrated where there is data:** at 1h, contracts priced 5.8% happen 5.8% (69 games);
   priced 94.6% happen 93.9% (66). Mid-range buckets have 16-25 games and show nothing distinguishable.
5. **Early quotes are expensive:** buying at the displayed ask at listing (OPEN) loses 16-71% depending on
   side/role because the first books are wide; the spread, not the signal, dominates.

## Verdict
No executable advantage is established. The underdog moneyline and the model-value rule are the only
non-negative discovery results, they are not distinguishable from zero, and they fail the chronological holdout.
They are registered as preregistered candidates and will be judged only on games that tip after registration.

## Preregistered candidates (`research/candidates/*.json`)
Five frozen rules (two controls expected to be negative), hashed and tamper-checked in CI and in every research
run. Required before any would be called VALIDATED: >= 300 prospective games, 90% lower bound of net ROI > 0,
Bonferroni-adjusted p < 0.05/5, and a verified official fee schedule. At 110-140 games the interval on a
~20% underdog hit rate is about +-30 points of ROI; resolving a 5-point edge needs on the order of 1,000+ games,
which the season supplies but the first week does not.
