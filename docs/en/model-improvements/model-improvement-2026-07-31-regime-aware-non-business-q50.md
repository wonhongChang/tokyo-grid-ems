# Regime-Aware Non-Business q50 Ensemble

Date: 2026-07-31 (JST)

## Background

Operational forecasts from July 28 through July 31 did not show one stable directional bias. July 30 had sustained daytime underprediction, while July 31 alternated between positive and negative hourly errors and produced an unstable shape. This pointed to a q50 regime problem rather than another global uplift or reduction rule.

The model's latest 30-day served MAE was 643.9 MW, compared with a TEPCO reference MAE of 366.0 MW. The July 3-30 operational replay reported a served MAE of 639.4 MW and a shape-delta MAE of 560.5 MW. TEPCO forecasts remain an external benchmark only and are not used as a feature or calibration target.

## Diagnosis

- The previous absolute-demand q50 learned business and non-business days in one model.
- `humidity_delta_24h`, `discomfort_delta_24h`, and their two morning interactions had high recent importance, but source changes and imputation around weekend boundaries could destabilize q50 shape.
- Removing those four inputs from every q50 path reduced some average errors but increased business-day maximum-error and daytime risk.
- Replacing the non-business q50 completely was also less stable than blending it.
- Disabling the lag-24 residual ensemble across every business-type transition degraded the 28-day validation and was rejected.

## Change

The interval contract advances to `q025_q50_q975_p95_v12_regime_q50`.

- q025, q975, unified q50, and lag-24 residual q50 retain all 63 features.
- A dedicated non-business q50 is trained separately.
- Only that dedicated model excludes four source-sensitive deltas:
  - `humidity_delta_24h`
  - `discomfort_delta_24h`
  - `business_morning_x_humidity_delta_24h`
  - `business_morning_x_discomfort_delta_24h`
- Saturday, Sunday, and holiday forecasts blend unified q50 and non-business q50 50:50.
- Interval models and the business-day q50 path are unchanged.
- The v11 Champion remains load-compatible so a rejected promotion does not fall back to the baseline model.

## 28-Day Temporal Validation

The holdout covers 672 hours from 2026-07-03 through 2026-07-30. Both contracts use the same training cutoff and final observed weather context.

| Metric | Previous contract | v12 challenger | Change |
|---|---:|---:|---:|
| Overall MAE | 951.7 MW | 931.7 MW | -2.1% |
| Overall WAPE | 2.700% | 2.644% | -0.056 pp |
| Overall RMSE | 1,292.5 MW | 1,267.9 MW | -1.9% |
| Shape-delta MAE | 574.9 MW | 547.2 MW | -4.8% |
| Maximum error | 4,873.4 MW | 4,873.4 MW | unchanged |
| Business-day MAE | 975.8 MW | 975.8 MW | unchanged |
| Non-business MAE | 900.8 MW | 838.5 MW | -6.9% |
| Morning MAE | 965.9 MW | 921.7 MW | -4.6% |
| Evening MAE | 973.6 MW | 944.1 MW | -3.0% |

The challenger passed the absolute MAE, WAPE, shape, maximum-error, and segment limits. Its MAE improvement over the seasonal baseline was 73.21%.

### Forecast Intervals

On the same frozen-origin holdout, p95 coverage did not improve: 84.4% for the previous contract and 84.2% for the challenger. Morning coverage improved from 89.3% to 90.0%, late afternoon from 83.3% to 84.5%, and evening from 88.6% to 90.0%, while daytime moved from 72.9% to 72.1%.

The latest 28-day served replay has 96.1% overall coverage, with 92.9% in both morning and daytime and 99.3% in the evening. q50 regime accuracy and interval calibration are separate problems. A global width increase was rejected because it would further over-cover the already-wide served evening interval.

## August 1 Weekend Transition

The August 1 weather input reaches 37.0°C and remains hot into the evening. The v12 shadow q50 is 36.84 GW at 08:00, 46.07 GW at 12:00, 46.40 GW at 16:00, 44.82 GW at 19:00, and 38.17 GW at 22:00. It removes the unsupported 17:00 and 19:00 troughs in v11 and is closer in shape to prior hot weekends.

These values neither follow TEPCO's forecast nor represent a promoted public forecast.

## Promotion Status

Against the current v11 Champion, the latest today/tomorrow 48-hour drift was 943.1 MW on average with a 3,579.7 MW maximum. Both exceed the operating limits of 900 MW mean and 2,500 MW hourly drift, so the artifact must not be force-promoted.

The implementation is therefore a validated Challenger contract. The current Champion remains active until the prediction-drift gate also passes. The gate and model artifact are not overridden to repair a single day.

## Verification

- 43 LightGBM and promotion unit tests passed
- 486 full Python tests passed
- 672/672 temporal holdout hours evaluated
- Challenger absolute-quality gate: passed
- Prediction-drift gate versus Champion: rejected
