# 2026-05-23 Non-Business Transition Calibration
> Operational calibration for Saturday/holiday forecasts when the previous day's business-day lag is too strong.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md)

---

## Why

The 2026-05-23 Saturday forecast was correctly marked as a weekend, but the raw LightGBM line still looked too close to a weekday curve. The cause was not a missing weekend flag. The 24-hour lag came from Friday, and it was several thousand MW higher than the recent same-hour non-business-day anchor.

In that regime, `lag_24h` can dominate the model even when `is_weekend` and `is_non_business_day` are present. The existing intraday residual correction lowered the curve, but only by the recent residual amount, so the remaining forecast still carried too much Friday demand inertia.

## Change

Added a conservative `business_type_transition` calibration inside the intraday correction layer.

It activates only when:

- the target day is a non-business day,
- the previous-day lag comes from a different business type,
- same-day observed residuals already show the model is overpredicting,
- `lag_24h` is much higher than the recent same-business-type mean,
- the current forecast is still above that non-business-day anchor after a configurable allowance.

The correction is applied only to future hours. Observed/published hours are left untouched.

## Operating Behavior

This is not a fixed Saturday curve and it does not use TEPCO's forecast as a target. It uses the project's own historical same-business-type anchor plus same-day observed evidence.

Warm non-business days still get extra allowance through temperature anomaly and cooling-degree terms, so the correction should not suppress genuinely hot weekend demand too aggressively.

## Diagnostics

The operational calibration metadata now records:

- `businessTypeTransitionApplied`
- `businessTypeTransitionBiasMw`
- `business_type_transition_lag_overheat` in `appliedRegimeReason`

These fields make it easier to confirm whether a weekend/holiday line was lowered by this calibration or by the ordinary residual correction.

## Test Coverage

Added a focused intraday correction test for a Saturday after a business day where recent observed residuals show overprediction and the Friday lag is far above the non-business-day anchor.
