# 2026-05-23 Negative Residual Recovery Damping
> Recovery-aware intraday calibration for non-business days after a business-day lag overheat.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md)

---

## Why

The 2026-05-23 Saturday live forecast exposed a second failure mode after the non-business transition prior was added.

Early in the morning, the model was too high because Friday's 24-hour lag still carried business-day inertia. The ordinary intraday residual correction correctly produced a negative adjustment. Later, however, observed demand recovered quickly toward the recent same-business-type weekend anchor. The raw forecast for later morning hours was already close to the actual level, but the negative residual from the early miss kept being carried forward and pulled the public line too low.

This is not a fixed hour problem. It is a residual-propagation problem: once the observed series proves that demand has recovered, the model should stop letting early negative residuals dominate future hours.

## Change

Added `negative_residual_recovery_damping` to the intraday correction layer.

The layer does not modify the raw LightGBM forecast. It only weakens the carry-over strength of an already computed negative `base_adjustment_mw`.

It is evaluated only when:

- the target day is a non-business day,
- the 24-hour lag comes from a different business type,
- the residual adjustment is negative,
- recent observed demand is rising,
- at least one recent one-hour slope exceeds the configured recovery threshold,
- the latest observed demand has returned near the same-business-type anchor,
- recent residuals are clearly improving, for example `-2400 -> -1600 -> -1100`.

If observed demand rises but residuals are getting worse, the layer stays off. This avoids treating a genuinely low-demand day as a false recovery.

## Operating Parameters

Default configuration:

- `recovery_slope_base_mw`: 1000
- `anchor_proximity_tolerance_mw`: 1200
- `damping_factor_default`: 0.4
- `damping_factor_strong`: 0.2
- `strong_recovery_mean_slope_mw`: 500

The effective future adjustment becomes:

```text
base_adjustment_mw * recovery_damping_factor * decay_per_hour^(lead_hours - 1)
```

The project-wide `max_abs_adjustment_mw` cap still applies before this layer. With the default cap, a clipped `-1200 MW` residual and strong recovery factor `0.2` becomes a `-240 MW` future adjustment before lead-time decay.

## Diagnostics

Correction metadata now records:

- `negResidualRecoveryDampingApplied`
- `negResidualRecoveryDampingFactor`
- `negative_residual_recovery_damping_triggered` in `appliedRegimeReason`

These fields make it possible to see whether the intraday layer preserved a recovering raw forecast by reducing negative residual carry-over.

## Test Coverage

Added dual regression tests:

- a Saturday recovery case where early negative residuals improve while observed demand rebounds toward the weekend anchor, so negative residual carry-over is damped,
- a false-recovery case where demand rises but residuals worsen, so the damping layer remains off.
