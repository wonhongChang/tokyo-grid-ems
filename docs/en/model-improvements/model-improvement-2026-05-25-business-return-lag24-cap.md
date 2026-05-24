# 2026-05-25 Business-Day Return Lag24 Cap Fix
> Prevent warm-day post-processing from capping Monday business demand against Sunday's lower `lag_24h`.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md)

---

## Why

The 2026-05-25 Monday forecast exposed a post-processing failure mode. Raw LightGBM still produced a business-day daytime peak, but the `post_holiday_timeband_guard` stage suppressed the public curve after the warm-day cap ran.

The problem was the cap reference. `lag24_warm_day_cap` limits warm-day forecasts to `lag_24h + configured allowance`. That is reasonable when the previous day is comparable, but Monday's `lag_24h` comes from Sunday. Using Sunday demand as the cap anchor incorrectly pushed the business-day recovery curve down.

## Change

`PostHolidayTimeBandGuard` now skips the `lag24_warm_day_cap` when `lag_24h_business_type_mismatch > 0`.

This keeps the cap for comparable days, such as business-day to business-day transitions, while avoiding a Sunday-to-Monday or holiday-to-business-day cap based on the wrong operating regime.

## Operating Behavior

This does not force a Monday uplift and does not follow TEPCO forecasts. It only removes an invalid cap when the 24-hour lag comes from a different business/non-business type. The model, analogous-day adjustment, weather features, and intraday residual correction remain responsible for the actual forecast level.

## Test Coverage

Added a focused unit test for a warm Monday after a non-business day. The test verifies that the warm-day lag24 cap still works on comparable days, but does not cap a business-day recovery against Sunday's lower `lag_24h`.
