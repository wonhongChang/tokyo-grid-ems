# 2026-06-14 Non-Business Shape and Residual Guards

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-14-non-business-shape-and-residual-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-14-non-business-shape-and-residual-guards.md)

## Problem

The 2026-06-14 Sunday serving chart showed three different failure modes between 09:00 and 19:00 JST.

- 09:00-10:00 were under-forecast because the analogous-day adjustment still pushed the non-business morning line below raw LightGBM. The raw line was already closer to actual demand, but the post-adjustment line accepted a small negative analog shift.
- 14:00-17:00 exposed a weekend version of the afternoon plateau problem. Recent observations showed the model was running high, but `afternoon_observed_anchor_cap` was limited to business days, so it did not protect Sunday afternoon.
- 18:00-19:00 were pulled too low by a negative intraday residual carryover from the 18:31 snapshot. By that point the same-day actual demand had already recovered from 15:00 to 17:00, so the downward residual should have been damped instead of carried forward unchanged.

The 11:00-12:00 over-forecast remained mostly a raw LightGBM shape issue. There was not enough safe same-day evidence before the period closed to rewrite that part without introducing an even larger hard-coded midday rule.

## Changes

- Tightened `non_business_analog_downshift_guard`.
  - The guard now blocks even small negative analog downshifts when non-business ramp support exists.
  - The default allowed downshift was changed from 300 MW to 0 MW under the guard condition.
  - This keeps the weekend morning line closer to raw LightGBM when the analog day would erase a supported ramp.
- Extended `afternoon_observed_anchor_cap` to non-business days.
  - `business_day_only` is now `false`.
  - The target range now includes 17:00.
  - The cap still requires observed over-forecast evidence, so it remains a reactive guard rather than a Sunday-specific rule.
- Added `non_business_evening_negative_residual_damping`.
  - It applies only on non-business evenings, currently 18:00-20:00.
  - It activates when the base residual is strongly negative, the latest same-day actual slope is recovering, and lag/recent same-business deltas do not contradict a flat or rising evening.
  - It dampens only the negative residual carryover; it does not lift the raw forecast or follow TEPCO.
- Added AI Ops Report context fields for the new negative residual damping layer so future reports can explain the control behavior from calibration JSON instead of guessing from the final chart.

## Expected Effect

On the 2026-06-14 public data:

- 09:00 and 10:00 should no longer receive a supported non-business analog downshift below raw LightGBM.
- 16:00 and 17:00 can now be capped by observed over-forecast evidence even on Sundays.
- 18:00 and 19:00 negative residual carryover is damped when the same-day actual series has already turned upward.

This change does not rewrite already frozen served forecasts. It improves the next intraday run under the same evidence pattern and preserves the project's rule that TEPCO is a diagnostic reference, not a calibration target.

## Remaining Risk

The 11:00-12:00 Sunday over-forecast is still a raw model shape problem. The safer next step is feature/backtest work around non-business midday shape, not another broad post-processing cap.

## Validation

```text
tests/test_adjustment.py::test_guard_caps_non_business_analog_downshift_when_ramp_is_supported
tests/test_adjustment.py::test_guard_keeps_non_business_analog_downshift_without_shape_support
tests/test_intraday_correction.py::test_intraday_afternoon_observed_anchor_cap_can_run_on_non_business_days
tests/test_intraday_correction.py::test_intraday_damps_non_business_evening_negative_carryover_when_actual_recovers

Full suite: 395 passed
```
