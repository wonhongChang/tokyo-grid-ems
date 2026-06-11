# 2026-06-11 Humidity/Discomfort Features and Localized Shape Spike Guard

## Problem

Two independent shape issues showed up in recent serving data:

- On 2026-06-10, the 15:00 slot formed a one-hour local peak even though nearby hours, lag slope, recent same-business-type shape, and weather direction did not support a standalone spike.
- On 2026-06-11, warm and humid business-day daytime demand was underrepresented. The model had apparent-temperature and cooling-degree features, but it did not expose direct humidity/discomfort deltas or business-hour humidity interactions to LightGBM.

## Changes

- Expanded the LightGBM feature set from 56 to 63 features.
- Added direct humidity/discomfort inputs:
  - `humidity_pct`
  - `discomfort_index`
  - `humidity_delta_24h`
  - `discomfort_delta_24h`
  - `business_morning_x_humidity_delta_24h`
  - `business_morning_x_discomfort_delta_24h`
  - `business_daytime_x_discomfort_index`
- Added conservative filling for legacy weather rows so old cache data without humidity fields does not remove training rows.
- Bumped the LightGBM interval/model compatibility version to `q025_q50_q975_p95_v10_humidity_discomfort`, forcing retraining instead of reusing an incompatible older model file.
- Added `LocalizedShapeSpikeGuard` after the midday guard and before intraday calibration. It only damps unsupported one-hour afternoon peaks when neighboring hours are lower and lag/recent/weather context does not justify the local spike.
- Added humidity/discomfort fields to operational calibration snapshots and to the AI report feature catalog so reports can point to the correct feature family.

## Guard Scope

The localized shape guard is intentionally narrow:

- business days only,
- 13:00-17:00 target hours by default,
- requires a clear one-hour excess over both neighboring hours,
- skips when lag shape, recent same-business-type shape, same-day actual slope, or weather deltas support a real peak,
- applies shrinkage and maximum reduction caps.

The goal is to remove isolated post-processing artifacts, not to flatten legitimate hot-day peaks.

## Validation

```text
389 passed
```

Additional unit coverage verifies that:

- an unsupported 15:00 one-hour peak is damped,
- a weather-supported peak is preserved.

## Operational Notes

This change is a feature-side improvement first and a guard-side safety net second. The humidity/discomfort features should help the raw model learn warm-humid daytime demand more directly, while the localized guard protects against rare analog/post-processing shape artifacts.
