# 2026-06-26 business-day anchor cap retuning

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-26-business-day-anchor-cap-retuning.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-26-business-day-anchor-cap-retuning.md)

## Context

The 2026-06-26 live forecast exposed another business-day warm-ramp overhang:

- 09:00-11:00 JST was over-forecast even though same-day actuals were already showing that the ramp was flattening.
- The raw LightGBM line was high, and the analogous-day / warm-day layers added or preserved too much level around 10:00-14:00.
- Later intraday runs correctly pushed the remaining future hours downward, but already published morning slots could not be rewritten.

TEPCO values were used only as an external reference while diagnosing the miss. They are not blended into the model and are not used as calibration input.

## Changes

### Stronger morning observed anchor cap

`intraday_correction.morning_observed_anchor_cap` now reacts more decisively when the latest observed morning slot is already materially over-forecast:

- `min_latest_overforecast_mw`: 500 -> 400
- `cap_buffer_mw`: 250 -> 0
- `shrinkage`: 0.75 -> 1.0
- `max_reduction_mw`: 800 -> 1000

This keeps the cap tied to observed same-day evidence, but removes the extra slack that let an overheated 10:00-13:00 line survive.

### Afternoon anchor cap can handle moderate recovery

`intraday_correction.afternoon_observed_anchor_cap.max_latest_slope_mw` is relaxed from 500 MW/h to 900 MW/h.

The previous value disabled the afternoon cap whenever actual demand recovered moderately after lunch, even if the model was still clearly over-forecasting. The cap now stays available for a moderate recovery, while still avoiding intervention during a very strong genuine ramp.

## Validation

Added regression tests for:

- a warm business morning where 09:00 observed residual is negative and 10:00-13:00 should be capped more firmly,
- a post-lunch recovery where the actual slope is positive but residuals still confirm model overhang.

Targeted intraday correction tests:

```text
64 passed
```

## Operational Notes

This change does not follow TEPCO and does not modify already-published past slots. It tightens the next intraday run's near-term business-day caps when the model has already been proven high by same-day actuals.
