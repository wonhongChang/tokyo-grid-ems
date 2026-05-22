# Validation Metrics Scorecard

Languages: [한국어](../../../ko/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md) / [日本語](../../../ja/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md)

## Background

The validation tab originally emphasized MAE and hourly win counts. That was useful for a first dashboard, but it could make the operational comparison look like a sports score. Power demand forecasting needs a broader scorecard: average error, total-load error rate, large single-hour misses, and the number of hours where each forecast was closer.

## Change

- Kept `MAE` as the headline MW metric because it is easy to understand.
- Added `WAPE` to compare error against total actual demand.
- Added `RMSE` and max-error fields to surface large forecast-risk events.
- Renamed the UI concept from win/loss to operational assessment and advantage hours.
- Added a `mixed` verdict for days where average error and large-error risk point in different directions.
- Preserved legacy `modelWins`, `tepcoWins`, and `modelWinRate` fields for backward compatibility.

## Operational Interpretation

The dashboard now treats hourly advantage counts as supporting context, not as the primary ranking. A model can have more advantage hours but still be less useful operationally if it creates one or two large misses. In that case, WAPE/RMSE and the `mixed` verdict make the risk visible.

## Affected Outputs

- `web/public/metrics/forecast_accuracy.json`
- `web/public/reports/daily/*.json`
- Dashboard validation tab

## Validation

- `py -m pytest -q`
- `npm.cmd run build`
