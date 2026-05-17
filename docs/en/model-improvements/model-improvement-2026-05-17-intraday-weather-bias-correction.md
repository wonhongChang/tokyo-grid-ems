# 2026-05-17 Intraday Weather Bias Correction and Forecast Freezing

> Operational improvement for same-day forecasts when forecast weather is materially colder or warmer than observed conditions.

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-05-17-intraday-weather-bias-correction.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-17-intraday-weather-bias-correction.md)

---

## Why This Was Needed

On 2026-05-17, the Open-Meteo forecast temperature for Tokyo's evening hours stayed much lower than the later observed/archive temperature.

Example for 20:00 JST:

| Value | Temperature |
|---|---:|
| Forecast weather input around daytime/evening runs | about 20-21°C |
| Archive/observed weather after the fact | about 23-24°C |

The demand model therefore received a weather input that implied evening cooling demand would drop faster than it actually did. TEPCO's intraday demand forecast also started low, but it was gradually revised upward as the evening approached.

This showed two operational needs:

1. Near-term same-day forecast weather should be adjusted when recent observed weather has a consistent bias against the forecast.
2. Once an hour has an observed demand value, the model forecast that was already shown for that hour should not be silently recalculated.

---

## Forecasting Change

`run_batch.py` now applies a weather forecast bias correction after forecast weather rows are refreshed and before model inference.

The correction is general, not evening-only and not heat-only:

- If recent observed weather is warmer than forecast, near-term future weather is nudged upward.
- If recent observed weather is colder than forecast, near-term future weather is nudged downward.
- The correction applies only to same-day future hours and fades with forecast horizon.

Default configuration:

```yaml
weather_forecast_bias_correction:
  enabled: true
  lookback_hours: 4
  observation_lag_hours: 1
  horizon_hours: 4
  min_abs_bias_c: 0.8
  max_abs_bias_c: 2.5
  decay_per_hour: 0.75
```

The model target is not modified. Only `temp_c` and `apparent_temp_c` inputs for near-term future hours are adjusted.

---

## Observed-Hour Forecast Freeze

Intraday runs rebuild the whole current-day forecast JSON. Before this change, a past hour could be recalculated after its actual demand became available. That made the chart look as if the model forecast had changed after the fact.

The new behavior is:

- Hours with real `actualSource: observed` demand keep the already-published model forecast.
- Future hours continue to update with the latest weather, residual correction, and model inference.
- The 23:00 TEPCO forecast fallback is not treated as observed demand and is not frozen.

This makes model evaluation more honest because MAE is computed against the forecast that was actually visible operationally.

---

## Design Boundary

This is not a TEPCO forecast snapshot system yet.

TEPCO's CSV forecast values can change during the day. For strict same-timestamp comparison, TEPCO forecast snapshots should eventually be archived separately. For now, this change focuses on preserving the model's own operational forecast history and improving weather input quality.

---

## Expected Impact

This should help on days where:

- Forecast weather cools down too quickly but observed conditions stay warm.
- Forecast weather stays too warm but observed conditions cool down faster.
- Same-day demand is sensitive to near-term HVAC conditions.

The cap and decay are intentionally conservative to avoid over-correcting a noisy weather observation.

---

## Tests

Added tests cover:

- Positive same-day weather bias correction in a morning scenario.
- Negative same-day weather bias correction for cold-biased forecasts.
- Preserving already-published forecasts for observed demand hours.
- Not freezing TEPCO fallback demand as if it were observed.
