# 2026-06-20 Non-Business Prior and Plateau Guards

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md)

## Problem

The 2026-06-20 Saturday serving forecast exposed three non-business-day failure modes.

- Before same-day observations arrived, stacked no-observation priors pushed several early and daytime buckets too far below the raw model. The 00:54 JST run combined cooler-day scale bias, day-boundary carryover, and business-type transition prior, then those values were preserved by the published forecast freeze.
- After the first morning observations arrived, the same-day weekend ramp was real, but `morning_observed_ramp_floor` was business-day only. The 10:00-11:00 support therefore stayed too weak.
- In the humid afternoon, 14:00-15:00 remained below actual demand. Temperature deltas were cooler than the previous day, so the business-day heat/ramp lift did not recognize the non-business humid plateau.

Evening buckets were also inspected. The existing non-business evening residual damping was already active, so this change does not add a hard evening cap without observed near-term evidence.

## Change

- Added `pre_observation_prior_stack_cap` to limit the total negative shift from stacked no-observation priors when there are no or almost no same-day actuals.
- Extended `morning_observed_ramp_floor` to non-business days with a smaller slope fraction and smaller lift cap.
- Extended `daytime_sustained_underforecast_lift` to a narrow non-business humid-plateau branch for 14:00-15:00.
- Added humidity/discomfort diagnostics to the per-hour residual carryover log.
- Added the new guard names to the AI report feature catalog so future operation reports can reference them directly.

## Risk Controls

- The logic does not use TEPCO forecasts as calibration input.
- The no-observation cap only restores excessive downward movement relative to the raw forecast; it does not create a new upward forecast regime.
- The weekend morning floor still requires observed same-day ramp evidence.
- The humid plateau lift requires sustained positive residuals, positive residual pressure, and high humidity or discomfort index.
- The evening shape remains monitored rather than forcibly suppressed.

## Validation

```text
tests/test_intraday_correction.py::test_intraday_caps_pre_observation_prior_stack_before_weekend_actuals
tests/test_intraday_correction.py::test_intraday_weekend_morning_ramp_floor_lifts_observed_non_business_ramp
tests/test_intraday_correction.py::test_intraday_weekend_humid_daytime_underforecast_lifts_plateau_hours
```
