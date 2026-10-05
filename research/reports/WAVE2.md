# Wave 2 — independent PURE_BASKETBALL engine

Model version `pure-0.2.0`. All arms are **PURE_BASKETBALL** (market inputs: NONE). Training window for every stacked arm starts in 2012 (expanding, walk-forward); validation 2015–2024; historical [2025, 2026] (the PR #1 holdout — already observed, reported as evidence only); the clean test is the 2026-27 prospective archive.

Promotion rule (fixed before results): validation margin RMSE below B3, better in ≥ 7 of 10 validation seasons, and log loss not worse.

## Arms

| Arm | Description | Pure | Val N | Val margin RMSE | Val MAE | Val total RMSE | Val total MAE | Val log loss | Val Brier | Δ RMSE vs B3 | Seasons better | Hist margin RMSE | Hist total RMSE | market_gap val | market_gap hist | Complexity | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B3 | PR #1 best: adjusted efficiency + Four Factors + shot rates (team level) | YES | 53778 | 11.248 | 8.853 | 17.062 | 13.346 | 0.5283 | 0.1782 | — | —/10 | 11.542 | 16.807 | 0.182 | 0.155 | low | BASELINE |
| B6 | B3 + player impact (walk-forward RAPM, NCAA stints) on expected rotation | YES | 53778 | 11.242 | 8.850 | 17.052 | 13.341 | 0.5279 | 0.1781 | -0.006 | 7/10 | 11.504 | 16.803 | 0.177 | 0.143 | high | PROMOTE |
| B7 | B3 + opponent-adjusted shot profile (rim/mid/assisted) + matchup terms | YES | 53778 | 11.242 | 8.845 | 17.062 | 13.343 | 0.5280 | 0.1781 | -0.006 | 9/10 | 11.530 | 16.806 | 0.174 | 0.135 | medium | PROMOTE |
| B8 | B3 + context: rest, season phase, team-specific home court (shrunk) | YES | 53778 | 11.238 | 8.845 | 17.058 | 13.347 | 0.5280 | 0.1781 | -0.010 | 9/10 | 11.536 | 16.804 | 0.167 | 0.150 | low | PROMOTE |
| B9 | B3 + B6 + B7 + B8 blocks combined | YES | 53778 | 11.223 | 8.833 | 17.052 | 13.341 | 0.5271 | 0.1778 | -0.025 | 10/10 | 11.482 | 16.798 | 0.153 | 0.113 | high | PROMOTE (production) |

market_gap = PURE margin RMSE − MARKET (free closing line) margin RMSE on games with a usable line (validation lines: 2018–2023; historical: 2026). Lower is better; 0 = as accurate as the closing market using basketball data alone.

## Margin RMSE by season (all D-I games, common sample)

| Season | B3 | B6 | B7 | B8 | B9 |
|---|---|---|---|---|---|
| 2015 | 10.744 | 10.733 | 10.743 | 10.745 | 10.732 |
| 2016 | 10.968 | 10.958 | 10.959 | 10.965 | 10.943 |
| 2017 | 11.180 | 11.180 | 11.173 | 11.171 | 11.154 |
| 2018 | 11.265 | 11.258 | 11.265 | 11.257 | 11.255 |
| 2019 | 11.312 | 11.304 | 11.302 | 11.299 | 11.282 |
| 2020 | 11.370 | 11.368 | 11.369 | 11.357 | 11.350 |
| 2021 | 11.907 | 11.912 | 11.893 | 11.886 | 11.869 |
| 2022 | 11.254 | 11.262 | 11.240 | 11.228 | 11.221 |
| 2023 | 11.271 | 11.265 | 11.267 | 11.268 | 11.258 |
| 2024 | 11.374 | 11.346 | 11.367 | 11.363 | 11.328 |
| 2025 | 11.509 | 11.468 | 11.504 | 11.500 | 11.450 |
| 2026 | 11.575 | 11.539 | 11.556 | 11.571 | 11.514 |

## Team score error (validation)

| Arm | Home pts MAE | Away pts MAE | Home pts bias | Away pts bias |
|---|---|---|---|---|
| B3 | 8.131 | 7.972 | 0.077 | 0.122 |
| B6 | 8.124 | 7.972 | 0.094 | 0.088 |
| B7 | 8.128 | 7.972 | 0.041 | 0.166 |
| B8 | 8.128 | 7.966 | 0.080 | 0.127 |
| B9 | 8.118 | 7.967 | 0.062 | 0.140 |

## Early season (November–December)

| Arm | Split | N | Margin RMSE | Total RMSE | Log loss |
|---|---|---|---|---|---|
| B3 | validation | 20128 | 11.802 | 17.196 | 0.4755 |
| B3 | historical | 4368 | 12.234 | 16.861 | 0.4566 |
| B6 | validation | 20128 | 11.783 | 17.170 | 0.4746 |
| B6 | historical | 4368 | 12.157 | 16.852 | 0.4536 |
| B7 | validation | 20128 | 11.795 | 17.190 | 0.4751 |
| B7 | historical | 4368 | 12.226 | 16.860 | 0.4562 |
| B8 | validation | 20128 | 11.790 | 17.182 | 0.4753 |
| B8 | historical | 4368 | 12.227 | 16.864 | 0.4568 |
| B9 | validation | 20128 | 11.760 | 17.160 | 0.4738 |
| B9 | historical | 4368 | 12.134 | 16.846 | 0.4532 |

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
| validation | logistic_wp | 0.5306 | 0.1791 |
| validation | bucket_sd_normal_wp | 0.5304 | 0.1790 |
| validation | hetero_normal_wp | 0.5304 | 0.1790 |
| historical | logistic_wp | 0.5212 | 0.1764 |
| historical | bucket_sd_normal_wp | 0.5207 | 0.1763 |
| historical | hetero_normal_wp | 0.5208 | 0.1763 |

| Split | Margin interval coverage (hetero) | (bucket SD) | PIT dev hetero | PIT dev bucket | Total coverage (hetero) | σ_margin 5–95% |
|---|---|---|---|---|---|---|
| validation | {'cov50': 0.5088900211858725, 'cov80': 0.8031322910241626, 'cov95': 0.9441390222317574} | {'cov50': 0.5062887178524498, 'cov80': 0.7990828394432674, 'cov95': 0.9426372388640082} | 0.0025 | 0.0020 | {'cov50': 0.5201533964439915, 'cov80': 0.8173455978975033, 'cov95': 0.9565019174555499} | 10.6–12.4 |
| historical | {'cov50': 0.5079888850295241, 'cov80': 0.8062695380340396, 'cov95': 0.9447724904480722} | {'cov50': 0.5046022924626606, 'cov80': 0.801146231330323, 'cov95': 0.9426015977770059} | 0.0032 | 0.0022 | {'cov50': 0.5229246266064606, 'cov80': 0.8177318513372699, 'cov95': 0.9543244182007642} | 10.7–12.4 |

## Error decomposition (best arm, validation)

* Total-points error variance 284.4 (RMSE 16.86). Pace component variance 103.8 (36.5%), efficiency component 200.1 (70.4%), covariance term -19.5.
* Possession MAE 3.75, bias -0.19.
* Per-side PPP error attributed to factors (linear PPP map R² 0.944): efg var 0.0124, to var 0.0040, orb var 0.0027, ftr var 0.0003

## Residual slices (best arm, validation)

**season**

| season | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| 2015 | 5499.0 | 10.73 | 0.09 | 16.75 | -0.18 | 7.96 | 7.83 | 3.99 |
| 2016 | 5469.0 | 10.94 | -0.16 | 17.39 | -1.40 | 8.18 | 8.11 | 3.97 |
| 2017 | 5521.0 | 11.15 | -0.12 | 17.08 | -0.08 | 8.11 | 7.92 | 3.81 |
| 2018 | 5540.0 | 11.25 | -0.24 | 17.28 | -0.15 | 8.18 | 8.10 | 3.83 |
| 2019 | 5603.0 | 11.28 | 0.02 | 17.12 | 1.45 | 8.14 | 8.11 | 3.78 |
| 2020 | 5328.0 | 11.35 | -0.25 | 16.72 | 1.39 | 8.13 | 7.90 | 3.68 |
| 2021 | 3868.0 | 11.87 | 0.35 | 16.80 | 1.51 | 8.21 | 8.11 | 3.70 |
| 2022 | 5503.0 | 11.22 | 0.30 | 17.65 | 1.05 | 8.09 | 7.98 | 3.58 |
| 2023 | 5721.0 | 11.26 | -0.49 | 17.07 | -0.39 | 8.04 | 7.89 | 3.56 |
| 2024 | 5726.0 | 11.33 | -0.14 | 16.58 | -0.72 | 8.18 | 7.77 | 3.58 |

**month**

| month | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| 1 | 14105.0 | 10.90 | 0.12 | 17.06 | 0.44 | 8.00 | 7.89 | 3.72 |
| 2 | 13382.0 | 10.89 | -0.08 | 16.96 | -0.10 | 7.98 | 7.87 | 3.63 |
| 3 | 6121.0 | 10.87 | -0.06 | 16.86 | 0.17 | 7.86 | 7.95 | 3.55 |
| 4 | 42.0 | 10.86 | -0.32 | 18.34 | -0.62 | 8.34 | 8.30 | 4.00 |
| 11 | 9838.0 | 12.05 | -0.27 | 17.61 | 0.61 | 8.56 | 8.28 | 4.07 |
| 12 | 10290.0 | 11.48 | -0.17 | 16.72 | -0.10 | 8.17 | 7.91 | 3.75 |

**site**

| site | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| home | 47402.0 | 11.21 | -0.07 | 17.06 | 0.17 | 8.11 | 7.96 | 3.75 |
| neutral | 6376.0 | 11.35 | -0.11 | 16.96 | 0.44 | 8.15 | 8.03 | 3.76 |

**phase**

| phase | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| conference | 31330.0 | 10.92 | 0.02 | 17.03 | 0.12 | 7.99 | 7.88 | 3.66 |
| nonconf_nov_dec | 18249.0 | 11.78 | -0.26 | 17.17 | 0.29 | 8.40 | 8.09 | 3.93 |
| nonconf_other | 357.0 | 10.22 | 0.27 | 16.55 | -0.28 | 7.76 | 7.73 | 3.79 |
| postseason | 3842.0 | 11.05 | -0.06 | 16.73 | 0.51 | 7.92 | 8.04 | 3.63 |

**strength**

| strength_quintile | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| q1_weak | 10756.0 | 11.19 | 0.38 | 17.38 | 0.66 | 8.19 | 8.00 | 3.93 |
| q2 | 10755.0 | 11.01 | -0.04 | 17.18 | -0.00 | 8.11 | 7.93 | 3.79 |
| q3 | 10756.0 | 11.27 | -0.00 | 17.33 | -0.21 | 8.17 | 8.07 | 3.72 |
| q4 | 10755.0 | 11.39 | -0.27 | 16.90 | 0.02 | 8.16 | 8.00 | 3.70 |
| q5_strong | 10756.0 | 11.25 | -0.45 | 16.45 | 0.54 | 7.95 | 7.83 | 3.59 |

**spread_bucket**

| abs_proj_margin | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| [0, 3) | 13844.0 | 10.98 | -0.20 | 17.28 | 0.20 | 8.20 | 7.94 | 3.80 |
| [3, 6) | 12237.0 | 11.12 | -0.11 | 17.10 | 0.05 | 8.12 | 7.98 | 3.75 |
| [6, 10) | 12031.0 | 11.02 | 0.01 | 17.11 | 0.31 | 7.97 | 8.05 | 3.72 |
| [10, 15) | 8635.0 | 11.25 | 0.30 | 16.81 | 0.29 | 7.94 | 7.92 | 3.64 |
| [15, 25) | 5858.0 | 11.94 | -0.21 | 16.52 | 0.46 | 8.28 | 7.86 | 3.76 |
| [25, 99) | 1173.0 | 13.18 | -1.30 | 17.62 | -1.28 | 9.19 | 8.07 | 4.21 |

**pace_bucket**

| proj_pace | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| slowest | 10756.0 | 10.80 | 0.03 | 16.20 | -0.01 | 7.80 | 7.64 | 3.52 |
| slow | 10755.0 | 11.05 | 0.01 | 16.69 | 0.33 | 8.01 | 7.74 | 3.65 |
| mid | 10756.0 | 11.15 | -0.10 | 16.94 | -0.18 | 8.02 | 7.97 | 3.69 |
| fast | 10755.0 | 11.30 | -0.15 | 17.29 | 0.47 | 8.20 | 8.10 | 3.84 |
| fastest | 10756.0 | 11.80 | -0.17 | 18.09 | 0.39 | 8.56 | 8.38 | 4.05 |

**games_seen**

| min_games_seen | n | margin_rmse | margin_bias | total_rmse | total_bias | home_pts_mae | away_pts_mae | poss_mae |
|---|---|---|---|---|---|---|---|---|
| [0, 1) | 2188.0 | 13.02 | -0.12 | 18.74 | 0.16 | 9.32 | 8.70 | 4.58 |
| [1, 3) | 3934.0 | 12.06 | -0.71 | 17.34 | 1.27 | 8.54 | 8.17 | 3.96 |
| [3, 6) | 5595.0 | 11.55 | 0.11 | 17.05 | 0.32 | 8.19 | 8.13 | 3.85 |
| [6, 11) | 9050.0 | 11.32 | -0.12 | 16.96 | 0.02 | 8.15 | 7.92 | 3.76 |
| [11, 99) | 33011.0 | 10.90 | -0.02 | 16.92 | 0.11 | 7.97 | 7.88 | 3.65 |

## Market benchmark (downstream only)

| Split | Season | N | MARKET | B3 | B6 | B7 | B8 | B9 |
|---|---|---|---|---|---|---|---|---|
| validation | 2018 | 3875 | 11.061 | 11.197 | 11.197 | 11.194 | 11.189 | 11.193 |
| validation | 2019 | 2056 | 11.243 | 11.449 | 11.438 | 11.433 | 11.426 | 11.405 |
| validation | 2020 | 5183 | 11.158 | 11.357 | 11.356 | 11.357 | 11.346 | 11.340 |
| validation | 2021 | 3678 | 11.525 | 11.790 | 11.772 | 11.772 | 11.771 | 11.722 |
| validation | 2022 | 4965 | 10.947 | 11.104 | 11.105 | 11.089 | 11.078 | 11.063 |
| validation | 2023 | 5499 | 11.154 | 11.307 | 11.299 | 11.305 | 11.301 | 11.294 |
| historical | 2026 | 4760 | 11.168 | 11.324 | 11.311 | 11.303 | 11.318 | 11.281 |

MARKET_ENSEMBLE diagnostic (validation, B9 + market, n=21381): margin RMSE 11.166 — diagnostic only, never the default projection.

MARKET_ENSEMBLE diagnostic (historical, B9 + market, n=4760): margin RMSE 11.168 — diagnostic only, never the default projection.
