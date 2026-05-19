# 2026-05-20 Relative Weather and Thermal Memory Features

> Adds morning-ramp weather interactions and 3-day thermal memory features without using fixed temperature correction rules.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-20-relative-morning-weather-features.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-20-relative-morning-weather-features.md)

---

## Why This Was Needed

The 2026-05-20 morning forecast stayed very close to the previous day's observed demand even though the operational expectation was for stronger morning demand under warmer conditions.

The model already had temperature features, including cooling/heating degree values, but morning demand was still heavily anchored by:

- `recent_same_business_type_mean`
- `lag_24h`
- same-hour historical patterns

This made the forecast slow to react when the morning looked warmer relative to recent references.

---

## Change

Reviewed the weather feature set and kept degree-day style CDD/HDD features as model inputs:

- `cooling_degree = max(0, temp_c - cooling_base_temp_c)`
- `heating_degree = max(0, heating_base_temp_c - temp_c)`

These are not rule-based corrections. They are configurable feature transformations that let LightGBM learn the nonlinear demand response around the comfort zone.

The heating balance point was changed from 10.0C to 18.0C so winter heating demand is visible before very cold conditions.

Added three LightGBM features for business-day morning ramp hours, currently 05:00-11:00:

- `business_morning_x_temp_delta_24h`
- `business_morning_x_temp_anomaly_7d`
- `business_morning_x_temp_anomaly_doy`

These features use relative temperature signals:

- warmer or cooler than yesterday at the same hour,
- warmer or cooler than the recent 7-day average,
- warmer or cooler than the historical same-month/same-hour reference.

No absolute "if temperature is above N degrees" rule is used.

Added three 72-hour thermal memory features:

- `temp_72h_mean`
- `cooling_degree_72h_mean`
- `heating_degree_72h_mean`

These represent building and city-scale thermal inertia during sustained heat or cold.

---

## Expected Effect

The model can learn that weekday morning load may move differently when temperature is already elevated relative to yesterday or the recent baseline.

This should help reduce cases where the morning forecast simply follows `lag_24h` even when the weather regime has shifted.

The 72-hour features should also help avoid overreacting to a single hourly temperature point while still recognizing sustained hot or cold periods.

---

## Notes

- Existing degree-style features remain as generic model inputs, with configurable base temperatures.
- Humidity-specific heat-index features were not added because the current official JMA forecast feed used in production does not provide hourly humidity. `apparent_temp_c` remains available when the source provides it, and falls back to `temp_c` otherwise.
- The operational guard no longer keeps an optional absolute warm-day temperature floor.
- The LightGBM interval version was bumped so the next ETL/intraday run retrains with the new feature set.
