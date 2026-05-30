# 2026-05-27 Evening Decline Continuity Guard
> A near-term intraday guard that caps abnormal evening rebounds when same-day demand is already falling.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md)

---

## Why

The 2026-05-27 live forecast exposed an evening shape-risk case.

By 17:00, observed demand had already dropped sharply from the previous hour. The latest same-day slope, `lag_24h_hourly_delta`, and recent same-business-type delta all pointed to a flat-to-declining evening context. However, the served model forecast rebounded strongly at 18:00.

The intraday residual carry-over was small, so the spike was not primarily a residual-controller issue. The risk came from the raw model line and daytime warm-day guard still allowing a near-term rebound even after real same-day demand had rolled over.

## Change

Added `evening_decline_continuity_guard` inside the intraday correction layer.

The guard does not follow TEPCO forecasts and does not hard-code the 18:00 bucket. It only caps abnormal near-term rebounds when the current day has already shown a clear evening decline and the internal shape signals do not support a rebound.

It is evaluated only when:

- the latest observed hour is at or after the configured evening reference hour,
- the latest same-day actual slope and recent mean slope are clearly negative,
- the target forecast hour is a near-term future bucket,
- both `lag_24h_hourly_delta` and `recent_same_business_type_delta_mean` do not support an increase,
- the forecast rebound from the previous final forecast exceeds the configured threshold,
- the rebound exceeds a capped upper buffer after weather allowance is included.

The later 2026-05-29 high-level overhang extension is documented separately in [Evening Level-Overhang Guard](model-improvement-2026-05-29-evening-level-overhang-guard.md).

## Operating Parameters

Default configuration:

- `target_hours`: 16-20
- `min_reference_hour`: 15
- `max_lead_hours`: 2
- `latest_slope_max_mw`: -500
- `mean_slope_max_mw`: -300
- `max_supporting_delta_mw`: 200
- `min_forecast_rebound_mw`: 800
- `max_rebound_mw`: 600
- `actual_reference_slack_mw`: 300
- `weather_allowance_mw_per_c`: 120
- `hot_temp_c`: 30.0
- `max_weather_allowance_mw`: 400
- `max_reduction_mw`: 900
- `min_reduction_mw`: 100
- `level_overhang_enabled`: true
- `min_level_overhang_mw`: 500
- `level_overhang_shrinkage`: 0.75

The cap is intentionally conservative. It reduces only the excess rebound or level overhang and keeps a weather allowance so genuinely hot evenings are not suppressed too aggressively.

## Diagnostics

Correction metadata now records:

- `eveningDeclineContinuityGuardApplied`
- `eveningDeclineContinuityMaxReductionMw`
- `evening_decline_continuity_guard` in `appliedRegimeReason`
- per-hour `residualCarryoverByHour` fields for the cap, mode, rebound, weather allowance, and reduction amount

Operational calibration snapshot summaries also include the guard state so daily reports can explain why an evening spike was capped.

## Test Coverage

Added regression tests for:

- a 2026-05-27-style evening decline where an abnormal 18:00 rebound is capped,
- a legitimate rebound case where lag and same-business shape both support an increase, so the guard does not intervene.
