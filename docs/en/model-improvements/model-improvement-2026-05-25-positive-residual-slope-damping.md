# 2026-05-25 Positive Residual Slope Damping
> Slope-aware intraday calibration to prevent positive residual carry-over from over-lifting near-term peaks.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md)

---

## Why

The 2026-05-25 Monday live forecast exposed a shape-risk chain around 12:00-15:00.

The raw model was too low around 12:00-14:00, especially after the lunch dip. Intraday residual correction then accumulated a positive `base_adjustment_mw`. The issue was not the positive residual itself; same-day residuals are useful. The problem was that the residual carried into the next peak even while observed demand was already losing upward momentum.

This created a controller overshoot: the forecast line had been too low before 14:00, then became too high around 15:00.

## Change

Added `positive_residual_slope_damping` inside the intraday correction layer.

The layer does not modify raw LightGBM output and does not change already observed or frozen forecast hours. It only reduces the future carry-over strength of an already positive residual adjustment when recent observations show that the positive miss is easing and demand slope is rolling over.

It is evaluated only when:

- the residual adjustment is positive and large enough,
- at least three real observed residuals exist,
- the latest observed hour is after the configured reference hour,
- the last three residuals are positive,
- the latest residual has improved versus the previous residual,
- recent observed demand is falling or clearly decelerating,
- the latest actual demand is still near the same-business-type anchor,
- the residual-adjusted future forecast would exceed the recent observed/anchor level by more than the configured allowance.

## Operating Parameters

Default configuration:

- `min_reference_hour`: 12
- `max_lead_hours`: 3
- `min_base_adjustment_mw`: 300
- `min_positive_residual_mw`: 300
- `min_residual_improvement_mw`: 300
- `min_slope_deceleration_mw`: 500
- `drop_slope_threshold_mw`: 300
- `latest_slope_max_mw`: 400
- `anchor_proximity_tolerance_mw`: 1200
- `peak_excess_allowance_mw`: 300
- `damping_factor`: 0.4

The effective positive residual adjustment for eligible near-term hours becomes:

```text
base_adjustment_mw * decay_per_hour^(lead_hours - 1) * positive_residual_slope_damping_factor
```

## Diagnostics

Correction metadata now records:

- `positiveResidualSlopeDampingApplied`
- `positiveResidualSlopeDampingFactor`
- `positiveResidualSlopeDampingMaxMw`
- `positive_residual_slope_damping_triggered` in `appliedRegimeReason`
- `residualCarryoverByHour`, including per-hour decay, damping factors, and final residual adjustment

Operational calibration rows also include `residualCarryover` for each hour. This makes it easier to trace which intraday run pushed which future hour and whether the slope-aware damping layer intervened.

## Test Coverage

Added regression tests for:

- a Monday afternoon deceleration case where positive residual carry-over is damped,
- a genuine rising-demand case where residuals are worsening, so the positive residual is preserved.
