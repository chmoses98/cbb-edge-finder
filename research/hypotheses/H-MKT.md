# H-MKT-1: The model anticipates open→close line movement (prospective test)

Registered 2026-10-04 **after** an exploratory look at the 2026 holdout (labelled as such).

* Exploratory observation (2026 DraftKings open/close via ESPN, n = 4,760 D-I games):
  corr(B3 edge vs open, open→close move) = 0.58; when |edge vs open| ≥ 2 the line moved
  toward the model 79% of the time. B3 "ATS vs open": 54.1% (edge ≥ 2, n = 1,415),
  57.8% (≥ 3, n = 606); ATS vs close: 51.1% / 51.2% — no edge at the close.
* Why this is NOT evidence of a tradeable edge: the opening line is posted before games
  whose results our pregame state already contains (states are fit just before tip-off).
  Part or all of the "edge vs open" is information timing. The thresholds were also
  chosen after looking.
* Prospective test (2026-27 season, untouched data): at each Kalshi capture time t,
  compare the projection built from information available at t with the Kalshi price at
  t (and ESPN line snapshots if captured), then measure movement to the last pre-tip
  capture. Accept only if the price-at-t → close move is predictable out of sample with
  a pre-specified threshold (|edge| ≥ 2 pts / ≥ 5 pp), n ≥ 500, CI excluding zero.
