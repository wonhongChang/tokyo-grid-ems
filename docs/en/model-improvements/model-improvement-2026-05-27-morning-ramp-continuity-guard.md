# 2026-05-27 Morning Ramp Continuity Guard
> A near-term intraday guard that prevents negative residual carry-over from breaking a confirmed business-day morning ramp.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md)

---

## Why

The 2026-05-27 live forecast exposed a morning shape-risk case.

During the business-day morning ramp, observed demand was rising strongly through the early hours. However, a negative intraday residual adjustment could still leak into the nearest future buckets and create an unnatural dip around the next forecast hour.

This was not a TEPCO-following problem. The issue was controller continuity: once same-day observations prove a strong ramp-up, a short-lived negative residual should not be allowed to break the local curve shape.

## Change

Added `morning_ramp_continuity_guard` inside the intraday correction layer.

The guard does not raise the raw LightGBM forecast above its original pre-calibration level. It only restores part of the excessive downward residual effect when recent actual demand shows a strong same-day ramp and the affected forecast hour is a near-term morning bucket.

It is evaluated only when:

- the day is a business day,
- the base residual adjustment is negative,
- at least three consecutive same-day actual points are available,
- recent actual slopes exceed the configured ramp thresholds,
- the target hour is inside the configured morning window,
- the target hour is within the near-term lead-time limit.

## Operating Parameters

Default configuration:

- `target_hours`: 6-11
- `min_reference_hour`: 7
- `max_lead_hours`: 2
- `min_recent_slope_mw`: 1000
- `min_mean_slope_mw`: 1000
- `floor_slope_fraction`: 0.25
- `max_floor_delta_mw`: 900
- `max_restore_mw`: 700
- `min_restore_mw`: 100

The cap is intentionally conservative: it preserves local ramp continuity without adding new demand beyond the raw model line.

## Diagnostics

Correction metadata now records:

- `morningRampContinuityGuardApplied`
- `morningRampContinuityMaxRestoreMw`
- `morning_ramp_continuity_guard` in `appliedRegimeReason`
- per-hour diagnostic rows with forecast deltas, lag deltas, same-day actual slope, residual adjustment, and weather delta

## Test Coverage

Added regression tests for:

- a strong business-day morning ramp where negative residual carry-over would otherwise create a local dip,
- non-business or unsupported ramp contexts where the guard must not intervene.
