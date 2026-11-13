# Wave 14 post-merge verification (2026-11-13, after PR #51 merge 2d932f9)

Both result sets were produced from the SAME inputs and are kept separately. The committed
`research/wave14/wave14_results.json` (23 eligible, registration-time evidence) is untouched historical evidence.

| | original protocol (code 115cb17) | amendment 5a (code 2d932f9) |
|---|---|---|
| eligible games | 24 | 24 |
| ET dates | 2 | 2 |
| no verified final yet | 116 | 116 |
| record before registration | 472 | 472 |
| no verified pre-tip record (5a only) | n/a | 0 |
| quarantined / fallback (5a only) | n/a | 0 / 0 |
| verdict | COLLECTING / INSUFFICIENT EVIDENCE (24/150, 2/5) | same |

Identical eligible set, identical `as_of` per game, identical summary metrics. Min push lead before tip: 96 min.

Inputs: projections-archive ea35e884, schedule-archive b9d68b3, espn-lines-archive 3e19eee (the same commits the
Actions `wave14-regrade` job of ci run 43516493326 used; that job's own `--fetch-evidence` run reported the same
5a funnel: eligible 24, no_verified_final_yet 116, record_before_registration 472).

Push-time evidence: `provenance_evidence.json` = committed evidence + GitHub Actions job records for runs
43405211540, 43478453688, 43505580950 (append-step completion times read from GitHub). All 5 post-boundary
manifests verify; each `pushed_by` is 2 s after the archive commit's committer time.

Finals: `outcome_crosscheck.json`, live ESPN re-check at 2026-11-13T22:54Z: 24/24 graded finals match.
Orientation: 487 SAME, 5 SWAPPED, 0 excluded. Archive integrity: 8265 files, 0 hash mismatches, 0 missing.
