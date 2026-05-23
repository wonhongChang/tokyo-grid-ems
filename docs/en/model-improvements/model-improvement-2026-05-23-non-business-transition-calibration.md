# 2026-05-23 Non-Business Transition Calibration
> Operational calibration for Saturday/holiday forecasts when the previous day's business-day lag is too strong.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md)

---

## Why

The 2026-05-23 Saturday forecast was correctly marked as a weekend, but the raw LightGBM line still looked too close to a weekday curve. The cause was not a missing weekend flag. The 24-hour lag came from Friday, and it was several thousand MW higher than the recent same-hour non-business-day anchor.

In that regime, `lag_24h` can dominate the model even when `is_weekend` and `is_non_business_day` are present. The existing intraday residual correction lowered the curve, but only by the recent residual amount, so the remaining forecast still carried too much Friday demand inertia.

## Change

Added a conservative `business_type_transition` calibration inside the intraday correction layer.

The observed transition layer activates only when:

- the target day is a non-business day,
- the previous-day lag comes from a different business type,
- same-day observed residuals already show the model is overpredicting,
- `lag_24h` is much higher than the recent same-business-type mean,
- the current forecast is still above that non-business-day anchor after a configurable allowance.

The correction is applied only to future hours. Observed/published hours are left untouched.

## Midnight Prior

Added a separate `business_type_transition_prior` layer for the midnight-to-early-morning information gap.

This layer is intentionally weaker than the observed transition correction. Its evaluation window stays open while `lastObservedHour < 6`, even if more than the normal intraday minimum number of observations has already arrived. It is forced off once `lastObservedHour >= 6`, where the observed transition layer can take over.

Default behavior:

- `shrinkage`: 0.25
- `max_abs_bias_mw`: 500
- `lag_overheat_threshold_mw`: 1500
- `base_allowed_excess_mw`: 900

It lowers a future hour only when the forecast is above `recent_same_business_type_mean + base_allowed_excess_mw`. This makes it a weak prior against Friday-to-Saturday lag contamination, not a fixed weekend shape.

## Handoff Gap Mitigation

The 2026-05-23 live run exposed a handoff gap around the early morning ramp. At 07:44 JST, five observed readings existed, but the latest observed hour was still 04:00. The old logic had already turned the prior off because the observation count reached the intraday minimum, while the observed transition layer was still off because `lastObservedHour < 6`.

The new behavior keeps the prior eligible through that handoff gap. It also prevents small positive overnight residuals from lifting overheated weekend ramp forecasts when all of the following are true:

- the target day is non-business and the 24h lag comes from a different business type,
- `lag_24h` is above the recent same-business-type anchor,
- the affected hour is in the configured morning ramp window,
- the current forecast is already above `recent_same_business_type_mean + base_allowed_excess_mw`.

This does not suppress every positive residual. If the forecast still has room under the non-business anchor plus allowance, the positive residual can pass through normally.

## Operating Behavior

This is not a fixed Saturday curve and it does not use TEPCO's forecast as a target. It uses the project's own historical same-business-type anchor plus same-day observed evidence.

Warm non-business days still get extra allowance through temperature anomaly and cooling-degree terms, so the correction should not suppress genuinely hot weekend demand too aggressively.

## Diagnostics

The operational calibration metadata now records:

- `businessTypeTransitionPriorApplied`
- `businessTypeTransitionPriorBiasMw`
- `businessTypeTransitionApplied`
- `businessTypeTransitionBiasMw`
- `positiveResidualMitigationApplied`
- `positiveResidualMitigationMaxMw`
- `business_type_transition_prior_lag_overheat` in `appliedRegimeReason`
- `business_type_transition_lag_overheat` in `appliedRegimeReason`
- `positive_residual_mitigation` in `appliedRegimeReason`

These fields make it easier to confirm whether a weekend/holiday line was lowered by this calibration or by the ordinary residual correction.

## Test Coverage

Added focused intraday correction tests for a Saturday after a business day where recent observed residuals show overprediction, the Friday lag is far above the non-business-day anchor, and the 07:44-style handoff gap could otherwise let small positive overnight residuals lift the 07:00-08:00 ramp.
