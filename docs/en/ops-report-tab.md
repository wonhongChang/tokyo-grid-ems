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
| OpenAI narrative | `TOKYO_GRID_EMS_OPENAI_API_KEY` is available | OpenAI writes the narrative layer from a compact fact packet |

Even with OpenAI enabled, deterministic Python code owns the performance metrics, input references, data-quality fields, coverage separation, stage attribution, controller diagnosis, and band quality. OpenAI does not recompute metrics.

---

## Error Direction Rule

The fact packet explicitly marks signed error direction before the model writes the narrative.

- `modelErrorMw = modelForecastMw - actualMw`
- `modelBiasMw = mean(modelForecastMw - actualMw)`
- positive values mean overprediction, or forecast above actual
- negative values mean underprediction, or forecast below actual

If an OpenAI hypothesis contradicts this sign rule, the report generator rejects that hypothesis and falls back to deterministic wording.

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
- `provider: "openai"`: AI Ops Analysis
- `contentLanguage !== language`: English fallback text is being shown

### Metric Cards

Summarize model-vs-TEPCO performance.

- MAE
- WAPE
- RMSE
- Max error
- Model advantage hours versus TEPCO

Power units follow the current UI locale. Japanese UI uses `万kW` to match TEPCO convention.

### Ops Diagnostics

Reports with `diagnosticContext` show a compact operational diagnostics summary.

- Final actual coverage
- Controller/base adjustment
- Forecast band quality
- Published forecast freeze impact

This section avoids exposing long internal logs as the primary reading path. Operators get a quick explanation of why the served forecast curve looked the way it did, while stage attribution and freeze details stay in a collapsible detail area.

### Root-Cause Hypotheses

`rootCauseHypotheses[]` cards explain likely causes. Each hypothesis includes:

- Title and explanation
- Mechanism: how the input features, calibration layer, or serving policy could have produced the miss
- Next check: the replay, diagnostic field, or snapshot to inspect before changing code
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

The UI renders each recommendation as an experiment-style ticket.

- Experiment candidate
- Expected effect
- Risk
- Validation plan

Recommendation copy should therefore stay in a backtest/replay candidate tone, not a production command tone.

### Date Selector

The tab reads `reports/ai/daily/{locale}/index.json` and lists report dates.

```text
2026-05-22
2026-05-23
2026-05-24
```

The UI does not scan the whole folder. The default index range is recent days, so the selector does not grow without bound.

---

### Operator Notes and Technical Details

Ordinary operator notes remain visible. Calibration signal catalogs appear in an initially collapsed `Technical details: calibration signals` section, accessible by keyboard. Long identifiers wrap on mobile. Known Korean, English and Japanese catalog labels are recognized; unknown notes stay visible. This presentation does not modify the source JSON or generated analysis.

## Activation and Report-only Recovery

Having a report key alone does not enable narrative calls in `run_batch.py`. For a Python ETL run, set the opt-in flag in the process environment before starting:

```powershell
$env:TOKYO_GRID_EMS_OPENAI_API_KEY='YOUR_REPORT_KEY'
$env:OPENAI_DAILY_REPORT_AUTO_ENABLE='true'
python python/etl/run_batch.py --input data/raw --out web/public
```

For Docker ETL, put those two variable names and values in the local `.env`; Compose loads them into the container. Never commit `.env` or credentials. The project report key is `TOKYO_GRID_EMS_OPENAI_API_KEY`, not the generic runtime variable `OPENAI_API_KEY`.

With existing daily evidence available, the dedicated CLI can recover a missing/fallback latest report without rerunning ETL:

```bash
python -m python.eval.ai_daily_report --public-dir web/public --languages ko,en,ja --use-openai --openai-max-calls 2
```

This writes local reports/indexes but does not publish them. It preserves successful existing OpenAI reports unless explicitly instructed to overwrite; the latest fallback can be replaced when a call succeeds. The local host orchestration uses the same report-only recovery path when yesterday is already finalized. These commands can incur API costs; they are not dashboard-preview commands.

## Cost Control

- Only the latest finalized date is eligible for OpenAI by default
- Default budget: 2 logical calls per generation run: one English master call and one Korean/Japanese localization call. Both models default to `gpt-4o-mini`.
- Successful existing OpenAI reports are preserved; missing/latest fallback reports can be recovered.
- A transient OpenAI HTTP error is retried once. If the first local morning ETL still stores a fallback for yesterday, the later scheduled runs retry only the report and publish it after a successful OpenAI response.
- OpenAI receives a compact fact packet with bounded focused evidence, not the full hourly source artifacts
- The fact packet includes computed fields such as `controllerDiagnosis`, `stageAttribution`, `bandQuality`, `freezeImpact`, `coverageContext`, and `rollingPatternContext`
- Fallback narratives, full hourly diagnostics, SHA fingerprints, and file paths are excluded from the prompt

Defaults:

```text
OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN=2
OPENAI_DAILY_REPORT_LATEST_ONLY=true
OPENAI_DAILY_REPORT_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_LOCALIZATION_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_HTTP_ATTEMPTS=2
OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90
OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180
```

Logical budget and HTTP attempts are different: `OPENAI_DAILY_REPORT_HTTP_ATTEMPTS=2` permits one retry for retryable HTTP responses within a logical call. These transport attempts do not consume another logical-call budget slot, so the logical budget is not a hard request-count or billing cap. A further localization/validation retry consumes an additional logical slot and is possible only if budget remains, for example with a budget of 3. Raising the budget is an explicit operator choice, not the default.

GitHub Actions can keep the repository secret named `OPENAI_API_KEY`, but the workflow maps it to the project-scoped runtime variable `TOKYO_GRID_EMS_OPENAI_API_KEY`. Model, budget, and timeout values can be supplied through the workflow's repository variables. The ETL opt-in flag must also reach the `run_batch.py` process; injecting a key does not replace that requirement.

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
