# 2026-05-14 Lag Temperature Regime Features

> Feature-side improvement for season-transition periods where last week's demand lag can be too low.

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md)

---

## Why This Was Needed

On 2026-05-14, the model did receive the previous day's TEPCO actuals through `lag_24h`, but the 09:00-13:00 forecast was still pulled down by lower `lag_168h`, lower 4-week same-hour averages, and weak temperature signals.

That exposed a feature gap: during season transitions, the same hour one week ago may be a poor demand anchor when weather conditions have changed.

## Forecasting Change

The LightGBM feature set now includes:

- `temp_delta_168h`: current same-hour temperature minus the temperature 168 hours ago
- `cooling_delta_168h`: current same-hour cooling degree minus the cooling degree 168 hours ago

The cooling and heating balance points are no longer hard-coded inside feature engineering. They are configured in `config.yaml`:

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 10.0
```

Because the feature columns changed, the LightGBM model compatibility version was bumped. Existing saved models are treated as stale and will be retrained by the next ETL/intraday run.

Intraday runs also refresh virtual forecast-weather rows while `actual_mw` is still missing. This prevents stale morning weather forecasts from locking the model into an outdated daily temperature curve.

## Design Boundary

This does not use TEPCO forecast values as model inputs. It only adds weather-derived context so the model can learn when week-over-week demand lags should be trusted less.
