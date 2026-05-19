# JSON Schema Specification (Dashboard Contract)

Languages: [한국어](../ko/json_schema.md) · [日本語](../ja/json_schema.md)

This is the **static JSON output contract** that the GitHub Pages dashboard reads directly.
The ETL/batch pipeline generates files under `web/public/` conforming to this schema.

> Principles
> - Date-keyed outputs use **Asia/Tokyo (JST)** dates (`YYYY-MM-DD`), not UTC.
> - Missing or unevaluated states are represented as `null` values or explicit `status` fields.
> - The schema is fixed at MVP and should **not change** as data coverage expands.

---

## File List
- `web/public/status.json`
- `web/public/alerts/YYYY-MM-DD.json`
- `web/public/forecast/YYYY-MM-DD.json`
- `web/public/forecast_snapshots/YYYY-MM-DD/index.json`
- `web/public/forecast_snapshots/YYYY-MM-DD/*.json`
- `web/public/actual/YYYY-MM-DD.json`
- `web/public/metrics/forecast_accuracy.json`
- `web/public/metrics/model_backtest.json`

---

## Common Rules
- Risk/importance level is unified as `severity` (`info|warning|critical`) across all outputs.

## Common Type Definitions

### Timestamp
- ISO 8601 string; **timezone offset (+09:00) is strongly recommended in batch outputs**
  - Example: `2025-12-01T18:00:00+09:00`

### Severity
- `"info" | "warning" | "critical"`

### DataAvailability (dashboard state)
- `"ok"`: successfully processed
- `"missing"`: not collected/processed (batch skipped, etc.)
- `"failed"`: attempted but failed (parse/quality gate/input error, etc.)
- `"not_yet_available"`: delayed but possibly normal

---

# 1) status.json

## Purpose
Provides the **current system state (Last Updated / result summaries)** and KPIs shown at the top of the dashboard.

## Path
`web/public/status.json`

## Schema
```json
{
  "project": "tokyo-grid-ems",
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",

  "lastUpdatedAt": "2025-12-02T07:05:12+09:00",
  "coverageTo": "2025-12-01",

  "availability": "ok",
  "missingDays": ["2025-11-23"],
  "failedDays": ["2025-11-24"],

  "latest": {
    "date": "2025-12-01",
    "peakActualMw": 58230.0,
    "peakActualAt": "2025-12-01T18:00:00+09:00",
    "peakUsagePct": 96.2,
    "peakSupplyMw": 61000.0
  },

  "yesterday": "2025-12-01",

  "today": {
    "date": "2025-12-02",
    "peakForecastMw": 57500.0,
    "peakForecastAt": "2025-12-02T18:00:00+09:00",
    "severity": "warning"
  },

  "tomorrow": {
    "date": "2025-12-03",
    "peakForecastMw": 56000.0,
    "peakForecastAt": "2025-12-03T18:00:00+09:00",
    "severity": "info"
  }
}
```

## Field Descriptions
- `lastUpdatedAt`: timestamp of the last successful status update by the batch
- `coverageTo`: **up to which date** anomaly detection and actuals-based outputs have been generated
- `availability`: overall dashboard state
- `missingDays`, `failedDays`: lists of missing/failed dates (display use)
- `latest`: most recently processed actuals summary (previous day)
- `yesterday`: always `today − 1` as an ISO date string. Unlike `coverageTo`, this is purely calendar-based regardless of CSV processing status. Used as the "Yesterday" tab date in the dashboard
- `today`, `tomorrow`: today/tomorrow forecast summaries

---

# 2) alerts/YYYY-MM-DD.json

## Purpose
Provides **anomaly detection results** for the previous day as individual events.

## Path Example
- `web/public/alerts/2025-12-01.json`

## Schema
```json
{
  "date": "2025-12-01",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "summary": {
    "critical": 1,
    "warning": 2,
    "info": 0
  },

  "events": [
    {
      "id": "2025-12-01T18:00:00+09:00_spike",
      "type": "spike",
      "severity": "critical",
      "startAt": "2025-12-01T18:00:00+09:00",
      "endAt": "2025-12-01T19:00:00+09:00",
      "metric": "actual_mw",
      "actualMw": 61500.0,
      "expectedMw": 58000.0,
      "interval": {
        "p95Lower": 56000.0,
        "p95Upper": 60000.0,
        "p99Lower": 55000.0,
        "p99Upper": 61000.0
      },
      "reason": "Actual exceeded p99 upper bound by 0.8%",
      "tags": ["interval", "peak"]
    },
    {
      "id": "2025-12-01T09:00:00+09:00_drift",
      "type": "drift",
      "severity": "warning",
      "startAt": "2025-12-01T09:00:00+09:00",
      "endAt": "2025-12-01T12:00:00+09:00",
      "metric": "residual_mw",
      "residualAvgMw": 1200.0,
      "method": "ewma",
      "thresholdMw": 1000.0,
      "reason": "EWMA residual above threshold for 3 hours",
      "tags": ["residual"]
    },
    {
      "id": "2025-12-01T17:00:00+09:00_reserve_risk",
      "type": "reserve_risk",
      "severity": "warning",
      "startAt": "2025-12-01T17:00:00+09:00",
      "endAt": "2025-12-01T19:00:00+09:00",
      "metric": "usage_pct",
      "usagePct": 95.4,
      "thresholdPct": 92.0,
      "supplyMw": 61000.0,
      "reason": "Usage rate exceeded threshold",
      "tags": ["kpi"]
    }
  ]
}
```

## Field Descriptions
- `events[].type`: `"spike" | "drop" | "drift" | "reserve_risk" | "quality"`
- `events[].interval`: included only for spike/drop events with forecast interval data

### Missing/Failed Example
```json
{
  "date": "2025-12-02",
  "timezone": "Asia/Tokyo",
  "availability": "missing",
  "summary": { "critical": 0, "warning": 0, "info": 0 },
  "events": [],
  "message": "No source data. Ingestion was skipped or data was not available."
}
```

---

# 3) forecast/YYYY-MM-DD.json

## Purpose
Provides **hourly demand forecast for a specific date** (today or tomorrow).

## Path Example
- `web/public/forecast/2025-12-02.json`

## Schema
```json
{
  "date": "2025-12-02",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "model": {
    "name": "baseline_dow_hour_mean",
    "version": "mvp-1",
    "nWeeks": 12
  },

  "peak": {
    "forecastMw": 57500.0,
    "at": "2025-12-02T18:00:00+09:00"
  },

  "series": [
    {
      "ts": "2025-12-02T00:00:00+09:00",
      "forecastMw": 42000.0,
      "p95LowerMw": 40000.0,
      "p95UpperMw": 44000.0,
      "p99LowerMw": 39000.0,
      "p99UpperMw": 45000.0
    }
  ]
}
```

## Field Descriptions
- `model.name`: `baseline_dow_hour_mean` — mean of same weekday/hour over rolling N weeks
- `model.nWeeks`: number of rolling weeks used for training
- `series[]`: 24-point forecast + prediction intervals (95/99%)
- When data is insufficient: `availability: "not_yet_available"`, `series: []`

---

# 3.5) forecast_snapshots/YYYY-MM-DD/*.json

## Purpose
Preserves bounded lead-time forecast snapshots for operational review. These files are stored with Pages outputs but are not directly linked from the dashboard UI.

## Path Example
- `web/public/forecast_snapshots/2025-12-02/index.json`
- `web/public/forecast_snapshots/2025-12-02/2025-12-01T21-20-00-09-00.json`

## Snapshot Schema
```json
{
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",
  "targetDate": "2025-12-02",
  "generatedAt": "2025-12-01T21:20:00+09:00",
  "runType": "intraday",
  "preserveObservedForecastHours": true,
  "model": {
    "name": "lgbm_quantile_q50_intraday_residual",
    "version": "mvp-1",
    "nWeeks": 12
  },
  "peak": {
    "forecastMw": 57500.0,
    "at": "2025-12-02T18:00:00+09:00"
  },
  "observationSummary": {
    "actualHoursAtGeneration": 12,
    "observedActualHoursAtGeneration": 12,
    "fallbackActualHoursAtGeneration": 0,
    "lastActualHour": 11,
    "lastObservedActualHour": 11,
    "lastFallbackActualHour": null
  },
  "series": []
}
```

## Retention
- `config.yaml` controls `forecast_snapshots.retention_days` and `forecast_snapshots.max_per_day`.
- Current default: 21 target dates, maximum 16 snapshots per target date.

---

# 4) actual/YYYY-MM-DD.json

## Purpose
Provides **hourly actual measurements for a specific date**. Same-day data is updated in real time by the intraday workflow.

## Path Example
- `web/public/actual/2025-12-01.json`

## Schema
```json
{
  "date": "2025-12-01",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "series": [
    {
      "ts": "2025-12-01T00:00:00+09:00",
      "actualMw": 42000.0,
      "actualSource": "observed",
      "tepcoForecastMw": 41500.0,
      "usagePct": 68.5,
      "supplyMw": 61000.0
    }
  ]
}
```

## Field Descriptions
- `actualMw`: actual power demand (MW); `null` for unconfirmed hours
- `actualSource`: source of `actualMw`; `observed` for measured values, `tepco_forecast_fallback` when the 23:40 JST refresh fills a still-missing 23:00 actual with TEPCO's forecast. Fallback values are used for operational forecast inputs, but excluded from validation metrics and anomaly actual checks
- `tepcoForecastMw`: TEPCO's official forecast value (from CSV)
- `usagePct`: usage rate (%)
- `supplyMw`: available supply capacity (MW)

---

# 5) metrics/*.json

## Purpose
Evaluation outputs used by the dashboard's **Validation** tab.

## Files
- `metrics/forecast_accuracy.json`: operational hourly-error comparison between the project model and TEPCO forecasts
- `metrics/model_backtest.json`: offline LightGBM backtest against the baseline

## Common Fields
- `schemaVersion`: metrics schema version
- `timezone`: `Asia/Tokyo`
- `generatedAt`: evaluation generation timestamp

## forecast_accuracy Key Fields
- `modelScope.summaryModelFamily`: latest operating model family included in the aggregate summary
- `modelScope.excludedDates`: dates excluded from the aggregate summary because they use another model family such as baseline
- `summary.modelMaeMw`, `summary.tepcoMaeMw`: MAE over comparable recent hours
- `summary.modelWins`, `summary.tepcoWins`: hourly win counts by absolute error
- `daily[]`: daily MAE and win counts. Dates with `includedInSummary: false` are excluded from the aggregate summary
- `daily[].maeGapMw`: model MAE minus TEPCO MAE. Positive means TEPCO was closer; negative means the model was closer
- `daily[].verdict`: daily verdict, one of `model_better`, `tepco_better`, `close`, or `insufficient`
- `hourly[]`: hour-of-day MAE and win counts

## model_backtest Key Fields
- `methodology`: backtest strategy and split point
- `trainPeriod`, `testPeriod`: training and test windows
- `baseline`, `lightgbm`: RMSE, MAE, MAPE, sample count
- `improvementPct`: LightGBM improvement against the baseline

---

# Dashboard Implementation Tips (Frontend)
- Treat missing values as `null` so the line breaks rather than interpolates
- If `availability !== "ok"`, show a badge or message at the top of the tab
- Always display `status.json`'s `lastUpdatedAt` (trust signal)

---

# Schema Change Policy
- **File paths and schema are frozen**
- Changes are handled via config only (training window, baseline window, thresholds)
- `model.nWeeks` may change; `series/alerts` structure remains identical
