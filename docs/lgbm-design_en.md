# LightGBM Forecast Model Design

> Phase 5-A: Replace statistical baseline with a LightGBM ML model  
> No temperature data — calendar, lag, and holiday-correction features only

---

## Goals

| Item | Current (baseline) | Target (LightGBM) |
|---|---|---|
| Model type | Same-weekday mean/std | Gradient Boosting (LightGBM) |
| Feature count | Implicit 2 (weekday, hour) | Explicit 17 |
| Holiday handling | Manual seasonal window | `is_holiday` + holiday lag correction features |
| Uncertainty | Normal distribution (1.96σ) | Quantile regression (q10/q90) |
| Evaluation | None | RMSE, MAE, MAPE |

---

## Feature Design (17 features)

```python
# Calendar features
'hour'                   # 0–23
'dayofweek'              # 0(Mon)–6(Sun)
'month'                  # 1–12
'is_holiday'             # 0/1  (jpholiday — public holidays)
'is_weekend'             # 0/1  (Sat/Sun)
'is_non_business_day'    # 0/1  (is_holiday OR is_weekend)

# Lag features (historical actuals)
'lag_24h'       # actual_mw at same hour yesterday
'lag_48h'       # same hour 2 days ago
'lag_168h'      # same hour 1 week ago (most important)
'lag_336h'      # same hour 2 weeks ago

# Rolling statistics (same hour + same weekday over last 4 weeks)
'roll_4w_mean'  # mean of same (hour, dayofweek) over last 4 weeks
'roll_4w_std'   # std dev of same (hour, dayofweek) over last 4 weeks

# Holiday lag correction (prevents underestimation on return-from-holiday days)
'lag_last_biz_hour'       # actual_mw at same hour on last non-holiday weekday
'lag_last_nonhol_hour'    # actual_mw at same hour on last non-public-holiday day
'consec_holiday_len'      # consecutive non-business days immediately before this date
'days_since_holiday_end'  # calendar days since last holiday period ended (capped at 7)
'major_holiday_season'    # 0=normal 1=golden_week_zone 2=obon_zone 3=newyear_zone
```

> **Holiday lag correction rationale**: After Golden Week, lag_24h/lag_168h point to low-demand  
> holiday readings. lag_last_biz_hour references the last working day, correcting for systematic  
> underestimation of the post-holiday demand surge.

---

## File Structure

```
python/
  forecast/
    baseline.py          # Existing statistical model (kept for display until Phase 5-B)
    lgbm_model.py        # LightGBM train / infer / save / load
    feature_builder.py   # Shared feature engineering (training + inference)
  eval/
    compare_models.py    # Walk-forward evaluation script
  etl/
    run_batch.py         # LightGBM training integrated (display stays on baseline until 5-B)
```

---

## lgbm_model.py Design

```python
class LGBMForecaster:
    MIN_TRAIN_ROWS = 90 * 24  # minimum 90 days

    def fit(self, cache: pd.DataFrame) -> None:
        """Train q10/q50/q90 on hourly cache. Pass DataFrame to preserve feature names."""
        X, y = build_training_features(cache)
        self.model_q10 = LGBMRegressor(objective='quantile', alpha=0.10, ...).fit(X, y)
        self.model_q50 = LGBMRegressor(objective='quantile', alpha=0.50, ...).fit(X, y)
        self.model_q90 = LGBMRegressor(objective='quantile', alpha=0.90, ...).fit(X, y)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """Return 24-hour HourlyForecast list for target_date."""
        X = build_inference_features(cache, target_date)
        ...

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> 'LGBMForecaster':
        return joblib.load(path)
```

---

## Uncertainty Estimation: Quantile Regression

```python
params_q10 = {'objective': 'quantile', 'alpha': 0.10, ...}
params_q50 = {'objective': 'quantile', 'alpha': 0.50, ...}  # median = point forecast
params_q90 = {'objective': 'quantile', 'alpha': 0.90, ...}
```

Output mapping:
- `forecastMw` = q50
- `p95LowerMw` = q10 (technically 80% interval, reusing existing field)
- `p95UpperMw` = q90

---

## run_batch.py Integration Strategy (Phase 5-A)

In Phase 5-A the model is **trained and saved only** — displayed predictions stay on baseline.  
The switch to LightGBM predictions happens in Phase 5-B when temperature features are added.

```python
# After cache build — train and save (not used for display yet)
forecaster = _try_train_lgbm(hourly_cache, out_dir)  # writes .lgbm_model.pkl

# Forecast — always baseline until Phase 5-B
def _get_forecast(forecaster, cache, target_date, n_weeks, min_samples):
    return compute_forecast(cache, target_date, n_weeks, min_samples), "baseline_dow_hour_mean"
```

**Model file management**: `.lgbm_model.pkl` is stored under `web/public/` for caching between Actions runs.

---

## Evaluation

### Walk-forward Validation

```
Train:  2023-01-01 – 2025-12-31
Test:   2026-01-01 – recent (last ~4 months)
```

Metrics:
```python
RMSE = sqrt(mean((actual - forecast)^2))
MAE  = mean(abs(actual - forecast))
MAPE = mean(abs((actual - forecast) / actual)) * 100
```

Results saved to `web/public/model_eval.json`.

---

## Implementation Status

1. ✅ `feature_builder.py` with 17 features + unit tests
2. ✅ `lgbm_model.py` (fit / predict / save / load)
3. ✅ Walk-forward CV script (`python/eval/compare_models.py`)
4. ✅ `run_batch.py` integration (train/save; baseline display until Phase 5-B)
5. ✅ `requirements.txt`: added `lightgbm`, `joblib`, `scikit-learn`
6. Phase 5-B: add temperature feature, switch display to LightGBM

---

## Expected Impact

Without temperature, lag features alone provide:
- Continuous weekday trend carry-over (if yesterday was high, today likely is too)
- Automatic post-holiday demand correction via holiday lag features
- Capture of demand spikes at seasonal transitions

Estimated RMSE improvement over baseline: **10–20%** (limited by lack of temperature).  
Additional 10–15% improvement expected when temperature is added in Phase 5-B.
