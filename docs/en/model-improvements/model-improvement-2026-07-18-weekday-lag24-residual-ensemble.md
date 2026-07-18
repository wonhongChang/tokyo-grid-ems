# 2026-07-18 Weekday Lag-24 Residual Ensemble

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md)

## Problem

Operational forecasts from July cannot be treated as one homogeneous backtest because the model and guards changed repeatedly. A current-code replay separated raw LightGBM, deterministic post-processing, intraday correction, and published-forecast preservation. It showed that the recurring weekday error was not explained by one hour-specific guard.

The absolute-demand q50 remained strongly dependent on lag and anchor levels. It tended to stay too low when current demand rose above yesterday and recent same-business-day anchors, and too high when lag-24 remained elevated during a cooler regime. Adding hourly-delta features, a weekday-only model, or more midday rules did not improve both recent and older holdouts consistently.

## Change

A fourth LightGBM median model learns:

```text
target = actual_mw - lag_24h
```

For business days only, the point forecast becomes:

```text
q50_final = 0.5 * q50_absolute + 0.5 * (lag_24h + q50_residual)
```

Non-business days keep the existing absolute-demand q50. The q025/q975 half-widths are calibrated as before and recentered around the blended q50, so this change does not independently alter interval width.

## Validation

Current-code rolling replay on ten business days from 2026-07-06 through 2026-07-17, including deterministic post-processing:

| Metric | Existing | Ensemble |
|---|---:|---:|
| Final MAE | 718.3 MW | 660.9 MW |
| 00-05 MAE | 327.7 MW | 292.0 MW |
| 06-10 MAE | 824.3 MW | 754.1 MW |
| 11-13 MAE | 1,009.0 MW | 938.3 MW |
| 14-18 MAE | 1,046.3 MW | 952.1 MW |
| 19-23 MAE | 578.7 MW | 553.0 MW |

The candidate improved 8 of 10 replay days. The two regressions were small, while the largest unstable days improved materially.

A frozen-origin January-May 2026 holdout also improved in every month and every time band:

| Metric | Existing | Ensemble |
|---|---:|---:|
| Overall MAE | 819.0 MW | 775.7 MW |
| Shape-delta MAE | 409.8 MW | 371.0 MW |
| Maximum daily MAE | 2,442.4 MW | 2,086.1 MW |

These replays use realized target-day weather and therefore represent an upper-bound model comparison, not a claim about live forecast-weather accuracy.

## Safety

- TEPCO forecasts are not used as model input or calibration targets.
- No hour-specific correction was added.
- The feature set and existing post-processing order are unchanged.
- Weekend and holiday point forecasts are unchanged.
- The interval version is bumped so stale pickles retrain before serving.
- The ensemble can be disabled or retuned in `config.yaml`.

## Verification

- `pytest tests/test_lgbm_model.py -q`
- full regression suite
- version-aware rolling replay with current post-processing
- frozen-origin January-May 2026 holdout
