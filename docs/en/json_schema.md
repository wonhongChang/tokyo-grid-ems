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
- `web/public/reports/daily/YYYY-MM-DD.json`
- `web/public/reports/daily/index.json`
- `web/public/reports/ai/daily/YYYY-MM-DD.json`
- `web/public/reports/ai/daily/index.json`
- `web/public/reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json`
- `web/public/reports/ai/daily/{ko,en,ja}/index.json`
- `web/public/reports/internal/operational-calibration/YYYY-MM-DD.json`
- `web/public/reports/internal/operational-calibration/snapshots/YYYY-MM-DD/index.json`
- `web/public/reports/internal/operational-calibration/snapshots/YYYY-MM-DD/*.json`

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
  "forecastBuild": {
    "stageSummary": {
      "raw_lgbm": { "hours": 24, "peak": {} },
      "pre_calibration": { "hours": 24, "peak": {} }
    },
    "series": [
      {
        "hour": 9,
        "ts": "2025-12-02T09:00:00+09:00",
        "forecastMwByStage": {
          "raw_lgbm": 31000.0,
          "analog_adjusted": 30950.0,
          "post_holiday_guarded": 30950.0,
          "midday_guarded": 30950.0,
          "pre_calibration": 30950.0
        }
      }
    ]
  },
  "series": []
}
```

`forecastBuild` is an optional operational-analysis field. It is not directly shown in the public UI, but it lets lead-time snapshots compare raw LightGBM, analog adjustment, guard stages, and the pre-intraday-calibration value.

## Retention
- `config.yaml` controls `forecast_snapshots.retention_days` and `forecast_snapshots.max_per_day`.
- Current default: 21 target dates, maximum 16 snapshots per target date.

---

# 3.6) reports/internal/operational-calibration/YYYY-MM-DD.json

## Purpose
Internal diagnostics JSON for tracking how the operational calibration layer moved the forecast line. It is not directly linked from the dashboard UI.

## Key Fields
- `source_confidence`: same-day observed/fallback/missing source summary
- `applied_regime_reason`: list of applied calibration reasons
- `applied_day_bias`: average day-level scale adjustment
- `forecast_build.stageSummary`: stage summary from raw model to pre-calibration
- `correction`: residual-correction metadata, including day-boundary carry-over, day-level bias, business-type transition calibration flags such as `businessTypeTransitionPriorApplied`, `businessTypeTransitionPriorBiasMw`, `businessTypeTransitionApplied`, and `businessTypeTransitionBiasMw`, plus handoff and recovery fields such as `positiveResidualMitigationApplied`, `positiveResidualMitigationMaxMw`, `negResidualRecoveryDampingApplied`, and `negResidualRecoveryDampingFactor`
- `hourlyDiagnostics[]`: per-hour actual, TEPCO, stage forecasts, pre/post calibration forecast, calibration delta, and residuals

---

# 3.7) reports/internal/operational-calibration/snapshots/YYYY-MM-DD/*.json

## Purpose
Preserves bounded per-run operational calibration snapshots. The latest `operational-calibration/YYYY-MM-DD.json` is overwritten, while the snapshot index keeps intermediate intraday runs so the **Ops Report** can explain the calibration timeline with stronger evidence.

## Path Example
- `web/public/reports/internal/operational-calibration/snapshots/2026-05-23/index.json`
- `web/public/reports/internal/operational-calibration/snapshots/2026-05-23/2026-05-23T09-20-00-09-00.json`

## Index Key Fields
- `snapshots[]`: retained run list
- `snapshots[].appliedRegimeReason`: calibration reasons recorded for the run
- `snapshots[].baseAdjustmentMw`, `snapshots[].appliedDayBiasMw`: residual and day-scale adjustment amounts
- `snapshots[].businessTypeTransitionPriorApplied`, `snapshots[].positiveResidualMitigationApplied`, `snapshots[].negResidualRecoveryDampingApplied`: major calibration-layer flags

## Retention
- `config.yaml` controls `operational_calibration_snapshots.retention_days` and `operational_calibration_snapshots.max_per_day`.
- Current default: 14 target dates, maximum 24 snapshots per target date.

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
- `summary.modelWapePct`, `summary.tepcoWapePct`: absolute error divided by total actual demand
- `summary.modelRmseMw`, `summary.tepcoRmseMw`: RMSE for large-error risk
- `summary.modelMaxErrorMw`, `summary.tepcoMaxErrorMw`: largest single-hour miss in the comparison window
- `summary.modelAdvantageHours`, `summary.tepcoAdvantageHours`: hourly advantage counts by absolute error. `summary.modelWins` and `summary.tepcoWins` remain for backward compatibility
- `summary.modelAdvantageRate`: `modelAdvantageHours / summary.hours`
- `daily[]`: daily MAE/WAPE/RMSE and advantage-hour counts. Dates with `includedInSummary: false` are excluded from the aggregate summary
- `daily[].maeGapMw`: model MAE minus TEPCO MAE. Positive means TEPCO was closer; negative means the model was closer
- `daily[].wapeGapPct`: model WAPE minus TEPCO WAPE
- `daily[].verdict`: daily operational assessment, one of `model_better`, `tepco_better`, `close`, `mixed`, or `insufficient`
- `hourly[]`: hour-of-day MAE/WAPE/RMSE and advantage-hour counts

## model_backtest Key Fields
- `methodology`: backtest strategy and split point
- `trainPeriod`, `testPeriod`: training and test windows
- `baseline`, `lightgbm`: RMSE, MAE, MAPE, sample count
- `improvementPct`: LightGBM improvement against the baseline

---

# 6) reports/ai/daily/*.json

## Purpose
Provides an **AI-generated daily operations analysis** for the Daily Report tab. The AI report is a narrative layer over deterministic JSON outputs; it must not recalculate metrics or autonomously change model settings.

## Path Examples
- `web/public/reports/ai/daily/2026-05-23.json`
- `web/public/reports/ai/daily/index.json`
- `web/public/reports/ai/daily/ko/2026-05-23.json`
- `web/public/reports/ai/daily/en/2026-05-23.json`
- `web/public/reports/ai/daily/ja/2026-05-23.json`

## Daily Report Schema
```json
{
  "schemaVersion": "1.0.0",
  "reportType": "ai_daily_operation_report",
  "timezone": "Asia/Tokyo",
  "date": "2026-05-23",
  "generatedAt": "2026-05-24T09:25:00+09:00",
  "availability": "ok",
  "language": "ko",
  "contentLanguage": "ko",
  "generator": {
    "provider": "fallback",
    "model": null,
    "localizationModel": null,
    "localizationStatus": "not_requested",
    "localizationFallback": null,
    "promptVersion": "fallback_rules_v1",
    "schemaVersion": "1.0.0"
  },
  "inputRefs": {
    "operationReport": "reports/daily/2026-05-23.json",
    "internalDiagnostics": "reports/internal/daily-diagnostics/2026-05-23.json",
    "operationalCalibration": "reports/internal/operational-calibration/2026-05-23.json",
    "operationalCalibrationHistory": "reports/internal/operational-calibration/snapshots/2026-05-23/index.json",
    "alerts": "alerts/2026-05-23.json",
    "forecast": "forecast/2026-05-23.json",
    "actual": "actual/2026-05-23.json",
    "metrics": "metrics/forecast_accuracy.json"
  },
  "inputSnapshot": {
    "schemaVersion": "1.0.0",
    "createdAt": "2026-05-24T09:25:00+09:00",
    "fingerprint": "sha256:...",
    "sources": {
      "operationReport": {
        "path": "reports/daily/2026-05-23.json",
        "exists": true,
        "date": "2026-05-23",
        "generatedAt": "2026-05-24T09:20:00+09:00",
        "fingerprint": "sha256:..."
      }
    }
  },
  "dataQuality": {
    "comparableHours": 21,
    "observedHours": 21,
    "fallbackActualHours": 0,
    "calibrationSnapshotCount": 3,
    "limitations": []
  },
  "executiveSummary": {
    "severity": "warning",
    "headline": "Morning ramp overprediction dominated the daily miss.",
    "summary": "The model trailed TEPCO overall, mainly due to large 07:00-08:00 misses and a later residual handoff issue.",
    "modelVerdict": "tepco_better",
    "confidence": "medium"
  },
  "performance": {
    "comparableHours": 21,
    "modelMaeMw": 535.2,
    "tepcoMaeMw": 279.0,
    "modelWapePct": 2.23,
    "tepcoWapePct": 1.16,
    "modelRmseMw": 732.9,
    "tepcoRmseMw": 382.4,
    "modelMaxErrorMw": 2008.3,
    "tepcoMaxErrorMw": 1110.0,
    "modelMaxErrorHour": 8,
    "tepcoMaxErrorHour": 8,
    "maeGapMw": 256.2,
    "wapeGapPct": 1.07,
    "verdict": "tepco_better",
    "modelAdvantageHours": 3,
    "tepcoAdvantageHours": 18,
    "equalHours": 0,
    "modelAdvantageRate": 0.143
  },
  "rootCauseHypotheses": [
    {
      "id": "h1",
      "severity": "warning",
      "confidence": "medium",
      "evidenceStatus": "partial",
      "title": "Business-day lag may have contaminated the non-business morning ramp.",
      "explanation": "The largest misses occurred during the morning ramp while lag_24h came from a different business type.",
      "mechanism": "The previous business-day lag can lift early non-business demand before same-day observations have enough weight.",
      "nextCheck": "Replay the 06:00-11:00 band and compare lag_24h, recent_same_business_type_mean, and intraday calibration deltas.",
      "sourceEventIds": ["top_miss_h8"],
      "evidence": [
        {
          "source": "reports/daily",
          "metric": "modelAbsErrorMw",
          "value": 2008.3,
          "unit": "MW",
          "hour": 8,
          "timeBand": "morning_ramp"
        }
      ],
      "relatedHours": [7, 8],
      "relatedTimeBands": ["morning_ramp"],
      "relatedFeatures": [
        "lag_24h",
        "lag_24h_business_type_mismatch",
        "recent_same_business_type_mean"
      ],
      "counterEvidence": [
        "The model recovered around 09:00, so the issue may be limited to early ramp handoff."
      ]
    }
  ],
  "featureRecommendations": [
    {
      "id": "r1",
      "priority": "medium",
      "type": "calibration",
      "target": "intraday_correction.business_type_transition_prior",
      "suggestion": "Review whether the prior handoff should remain active until the latest observed hour reaches the morning ramp.",
      "expectedEffect": "Reduce early non-business overprediction when the previous day's lag is overheated.",
      "risk": "Can suppress genuinely high weekend demand if the same-business anchor is too low.",
      "validationPlan": "Replay recent Friday-to-Saturday transitions and compare MAE/WAPE before and after the change.",
      "linkedHypotheses": ["h1"],
      "autoApply": false
    }
  ],
  "operatorNotes": [
    "Feature recommendations are review candidates only and must not be applied automatically."
  ],
  "limitations": [
    "The AI report is an interpretation of deterministic metrics, not a source of truth."
  ]
}
```

## Index Schema
```json
{
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",
  "generatedAt": "2026-05-24T09:25:00+09:00",
  "availability": "ok",
  "latest": {
    "date": "2026-05-23",
    "availability": "ok",
    "severity": "warning",
    "headline": "Morning ramp overprediction dominated the daily miss.",
    "modelVerdict": "tepco_better"
  },
  "reports": [
    {
      "date": "2026-05-23",
      "availability": "ok",
      "severity": "warning",
      "headline": "Morning ramp overprediction dominated the daily miss.",
      "modelVerdict": "tepco_better",
      "modelMaeMw": 535.2,
      "tepcoMaeMw": 279.0
    }
  ]
}
```

## Field Rules
- `performance` must be copied from deterministic daily report metrics; the AI generator must not invent or recompute these values.
- `rootCauseHypotheses[].evidence[]` must cite an input source and metric.
- `rootCauseHypotheses[].mechanism` describes the causal path; `nextCheck` names the replay, field, or diagnostic to inspect before changing code.
- `rootCauseHypotheses[].sourceEventIds` links the narrative hypothesis back to `analysisPriorities.events`.
- `inputRefs.operationalCalibration` is optional and may be `null` when no intraday calibration report exists for that date.
- `inputRefs.operationalCalibrationHistory` is optional and may be `null` when no intraday calibration snapshot index exists for that date.
- `inputSnapshot` records the deterministic input version used by the AI narrative. Its fingerprint changes when referenced input JSON changes, but existing AI report bodies remain frozen unless explicitly regenerated.
- `rootCauseHypotheses[].evidenceStatus` is `"confirmed"` only when an input JSON contains a direct flag or control value, `"partial"` for strong metric/feature evidence, and `"not_observed"` when the overwritten intraday timeline prevents verification. `"not_observed"` hypotheses must use `confidence: "low"`.
- `featureRecommendations[]` are candidate improvements only. `autoApply` is always `false`.
- `relatedFeatures[]` may include internal feature names because this tab is an operational analysis view.
- A successful deterministic fallback report uses `availability: "ok"`, `generator.provider: "fallback"`, and `generator.model: null`. When an OpenAI key is available, OpenAI only generates the narrative layer; `performance`, `inputRefs`, and `dataQuality` are still fixed by deterministic code. `availability: "failed"` is used only when report generation was attempted and failed.
- `language` is the generated report language. Reports are generated separately for `ko`, `en`, and `ja`; the dashboard reads the subpath matching the active UI locale. The root `reports/ai/daily/YYYY-MM-DD.json` remains the Korean report for backward compatibility.
- `contentLanguage` is the language actually shown in the narrative. It normally matches `language`; if localization fails, `ko`/`ja` report paths may set `contentLanguage: "en"` and display the English master report.
- AI reports are generated only during ETL runs. Intraday/status-only runs do not create or update report bodies.
- If a report JSON already exists for the same date and language, later ETL retries preserve that file. The index may be rebuilt, but the report body and OpenAI call are not executed again.
- OpenAI calls are cost-capped by default: only the latest daily report date is eligible. The default chain uses low-cost models: first an English master analysis from the compact fact packet (`OPENAI_DAILY_REPORT_MODEL`, default `gpt-4o-mini`), then `ko`/`ja` localization from that English master (`OPENAI_DAILY_REPORT_LOCALIZATION_MODEL`, default `gpt-4o-mini`). Use `OPENAI_DAILY_REPORT_LOCALES`, `OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN`, and `OPENAI_DAILY_REPORT_LATEST_ONLY` to deliberately narrow or widen that scope. Set `OPENAI_DAILY_REPORT_MODEL` explicitly when a stronger analysis model is needed.
- If the localization call fails or returns invalid Korean/Japanese text, the localized report path falls back to the English master narrative with `generator.localizationStatus: "fallback_en"` and `generator.localizationFallback: "en"`.
- OpenAI receives a compact fact packet, not full hourly diagnostic rows. The fact packet includes Python-computed decision/summary fields such as `coverageContext`, `controllerDiagnosis`, `stageAttribution`, `bandQuality`, `freezeImpact`, and `rollingPatternContext`. Prompt input excludes fallback narrative objects, rule-based `insights`, file paths, SHA-256 fingerprints, and summary blocks that duplicate `performance`. Deterministic metrics, input references, data quality, and `inputSnapshot` remain owned by Python code.

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
