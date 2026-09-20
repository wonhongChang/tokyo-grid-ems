# 2026-09-21 Observed Recovery Before Weekend Residual Damping

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-21-observed-evening-recovery.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-21-observed-evening-recovery.md)

## Problem and Scope

The [September 20 review](../model-reviews/model-review-2026-09-20.md) identified a conflict between observed recovery and `non_business_evening_positive_residual_damping`. At 17:34 on September 20, the latest actual slope was +710MW, but weak historical target-hour slopes still reduced the positive residual by 190.1MW for target 18:00. Raw demand was already too low.

Disabling the entire rule is inappropriate: September 12 contains cases where damping limited overprediction. The change only skips this additional damping when genuine observations and target-hour shape jointly support recovery. It adds no demand floor, does not extrapolate the observed slope into future demand, and does not follow TEPCO forecasts.

## Application Contract

Configuration: `intraday_correction.non_business_evening_positive_residual_damping.observed_recovery_veto`.

| Setting | Value | Meaning |
|---|---:|---|
| `enabled` | `true` | Missing/false preserves the existing rule |
| `max_lead_hours` | 3 | Distance from the latest genuine observed hour, not issuance time |
| `min_latest_slope_mw` | 600 | Minimum latest observed increase |
| `min_mean_slope_mw` | 300 | Minimum average increase over two consecutive observed intervals |

The original non-business-day, target-hour, positive-base-residual, historical-support and minimum-reduction gates must first pass. Recovery then requires:

1. Three consecutive, finite, genuine observations and their same-hour pre-calibration forecasts. The residual input filter excludes `tepco_forecast_fallback`.
2. Three strictly positive `actual - pre_calibration` residuals and both slope thresholds satisfied.
3. A target within three observed-hour steps, with a nonnegative maximum finite lag24/matching-business-type target delta. Missing support or jointly negative target slopes retain damping.

When these conditions pass, retain the incoming, already-decayed positive residual instead of multiplying it by 0.45. Earlier damping and later guards remain active; no restoration beyond the incoming residual is allowed. The 600/300MW thresholds follow the existing evening negative-residual recovery thresholds, not a parameter search fitted to September 20.

`residualCarryoverByHour[].nonBusinessEveningPositiveResidualObservedRecovery` records `latestSlopeMw`, `meanSlopeMw` and `minResidualMw`, or `null`. The corresponding reason is `non_business_evening_positive_residual_observed_recovery`. Historical support fields remain available when the veto applies.

## Replay Results

Evidence is pinned to data revision `12dc8a2952de19f572489f9b36d8880b36cfeaa9`. September 20 actuals cover 00:00-20:00 only; earlier dates use finalized actuals. The scope is August 24-September 20, 28 calendar days.

- Screened 492 retained calibration snapshots across all 28 dates.
- Replayed 11 runs with evening positive damping and 29 with sustained-underforecast lift: 36 unique runs. All reproduced the recorded baseline q50 with a maximum difference of 0.0MW.
- Used historical Git caches, captured pre-calibration curves and then-known actuals as inputs. Final target actuals were scoring-only. External networking was disabled.
- Only one of 352 evaluated positive-lead run/target pairs changed. Repeated target hours from different issuances are included; this is not a daily MAE sample of 352 independent hours.

| Target / run | Actual MW | Baseline MW | Revised MW | Absolute error before / after MW |
|---|---:|---:|---:|---:|
| Sep 20 18:00 / 17:34 | 29,240.0 | 28,548.7 | 28,738.8 | 691.3 / 501.2 |

The other 351 pairs, including September 12 counterexamples, were unchanged. Synthetic bounds around the captured q50 were used for this post-processing replay. Width preservation and bound order were checked, but this is **not a retrained-model promotion replay or evidence of improved interval coverage**. The demonstrated accuracy benefit is one target on one date, not a general weekend or seasonal improvement.

A second candidate limited sustained-underforecast lift to the latest residual after three declining positive residuals. Its 29 baselines reproduced, but it was rejected: on September 6 it improved target 13:00 while increasing target 14:00 absolute error from 449.6 to 521.8MW. RMSE over the two affected pairs rose from 374.71 to 375.72MW. Daytime lift and raw prediction logic remain unchanged.

## Verification and Operations

- Full Python suite: 717 passed with external networking disabled; one subsequently added captured-value regression test also passed. Focused tests cover missing/fallback/nonfinite data, nonconsecutive hours, zero/negative residuals, negative/missing support, business days, switch off, horizon limits, input immutability and interval-width preservation. Run them with `python -m pytest tests/test_evening_positive_recovery.py -q`.
- The trained `v14-r2-source-robust-day-ahead` artifact, 63 training features, published-forecast preservation, API models and call budgets are unchanged.
- Serving fingerprint changes from `d788cbbcd3d956a5344bf0ce2fb7d960da425390c148516acfbd40b8f9b94ee4` to `ba4d14312e56659c46a87b8e9c13750b51e93334dcb59661b8d37e6f2d0647bc`. Compatible interval history must accumulate again. Native bands may temporarily return; do not weaken sample gates or reuse incompatible history to hide this effect.
- Set `observed_recovery_veto.enabled: false` to disable only this change. To restore the previous fingerprint, remove the new block while keeping every other setting identical.
- Actual activation requires the normal code deployment and forecast update. Replay does not rewrite published history. Weekday midday errors and within-bucket raw recalculation remain separate unresolved issues.
