# Ops Report Tab

The Ops Report tab provides a daily operational explanation of the previous day's power-demand forecast. The Validation tab focuses on quantitative metrics such as MAE, WAPE, and RMSE; the Ops Report tab explains **why the errors happened**, **which calibration layers may be related**, and **what should be reviewed next**.

---

## Purpose

The tab is designed for daily operational review.

- Summarize the previous day's model-vs-TEPCO performance
- Highlight the largest misses and affected time bands
- Present root-cause hypotheses related to lag, weather, business-day transitions, and intraday calibration
- Record feature or calibration recommendations as review candidates, not automatic changes

The Ops Report does not modify the forecast model.

---

## Data Flow

The report is generated during ETL.

```text
TEPCO CSV / forecast JSON / actual JSON
  -> reports/daily/YYYY-MM-DD.json
  -> reports/internal/daily-diagnostics/YYYY-MM-DD.json
  -> reports/internal/operational-calibration/YYYY-MM-DD.json
  -> reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json
  -> Dashboard Ops Report tab
```

By default, only the latest finalized daily report date, usually yesterday, is eligible for OpenAI generation. If a report already exists for the same date and language, ETL preserves it to avoid repeated API cost.

Intraday/status-only runs update same-day data and forecasts, but do not rewrite Ops Report bodies.

---

## Generation Modes

| Mode | Condition | Description |
|------|-----------|-------------|
| deterministic fallback | No OpenAI key or OpenAI disabled | Python rules summarize metrics and top misses |
| OpenAI narrative | `OPENAI_API_KEY` is available | OpenAI writes the narrative layer from a compact fact packet |

Even with OpenAI enabled, deterministic Python code owns the performance metrics, input references, data-quality fields, coverage separation, stage attribution, controller diagnosis, and band quality. OpenAI does not recompute metrics.

---

## Localization

OpenAI reports use a two-step chain.

1. Generate an English master analysis
2. Localize the English master into Korean and Japanese

Default models:

```text
OPENAI_DAILY_REPORT_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_LOCALIZATION_MODEL=gpt-4o-mini
```

If localization fails or times out, the localized report path falls back to the English master text.

```json
{
  "contentLanguage": "en",
  "generator": {
    "localizationStatus": "fallback_en",
    "localizationFallback": "en"
  }
}
```

The UI detects this state and shows an English-source badge.

---

## UI Sections

### Header

Shows the selected date, generation provider, severity, and model verdict.

- `provider: "fallback"`: system-generated diagnostic
- `provider: "openai"`: AI operational narrative
- `contentLanguage !== language`: English fallback text is being shown

### Metric Cards

Summarize model-vs-TEPCO performance.

- MAE
- WAPE
- RMSE
- Max error
- Model advantage hours versus TEPCO

Power units follow the current UI locale. Japanese UI uses `万kW` to match TEPCO convention.

### Root-Cause Hypotheses

`rootCauseHypotheses[]` cards explain likely causes. Each hypothesis includes:

- Title and explanation
- Related hours and time bands
- Related features or calibration layers
- `evidenceStatus`
- Counter-evidence

`evidenceStatus` indicates evidence quality.

| Value | Meaning |
|-------|---------|
| `confirmed` | Direct flags or control values exist in input JSON |
| `partial` | Metrics/features provide strong circumstantial evidence |
| `not_observed` | Intermediate history cannot be verified |

`not_observed` hypotheses use low confidence so the UI does not overstate unverified claims.

### Recommendations

`featureRecommendations[]` records model or calibration review candidates.

```json
{
  "autoApply": false
}
```

The report can suggest improvements, but never applies them automatically.

### Date Selector

The tab reads `reports/ai/daily/{locale}/index.json` and lists report dates.

```text
2026-05-22
2026-05-23
2026-05-24
```

The UI does not scan the whole folder. The default index range is recent days, so the selector does not grow without bound.

---

## Cost Control

- Only the latest finalized date is eligible for OpenAI by default
- Default maximum: 3 OpenAI calls per ETL run, including one localization validation retry
- Existing report files are preserved
- OpenAI receives a compact fact packet, not full hourly raw rows
- The fact packet includes computed fields such as `controllerDiagnosis`, `stageAttribution`, `bandQuality`, `freezeImpact`, `coverageContext`, and `rollingPatternContext`
- Fallback narratives, full hourly diagnostics, SHA fingerprints, and file paths are excluded from the prompt

Defaults:

```text
OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN=3
OPENAI_DAILY_REPORT_LATEST_ONLY=true
OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90
OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180
```

GitHub Actions only requires the `OPENAI_API_KEY` secret. Other values can be tuned later with repository variables.

---

## JSON Paths

```text
web/public/reports/ai/daily/index.json
web/public/reports/ai/daily/ko/index.json
web/public/reports/ai/daily/en/index.json
web/public/reports/ai/daily/ja/index.json
web/public/reports/ai/daily/{locale}/YYYY-MM-DD.json
```

The root `reports/ai/daily/YYYY-MM-DD.json` path remains the Korean report for backward compatibility.
