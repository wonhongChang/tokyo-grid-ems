# Data Retention and Archive Strategy

> Operational policy for keeping the GitHub Pages dashboard public while avoiding unbounded repository growth.

Languages: [한국어](../ko/data-retention-strategy.md) · [日本語](../ja/data-retention-strategy.md)

---

## Context

TokyoGridEMS publishes static JSON files through GitHub Pages. This keeps the system simple: GitHub Actions collects TEPCO/Open-Meteo data, writes JSON/parquet/model outputs, and GitHub Pages serves them without a backend server.

That simplicity is useful for a public portfolio project, but Git should not become a long-term database. If every daily JSON, model pickle, and cache snapshot is committed forever, clone size and Actions checkout time will gradually grow.

## Operating Principle

Use the repository as a public serving layer, not as the permanent data warehouse.

- GitHub Pages should keep the latest dashboard state and a bounded recent history.
- TEPCO CSV/ZIP data remains the source of truth for historical actual demand.
- Model forecast JSON is an operational output, useful for validation, but it should not become an infinite daily file store.
- Long-term public history should be compacted into monthly archive or metrics files that Pages can still fetch statically.

## Recommended Retention Policy

| Data type | Keep as daily JSON | Long-term form | Notes |
|---|---:|---|---|
| `status.json` | current only | none | latest dashboard summary |
| `actual/YYYY-MM-DD.json` | recent 180-365 days | monthly archive JSON | historical actuals are reproducible from TEPCO CSV/ZIP |
| `forecast/YYYY-MM-DD.json` | recent 180-365 days | monthly archive or daily metrics | old forecasts matter mainly for evaluation |
| `alerts/YYYY-MM-DD.json` | recent 180-365 days | monthly archive or summary metrics | keeps UI responsive |
| `metrics/*.json` | keep | compact rolling/monthly metrics | small and portfolio-relevant |
| `.hourly_cache.parquet` | current snapshot only | rebuildable from sources | useful for Actions, risky if committed forever with history |
| `.lgbm_model.pkl` | current model only | retrainable artifact | binary history can grow quickly |

## Proposed Public Layout

```text
web/public/
  status.json
  actual/YYYY-MM-DD.json
  forecast/YYYY-MM-DD.json
  alerts/YYYY-MM-DD.json

  archive/
    actual/2026-05.json
    forecast/2026-05.json
    alerts/2026-05.json

  metrics/
    forecast_accuracy.json
    model_backtest.json
    daily_mae.json
```

The dashboard should load recent daily files by default. If a future UI needs older data, it can fetch the relevant monthly archive file on demand.

## Why Not an External Database Yet

An external store such as S3, R2, Supabase, or a managed database would solve repository growth, but it would also add CORS, public access rules, credentials, cost, and another operational dependency.

For this project, the better trade-off is:

- keep GitHub Pages as the only public hosting layer
- compact old public data into static monthly files
- keep the first screen lightweight
- avoid private API keys or backend infrastructure

## Forecast Data Boundary

Past model forecast JSON should not be used as training actuals. Training and lag features should come from TEPCO actuals, with TEPCO forecast fallback only for hours where the latest intraday actual has not been published yet.

This prevents the model from feeding its own forecasts back into future training data.

## Future Implementation Tasks

1. Add a `retention_days` setting to `config.yaml`.
2. Add an ETL cleanup step that compacts old daily JSON into `archive/{actual,forecast,alerts}/YYYY-MM.json`.
3. Keep only recent daily JSON files after archive creation.
4. Add a link/index file for archive months if the UI needs historical browsing.
5. Consider making `.hourly_cache.parquet` and `.lgbm_model.pkl` rebuildable or stored outside long-term Git history if repository size becomes a problem.

