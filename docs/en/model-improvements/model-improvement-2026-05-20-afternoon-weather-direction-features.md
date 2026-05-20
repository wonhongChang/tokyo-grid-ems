# 2026-05-20 Afternoon Weather Direction Features

> Adds hourly temperature-direction features so the model can learn afternoon demand hysteresis instead of relying only on absolute temperature level.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-20-afternoon-weather-direction-features.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-20-afternoon-weather-direction-features.md)

---

## Why This Was Needed

On 2026-05-20, demand tracked the forecast well until around 15:00, then actual demand dropped much faster than both this model and TEPCO's published forecast.

The weather input already showed falling temperature after the afternoon peak. The issue was not that the model lacked temperature data, but that it did not have enough direct features for the direction of temperature change:

- morning warming can lift cooling demand quickly,
- afternoon cooling can reduce office cooling load faster than an absolute temperature value suggests,
- the same temperature can mean different demand depending on whether the day is warming up or cooling down.

From an operational forecasting perspective, this is a hysteresis-like error. Electricity demand does not respond only to the current temperature level; it also depends on the path taken to reach that temperature. A hot afternoon can build up cooling load, but once temperature and apparent temperature start falling near the end of business hours, office cooling and occupancy-related demand can unwind faster than a level-only temperature feature suggests.

The previous feature set already represented absolute heat/cold, relative warmth versus recent days, and 3-day thermal memory. What was missing was the short-term sign and speed of the latest weather movement. Without that, the model could treat a cooling 27C late afternoon too similarly to a warming 27C late morning.

---

## Change

Added short-horizon weather direction features to LightGBM inputs:

- `temp_delta_1h`
- `temp_delta_2h`
- `apparent_temp_delta_1h`
- `cooling_delta_1h`

Added weekday late-afternoon interaction features for 15:00-18:00:

- `business_late_afternoon_x_temp_delta_1h`
- `business_late_afternoon_x_cooling_delta_1h`

These are model features, not rule-based downward corrections. When temperature is falling, the interaction values become negative; when temperature is rising, they become positive. LightGBM can learn the relationship from historical demand rather than being forced by a fixed guard.

---

## Expected Effect

The model should better distinguish:

- hot and still-warming business mornings,
- hot but cooling late afternoons,
- late-day office demand decay when cooling load starts falling.

This is designed to work alongside the existing observed-demand drop relaxation. The feature layer helps next forecasts learn the pattern; the intraday guard still only reacts when actual demand has already started falling sharply.

---

## Notes

- No hard-coded demand reduction was added for 15:00-18:00.
- The feature values are available for both training and inference from forecast or observed hourly weather.
- Internal operation reports now include these weather-direction features for post-day review.
- The LightGBM interval version was bumped so the next ETL/intraday run retrains before using the new feature set.
