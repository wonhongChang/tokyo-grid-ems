# 2026-05-21 Business-Day Midday Shock Guard

> Keeps the 12:00 lunch bucket as a local transition problem and prevents a one-hour miss from contaminating the afternoon intraday correction.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-21-midday-shock-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-21-midday-shock-guard.md)

---

## Why This Was Needed

The 12:00 chart point represents the 12:00-13:00 demand bucket. On 2026-05-21, actual demand dropped sharply from the 11:00 bucket into the 12:00 bucket, then partially recovered at 13:00.

That is not the same as a linear afternoon downtrend. If the intraday residual corrector treats the lunch dip as normal momentum, it can push 13:00-15:00 too low. The operational model should treat this as a localized business-day lunch transition unless later actuals confirm a broader decline.

---

## Change

The pipeline now keeps TEPCO forecast out of the model and out of the guard logic. The new signals are based only on observed demand history and same-day observed demand:

- `recent_same_business_type_delta_q25`: lower quartile of recent same-business-type hourly deltas for the target hour.
- `same_day_latest_actual_hour`: latest observed hour available before the target bucket.
- `same_day_latest_hourly_delta`: latest observed same-day hour-to-hour change.
- `same_day_recent_hourly_delta_mean`: recent same-day change over the latest observed hours.

`MiddayTransitionGuard` now strengthens the 12:00 downward correction only when:

- the target day is a business day,
- recent business-day 12:00 transitions show a real negative shape,
- same-day morning demand is already softening,
- the current forecast is still meaningfully above that transition context.

Separately, `IntradayResidualCorrector` now de-weights large business-day 12:00 residuals when computing the future same-day residual correction. This keeps a one-bucket lunch miss from pulling the afternoon line down.

---

## Expected Effect

The model should handle three cases more cleanly:

- a normal warm business day with a high demand level,
- a lunch-hour dip that should mainly affect 12:00-13:00,
- an actual afternoon decline confirmed by later observed hours.

This keeps the model independent from TEPCO forecasts while making the lunch transition safer in operation.
