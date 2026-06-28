# 2026-06-28 weekend humid daytime lift

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-28-weekend-humid-daytime-lift.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-28-weekend-humid-daytime-lift.md)

## Background

The 2026-06-27 Saturday forecast was acceptable overall: the model beat TEPCO on daily MAE, and all actual values stayed within the p95 band. The 2026-06-28 Sunday forecast exposed a different weekend weakness:

- Early morning demand was under-forecast before enough same-day observations were available.
- After the morning ramp recovered, the 12:00-15:00 JST daytime line stayed too low.
- The day was humid, but not hot enough by `cooling_delta_24h` to trigger the existing non-business daytime lift.

TEPCO is used only as an external benchmark for diagnosis. The model input and correction logic do not consume TEPCO forecasts.

## Changes

### Non-business daytime lift now supports moderate humid days

`intraday_correction.daytime_sustained_underforecast_lift` now has separate non-business residual response parameters:

- `non_business_residual_pressure_shrinkage`
- `non_business_residual_slack_mw`

This keeps the business-day controller unchanged while allowing weekend daytime corrections to react more directly when actual residuals are consistently positive.

### Weekend target hours and weather thresholds were retuned

The non-business target window was expanded from `[14, 15]` to `[12, 13, 14, 15]`.

The humidity/discomfort gates were lowered from very humid-only settings to moderate humid-day settings:

- `non_business_min_discomfort_index`: `74.0 -> 70.0`
- `non_business_min_humidity_pct`: `90.0 -> 85.0`

The lift still requires same-day residual evidence, so it does not blindly raise every weekend noon forecast.

## Validation

Added a regression test for the 2026-06-28 Sunday pattern:

- non-business day
- positive residuals across the morning ramp
- moderate humidity and discomfort index around 70
- cooling deltas that are not strongly positive

Expected behavior: 12:00-14:00 JST forecasts are lifted by the residual-pressure path while business-day behavior remains unchanged.

Targeted test:

```powershell
python -m pytest tests/test_intraday_correction.py -q
```

Result: `65 passed`.

## Operational Notes

This is not a TEPCO-following layer. It is a same-day evidence layer for weekend demand that is too low despite repeated observed underforecasting.

The next things to watch are:

- whether Sunday daytime WAPE improves without over-lifting cooler weekends
- whether 06:00-07:00 JST still needs a separate pre-observation weekend ramp prior
- whether the p95 band remains wide enough but not visually excessive around weekend daytime ramps
