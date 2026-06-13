# 2026-06-13 Non-Business Analog and Carryover Guards

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md)

## Problem

The 2026-06-13 Saturday serving chart exposed two separate non-business-day shape issues:

- The raw LightGBM morning forecast was not the main problem. The analogous-day adjustment pushed 08:00-13:00 down by roughly 500-1,100 MW, making an already rising Saturday demand curve too low.
- By 16:37 JST, the intraday residual correction had accumulated a positive base adjustment of about +963 MW from daytime underprediction. That carryover was still adding roughly +815 MW at 18:00 and +750 MW at 19:00, even though the weekend evening lag/recent shape did not strongly support a rebound.

## Changes

- Added `non_business_analog_downshift_guard` to `PostHolidayTimeBandGuard`.
  - It applies only on non-business days.
  - It limits large negative analogous-day shifts in 07:00-13:00 when lag/recent same-business deltas or anchor context say the raw ramp should not be erased.
  - The default maximum allowed downshift is 300 MW.
- Added `non_business_evening_positive_residual_damping` to `IntradayResidualCorrector`.
  - It applies only on non-business evenings, currently 18:00-20:00.
  - It dampens positive intraday residual carryover only when lag/recent deltas do not support a rebound.
  - It leaves 16:00-17:00 responsive and focuses on longer lead evening overhang.
- Added calibration metadata:
  - `nonBusinessEveningPositiveResidualDampingApplied`
  - `nonBusinessEveningPositiveResidualDampingFactor`
  - `nonBusinessEveningPositiveResidualDampingMaxMw`
  - per-hour support delta and damped MW fields in `residualCarryoverByHour`.

## Expected Effect

On the 2026-06-13 public calibration snapshot, applying the new rules in memory produced:

- 08:00-13:00 pre-calibration lines closer to raw LGBM instead of the strongly lowered analog line.
- Base intraday adjustment reduced from about +963 MW to about +913 MW because recent observed residuals were less inflated by the analog downshift.
- 18:00-19:00 positive carryover reduced by roughly 425 MW and 391 MW respectively.

The intent is not to follow TEPCO. TEPCO is used only as a diagnostic reference; the guards are driven by internal raw, analog, lag, recent same-business shape, and observed residual signals.

## Validation

```text
tests/test_adjustment.py + tests/test_intraday_correction.py: 92 passed
```

New unit tests cover:

- limiting a Saturday morning analog downshift when ramp support is present,
- preserving an analog downshift when weekend afternoon shape is genuinely declining,
- damping weakly supported positive residual carryover in the non-business evening.
