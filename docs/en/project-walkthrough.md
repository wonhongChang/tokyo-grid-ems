# Project Walkthrough for Students

Languages: [한국어](../ko/project-walkthrough.md) · [日本語](../ja/project-walkthrough.md)

This document explains Tokyo Grid EMS for someone learning programming and data engineering.

---

## What This Project Does

Tokyo Grid EMS takes electricity demand CSV files published by TEPCO and turns them into a web dashboard.

The dashboard answers four questions:

1. What happened yesterday?
2. Are there any anomaly alerts?
3. What will electricity demand look like today and tomorrow?
4. Is this project's model performing better or worse than TEPCO's forecast?

---

## The Big Picture

```text
TEPCO CSV files
  -> Python ETL
  -> cleaned hourly data
  -> forecast model
  -> anomaly detection
  -> JSON files
  -> React dashboard on GitHub Pages
```

There is no always-running backend server. GitHub Actions runs the Python jobs, saves JSON files, and GitHub Pages serves the static dashboard.

---

## Two Kinds of TEPCO Data

TEPCO provides data in two different ways.

| Data | When it updates | How the project uses it |
|---|---|---|
| Monthly ZIP | around morning JST, includes confirmed historical data | main ETL source |
| Intraday CSV | updated through the current day | fills today's actuals before the monthly ZIP catches up |

This is why the project has two workflows:

- `ETL + Deploy`: handles confirmed data and model training.
- `Intraday Update`: refreshes today's data and forecasts.

---

## Main Folders

```text
python/
  etl/                 data download, parsing, cache, JSON writing
  forecast/            baseline, LightGBM, feature building, intraday correction
  anomaly/             anomaly detection rules
  eval/                model backtest and TEPCO comparison

web/
  src/                 React dashboard source
  public/              generated JSON during workflow runtime

docs/                  project documentation
tests/                 automated tests
```

If you are learning the project, read files in this order:

1. `python/etl/fetch_tepco.py`
2. `python/tepc_parser.py`
3. `python/etl/run_batch.py`
4. `python/forecast/feature_builder.py`
5. `python/forecast/lgbm_model.py`
6. `python/anomaly/detector.py`
7. `web/src/App.tsx`
8. `web/src/components/ForecastChart.tsx`
9. `web/src/components/ValidationPanel.tsx`

---

## What ETL Means Here

ETL means:

- Extract: download TEPCO CSV or ZIP files.
- Transform: parse Japanese CSV tables, convert units, attach timestamps, enrich weather data.
- Load: write dashboard-ready JSON files.

The project writes files like:

```text
status.json
actual/YYYY-MM-DD.json
forecast/YYYY-MM-DD.json
alerts/YYYY-MM-DD.json
metrics/forecast_accuracy.json
metrics/model_backtest.json
```

The React app does not compute forecasts. It reads these files and visualizes them.

---

## Why There Is a Cache

Forecasting needs historical rows. Re-parsing every CSV every time would be slow, so the ETL keeps an hourly cache:

```text
web/public/.hourly_cache.parquet
```

The cache stores hourly actual demand, TEPCO forecast, supply, usage rate, and temperature.

Generated cache/data files are not committed to `main`. GitHub Actions stores them on the `data` branch.

---

## Forecasting in Plain Language

The model tries to answer:

> "For each hour tomorrow, what demand value is likely?"

It uses clues such as:

- same hour yesterday,
- same hour last week,
- weekday or holiday,
- recent rolling average,
- temperature,
- whether yesterday's lag was distorted by a holiday period.

LightGBM learns patterns from these clues. The baseline model remains as a backup.

---

## Intraday Correction

During the day, the model can compare early actuals with its own forecast.

If actual demand is consistently higher than the model expected, the remaining hours are adjusted upward. If actual demand is lower, they are adjusted downward.

At 23:40 JST, TEPCO may still not have the final 23:00 actual. In that special case, TEPCO's forecast is marked as:

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

That value can help the next forecast input, but it is excluded from model scoring and anomaly actual checks.

---

## Anomaly Detection

The project detects three kinds of events.

| Event | Meaning |
|---|---|
| Reserve Risk | usage rate is high, so supply margin is tight |
| Spike / Drop | actual demand is outside the forecast band |
| Drift | the model is biased in one direction for several hours |

This separation is important because "the model missed" and "the grid is under supply pressure" are different problems.

---

## Validation

The Validation tab has two jobs.

| Report | Purpose |
|---|---|
| Model backtest | checks whether LightGBM improves over the baseline on historical data |
| Forecast accuracy | compares the project model with TEPCO's published forecast during operation |

TEPCO's forecast is a strong official baseline. The goal is not to claim that the project always wins, but to show honest operational performance.

---

## What To Learn From This Project

This project is useful for learning:

- how scheduled data pipelines work,
- why real-world data timing matters,
- how to separate generated data from source code,
- how to build a static dashboard without a backend server,
- how to evaluate a model fairly,
- how to document model limitations.
