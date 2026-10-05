# Wave 2 — independent PURE_BASKETBALL engine

Model version `pure-0.2.0`. All arms are **PURE_BASKETBALL** (market inputs: NONE). Training window for every stacked arm starts in 2012 (expanding, walk-forward); validation 2015–2024; historical [2025, 2026] (the PR #1 holdout — already observed, reported as evidence only); the clean test is the 2026-27 prospective archive.

Promotion rule (fixed before results): validation margin RMSE below B3, better in ≥ 7 of 10 validation seasons, and log loss not worse.

## Arms

| Arm | Description | Pure | Val N | Val margin RMSE | Val MAE | Val total RMSE | Val total MAE | Val log loss | Val Brier | Δ RMSE vs B3 | Seasons better | Hist margin RMSE | Hist total RMSE | market_gap val | market_gap hist | Complexity | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B3 | PR #1 best: adjusted efficiency + Four Factors + shot rates (team level) | YES | 53778 | 11.248 | 8.853 | 17.062 | 13.346 | 0.5283 | 0.1782 | — | —/10 | 11.542 | 16.807 | 0.182 | 0.155 | low | BASELINE |
| B6 | B3 + player impact (walk-forward RAPM, NCAA stints) on expected rotation | YES | 53778 | 11.240 | 8.849 | 17.053 | 13.342 | 0.5278 | 0.1780 | -0.008 | 7/10 | 11.503 | 16.805 | 0.175 | 0.142 | high | PROMOTE |
| B7 | B3 + opponent-adjusted shot profile (rim/mid/assisted) + matchup terms | YES | 53778 | 11.242 | 8.845 | 17.062 | 13.343 | 0.5280 | 0.1781 | -0.006 | 9/10 | 11.530 | 16.806 | 0.174 | 0.135 | medium | PROMOTE |
| B8 | B3 + context: rest, season phase, team-specific home court (shrunk) | YES | 53778 | 11.238 | 8.845 | 17.058 | 13.347 | 0.5280 | 0.1781 | -0.010 | 9/10 | 11.536 | 16.804 | 0.167 | 0.150 | low | PROMOTE |
| B9 | B3 + B6 + B7 + B8 blocks combined | YES | 53778 | 11.222 | 8.832 | 17.053 | 13.341 | 0.5271 | 0.1778 | -0.027 | 10/10 | 11.481 | 16.798 | 0.151 | 0.112 | high | PROMOTE (production) |

market_gap = PURE margin RMSE − MARKET (free closing line) margin RMSE on games with a usable line (validation lines: 2018–2023; historical: 2026). Lower is better; 0 = as accurate as the closing market using basketball data alone.

## Margin RMSE by season (all D-I games, common sample)

| Season | B3 | B6 | B7 | B8 | B9 |
|---|---|---|---|---|---|
| 2015 | 10.744 | 10.723 | 10.743 | 10.745 | 10.723 |
| 2016 | 10.968 | 10.957 | 10.959 | 10.965 | 10.942 |
| 2017 | 11.180 | 11.180 | 11.173 | 11.171 | 11.154 |
| 2018 | 11.265 | 11.257 | 11.265 | 11.257 | 11.254 |
| 2019 | 11.312 | 11.302 | 11.302 | 11.299 | 11.279 |
| 2020 | 11.370 | 11.368 | 11.369 | 11.357 | 11.351 |
| 2021 | 11.907 | 11.909 | 11.893 | 11.886 | 11.865 |
| 2022 | 11.254 | 11.269 | 11.240 | 11.228 | 11.228 |
| 2023 | 11.271 | 11.259 | 11.267 | 11.268 | 11.253 |
| 2024 | 11.374 | 11.343 | 11.367 | 11.363 | 11.325 |
| 2025 | 11.509 | 11.466 | 11.504 | 11.500 | 11.448 |
| 2026 | 11.575 | 11.540 | 11.556 | 11.571 | 11.515 |

## Team score error (validation)

| Arm | Home pts MAE | Away pts MAE | Home pts bias | Away pts bias |
|---|---|---|---|---|
| B3 | 8.131 | 7.972 | 0.077 | 0.122 |
| B6 | 8.124 | 7.973 | 0.093 | 0.084 |
| B7 | 8.128 | 7.972 | 0.041 | 0.166 |
| B8 | 8.128 | 7.966 | 0.080 | 0.127 |
| B9 | 8.118 | 7.967 | 0.062 | 0.137 |

## Early season (November–December)

| Arm | Split | N | Margin RMSE | Total RMSE | Log loss |
|---|---|---|---|---|---|
| B3 | validation | 20128 | 11.802 | 17.196 | 0.4755 |
| B3 | historical | 4368 | 12.234 | 16.861 | 0.4566 |
| B6 | validation | 20128 | 11.778 | 17.169 | 0.4744 |
| B6 | historical | 4368 | 12.157 | 16.854 | 0.4535 |
| B7 | validation | 20128 | 11.795 | 17.190 | 0.4751 |
| B7 | historical | 4368 | 12.226 | 16.860 | 0.4562 |
| B8 | validation | 20128 | 11.790 | 17.182 | 0.4753 |
| B8 | historical | 4368 | 12.227 | 16.864 | 0.4568 |
| B9 | validation | 20128 | 11.755 | 17.160 | 0.4736 |
| B9 | historical | 4368 | 12.134 | 16.848 | 0.4531 |

## Possession model

| Model | Split | N | MAE | RMSE | Bias |
|---|---|---|---|---|---|
| P0_additive_raw | validation | 53705 | 3.795 | 4.955 | 0.166 |
| P0_additive_raw | historical | 11511 | 3.635 | 4.751 | 0.291 |
| P0_additive_calibrated | validation | 53705 | 3.752 | 4.933 | -0.246 |
| P0_additive_calibrated | historical | 11511 | 3.582 | 4.705 | 0.045 |
| P1_ridge | validation | 53705 | 3.749 | 4.928 | -0.190 |
| P1_ridge | historical | 11511 | 3.575 | 4.694 | 0.093 |

## Uncertainty (arm B9)

| Split | Win-prob method | Log loss | Brier |
|---|---|---|---|
| validation | logistic_wp | 0.5305 | 0.1791 |
| validation | bucket_sd_normal_wp | 0.5303 | 0.1790 |
| validation | hetero_normal_wp | 0.5303 | 0.1790 |
| historical | logistic_wp | 0.5211 | 0.1764 |
| historical | bucket_sd_normal_wp | 0.5206 | 0.1762 |
| historical | hetero_normal_wp | 0.5207 | 0.1762 |

| Split | Margin interval coverage (hetero) | (bucket SD) | PIT dev hetero | PIT dev bucket | Total coverage (hetero) | σ_margin 5–95% |
|---|---|---|---|---|---|---|
| validation | {'cov50': 0.5093191021480866, 'cov80': 0.8026227573815334, 'cov95': 0.9441390222317574} | {'cov50': 0.5068250690552174, 'cov80': 0.7988146638418837, 'cov95': 0.9426640564241465} | 0.0025 | 0.0019 | {'cov50': 0.520046126203438, 'cov80': 0.8175065032583335, 'cov95': 0.9565555525758267} | 10.5–12.3 |
| historical | {'cov50': 0.5080757207363668, 'cov80': 0.8065300451545676, 'cov95': 0.9452066689822856} | {'cov50': 0.5046891281695033, 'cov80': 0.8007120527961098, 'cov95': 0.9424279263633206} | 0.0031 | 0.0022 | {'cov50': 0.5228377908996179, 'cov80': 0.8175581799235846, 'cov95': 0.9540639110802361} | 10.7–12.4 |

## Error decomposition (best arm, validation)

* Total-points error variance 284.4 (RMSE 16.86). Pace component variance 103.8 (36.5%), efficiency component 200.1 (70.4%), covariance term -19.5.
* Possession MAE 3.75, bias -0.19.
* Per-side PPP error attributed to factors (linear PPP map R² 0.944): efg var 0.0124, to var 0.0040, orb var 0.0027, ftr var 0.0003

## Residual slices (best arm, validation)

**season**

| season | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| 2015 | 5499.0 | 10.72 | 0.10 | 16.75 | -0.18 | 7.96 | 7.83 | 3.99 |
| 2016 | 5469.0 | 10.94 | -0.16 | 17.39 | -1.43 | 8.18 | 8.12 | 3.97 |
| 2017 | 5521.0 | 11.15 | -0.13 | 17.08 | -0.09 | 8.11 | 7.92 | 3.81 |
| 2018 | 5540.0 | 11.25 | -0.24 | 17.28 | -0.19 | 8.18 | 8.10 | 3.83 |
| 2019 | 5603.0 | 11.28 | 0.01 | 17.12 | 1.45 | 8.14 | 8.11 | 3.78 |
| 2020 | 5328.0 | 11.35 | -0.24 | 16.72 | 1.41 | 8.13 | 7.90 | 3.68 |
| 2021 | 3868.0 | 11.87 | 0.35 | 16.80 | 1.55 | 8.21 | 8.11 | 3.70 |
| 2022 | 5503.0 | 11.23 | 0.31 | 17.65 | 1.08 | 8.09 | 7.98 | 3.58 |
| 2023 | 5721.0 | 11.25 | -0.48 | 17.06 | -0.39 | 8.04 | 7.89 | 3.56 |
| 2024 | 5726.0 | 11.32 | -0.14 | 16.58 | -0.75 | 8.18 | 7.77 | 3.58 |

**month**

| month | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| 1 | 14105.0 | 10.90 | 0.11 | 17.06 | 0.44 | 8.00 | 7.89 | 3.72 |
| 2 | 13382.0 | 10.89 | -0.08 | 16.96 | -0.10 | 7.99 | 7.87 | 3.63 |
| 3 | 6121.0 | 10.87 | -0.06 | 16.86 | 0.16 | 7.86 | 7.95 | 3.55 |
| 4 | 42.0 | 10.86 | -0.31 | 18.35 | -0.60 | 8.34 | 8.29 | 4.00 |
| 11 | 9838.0 | 12.04 | -0.25 | 17.61 | 0.60 | 8.56 | 8.28 | 4.07 |
| 12 | 10290.0 | 11.48 | -0.17 | 16.72 | -0.11 | 8.18 | 7.91 | 3.75 |

**site**

| site | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| home | 47402.0 | 11.20 | -0.07 | 17.07 | 0.17 | 8.11 | 7.96 | 3.75 |
| neutral | 6376.0 | 11.35 | -0.10 | 16.96 | 0.44 | 8.15 | 8.03 | 3.76 |

**phase**

| phase | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| conference | 31330.0 | 10.92 | 0.02 | 17.03 | 0.12 | 7.99 | 7.89 | 3.66 |
| nonconf_nov_dec | 18249.0 | 11.77 | -0.25 | 17.17 | 0.28 | 8.39 | 8.10 | 3.93 |
| nonconf_other | 357.0 | 10.23 | 0.27 | 16.55 | -0.28 | 7.77 | 7.74 | 3.79 |
| postseason | 3842.0 | 11.05 | -0.05 | 16.73 | 0.51 | 7.92 | 8.04 | 3.63 |

**strength**

| strength_quintile | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| q1_weak | 10756.0 | 11.19 | 0.38 | 17.38 | 0.66 | 8.19 | 8.00 | 3.93 |
| q2 | 10755.0 | 11.01 | -0.04 | 17.18 | -0.00 | 8.11 | 7.93 | 3.79 |
| q3 | 10756.0 | 11.27 | 0.01 | 17.33 | -0.22 | 8.17 | 8.07 | 3.72 |
| q4 | 10755.0 | 11.39 | -0.26 | 16.90 | 0.01 | 8.16 | 8.00 | 3.70 |
| q5_strong | 10756.0 | 11.24 | -0.45 | 16.45 | 0.55 | 7.95 | 7.83 | 3.59 |

**spread_bucket**

| abs_proj_margin | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| [0, 3) | 13861.0 | 10.96 | -0.20 | 17.28 | 0.23 | 8.20 | 7.94 | 3.80 |
| [3, 6) | 12235.0 | 11.14 | -0.11 | 17.11 | 0.02 | 8.12 | 8.00 | 3.75 |
| [6, 10) | 12029.0 | 11.03 | 0.02 | 17.10 | 0.31 | 7.97 | 8.04 | 3.71 |
| [10, 15) | 8636.0 | 11.23 | 0.30 | 16.78 | 0.33 | 7.93 | 7.91 | 3.64 |
| [15, 25) | 5826.0 | 11.92 | -0.21 | 16.54 | 0.36 | 8.27 | 7.89 | 3.75 |
| [25, 99) | 1191.0 | 13.23 | -1.26 | 17.69 | -1.19 | 9.25 | 8.04 | 4.23 |

**pace_bucket**

| proj_pace | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| slowest | 10756.0 | 10.79 | 0.03 | 16.20 | -0.01 | 7.80 | 7.64 | 3.52 |
| slow | 10755.0 | 11.05 | 0.01 | 16.69 | 0.32 | 8.01 | 7.74 | 3.65 |
| mid | 10756.0 | 11.15 | -0.10 | 16.94 | -0.19 | 8.02 | 7.97 | 3.69 |
| fast | 10755.0 | 11.30 | -0.15 | 17.29 | 0.47 | 8.20 | 8.10 | 3.84 |
| fastest | 10756.0 | 11.80 | -0.16 | 18.09 | 0.39 | 8.56 | 8.39 | 4.05 |

**games_seen**

| min_games_seen | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| [0, 1) | 2188.0 | 12.98 | -0.04 | 18.74 | 0.12 | 9.30 | 8.70 | 4.58 |
| [1, 3) | 3934.0 | 12.06 | -0.71 | 17.34 | 1.28 | 8.54 | 8.17 | 3.96 |
| [3, 6) | 5595.0 | 11.55 | 0.11 | 17.05 | 0.32 | 8.19 | 8.13 | 3.85 |
| [6, 11) | 9050.0 | 11.32 | -0.12 | 16.96 | 0.01 | 8.15 | 7.92 | 3.76 |
| [11, 99) | 33011.0 | 10.90 | -0.02 | 16.93 | 0.11 | 7.97 | 7.88 | 3.65 |

## Market benchmark (downstream only)

| Split | Season | N | MARKET | B3 | B6 | B7 | B8 | B9 |
|---|---|---|---|---|---|---|---|---|
| validation | 2018 | 3875 | 11.061 | 11.197 | 11.197 | 11.194 | 11.189 | 11.193 |
| validation | 2019 | 2056 | 11.243 | 11.449 | 11.432 | 11.433 | 11.426 | 11.398 |
| validation | 2020 | 5183 | 11.158 | 11.357 | 11.356 | 11.357 | 11.346 | 11.340 |
| validation | 2021 | 3678 | 11.525 | 11.790 | 11.766 | 11.772 | 11.771 | 11.716 |
| validation | 2022 | 4965 | 10.947 | 11.104 | 11.109 | 11.089 | 11.078 | 11.067 |
| validation | 2023 | 5499 | 11.154 | 11.307 | 11.294 | 11.305 | 11.301 | 11.288 |
| historical | 2026 | 4760 | 11.168 | 11.324 | 11.310 | 11.303 | 11.318 | 11.281 |

MARKET_ENSEMBLE diagnostic (validation, B9 + market, n=21381): margin RMSE 11.166 — diagnostic only, never the default projection.

MARKET_ENSEMBLE diagnostic (historical, B9 + market, n=4760): margin RMSE 11.168 — diagnostic only, never the default projection.
