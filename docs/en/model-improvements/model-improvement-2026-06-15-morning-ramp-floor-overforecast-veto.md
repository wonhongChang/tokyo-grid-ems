# 2026-06-15 Morning Ramp Floor Over-Forecast Veto

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md)

## Problem

The 2026-06-15 05:00-12:00 serving chart showed that the morning forecast issue was not a single raw-model miss.

- 05:00 was mainly a stale early-serving/freeze issue. Later recalculation with updated inputs was much closer, but the public line had already been frozen.
- 08:00-10:00 were high while the day was much cooler than the previous day. At 09:32 JST, `morning_observed_ramp_floor` saw a strong 06:00-08:00 actual ramp and lifted 10:00 by roughly +1,150 MW.
- That 10:00 lift then created an over-forecasted observed bucket, and the following intraday run propagated a negative residual into 11:00, making 11:00 too low.

In short, the floor guard was looking at observed ramp strength, but it did not check whether the latest observed bucket was already materially over-forecast.

## Change

Added `max_latest_overforecast_mw` to `morning_observed_ramp_floor`.

- Default: `500 MW`.
- If the latest observed hour is already over-forecast by at least this threshold, the floor guard does not lift the near-future ramp.
- The existing strong-ramp behavior is preserved when the latest observed bucket is not already too high.

This is a veto on an auxiliary lift, not a new cap on the raw model. It avoids injecting extra upward pressure when the most recent evidence says the model is already high.

## Expected Effect

For the 2026-06-15 pattern:

- The 10:00 forecast would not receive the extra ramp-floor lift once 08:00 was already over-forecast by about 1,000 MW.
- The next intraday run would be less likely to generate an artificial negative residual from that lifted 10:00 bucket.
- 11:00 should be less exposed to a controller-induced downward swing.

The 05:00 stale-input/freeze issue and raw 08:00 model height remain separate topics.

## Validation

```text
tests/test_intraday_correction.py::test_intraday_correction_lifts_near_future_when_observed_morning_ramp_is_strong
tests/test_intraday_correction.py::test_intraday_correction_skips_morning_ramp_floor_when_latest_observed_bucket_is_already_high

Full suite: 396 passed
```
