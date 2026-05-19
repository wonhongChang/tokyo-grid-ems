# 2026-05-19 Forecast Snapshots and Shape Diagnostics

> Operational follow-up for making intraday forecast incidents easier to inspect after the fact.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md)

---

## Why This Was Added

The previous 2026-05-19 issue was not only an accuracy problem. The important question was:

> What did the model believe at each update time, and why did the published line change shape?

Keeping only the latest `forecast/YYYY-MM-DD.json` answers the current dashboard state, but it does not preserve lead-time context. For an operational model, the update-time forecast history matters.

---

## Changes

### 1. Lead-time forecast snapshots

ETL and intraday runs now write bounded forecast snapshots under:

```text
web/public/forecast_snapshots/YYYY-MM-DD/
```

Each snapshot includes:

- target date
- generation time
- run type (`etl`, `intraday`, or manual refresh variants)
- model name/version
- peak summary
- full hourly forecast series
- number of observed and TEPCO fallback actual hours available at generation time

Retention is intentionally limited:

- `retention_days: 21`
- `max_per_day: 16`

This is enough to inspect recent operational behavior without turning the data branch into an unlimited database.

### 2. Shape diagnostics

The daily operation report now includes a `shape` section.

It compares hour-to-hour deltas for:

- actual demand
- this model forecast
- TEPCO forecast

This catches cases where point-level MAE alone hides an implausible line shape, for example a model line dropping by several thousand MW while actual demand only changes slightly.

### 3. Weather-delta diagnostics

Internal daily diagnostics now include:

- `coolingDelta24hByBand`
- `weatherDeltaRiskByBand`

These summaries are for checking whether 24h weather-delta features are helping or pulling the model in the wrong direction during morning/daytime/afternoon bands.

### 4. Negative residual damping

Intraday residual correction now dampens negative residual adjustments after midday.

This keeps the model from over-chasing a temporary positive model error and pushing near-future demand down too aggressively. The existing bidirectional ramp guard still handles the closest future hours.

---

## Safety Notes

- Snapshots are public static JSON on the data branch, but they are not linked from the UI.
- Snapshots are diagnostic artifacts, not training actuals.
- TEPCO forecast fallback remains limited to missing intraday actual hours.
- The change improves post-incident analysis before adding more aggressive model features.

---

## Tests

Added coverage for:

- snapshot retention and index generation
- observed vs fallback hour counts in snapshots
- shape-drop detection in daily operation reports
- weather-delta diagnostic summaries
- afternoon negative residual damping
