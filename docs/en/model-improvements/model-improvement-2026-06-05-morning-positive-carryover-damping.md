# 2026-06-05 Morning Positive Residual Carryover Damping

## Problem

The 2026-06-05 live forecast exposed a different failure mode from the previous warm-lag overreaction incident.

- 07:00-08:00 actual demand rose faster than the model expected.
- Intraday correction interpreted that underforecast as a positive residual signal.
- The positive residual was then carried into 10:00-13:00, even though lag/recent same-business shape no longer supported a steep ramp.
- Later runs detected the overforecast and pushed the residual negative, but the already published 10:00-11:00 line stayed visible because of the published forecast freeze policy.

## Change

Added `morning_positive_residual_carryover_damping` to the intraday correction layer.

The guard does not rewrite the raw LightGBM forecast. It only dampens positive intraday carryover when all of the following are true:

- business-day morning context,
- strong recent same-day ramp created a positive residual,
- target hour is 10:00-13:00,
- target hour is at least two hours ahead,
- `lag_24h_hourly_delta` and `recent_same_business_type_delta_mean` no longer support a steep ramp.

## Operational Effect

This prevents an early morning underforecast from mechanically lifting the post-ramp plateau or lunch-transition hours. If the target slot still has strong lag/recent ramp support, the carryover is left untouched.

## Diagnostics

Operational calibration snapshots now include:

- `morningPositiveResidualCarryoverDampingFactor`
- `morningPositiveResidualCarryoverDampedMw`
- `morningPositiveResidualCarryoverSupportDeltaMw`

The AI operations report fact packet also exposes the guard so that future reports can distinguish raw model miss, carryover overshoot, and published freeze effects.

## Validation

- Added regression coverage for the 2026-06-05 style case.
- Added a bypass test proving that strong supported ramps are not damped.
- `tests/test_intraday_correction.py`: 41 passed.
