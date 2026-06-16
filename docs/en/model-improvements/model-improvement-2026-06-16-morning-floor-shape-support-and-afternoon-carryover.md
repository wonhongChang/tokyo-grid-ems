# 2026-06-16 Morning Floor Shape Support and Afternoon Carryover Damping

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md)

## Problem

The 2026-06-16 serving chart exposed two separate controller problems.

- Around 10:00, `morning_observed_anchor_cap` reacted too strongly to a mild negative residual and pulled the public line below the later recalculated line.
- Around 11:00, `morning_observed_ramp_floor` saw a strong same-day observed ramp and lifted the near-future bucket too aggressively, even though target-hour lag and recent same-business-type deltas only supported a much smaller increase.
- In the afternoon, positive intraday residuals accumulated around 12:00-14:00 and were carried into 15:00-19:00 even when the target-hour lag/recent shape support was weak or negative.

The final recalculated raw/pre-calibration line for 10:00-11:00 was materially closer to actual demand than the frozen served line. That means the issue was mainly controller arbitration and forecast-freeze interaction, not only the LightGBM raw curve.

## Change

- Raised `morning_observed_anchor_cap.min_latest_overforecast_mw` from `200 MW` to `500 MW`.
  - A small or noisy latest residual no longer allows a large morning anchor cap to cut the near-future line.
- Added `max_floor_delta_over_support_mw` to `morning_observed_ramp_floor`.
  - The floor still reacts to a real observed morning ramp.
  - However, its implied hourly floor delta is capped by target-hour `lag_24h_hourly_delta` / `recent_same_business_type_delta_mean` support plus a small allowance.
  - This prevents the ramp floor from pushing 11:00 far above the shape signal available for that hour.
- Added `afternoon_positive_residual_carryover_damping`.
  - It dampens only positive residual carryover.
  - In the production config, it is limited to business days so it does not overlap with the dedicated non-business evening guard.
  - It applies to 15:00-19:00 when the base adjustment is positive and the target-hour lag/recent shape support is weak.
  - It does not cap the raw model directly and does not use TEPCO as a calibration target.

## Expected Effect

For the 2026-06-16 pattern:

- 10:00 should be less exposed to a premature down-cap from a mild residual.
- 11:00 should still benefit from real same-day ramp evidence, but the lift is bounded by target-hour shape support instead of the largest recent slope.
- 15:00-19:00 should receive less inherited positive residual pressure when the afternoon/evening shape does not support that carryover.

This change is intentionally conservative. It reduces controller-induced sawtooth behavior, but it does not claim to solve every raw-model daytime miss.

## Validation

```text
tests/test_intraday_correction.py::test_intraday_correction_caps_observed_morning_ramp_floor_by_target_shape_support
tests/test_intraday_correction.py::test_intraday_damps_afternoon_positive_carryover_when_shape_support_is_weak

Full suite: 398 passed
```
