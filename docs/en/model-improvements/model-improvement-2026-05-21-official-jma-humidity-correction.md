# 2026-05-21 Official JMA Temperature and Hybrid Humidity Fallback

> Keeps official JMA as the temperature source of truth while preventing humidity-driven apparent-temperature signals from collapsing to plain air temperature.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md)

---

## Why This Was Needed

Recent intraday forecasts showed a repeated morning problem: the model sometimes saw a day as cooler than it felt operationally. The official JMA forecast feed provides the temperature curve, but the current Tokyo time-series endpoint does not publish hourly forecast humidity.

That means future rows could have:

- `temp_c` from official JMA
- `apparent_temp_c` equal to `temp_c`
- `humidity_pct = NaN`
- `discomfort_index = NaN`

For demand forecasting this is risky. A humid 22 C morning can drive more cooling demand than a dry 22 C morning, but the model cannot see that difference if humidity is missing.

---

## Change

The operational weather hierarchy is now:

1. **Observed/current and past hours**
   - Use JMA AMeDAS observations for temperature, humidity, discomfort index, and humidity-aware apparent temperature.

2. **Future temperature**
   - Keep official JMA time-series forecast as the only temperature source.

3. **Near-term future humidity**
   - If official JMA humidity is missing, fill the next 1-3 hours from the latest valid AMeDAS observed humidity.

4. **Later future humidity**
   - Use Open-Meteo JMA only as a humidity fallback.
   - It does not replace official JMA `temp_c`.
   - `apparent_temp_c` and `discomfort_index` are recomputed from the official temperature plus the fallback humidity.

5. **Final fallback**
   - If all live humidity sources fail, use a conservative monthly seasonal humidity mean.

The cache now also keeps `weather_source` so an operational miss can be traced back to sources such as:

- `AMEDAS_ACTUAL`
- `JMA_FORECAST+FORWARD_FILL`
- `JMA_FORECAST+OPEN_METEO_JMA`
- `JMA_FORECAST+SEASONAL_MEAN`

---

## Expected Effect

The model keeps the more trusted official JMA temperature curve while regaining humidity-sensitive apparent-temperature input for same-day operation.

This should help humid mornings and evenings where raw temperature looks ordinary but perceived heat is higher. It also avoids the earlier risk of replacing official JMA temperatures with a different provider's temperature forecast.

---

## Operational Notes

- Open-Meteo JMA is now a humidity-only fallback for future forecast rows.
- Legacy historical rows are not force-backfilled just because `humidity_pct` is missing; otherwise ETL could try to refill years of cache in one run.
- Existing historical apparent-temperature data remains usable for model training.
- `weather_source` is trace metadata. It is not added to LightGBM feature columns.

---

## Tests

Added and updated tests cover:

- Official JMA forecast temperatures are preserved even when Open-Meteo JMA humidity is used.
- AMeDAS humidity forward fill is preferred for the short near-term horizon.
- Seasonal humidity is used only as the final fallback.
- Legacy cache rows with only humidity gaps do not trigger a large historical archive refill.
- Full regression suite: `306 passed`.
