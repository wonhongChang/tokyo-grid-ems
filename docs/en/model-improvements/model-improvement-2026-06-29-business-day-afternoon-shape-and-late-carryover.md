# 2026-06-29 business-day afternoon shape and late carryover guards

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-29-business-day-afternoon-shape-and-late-carryover.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-29-business-day-afternoon-shape-and-late-carryover.md)

## Background

The 2026-06-29 business-day forecast exposed a chained shape failure:

- 09:00 JST stayed too high after the 08:00 actual value already showed an over-forecast.
- 13:00-16:00 JST was too low because a warm business-day afternoon inherited an unsupported negative analogous-day shift.
- 21:00-22:00 JST was likely too high because the positive residual correction created by the afternoon miss kept carrying into late evening even though lag/recent shape indicators were declining.

TEPCO is used only as an external benchmark for diagnosis. The correction logic does not consume TEPCO forecasts.

## Changes

### 09:00 morning anchor protection

`intraday_correction.morning_observed_anchor_cap.target_hours` now includes `9`.

This lets the 08:00 observed over-forecast cap protect the next 09:00 bucket instead of waiting until 10:00.

### Business afternoon analog downshift guard

Added `adjustment.post_holiday_timeband_guard.business_afternoon_analog_downshift_guard`.

The guard limits large negative analogous-day shifts on warm business afternoons when lag/recent shape support does not clearly justify a decline. This targets the case where raw LGBM was closer to the later actuals, but the analog stage pushed 14:00-15:00 too far down.

### Daytime underforecast lift can react to one strong latest miss

`intraday_correction.daytime_sustained_underforecast_lift` now:

- covers 15:00-16:00 as well as midday
- can activate from a strong latest residual override on business days
- keeps the post-midday shape gate focused on 12:00-13:00 so it does not block later hot-afternoon recovery

### Late-evening positive carryover damping

`intraday_correction.afternoon_positive_residual_carryover_damping` now covers 20:00-22:00 and can use references through 19:00.

This prevents an afternoon underforecast correction from mechanically lifting late-evening hours when both lag-24h and same-business-type shape indicators point downward.

## Validation

Regression tests were added for:

- business-day warm afternoon analog downshift capping
- preserving a real analog downshift when shape indicators strongly support decline
- 09:00 observed-anchor protection
- latest-residual daytime lift for hot business afternoons
- late-evening positive residual carryover damping

Validation command:

```powershell
python -m pytest -q
```

Result: `422 passed`.

## Operational Notes

This patch is deliberately conservative. It does not try to make the curve follow TEPCO. It only blocks cases where internal post-processing stages move the forecast against same-day evidence or against the available lag/recent shape context.

Watch the next business-day hot afternoon for:

- whether 13:00-16:00 stops being suppressed by analog downshifts
- whether 21:00-22:00 no longer inherits afternoon positive residuals
- whether the 09:00 anchor cap helps without flattening genuine morning ramp-up days
