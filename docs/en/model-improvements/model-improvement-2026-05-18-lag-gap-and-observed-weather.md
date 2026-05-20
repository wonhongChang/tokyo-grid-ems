# 2026-05-18 Lag-Gap Features and Observed Weather Correction

> A conservative follow-up after the 2026-05-18 forecast failure, focused on business-day transitions and recent weather forecast bias.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-18-lag-gap-and-observed-weather.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-18-lag-gap-and-observed-weather.md)

---

## Why This Was Needed

On 2026-05-18, the model missed a large part of the 06:00-18:00 demand shape.

The failure was not just a hot-day issue. Two safer signals were missing or underused:

- The previous-day 24h lag came from a different business type. For a Monday after a low-demand Sunday, `lag_24h` can pull the forecast down too much.
- Recent forecast temperatures can be colder or warmer than the actual JMA observation. If that gap is visible during the day, near-term future weather input should be nudged before the demand forecast is rebuilt.

---

## Forecasting Change

The LightGBM feature set now includes lag-gap features:

- `lag_24h_to_last_biz_gap`
- `lag_24h_to_same_business_type_gap`
- `lag_24h_gap_x_business_hour`

These features do not hard-code summer demand. They expose whether the 24h lag is abnormally low or high compared with recent demand for the same business-day type.

The weather bias correction also now prefers recent JMA AMeDAS Tokyo observations before falling back to Open-Meteo archive data. This allows the intraday model input to react when the latest official observations show that the forecast curve has been too cold or too warm.

---

## Operational Change

Manual GitHub Actions runs preserve today's already-observed forecast hours. This keeps the chart as an operational forecast history instead of rewriting past forecast values after actuals arrive.

Scheduled runs keep the normal forecast-preservation behavior. The manual option is intended for cases where a model or weather-source fix was deployed during the same operating day and the currently published line should be regenerated with the corrected pipeline.

---

## Safety Notes

- TEPCO forecast values are not used as model features.
- The new lag-gap features are season-neutral.
- Weather bias correction is capped and decays over the next few hours.
- Published past-hour forecast preservation remains the default for scheduled operation.

---

## Tests

Added and updated tests cover:

- Business/non-business 24h lag-gap features.
- JMA AMeDAS observed temperature parsing.
- Manual bypass of observed-hour forecast preservation.
- Continued default preservation behavior for scheduled runs.
