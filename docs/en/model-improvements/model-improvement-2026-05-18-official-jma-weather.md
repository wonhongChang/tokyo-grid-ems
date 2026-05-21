# 2026-05-18 Official JMA Weather Forecast Input

> Weather-source improvement for hot days where Open-Meteo JMA hourly temperatures understate the official JMA Tokyo forecast.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-18-official-jma-weather.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-18-official-jma-weather.md)

---

## Why This Was Needed

On 2026-05-18, the Open-Meteo JMA hourly forecast for Tokyo peaked around 26.7°C, while the official Japan Meteorological Agency Tokyo forecast showed 16°C / 29°C.

That difference matters for this project because electricity demand during warm business days is strongly affected by cooling demand. If the weather input is too cool, the demand model can underestimate the morning ramp and daytime plateau.

---

## Forecasting Change

The forecast weather pipeline now prefers the official JMA Tokyo three-hourly time-series forecast:

```text
https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/130010.json
```

The official JMA data provides:

- Three-hourly Tokyo temperature forecasts.
- Official daily minimum and maximum temperature guidance.
- JMA report timestamp.

Because the demand model needs hourly features, the three-hourly temperatures are interpolated to hourly values. Daily minimum and maximum constraints are then applied so the hourly curve preserves the official JMA min/max guidance.

---

## Current Source Policy

This document records the first step of moving the forecast input toward official JMA data. As of the 2026-05-21 follow-up, Open-Meteo JMA is no longer used as an operational forecast fallback.

- Future forecast weather comes from official JMA time-series data only.
- If official JMA forecast data is unavailable, the weather fetch fails visibly instead of switching to Open-Meteo JMA.
- Apparent temperature for future forecast rows falls back to official `temp_c` because the official JMA forecast feed does not provide hourly humidity.
- Recent AMeDAS observations can still adjust near-term apparent temperature during intraday runs.

---

## Expected Impact

This should improve same-day forecasts when:

- Official JMA expects a hotter Tokyo day than Open-Meteo's hourly grid output.
- Cooling demand is likely to rise during business hours.
- The model previously dropped the afternoon forecast too quickly because the weather input cooled too early.

The change affects weather features only. Actual demand, TEPCO demand forecasts, and anomaly thresholds are not modified.

---

## Tests

Added tests cover:

- Parsing official JMA three-hourly temperature data.
- Interpolating official JMA data to 24 hourly rows.
- Preserving official daily minimum and maximum temperatures.
- The 2026-05-21 follow-up covers removal of Open-Meteo JMA forecast fallback.
