# Weather Data Integration Design

> Production feature: adding Open-Meteo temperature and apparent-temperature features to the LightGBM model
> Open-Meteo API (free, no auth required) — Tokyo coordinates

Languages: [한국어](../ko/weather-integration.md) · [日本語](../ja/weather-integration.md)

---

## Why Temperature

Temperature explains 30–40% of electricity demand variation. Apparent temperature adds a "feels-like" signal that can better reflect cooling demand on humid or windy days.

| Season | Mechanism | Demand Impact |
|---|---|---|
| Summer (Jul–Sep) | Temp ↑ → AC load ↑ | Strong positive correlation |
| Winter (Dec–Feb) | Temp ↓ → Heating load ↑ | Strong negative correlation |
| Spring/Autumn | Temp 15–20°C comfort zone | Demand minimum |

The original motivation was to improve over calendar + lag features only. In production, temperature is also used to explain HVAC-driven demand and to stabilize forecasts around hot or cold days.

---

## Data Source: Open-Meteo

```
API: https://api.open-meteo.com/v1/forecast
Tokyo coordinates: latitude=35.6762, longitude=139.6503
Timezone: Asia/Tokyo
```

### Two Free Endpoints

| Purpose | Endpoint Parameter | Content |
|---|---|---|
| Historical | `&past_days=92` | Hourly historical temperatures for past 92 days |
| Forecast | `&forecast_days=2` | Hourly forecast temperatures for today + tomorrow |

### Response Example

```json
{
  "hourly": {
    "time": ["2026-05-05T00:00", "2026-05-05T01:00", ...],
    "temperature_2m": [18.3, 17.9, 17.5, ...],
    "apparent_temperature": [18.1, 17.6, 17.0, ...]
  }
}
```

No API key required. Commercial use allowed (CC BY 4.0).

---

## Weather Fetch Module: `python/etl/fetch_weather.py`

```python
TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503
_ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_MAX_RETRIES  = 3

def fetch_past_temps(start: date, end: date) -> pd.DataFrame:
    """Fetch hourly archive weather for Tokyo."""

def fetch_forecast_temps(days: int = 3) -> pd.DataFrame:
    """Fetch hourly forecast weather for today and upcoming days."""

def enrich_cache_with_weather(cache: pd.DataFrame) -> pd.DataFrame:
    """Fill missing weather values in the hourly cache where actual_mw exists."""
```

`run_batch.py` persists temperature and apparent temperature inside `.hourly_cache.parquet`, so demand and weather history move together.

---

## Temperature Feature Design

```python
# Current temperature (actual archive or forecast)
'temp_c'              # temperature at that hour (°C)
'apparent_temp_c'     # apparent / feels-like temperature at that hour (°C)

# Cooling/heating degree values
'cooling_degree'      # max(0, temp_c - cooling_base_temp_c)
'heating_degree'      # max(0, heating_base_temp_c - temp_c)
'apparent_cooling_degree'  # max(0, apparent_temp_c - cooling_base_temp_c)

# Temperature regime context
'temp_anomaly_7d'     # temp_c minus trailing 7-day mean
'temp_anomaly_doy'    # temp_c minus historical same month/hour mean
'temp_delta_24h'      # current same-hour temp minus previous-day temp
'cooling_delta_24h'   # current cooling degree minus previous-day cooling degree
'temp_delta_168h'     # current same-hour temp minus 168h-ago temp
'cooling_delta_168h'  # current cooling degree minus 168h-ago cooling degree

# Heat interactions around holiday return-to-work periods
'holiday_x_heat'
'post_holiday_x_heat'
'business_hour_x_post_holiday_heat'
```

Cooling/heating balance points are configurable:

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 10.0
```

> **Why degree values and weather deltas**: degree values linearize HVAC-driven demand. The 24h deltas tell the model when yesterday's same-hour demand should be trusted less because today's weather is different. The 168h deltas do the same for last week's same-hour demand.

---

## File Structure Changes

```
python/
  etl/
    fetch_weather.py    # New: Open-Meteo data collection
    run_batch.py        # Modified: weather cache integration
  forecast/
    feature_builder.py  # Modified: temperature features added
```

```
web/public/
  .hourly_cache.parquet    # demand cache, including temp_c/apparent_temp_c when available
  .lgbm_model.pkl          # trained LightGBM model
```

---

## `feature_builder.py` Modifications

```python
def build_training_features(
    cache: pd.DataFrame,
    config: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    cache: hourly cache with ts, actual_mw, supply_mw, temp_c, apparent_temp_c, ...
    config: includes weather_features balance points
    """
    cooling_base_temp_c, heating_base_temp_c = _weather_feature_config(config)
    df["apparent_temp_c"] = df["apparent_temp_c"].fillna(df["temp_c"])
    df["cooling_degree"] = (df["temp_c"] - cooling_base_temp_c).clip(lower=0.0)
    df["heating_degree"] = (heating_base_temp_c - df["temp_c"]).clip(lower=0.0)
    df["apparent_cooling_degree"] = (df["apparent_temp_c"] - cooling_base_temp_c).clip(lower=0.0)
    df["temp_delta_24h"] = df["temp_c"] - df["temp_c_24h"]
    df["cooling_delta_24h"] = df["cooling_degree"] - df["cooling_degree_24h"]
    df["temp_delta_168h"] = df["temp_c"] - df["temp_c_168h"]
    df["cooling_delta_168h"] = df["cooling_degree"] - df["cooling_degree_168h"]
    return df[FEATURE_COLS], df["actual_mw"]
```

---

## `run_batch.py` Integration Strategy

```python
# Fill missing historical temp_c/apparent_temp_c values in the hourly cache.
hourly_cache = enrich_cache_with_weather(hourly_cache)

# Append virtual future rows with forecast weather so inference can use
# today's and tomorrow's weather without treating those rows as actual demand.
extended_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)

# Train and predict with the same weather feature configuration.
forecaster = LGBMForecaster(config=config)
forecaster.fit(hourly_cache)
tomorrow_fc = forecaster.predict(tomorrow, extended_cache)
```

---

## GitHub Actions Integration

```yaml
# ETL and intraday runs call python/etl/run_batch.py.
# Weather archive/forecast fetches are handled inside the batch job.
```

### Cache File Commit

```yaml
- name: Commit outputs
  run: |
    git add web/public/forecast/ web/public/status.json
    git add web/public/.hourly_cache.parquet || true
    git add web/public/.lgbm_model.pkl || true
    git commit -m "auto: ETL $(date -u +%Y-%m-%dT%H:%M)Z" || true
```

---

## Temperature Source by Prediction Stage

| Stage | Temperature Source | Notes |
|---|---|---|
| Training (full history) | Open-Meteo archive API | Historical `temp_c` / `apparent_temp_c` are stored in `.hourly_cache.parquet` |
| Yesterday's forecast | Historical actuals (confirmed) | Exact |
| Today's forecast | Historical (morning) + forecast (afternoon) | Mixed |
| Tomorrow's forecast | Open-Meteo 48h forecast | ±1–2°C error tolerated |

> Tomorrow's temperature forecast error propagates into model error.
> During summer heat waves, forecast error can be large; the quantile models and anomaly rules should be interpreted with that uncertainty in mind.

---

## Evaluation Plan

Comparison against Phase 5-A (no temperature):

```
Test period: 2026-01-01 ~ 2026-05-04

Metric      Phase 5-A    Phase 5-B    Improvement
RMSE (MW)   TBD          TBD          est. -20~35%
MAE  (MW)   TBD          TBD
Summer RMSE TBD          TBD          larger improvement
Winter RMSE TBD          TBD
```

Results saved to `web/public/model_eval.json`:

```json
{
  "evaluated_at": "2026-05-05T09:20:00+09:00",
  "test_period": { "from": "2026-01-01", "to": "2026-05-04" },
  "baseline":  { "rmse": null, "mae": null, "mape": null },
  "lgbm_no_temp": { "rmse": null, "mae": null, "mape": null },
  "lgbm_with_temp": { "rmse": null, "mae": null, "mape": null }
}
```

---

## Current Implementation Checklist

1. `fetch_weather.py` uses Open-Meteo archive and forecast endpoints with retry/backoff.
2. `run_batch.py` fills historical `temp_c` and `apparent_temp_c` into `.hourly_cache.parquet`.
3. Future forecast weather is appended and refreshed as virtual cache rows with `actual_mw = NaN`.
4. `feature_builder.py` creates 34 LightGBM features, including degree values, apparent temperature, temperature anomalies, and 24h/168h weather deltas.
5. `LGBMForecaster(config=config)` uses the same weather feature settings for training and inference.
6. Feature versioning marks older saved models as stale so the next run retrains them.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Open-Meteo API outage | Low | Retry/backoff; historical fetch failure is non-fatal and existing cache values remain |
| Gaps in historical temperature data | Low | Re-run ETL after API recovery; missing rows keep `temp_c = NaN` and are excluded from model training |
| Temperature lag feature leakage | Watch | Use only forecast values for future temperatures during inference |
| Summer heatwave extrapolation | Medium | Ensure training data includes past heatwave periods |
