# Weather Data Integration Design

> Production feature: adding Open-Meteo temperature features to the LightGBM model
> Open-Meteo API (free, no auth required) — Tokyo coordinates

Languages: [한국어](../ko/weather-integration.md) · [日本語](../ja/weather-integration.md)

---

## Why Temperature

Temperature explains 30–40% of electricity demand variation.

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
    "temperature_2m": [18.3, 17.9, 17.5, ...]
  }
}
```

No API key required. Commercial use allowed (CC BY 4.0).

---

## New File: `python/etl/fetch_weather.py`

```python
import requests
import pandas as pd
from pathlib import Path
from datetime import date

TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503
BASE_URL   = "https://api.open-meteo.com/v1/forecast"

def fetch_weather(past_days: int = 92, forecast_days: int = 2) -> pd.DataFrame:
    """
    Returns DataFrame: ts (tz-aware JST), temp_c (float)
    Covers past_days history + forecast_days future.
    """
    params = {
        "latitude":    TOKYO_LAT,
        "longitude":   TOKYO_LON,
        "hourly":      "temperature_2m",
        "timezone":    "Asia/Tokyo",
        "past_days":   past_days,
        "forecast_days": forecast_days,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["hourly"]

    df = pd.DataFrame({
        "ts":     pd.to_datetime(data["time"]).tz_localize("Asia/Tokyo"),
        "temp_c": data["temperature_2m"],
    })
    return df

def save_weather_cache(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path, index=False)

def load_weather_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_parquet(path)
```

---

## Temperature Feature Design

```python
# Current temperature (actual or forecast)
'temp_c'         # temperature at that hour (°C)

# Previous-day temperature lag (demand inertia)
'temp_lag_24h'   # temperature at same hour yesterday

# Heating/Cooling Degree values (HDD/CDD)
'hdd'            # max(0, 18 - temp_c)  — heating need
'cdd'            # max(0, temp_c - 26)  — cooling need

# Forecast-only feature (uses Open-Meteo forecast when predicting tomorrow)
'temp_forecast'  # Open-Meteo forecast temperature (inference only)
```

> **Why HDD/CDD**: linearizes the non-linear temperature effect.
> Below 18°C, heating demand increases linearly as temperature drops.
> Above 26°C, cooling demand increases linearly as temperature rises.

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
  .weather_cache.parquet   # temperature cache (committed like model file)
```

---

## `feature_builder.py` Modifications

```python
def build_features(
    power_cache: pd.DataFrame,
    weather_cache: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    power_cache: hourly_cache (ts, actual_mw, supply_mw, ...)
    weather_cache: result of fetch_weather() (ts, temp_c)
    """
    df = power_cache.copy()

    # Existing features (calendar + lag)
    df['hour']      = df['ts'].dt.hour
    df['dayofweek'] = df['ts'].dt.dayofweek
    df['month']     = df['ts'].dt.month
    df['is_holiday'] = df['ts'].dt.date.apply(_is_holiday)
    df['is_weekend'] = df['dayofweek'].isin([5, 6]).astype(int)
    df['lag_24h']   = df['actual_mw'].shift(24)
    df['lag_168h']  = df['actual_mw'].shift(168)
    df['lag_336h']  = df['actual_mw'].shift(336)

    # Temperature features (only when weather_cache is provided)
    if weather_cache is not None:
        df = df.merge(weather_cache, on='ts', how='left')
        df['temp_lag_24h'] = df['temp_c'].shift(24)
        df['hdd'] = (18 - df['temp_c']).clip(lower=0)
        df['cdd'] = (df['temp_c'] - 26).clip(lower=0)

    feature_cols = [
        'hour', 'dayofweek', 'month', 'is_holiday', 'is_weekend',
        'lag_24h', 'lag_168h', 'lag_336h',
        *([ 'temp_c', 'temp_lag_24h', 'hdd', 'cdd' ] if weather_cache is not None else [])
    ]
    X = df[feature_cols].dropna()
    y = df.loc[X.index, 'actual_mw']
    return X, y
```

---

## `run_batch.py` Integration Strategy

```python
WEATHER_CACHE_PATH = out_dir / ".weather_cache.parquet"

# Fetch weather during ETL run (non-fatal if it fails)
try:
    weather_df = fetch_weather(past_days=92, forecast_days=2)
    save_weather_cache(weather_df, WEATHER_CACHE_PATH)
except Exception as e:
    print(f"Weather fetch failed (non-fatal): {e}")
    weather_df = load_weather_cache(WEATHER_CACHE_PATH)  # cache fallback

# Include temperature when training LightGBM
if forecaster and weather_df is not None:
    forecaster.fit(hourly_cache, weather_cache=weather_df)
else:
    forecaster.fit(hourly_cache)  # train without temperature

# Use tomorrow's forecast temperature for prediction
tomorrow_weather = weather_df[weather_df['ts'].dt.date == tomorrow] if weather_df is not None else None
tomorrow_fc = forecaster.predict(tomorrow, hourly_cache, weather=tomorrow_weather)
```

---

## GitHub Actions Integration

```yaml
# Add to .github/workflows/etl.yml
- name: Fetch weather data
  run: python python/etl/fetch_weather.py --save web/public/.weather_cache.parquet
  continue-on-error: true   # don't abort ETL if weather API fails
```

### Cache File Commit

```yaml
- name: Commit outputs
  run: |
    git add web/public/forecast/ web/public/status.json
    git add web/public/.weather_cache.parquet || true  # OK if missing
    git add web/public/.lgbm_model.pkl || true
    git commit -m "auto: ETL $(date -u +%Y-%m-%dT%H:%M)Z" || true
```

---

## Temperature Source by Prediction Stage

| Stage | Temperature Source | Notes |
|---|---|---|
| Training (full history) | `past_days=365` historical | Annual full retrain possible |
| Yesterday's forecast | Historical actuals (confirmed) | Exact |
| Today's forecast | Historical (morning) + forecast (afternoon) | Mixed |
| Tomorrow's forecast | Open-Meteo 48h forecast | ±1–2°C error tolerated |

> Tomorrow's temperature forecast error propagates into model error.
> During summer heat waves, forecast error is large — uncertainty bands widen automatically (quantile regression property).

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

## Implementation Steps

1. Write `fetch_weather.py` + manual test (`python -m python.etl.fetch_weather`)
2. Add temperature features to `feature_builder.py` + unit tests
3. Add `weather_cache` optional arg to `LGBMForecaster.fit()`
4. Integrate into `run_batch.py` (weather fetch → model training → prediction)
5. Verify `requests` is in `requirements.txt` (likely already present)
6. Run A/B evaluation with `compare_models.py` and save `model_eval.json`
7. (Optional) Add "Model Performance" card to UI

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Open-Meteo API outage | Low | `continue-on-error: true` + use previous cache |
| Gaps in historical temperature data | Low | Increase `past_days` and re-fetch |
| Temperature lag feature leakage | Watch | Use only forecast values for future temperatures during inference |
| Summer heatwave extrapolation | Medium | Ensure training data includes past heatwave periods |
