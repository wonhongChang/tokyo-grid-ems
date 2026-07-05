# 2026-07-06 weekend positive-tail lift and 17:00 damping

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-06-weekend-positive-tail-and-evening-damping.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-06-weekend-positive-tail-and-evening-damping.md)

## Background

The 2026-07-04 Saturday forecast was acceptable: model MAE was about 245MW, slightly better than TEPCO's 268MW on the finalized public JSON.

The 2026-07-05 Sunday forecast exposed two specific issues:

- 12:00 JST was under-forecast by about 1.5GW. The 10:00 and 11:00 residuals were already positive, but the earlier 09:00 over-forecast kept the rolling residual gate too conservative.
- 17:00 JST was over-forecast by about 0.9GW. The raw/pre-calibration forecast was close to actual, but lunch/afternoon positive residual carryover lifted the served line too much.

The 2026-07-06 Monday forecast had only the 00:00 actual available at review time, so no strong Monday-specific model change was made from that incomplete evidence.

This change does not use TEPCO forecasts as an input. TEPCO remains an external benchmark only.

## Changes

### Non-business positive-tail override for daytime lift

`intraday_correction.daytime_sustained_underforecast_lift` now supports a narrow non-business positive-tail override.

When the latest weekend observations show consecutive positive residuals, the lift gate can use that latest positive tail instead of letting one earlier over-forecasted hour suppress the whole rolling mean. This targets the 2026-07-05 12:00 case, where 10:00 and 11:00 were both under-forecast but 09:00 had been over-forecast.

The override is still guarded by:

- non-business day context
- consecutive positive residuals
- minimum latest/mean/peak residual thresholds
- heat/humidity context in the target hour
- existing per-hour lift caps

The operational snapshot records `daytimeSustainedUnderforecastPositiveTailOverrideActive` so the AI/Ops report can explain why the lift was allowed.

### Non-business 17:00 positive residual damping

`intraday_correction.non_business_evening_positive_residual_damping` now covers 17:00 JST and can act from lead hour 2.

This closes the 2026-07-05 gap where a positive afternoon residual carried into 17:00 even though the target-hour lag/recent shape support was weak. The damping still requires:

- non-business day context
- sufficiently large positive base adjustment
- weak target-hour lag/recent support
- minimum damped MW threshold

## Validation

Added regression coverage for:

- a 2026-07-05-like weekend lunch case where a positive residual tail should activate the daytime lift despite one earlier over-forecast
- a weekend 17:00 weak-shape case where positive residual carryover should be damped

Targeted tests:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_weekend_daytime_lift_uses_positive_tail_after_one_earlier_overforecast tests/test_intraday_correction.py::test_intraday_damps_non_business_17h_positive_carryover_when_shape_is_weak -q
```

Result: `2 passed`.

Related tests:

```powershell
python -m pytest tests/test_intraday_correction.py tests/test_ai_daily_report.py -q
```

Result: `105 passed`.

## Operational Notes

This is a weekend-specific operational calibration improvement, not a broad increase in weekend demand. It only reacts after same-day actual residual evidence appears.

For 2026-07-06, the model should be re-evaluated after morning and daytime actuals accumulate. The available 00:00-only evidence was not enough to justify a Monday-specific guard change.
