# LightGBM Forecast Model Design

> Phase 5-A: Replace statistical baseline with a LightGBM ML model  
> No temperature data — calendar and lag features only

---

## Goals

| Item | Current (baseline) | Target (LightGBM) |
|---|---|---|
| Model type | Same-weekday mean/std | Gradient Boosting (LightGBM) |
| Feature count | Implicit 2 (weekday, hour) | Explicit ~12 |
| Holiday handling | Manual seasonal window | Auto-learned via `is_holiday` feature |
| Uncertainty | Normal distribution (1.96σ) | Quantile regression (q10/q90) |
| Evaluation | None | RMSE, MAE, MAPE |

---

## Feature Design

```python
# Time features (calendar)
'hour'          # 0–23
'dayofweek'     # 0(Mon)–6(Sun)
'month'         # 1–12
'is_holiday'    # 0/1  (jpholiday)
'is_weekend'    # 0/1

# Lag features (historical actuals)
'lag_24h'       # actual_mw at same hour yesterday
'lag_48h'       # same hour 2 days ago
'lag_168h'      # same hour 1 week ago (most important)
'lag_336h'      # same hour 2 weeks ago

# Rolling statistics (same hour + same weekday over recent N weeks)
'roll_4w_mean'  # mean of same (hour, dayofweek) over last 4 weeks
'roll_4w_std'   # std dev of same (hour, dayofweek) over last 4 weeks

# Supply feature (when available)
'supply_mw'     # most recently known supply capacity (available at prediction time)
```

> **Lag feature caveat**: At tomorrow's prediction time, only part of today's actuals are confirmed.  
> lag_24h etc. are exact during training, but during inference must be filled from the last confirmed hour.

---

## File Structure

```
python/
  forecast/
    baseline.py          # Existing statistical model (kept as fallback)
    lgbm_model.py        # New: LightGBM training/inference
    feature_builder.py   # New: shared feature engineering
  etl/
    run_batch.py         # Modified: LightGBM training + prediction integration
```

---

## lgbm_model.py Design

```python
class LGBMForecaster:
    def __init__(self, n_estimators=500, learning_rate=0.05):
        ...

    def fit(self, cache: pd.DataFrame) -> None:
        """Train on hourly_cache. Requires at least 90 days of data."""
        X, y = build_features(cache)
        # quantile regression: q10, q50, q90
        self.model_q10 = lgb.train(params_q10, ...)
        self.model_q50 = lgb.train(params_q50, ...)
        self.model_q90 = lgb.train(params_q90, ...)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """Return 24-hour forecast for target_date as a list of HourlyForecast."""
        ...

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> 'LGBMForecaster':
        return joblib.load(path)
```

---

## Uncertainty Estimation: Quantile Regression

The current baseline assumes a normal distribution and constructs p95 intervals as `mean ± 1.96σ`.  
LightGBM learns the intervals directly via quantile regression:

```python
# Train three separate models
params_q10 = {'objective': 'quantile', 'alpha': 0.10, ...}
params_q50 = {'objective': 'quantile', 'alpha': 0.50, ...}  # median = point forecast
params_q90 = {'objective': 'quantile', 'alpha': 0.90, ...}
```

Outputs:
- `forecastMw` = q50
- `p95LowerMw` = q10 (technically 80% interval, reusing existing field)
- `p95UpperMw` = q90

> Adding temperature features later only requires model retraining; the output interface stays the same.

---

## run_batch.py Integration Strategy

```python
from python.forecast.lgbm_model import LGBMForecaster

MODEL_PATH = out_dir / ".lgbm_model.pkl"
MIN_TRAIN_DAYS = 90

# After cache is built
if len(hourly_cache) >= MIN_TRAIN_DAYS * 24:
    forecaster = LGBMForecaster()
    forecaster.fit(hourly_cache)
    forecaster.save(MODEL_PATH)
else:
    forecaster = None

def get_forecast(target_date):
    if forecaster:
        return forecaster.predict(target_date, hourly_cache)
    return compute_forecast(hourly_cache, target_date, ...)  # baseline fallback
```

**Model file management**: `.lgbm_model.pkl` is stored in `web/public/` and cached between Actions runs.  
Do not add to `.gitignore` — commit it like a cache file.

---

## Evaluation Method

### Walk-forward Validation

```
Full dataset: 2023-01-01 ~ 2026-05-04 (~1220 days)

Train: 2023-01-01 ~ 2025-12-31
Test:  2026-01-01 ~ 2026-05-04 (most recent 4 months)
```

Metrics:
```python
RMSE = sqrt(mean((actual - forecast)^2))
MAE  = mean(abs(actual - forecast))
MAPE = mean(abs((actual - forecast) / actual)) * 100
```

Results saved to `web/public/model_eval.json` after numeric comparison with baseline.  
(Can be displayed later as a "Model Performance" card in the UI)

---

## Implementation Steps

1. Write `feature_builder.py` + unit tests
2. Write `lgbm_model.py` (fit / predict / save / load)
3. Write walk-forward CV script (`python/eval/compare_models.py`)
4. Integrate into `run_batch.py`
5. Add `lightgbm`, `joblib` to `requirements.txt`
6. Verify model file commit in `.github/workflows/etl.yml`

---

## Expected Impact

With lag features alone (no temperature):
- Reflects consecutive weekday trends (if yesterday was high, today likely is too)
- Auto-learns day-before/day-after holiday patterns
- Captures sharp demand swings at seasonal transitions

Expected **10–20% RMSE improvement** over current baseline (limited by lack of temperature data).
