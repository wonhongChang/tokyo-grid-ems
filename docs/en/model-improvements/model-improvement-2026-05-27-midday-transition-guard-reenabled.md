# 2026-05-27 Midday Transition Guard Re-enabled
> Restored the business-day lunch dip guard after confirming that the 12:00 bucket needed a dedicated, conservative shape correction.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md)

---

## Why

Recent business-day live forecasts showed that the 12:00 lunch bucket could remain too smooth even when recent same-business-type history showed a clear midday dip.

The midday dip is a one-slot shape effect rather than an afternoon trend. It should not be solved by pushing intraday residual slope into later hours, and it should not follow TEPCO forecasts. The safer correction is a narrow guard that only checks the model against same-business-type shape context around the lunch bucket.

## Change

Re-enabled `midday_transition_guard` in the adjustment layer.

The guard is limited to the configured midday hour and applies only when the same-business-type context shows a sufficiently negative lunch transition and the model forecast remains above the guarded shape reference by more than the configured allowance.

## Operating Parameters

Default configuration:

- `hours`: [12]
- `min_negative_delta_mw`: 500
- `min_excess_mw`: 300
- `shrinkage`: 0.5
- `triggered_shrinkage`: 0.75
- `max_downward_adjustment_mw`: 900
- `triggered_max_downward_adjustment_mw`: 1200
- `same_day_softening_min_latest_hour`: 10
- `same_day_softening_delta_mw`: -300
- `use_recent_quantile_when_softening`: true

## Scope

This is intentionally not an all-day residual controller. It is a narrow business-day lunch-shape guard, so the correction should not contaminate 13:00 and later recovery behavior.
