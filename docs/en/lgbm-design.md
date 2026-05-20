# LightGBM Forecast Model Design

> Current production design: LightGBM quantile regression with calendar, lag, holiday, weather, and intraday correction features.

Languages: [한국어](../ko/lgbm-design.md) · [日本語](../ja/lgbm-design.md)

---

## Role in the System

The model forecasts hourly electricity demand for Tokyo Grid EMS. It is used to generate:

- today's forecast after intraday actuals are refreshed,
- tomorrow's forecast,
- forecast bands displayed on the dashboard,
- expected values used by anomaly detection.

The statistical baseline (`baseline_dow_hour_mean`) remains as a fallback when LightGBM is unavailable, lacks enough training rows, or fails during prediction.

---

## Model

`python/forecast/lgbm_model.py` trains three LightGBM quantile regressors.

| Model | Purpose |
|---|---|
| q025 | lower p95 interval estimate |
| q50 | point forecast |
| q975 | upper p95 interval estimate |

The dashboard uses q50 as the main forecast line. q025/q975 are normalized into the displayed p95 forecast band, and a wider p99-style band is derived heuristically from the q025/q975 spread.

Minimum training data:

```text
90 days * 24 hourly rows
```

If this condition is not met, the pipeline falls back to the statistical baseline.

---

## Features

Feature engineering lives in `python/forecast/feature_builder.py`.

| Group | Examples | Why it matters |
|---|---|---|
| Calendar | hour, weekday, month, weekend, public holiday | captures daily and weekly demand rhythm |
| Lag | 24h, 48h, 168h, 336h | captures demand persistence |
| Rolling stats | 4-week same hour/weekday mean and std | provides stable local history |
| Holiday correction | last business day, consecutive holidays, days since holiday end | avoids underestimating post-holiday demand |
| Weather | temperature, apparent temperature, configurable cooling/heating degree, temperature anomalies, 24h/168h temperature and cooling deltas, 72h thermal memory | captures HVAC-driven demand and day-over-day/week-over-week regime changes |
| Interactions | holiday x heat, post-holiday x heat | handles Golden Week and similar return-to-work spikes |
| Lag context | lag_24h_dsh, lag_24h_consec, lag_168h_dsh, lag_24h business-type mismatch, recent same business-type mean | tells the model when lag values are holiday-contaminated or crossed a business/non-business boundary |

The current feature set has 50 explicit LightGBM training features.

Cooling/heating degree balance points are configured in `config.yaml`:

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 18.0
```

`temp_delta_24h` and `cooling_delta_24h` help the model decide how much to trust yesterday's same-hour demand when today's weather has shifted. `temp_delta_168h` and `cooling_delta_168h` do the same for the same-hour value from one week ago. `temp_72h_mean`, `cooling_degree_72h_mean`, and `heating_degree_72h_mean` capture sustained heat or cold. `apparent_temp_c` and `apparent_cooling_degree` add a feels-like temperature signal when the weather source provides one.

`lag_24h_business_type_mismatch` and `lag_24h_mismatch_x_business_hour` help the model treat Friday-to-Saturday and Sunday-to-Monday lag values more carefully, especially during daytime business hours. `recent_same_business_type_mean` provides a broader same-hour anchor from recent business or non-business days.

`lag_24h_hourly_delta`, `lag_168h_hourly_delta`, and `recent_same_business_type_delta_mean` are built as inference-only context for internal diagnostics and the noon transition guard. They are not part of the LightGBM training feature set because validation showed that global hourly-delta training features could disturb unrelated morning hours.

---

## Intraday Correction

`python/forecast/intraday_correction.py` adjusts the remaining hours of today's forecast using recent residuals:

```text
residual = actualMw - modelForecastMw
```

It uses the latest observed same-day hours, applies shrinkage, caps extreme adjustments, and decays the adjustment across future hours.

At the final 23:00 hour, if TEPCO has not published the actual value by the 23:40 JST refresh, the pipeline may use TEPCO's forecast as a marked fallback:

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

This fallback is allowed as an operational forecast input, but is excluded from model validation metrics and anomaly actual checks.

## Daytime Heat Guard

`python/forecast/adjustment.py` applies a conservative post-processing guard before intraday correction. On business days, when the same-hour 168h lag points to a holiday/weekend and the current daytime temperature anomaly is high, the guard prevents analogous-day adjustment from pushing daytime forecasts downward. It also applies a smaller warm-business-day guard when daytime temperature is high for the season, even without holiday-lag contamination. Non-business-day heat is left to the LightGBM weather features rather than a manual upward guard.

See [Daytime Heat Guard Improvement](model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md) for the incident analysis, implementation details, and validation result.

See [Warm Daytime Bias Guard](model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md) for the follow-up warm-day generalization.

See [Lag Temperature Regime Features](model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md) for the feature-side follow-up.

See [24h Weather Delta and Apparent Temperature Features](model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md) for the next feature-side follow-up.

See [Business-Type Lag Features](model-improvements/model-improvement-2026-05-16-business-type-lag-features.md) for the weekend/weekday transition follow-up.

See [Midday Transition Guard](model-improvements/model-improvement-2026-05-20-midday-transition-features.md) for the 12:00 lag-shape follow-up.

---

## Training and Inference Flow

1. ETL loads confirmed historical TEPCO data from monthly ZIP files.
2. Weather enrichment fills historical and forecast temperature / apparent-temperature features.
3. LightGBM is trained and saved to `web/public/.lgbm_model.pkl`.
4. The status/intraday workflow reloads the model.
5. Recent actual JSON files are injected into the cache to fill gaps before the monthly ZIP is updated.
6. Today's forecast is generated and adjusted with intraday residual correction.
7. Tomorrow's forecast is generated using the same enriched cache.
8. JSON outputs are written under `web/public/forecast/`.

---

## Evaluation

Two reports are generated:

- `metrics/model_backtest.json`: offline LightGBM vs baseline backtest with train/test separation.
- `metrics/forecast_accuracy.json`: operational comparison against TEPCO's published forecast.

The operational comparison is a scorecard, not a claim that the project always beats TEPCO. TEPCO may use internal information unavailable to this project.
