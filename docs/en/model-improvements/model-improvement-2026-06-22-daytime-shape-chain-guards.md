# 2026-06-22 daytime shape-chain guards

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-22-daytime-shape-chain-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-22-daytime-shape-chain-guards.md)

## Context

The 2026-06-22 live forecast failed through a chain rather than a single bad hour:

- 09:00-11:00 JST was under-forecast. The business-return excess cap trimmed the analogous-day line by roughly 700-900 MW even though recent same-business shape supported a strong Monday ramp.
- 12:00 JST was corrected by the midday guard, but the positive intraday residual created by the morning under-forecast was still carried into 13:00-14:00.
- 13:00-15:00 became over-forecast. The analogous-day adjustment lifted the raw LightGBM line by 700-1,100 MW while the afternoon shape support was weak or already declining.

TEPCO values were used only as an external reference while diagnosing the miss. They are not blended into the model and are not used as calibration input.

## Changes

### Business-return excess cap softening

`PostHolidayTimeBandGuard.business_return_anchor_excess_cap` now checks whether the target hour has strong ramp support from:

- `lag_24h_hourly_delta`
- `recent_same_business_type_delta_mean`

For 09:00-11:00 on business-return days, strong shape support adds a bounded allowance and lowers the cap shrinkage. This keeps the guard from erasing a legitimate Monday morning ramp.

### Business afternoon analog excess cap

`PostHolidayTimeBandGuard` now has `business_afternoon_analog_excess_cap`.

It caps only positive analogous-day uplift when all of these are true:

- the target is a business day afternoon slot,
- the analogous-day shift is materially positive,
- lag/recent same-business deltas do not strongly support the uplift,
- weather/cooling context is present, so ordinary benign analog shifts are not touched.

This is designed to reduce unsupported afternoon plateaus without suppressing real hot-day demand.

### Post-lunch decline continuity guard

`IntradayResidualCorrector` now has `post_lunch_decline_continuity_guard`.

When a business-day 11:00 -> 12:00 actual drop is already observed, the guard caps only the nearest 13:00-14:00 future slots if the line still jumps above the observed level and target-hour support is weak. This prevents morning positive residuals from undoing the lunch dip and pushing the early afternoon line upward.

### Daytime sustained under-forecast lift shape gate

`daytime_sustained_underforecast_lift` now has a `post_midday_shape_gate`.

For 12:00-14:00 business-day slots, the lift requires both lag and recent same-business deltas to support the recovery. This blocks a morning under-forecast residual from lifting post-lunch hours when the shape context still indicates a dip or weak recovery.

## Validation

Added regression tests for:

- shape-supported Monday morning ramp softening,
- unsupported afternoon analogous-day uplift cap,
- post-midday shape gate blocking `daytime_sustained_underforecast_lift`,
- post-lunch decline continuity cap for 13:00-14:00.

Full local test suite:

```text
413 passed
```

## Operational Notes

This change is intentionally conservative. It does not try to follow TEPCO and it does not rewrite already-published past forecast slots. It improves the next run's pre-calibration and near-term residual handling so the same morning-underforecast-to-afternoon-overforecast chain is less likely to repeat.
