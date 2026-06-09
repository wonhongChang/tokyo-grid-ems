# 2026-06-09 Morning Observed Anchor Cap

## Problem

The 2026-06-09 live forecast showed a large late-morning overprediction after the active-day forecast was rebuilt:

- 10:00 actual stayed flat at 30,690 MW, while the served model line climbed to roughly 32,081 MW.
- 11:00 and 12:00 also stayed above the observed path and breached the lower side of the forecast band.
- The 06:10 intraday snapshot was materially closer for 10:00-12:00, but the 07:30 ETL rebuild lifted the same-day future line by roughly 900-1,200 MW before enough same-day evidence existed.

## Rejected Option

A broad active-day forecast drift limiter was tested against recent forecast snapshots. It reduced the 2026-06-09 jump, but it also showed degradation risk on other recent days where a real morning ramp needed room to move. That approach was rejected because it would act on forecast movement itself rather than on observed evidence.

## Implemented Layer

Added `intraday_correction.morning_observed_anchor_cap`.

This is a conservative post-calibration layer. It does not follow TEPCO and does not suppress every morning increase. It only caps a near-term morning/noon forecast when the latest same-day observation already shows that the model is running high and the future path is above what lag/recent shape support can explain.

## Guard Contract

The layer can activate only when all conditions are met:

- Business day only.
- Last observed hour is between 08:00 and 12:00.
- Latest observed residual is at least 200 MW below the model.
- Target hour is 10:00-13:00 and within four lead hours.
- Forecast exceeds `last_actual + cumulative_shape_support + 250 MW`.

`cumulative_shape_support` uses the larger of:

- `lag_24h_hourly_delta`
- `recent_same_business_type_delta_mean`

Only the overhang above that cap is reduced, with 75% shrinkage and an 800 MW maximum reduction.

## Diagnostics

The layer writes these fields into operational calibration metadata:

- `morningObservedAnchorCapApplied`
- `morningObservedAnchorCapMaxReductionMw`
- `morningObservedAnchorCapReductionMw`
- `morningObservedAnchorCapMw`
- `morningObservedAnchorCapCumulativeSupportMw`
- `morningObservedAnchorCapLatestResidualMw`

The AI daily report feature catalog now includes `intraday_correction.morning_observed_anchor_cap`.

## Validation

- Added regression tests for the 2026-06-09 late-morning overforecast pattern.
- Added a no-op test proving the layer waits when the latest residual is not meaningfully negative.
- Targeted test result: `tests/test_intraday_correction.py` passed.
