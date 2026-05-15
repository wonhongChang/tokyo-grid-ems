# 2026-05-15 24h Weather Delta and Apparent Temperature Features

> Feature-side improvement for days when yesterday's demand lag is strong, but today's weather curve is materially different.

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md)

---

## Why This Was Needed

Recent operational forecasts showed that `lag_24h` can be useful and risky at the same time.

When yesterday's same-hour demand was high, the model should usually pay attention to it. But if today's temperature path is cooler, warmer, or peaks at a different hour, yesterday's demand can become a misleading anchor. The previous improvement added a 168h weather-regime signal, but it did not explicitly explain the day-over-day weather shift that affects `lag_24h`.

The 2026-05-15 forecast made this gap visible: the model had access to yesterday's TEPCO actuals, but it still needed a clearer signal for "today is not yesterday weather-wise."

## Forecasting Change

The LightGBM feature set now includes:

- `temp_delta_24h`: current same-hour temperature minus previous-day same-hour temperature
- `cooling_delta_24h`: current same-hour cooling degree minus previous-day same-hour cooling degree
- `apparent_temp_c`: Open-Meteo apparent temperature
- `apparent_cooling_degree`: cooling degree computed from apparent temperature

The existing 168h weather-regime features remain:

- `temp_delta_168h`
- `cooling_delta_168h`

Together, these features let the model compare the target hour against both yesterday and last week. This is especially useful during season transitions, warm afternoons after cooler mornings, and days where the peak temperature arrives earlier or later than the previous day.

## Expected Effect

`temp_delta_24h` and `cooling_delta_24h` should help the model learn when `lag_24h` is reliable and when it should be softened.

`apparent_temp_c` and `apparent_cooling_degree` add a second weather signal for cooling demand. They are not a replacement for temperature, but they may help on days where air temperature alone under-describes perceived heat.

## Design Boundary

This does not use TEPCO forecast values as model inputs. TEPCO forecast fallback is still only used for operational 23:00 actual-gap handling before the confirmed CSV arrives.

No hour-specific 09:00-15:00 rule was added in this change. The improvement stays general-purpose so it can learn from more than one recent incident.

## Operational Note

Because the feature columns changed from 30 to 34, the LightGBM model compatibility version was bumped. Existing saved models are treated as stale and retrained by the next ETL or intraday run.
