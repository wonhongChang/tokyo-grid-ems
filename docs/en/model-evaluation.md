# Model Evaluation Report

Languages: [한국어](../ko/model-evaluation.md) · [日本語](../ja/model-evaluation.md)

Tokyo Grid EMS evaluates forecast quality from three angles.

1. **Offline backtest**: checks whether the model improves over the statistical baseline on historical data.
2. **Operational comparison**: checks whether the project model or TEPCO's published forecast was closer to actual demand in the dashboard's operating window.
3. **Matched-vintage benchmark**: compares model and TEPCO values captured in the same run and at the same lead time.

All three outputs are generated under `web/public/metrics/`. The dashboard's **Validation** tab currently shows the offline backtest and latest-published-value operational comparison; the matched-vintage result remains an internal promotion and qualification artifact until sufficient history is available.

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

TEPCO's forecast is a strong official operational baseline and may reflect information unavailable to this project. It can revise elapsed-hour values, so `forecast_accuracy.json` is explicitly a `latest_published_value_reference` and is not eligible for formal parity claims.

For strict train/test separation, use `model_backtest.json` as the primary model-quality signal.

Advantage-hour counts are supporting context, not the primary ranking signal. The dashboard prioritizes WAPE and large-error risk over a sports-like win/loss interpretation.

---

## Matched-vintage TEPCO Benchmark

Output:

```text
web/public/metrics/forecast_vintage_accuracy.json
```

- Each ETL/Intraday run stores future model and TEPCO values observed together under `reports/internal/forecast-vintages/`.
- Later TEPCO revisions cannot rewrite an earlier capture.
- `capturedAt` is used as the observable vintage because TEPCO does not expose an immutable issuance timestamp.
- Metrics are separated into `0-2h`, `2-4h`, `4-8h`, and `8-24h` lead buckets, then into operational time bands.
- Formal qualification requires complete 28-day and 84-day windows, overall MAE/WAPE ratio at or below 1.10, and each sufficiently covered time-band MAE ratio at or below 1.25.
- A paired date-block bootstrap reports uncertainty in model-minus-TEPCO absolute error.

`collecting` means the benchmark is functioning but does not yet have enough history. It must never be interpreted as a pass or failure.
