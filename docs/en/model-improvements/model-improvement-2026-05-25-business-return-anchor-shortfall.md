# 2026-05-25 Business-Return Anchor Shortfall Guard
> Conservative support for business-day morning recovery when the previous non-business-day lag pulls the forecast too low.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md)

---

## Why

The 2026-05-25 Monday morning forecast showed a structural underprediction around 09:00. The model received the business-day transition features, but the 24-hour lag came from Sunday and was far below the recent business-day anchor for the same hour.

For 09:00, the live diagnostic context showed:

- `lag_24h`: 22,830 MW
- `recent_same_business_type_mean`: 31,795 MW
- model forecast: 29,570 MW

The model partially recovered from the Sunday lag, but not enough for a warm business-day return.

## Change

Added `business_return_anchor_shortfall` inside `PostHolidayTimeBandGuard`.

The guard activates only when:

- the target day is a business day,
- `lag_24h_business_type_mismatch > 0`,
- `recent_same_business_type_mean - lag_24h` exceeds the configured threshold,
- the current adjusted forecast is below `recent_same_business_type_mean - allowance_mw`.

When those conditions hold, the guard lifts only part of the shortfall:

```text
shortfall = recent_same_business_type_mean - allowance_mw - forecast
adjustment = min(shortfall * shrinkage_by_hour, max_clipping_mw)
```

This does not force the forecast up to the anchor. It provides a bounded correction when a non-business-day lag suppresses the business-day recovery curve too much.

## Defaults

- `target_hours`: 06:00-11:00
- `gap_threshold_mw`: 6,000
- `allowance_mw`: 1,000
- `max_clipping_mw`: 1,000
- `shrinkage_map`: 0.25 at 06:00, 0.35 at 07:00, 0.45 at 08:00, 0.50 at 09:00, 0.30 at 10:00, 0.20 at 11:00

## Test Coverage

Added unit tests for:

- the 2026-05-25 09:00 arithmetic case, where a 1,225 MW shortfall receives a 612.5 MW lift,
- ordinary business-day sequences where `lag_24h_business_type_mismatch == 0`,
- `enabled: false`, confirming that other warm-day guards still work independently.
