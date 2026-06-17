# 2026-06-18 Early Observed Residual Carryover

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-18-early-observed-residual-carryover.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-18-early-observed-residual-carryover.md)

## Problem

The 2026-06-18 00:00-01:00 JST serving data showed a large overnight under-forecast.

- 00:00 actual was 24,240 MW while the model served 23,233.7 MW.
- 01:00 actual was 22,950 MW while the model served 22,050.3 MW.
- The 02:26 JST calibration run already had two real observed buckets, but `min_observed_hours=3` prevented the standard intraday residual loop from using them.
- Because the standard loop was still waiting, the pipeline kept using the previous day's day-boundary residual carryover of about `-120 MW`, which pushed future hours lower even though the same-day evidence was strongly positive.

This was not a TEPCO-following issue. It was a low-observation handoff gap: the system had enough evidence to know the direction of the miss, but the normal residual loop had not yet started.

## Change

Added `early_observed_residual_carryover`.

- It runs only while same-day observed points are still below the normal `min_observed_hours`.
- Default trigger requires at least two observed buckets.
- The early residuals must have the same sign.
- The mean residual must exceed `500 MW` in absolute value.
- The applied adjustment is shrunk by `0.5` and capped at `700 MW`.
- When it applies, it takes priority over stale previous-day day-boundary carryover.

For the 2026-06-18 pattern, the two early residuals imply a conservative future lift of about `+416 MW` instead of continuing the stale `-120 MW` carryover.

## Expected Effect

When 00:00-01:00 are both clearly under-forecast or over-forecast, the next near-term hours can move in the observed direction before the third actual bucket arrives. One noisy single bucket is still ignored.

This does not rewrite already closed hours. It improves the forecast from the first still-open future bucket onward.

## Validation

```text
tests/test_intraday_correction.py::test_intraday_correction_prefers_early_same_day_residuals_over_stale_midnight_carryover

Full suite: 399 passed
```
