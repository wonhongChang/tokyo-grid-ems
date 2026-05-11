# Model Evaluation Report

Tokyo Grid EMS evaluates forecast quality from two angles.

1. **Offline backtest**: checks whether the model improves over the statistical baseline on historical data.
2. **Operational comparison**: checks whether the project model or TEPCO's published forecast was closer to actual demand in the dashboard's operating window.

Both outputs are generated under `web/public/metrics/` and displayed in the dashboard's **Validation** tab.

---

## Offline Backtest

Output:

```text
web/public/metrics/model_backtest.json
```

Method:

- Train only on data before `testStart` (default: `2026-01-01`).
- For each test date, use only cache rows before that target date for lag and rolling features.
- Target: hourly actual demand (`actual_mw`).
- Compare the weekday/hour statistical baseline against the LightGBM model.

Key metrics:

| Metric | Meaning |
|---|---|
| `MAE` | Mean absolute error. Most intuitive for dashboard interpretation. |
| `RMSE` | Penalizes large misses more strongly. Useful for peak-risk failures. |
| `MAPE` | Relative error against actual demand. |
| `improvementPct` | LightGBM improvement against the baseline. Positive is better. |

Reproduce:

```bash
python python/eval/compare_models.py \
  --cache web/public/.hourly_cache.parquet \
  --out web/public/metrics/model_backtest.json \
  --test-start 2026-01-01
```

---

## Operational Comparison vs TEPCO

Output:

```text
web/public/metrics/forecast_accuracy.json
```

Method:

- Use recent hours where all three values exist: actual demand, project model forecast, and TEPCO forecast.
- Compute absolute error for each forecast.
- Aggregate MAE and win counts by summary, day, and hour of day.
- The aggregate `summary` includes only the latest operating model family.
  - Example: if LightGBM is the current operating model, baseline-era forecast dates are excluded from the aggregate win rate.

Important caveat:

TEPCO's forecast is a strong official operational baseline and may reflect information unavailable to this project. This comparison is not a claim that the project model always beats TEPCO; it is a transparent operational scorecard for when each forecast is closer to actual demand.

For strict train/test separation, use `model_backtest.json` as the primary model-quality signal.
