# Model Evaluation Report

Languages: [한국어](../ko/model-evaluation.md) · [日本語](../ja/model-evaluation.md)

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
- Aggregate MAE, WAPE, RMSE, max-error risk, and advantage-hour counts by summary, day, and hour of day.
- Exclude rows where `actualSource` is `tepco_forecast_fallback`.
- The aggregate `summary` includes only the latest operating model family.
  - Example: if LightGBM is the current operating model, baseline-era forecast dates are excluded from the aggregate scorecard.

Key metrics:

| Metric | Meaning |
|---|---|
| `modelMaeMw`, `tepcoMaeMw` | Mean absolute error in MW. This remains the most intuitive headline metric. |
| `modelWapePct`, `tepcoWapePct` | Weighted absolute percentage error: absolute error divided by total actual demand. This is the main scale-aware error-rate metric. |
| `modelRmseMw`, `tepcoRmseMw` | Large-error risk metric. It penalizes single-hour misses more strongly than MAE. |
| `modelMaxErrorMw`, `tepcoMaxErrorMw` | Largest single-hour miss in the comparison window. |
| `modelAdvantageHours`, `tepcoAdvantageHours` | Number of hours where each forecast had lower absolute error. These are the operational names for the legacy `modelWins` and `tepcoWins` fields. |
| `verdict` | Operational assessment derived from MAE, WAPE, and RMSE: `model_better`, `tepco_better`, `close`, `mixed`, or `insufficient`. |

Important caveat:

TEPCO's forecast is a strong official operational baseline and may reflect information unavailable to this project. This comparison is not a claim that the project model always beats TEPCO; it is a transparent operational scorecard for when each forecast is closer to actual demand.

For strict train/test separation, use `model_backtest.json` as the primary model-quality signal.

Advantage-hour counts are supporting context, not the primary ranking signal. The dashboard prioritizes WAPE and large-error risk over a sports-like win/loss interpretation.
