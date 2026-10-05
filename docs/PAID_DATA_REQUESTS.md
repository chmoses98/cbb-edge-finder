# Paid / Metered Data — Requests for Owner Approval

Nothing below has been used. Each item states what is missing, why free sources cannot
answer it, estimated usage, and the expected research benefit. **Awaiting approval.**

## R1. Historical lines for 2024 and 2025 (and earlier openers)

* Missing: spreads/totals for the 2024 and 2025 seasons (ESPN's archive has none), and
  opening lines before 2026.
* Why free fails: the ESPN pickcenter archive is empty for those seasons; no other free
  bulk archive was found (the CBBD community mirror was taken down at the owner's request).
* Option A — CBBD `/lines` (UNKNOWN_COST): ~1 request per season-date-range page; a full
  season is on the order of 150–300 calls if pulled by date, well inside a free key's
  monthly quota but it **does** consume quota. Estimated 300–600 calls total.
* Option B — The Odds API historical (PAID_METERED): ~10 credits per snapshot request per
  market/region; one snapshot per game day for two seasons ≈ 300 days × 2 markets ≈ 6,000
  credits. Not recommended — CBBD covers the need for closing lines.
* Benefit: two more seasons of market comparison (≈11,000 games), making ATS/total
  confidence intervals ~40% narrower and allowing a 2024–2025 market-holdout test.

## R2. Recruiting rankings (roster priors, arm B4)

* Missing: freshman recruiting ratings.
* Why free fails: no free bulk source was found; ESPN rosters only give class year.
* Option: CBBD `/recruiting` — ~1 call per season (≈20 calls total).
* Benefit: better preseason priors for freshman-heavy teams; expected to matter most in
  November–December.

## R3. Torvik time-machine ratings (benchmark only)

* Free, but blocked from both the sandbox and GitHub Actions (HTTP 403). Can be fetched
  from the owner's machine with `scripts/data/probe_sources.py`-style requests at ≤1/3 s.
  No cost; listed here only because it needs the owner's environment.
