# 2026-06-12 Morning Observed Ramp Floor and Band Tail Tightening

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md)

## Problem

Two issues appeared in the 2026-06-11 and 2026-06-12 serving data:

- 2026-06-11 09:00-15:00 looked poor on the published chart, but the latest operational recalculation was already much closer to actual demand. This was mainly a published forecast freeze artifact.
- 2026-06-12 09:00-13:00 remained too low even after recalculation. Same-day actual demand had already shown a strong morning ramp, but the intraday correction layer could only reduce negative residual carryover and could not support a near-future forecast that was below the observed ramp trajectory.
- The forecast bands became visually one-sided. Several hours had a minimum-width side near 500 MW and the other side capped around 4,000 MW, making p95/p99 look too distorted for operation review.

## Changes

- Added `morning_observed_ramp_floor` to `IntradayResidualCorrector`.
- The floor only activates when recent same-day actual demand shows two consecutive strong positive hourly slopes during the business morning reference window.
- It applies only to near-term future hours and uses caps:
  - target hours: 08:00-11:00 by default,
  - max lead: 2 hours,
  - max lift: 1,200 MW,
  - minimum lift: 100 MW.
- Added operational metadata:
  - `morningObservedRampFloorApplied`
  - `morningObservedRampFloorMaxLiftMw`
  - `morningObservedRampFloorLiftMw`
  - `morningObservedRampFloorMw`
  - `morningObservedRampLatestSlopeMw`
- Tightened interval sanity calibration:
  - `max_p95_half_width_mw`: 4,500 -> 3,000
  - `max_p95_asymmetry_ratio`: 4.0 -> 2.5
  - `asymmetry_reference_half_width_mw`: 1,000 -> 900

## Scope

This is not a TEPCO-following layer and not a fixed hourly lift. It only reacts when same-day actual demand has already proven a strong morning ramp and the next one or two forecast buckets are still below a conservative continuation floor.

The band tightening does not move q50. It only limits rare one-sided quantile tail explosions so the dashboard band remains interpretable.

## Validation

```text
tests/test_intraday_correction.py: 46 passed
tests/test_lgbm_model.py + tests/test_run_batch.py: 72 passed
targeted smoke checks: 3 passed
```

Additional unit coverage verifies that a strong observed 06:00-08:00 ramp can lift only the near-term 09:00-10:00 forecast buckets, with max-lift metadata recorded.

## Operational Notes

The 2026-06-12 14:00-15:00 spike was partly a freeze issue, but the 09:00-13:00 miss exposed a real raw/recalculated underprediction. This change addresses only the near-term evidence gap; it does not replace the longer-term need to backtest morning humidity, discomfort, and lag-overheat interactions.
