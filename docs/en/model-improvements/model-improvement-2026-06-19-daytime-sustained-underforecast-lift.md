# 2026-06-19 Daytime Sustained Underforecast Lift

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md)

## Problem

The 2026-06-19 serving forecast showed a different failure mode from the earlier band issue. The p95 rebalance was deployed, but the central q50 forecast remained too low during the hot business-day daytime window.

- 10:00 was about `-2.9 GW` below the observed value.
- 13:00 was about `-2.2 GW` below the observed value.
- 16:00 was about `-1.5 GW` below the observed value.

The intraday residual loop detected the miss and raised `baseAdjustmentMw`, but the published forecast freeze meant already-served hours could not be rewritten. The remaining issue was not interval width; it was that sustained same-day underforecast evidence was not strong enough to lift near-future daytime hours.

## Change

- Added `daytime_sustained_underforecast_lift` to the intraday correction layer.
- The lift is gated by business-day context, sustained positive residuals, a material positive `baseAdjustmentMw`, hot/ramp weather context, and near-future target hours only.
- Default scope is intentionally narrow: `10:00-14:00`, max lead `3` hours, max lift `900 MW`.
- Added `daytimeSustainedUnderforecastLiftApplied`, `daytimeSustainedUnderforecastMaxLiftMw`, and per-hour lift diagnostics in `residualCarryoverByHour`.

## Expected Effect

When the model is persistently below actual demand on a hot business-day ramp, the next few daytime buckets can recover faster instead of waiting for residual carryover alone.

The layer should not fire on cool or neutral days, and it should not follow TEPCO forecasts. It uses same-day observed residuals plus weather/ramp context, so it is a conservative operational calibration rather than a third-party forecast blend.

## Validation

```text
tests/test_intraday_correction.py::test_intraday_daytime_sustained_underforecast_lifts_hot_business_day_future
tests/test_intraday_correction.py::test_intraday_daytime_sustained_underforecast_requires_heat_context

Full suite: 404 passed
```
