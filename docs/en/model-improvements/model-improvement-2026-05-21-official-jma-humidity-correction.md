# 2026-05-21 Official JMA Forecast and Humidity-Aware Correction

> Removes Open-Meteo JMA as an operational forecast fallback and uses official JMA AMeDAS humidity observations for near-term apparent-temperature correction.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md)

---

## Why This Was Needed

Recent intraday forecasts showed cases where the model interpreted the day as cooler than it felt operationally. The official JMA forecast feed provides temperature guidance, but not hourly humidity. Open-Meteo JMA can provide apparent temperature and humidity-like signals, but its Tokyo hourly forecast sometimes diverged from the official JMA view enough to weaken trust in it as an operational fallback.

For an operational forecast model, source consistency matters more than filling every derived field. If the future temperature curve comes from one provider while apparent temperature comes from another, the model can receive mixed signals.

---

## Change

Future forecast weather now uses the official JMA Tokyo time-series endpoint only:

```text
https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/130010.json
```

Open-Meteo JMA is no longer called from `fetch_forecast_temps()`. If the official JMA forecast is unavailable, the weather fetch fails visibly instead of silently switching to a less trusted forecast source.

Recent observed weather still uses official JMA AMeDAS Tokyo station data. The parser now keeps:

- `humidity_pct`
- `discomfort_index`
- humid apparent temperature estimated from official observed temperature, humidity, and wind

Because official JMA forecast does not provide hourly humidity, humidity is not added as a direct LightGBM feature yet. Instead, the intraday weather bias correction can adjust near-term `apparent_temp_c` when observed humidity makes the latest official observations feel warmer or cooler than the forecast input.

---

## Expected Effect

The model should avoid mixing Open-Meteo JMA apparent-temperature signals into an official-JMA forecast curve.

On humid mornings, recent AMeDAS observations can still raise near-term apparent temperature without changing the official forecast temperature itself. This is intentionally limited to short same-day horizons so it helps intraday operation without inventing tomorrow's humidity.

---

## Operational Notes

- Historical backfill for old missing cache rows may still use Open-Meteo archive data.
- Operational future forecast input does not use Open-Meteo JMA fallback.
- Official JMA forecast rows have `humidity_pct = NaN` and `discomfort_index = NaN` until observed AMeDAS data exists.
- This change updates source trust and weather correction behavior, not TEPCO demand data or reserve-risk thresholds.

---

## Tests

Added tests cover:

- Open-Meteo JMA forecast fallback is not called by `fetch_forecast_temps()`.
- Official JMA forecast failure is surfaced as an error.
- AMeDAS humidity and discomfort index are parsed.
- Intraday weather bias correction can adjust apparent temperature even when raw temperature bias is below threshold.
