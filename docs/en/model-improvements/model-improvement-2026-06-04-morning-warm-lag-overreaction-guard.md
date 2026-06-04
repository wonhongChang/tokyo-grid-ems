# 2026-06-04 Morning Warm-Lag Overreaction Guard

> An intraday q50 guard for warm business-day mornings where the raw model keeps a high lag/weather uplift even after same-day actuals prove the line is too high.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)

---

## Incident

The 2026-06-04 live forecast showed a q50 overprediction during the business-day morning ramp. The issue was not the forecast interval tail guard added on 2026-06-03. The band guard only limits p95/p99 interval tails; it does not change the q50 line.

The raw LightGBM forecast was already high from the previous night and early morning. As same-day actuals arrived, intraday residual correction became strongly negative, but published forecast freeze preserved already-served hours. The remaining near-term morning buckets still needed a conservative extra brake when the weather/lag uplift was not confirmed by actual demand.

## Change

Added `morning_warm_lag_overreaction_guard` inside the intraday correction layer.

The guard is intentionally narrow:

- applies only to configured morning buckets,
- requires a business-day context,
- requires a materially negative same-day residual adjustment,
- requires a warm-lag signal such as high `temp_delta_24h` or `cooling_delta_24h`,
- affects only near-term future buckets,
- never rewrites already observed or frozen published hours.

## Control Logic

For a target forecast hour, the guard builds a same-day cap from the latest actual demand and a clipped projected morning slope.

If the current post-calibration forecast remains above that cap, the guard subtracts only a capped fraction of the excess. This makes it a brake on raw overreaction, not a TEPCO-following rule.

Key config:

```yaml
morning_warm_lag_overreaction_guard:
  enabled: true
  target_hours: [8, 9, 10, 11]
  min_base_adjustment_mw: 500
  min_temp_delta_24h_c: 2.0
  min_cooling_delta_24h_c: 0.8
  max_projected_slope_mw: 1800
  shrinkage: 0.75
  max_reduction_mw: 800
```

## Observability

Operational calibration JSON now records:

- `morningWarmLagOverreactionGuardApplied`
- `morningWarmLagOverreactionMaxReductionMw`
- per-hour cap/reduction values in `residualCarryoverByHour`
- `morning_warm_lag_overreaction_guard` in `appliedRegimeReason`

The Ops Report fact packet also includes the new guard in the feature catalog so AI reports can distinguish q50 warm-lag overreaction from interval-band issues.

## Validation

Added regression tests for:

- a 2026-06-04-style warm business-day morning where the guard reduces an overheated near-term q50 forecast,
- a negative-residual morning without a warm signal where the guard stays inactive.
