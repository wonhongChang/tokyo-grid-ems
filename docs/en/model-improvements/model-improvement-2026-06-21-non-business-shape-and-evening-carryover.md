# 2026-06-21 Non-Business Shape and Evening Carryover

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md)

## Problem

The 2026-06-21 Sunday serving forecast was not dominated by a single residual loop failure. The observed day split into three different issues.

- Morning: 06:00 was under-forecast by about `1.37 GW`. The forecast dropped sharply from 05:00 to 06:00 even though `lag_24h_hourly_delta` and `recent_same_business_type_delta_mean` only supported a flat or mild decline.
- Afternoon: 14:00-15:00 were under-forecast. The raw LightGBM level was closer, but `analog_adjusted` pushed the non-business afternoon down too far. The existing non-business analog downshift guard stopped at 13:00, so it did not protect the afternoon plateau.
- Evening: 18:00-19:00 were mildly high. The 17:01 run carried a positive residual from the 14:00-16:00 under-forecast into the evening, but the non-business evening damping threshold was just high enough that it did not fire.

TEPCO forecasts were used only as an external comparison during analysis. They are not used as calibration inputs.

## Change

- Added `non_business_morning_shape_floor_guard` to `PostHolidayTimeBandGuard`.
  - It activates only on non-business morning transition buckets.
  - It compares the forecast slope against lag-24h and recent same-business-type slope support.
  - It lifts only unsupported sharp drops, with shrinkage and a maximum lift cap.
- Expanded `non_business_analog_downshift_guard` from 07:00-13:00 to 07:00-15:00.
  - This protects non-business afternoon plateau hours when raw demand is already near the recent same-business anchor.
  - Declining afternoon shapes can still keep the analog downshift when the anchor does not support a plateau.
- Lowered `non_business_evening_positive_residual_damping.min_base_adjustment_mw` from `500 MW` to `350 MW`.
  - This lets the evening carryover brake engage when afternoon under-forecast residuals are material but not extreme.
- Added the new guard to the AI report feature catalog.

## Risk Controls

- The morning guard does not create a fixed 06:00 value. It only caps a slope mismatch when recent non-business shape evidence does not justify a deep trough.
- The afternoon analog guard still allows negative analog shifts when raw forecasts are materially above the non-business anchor or when lag/recent deltas support a decline.
- The evening change only dampens positive residual carryover when the non-business evening shape has weak support. It does not lower the raw model directly.

## Validation

```text
tests/test_adjustment.py::test_guard_lifts_non_business_morning_shape_floor_when_drop_is_unsupported
tests/test_adjustment.py::test_guard_caps_non_business_afternoon_analog_downshift_when_anchor_supports_plateau
tests/test_adjustment.py::test_guard_keeps_non_business_analog_downshift_without_shape_support
tests/test_intraday_correction.py::test_intraday_damps_non_business_evening_positive_carryover_when_shape_is_weak
```
