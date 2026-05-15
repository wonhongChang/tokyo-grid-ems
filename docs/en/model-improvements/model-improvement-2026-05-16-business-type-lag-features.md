# 2026-05-16 Business-Type Lag Features

> Feature-side improvement for weekend/weekday transitions where `lag_24h` can point to a different demand regime.

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-05-16-business-type-lag-features.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-16-business-type-lag-features.md)

---

## Why This Was Needed

The model already knows the target day of week and whether the target date is a weekend or holiday. However, `lag_24h` can still be misleading when it crosses a business/non-business boundary.

Examples:

- Saturday daytime uses Friday daytime as `lag_24h`.
- Monday daytime uses Sunday daytime as `lag_24h`.

Those hours often differ because office, commercial, and industrial demand change sharply between business days and non-business days. If the model sees only a high or low `lag_24h`, it may over-trust yesterday's value.

## Forecasting Change

The LightGBM feature set now includes:

- `lag_24h_business_type_mismatch`: whether the target date and previous date differ in business/non-business type
- `lag_24h_mismatch_x_business_hour`: the same mismatch, focused on 08:00-18:00
- `recent_same_business_type_mean`: recent same-hour mean for the target's business/non-business type

This lets the model learn that Friday-to-Saturday and Sunday-to-Monday lag values should be interpreted differently from normal weekday-to-weekday or weekend-to-weekend lags.

## Design Boundary

This does not manually reduce Saturday forecasts. It only adds context so LightGBM can decide how much to trust `lag_24h` based on historical outcomes.

`lag_168h` remains unchanged because it usually compares the same weekday and is often a more natural weekend anchor.

## Operational Note

Because the feature columns changed from 34 to 37, the LightGBM model compatibility version was bumped. Existing saved models are treated as stale and retrained by the next ETL or intraday run.
