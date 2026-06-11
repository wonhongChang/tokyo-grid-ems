# LightGBM Forecast Model Design

> Current production design: LightGBM quantile regression with calendar, lag, holiday, weather, and operational calibration layers.

Languages: [한국어](../ko/lgbm-design.md) · [日本語](../ja/lgbm-design.md)

Operational reference: [Model operations specification](model-operations-spec.md)

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

The dashboard uses q50 as the main forecast line. q025/q975 are normalized into the displayed p95 forecast band, and a wider p99-style band is derived heuristically from the q025/q975 spread. When one side of the quantile interval collapses near q50, the pipeline keeps only a minimum width on that side instead of mirroring the opposite side's larger uncertainty. When an independent quantile model produces a rare one-sided tail explosion after a weather-regime shift, interval sanity calibration caps the maximum p95 half-width and the upper/lower asymmetry ratio without changing q50.

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
| Weather | temperature, humidity, apparent temperature, discomfort index, configurable cooling/heating degree, temperature anomalies, 1h/2h/24h/168h temperature and cooling deltas, 24h humidity/discomfort deltas, 3h/6h/72h thermal memory | captures HVAC-driven demand, warm-humid discomfort, weather direction, and day-over-day/week-over-week regime changes |
| Interactions | holiday x heat, post-holiday x heat | handles Golden Week and similar return-to-work spikes |
| Business/weather interactions | business-morning x temperature/humidity/discomfort delta, business-daytime x discomfort, late-afternoon x temperature/cooling delta | helps the model distinguish morning ramp-up, humid daytime load, afternoon cooling decay, and hysteresis-like demand behavior |
| Lag context | lag_24h_dsh, lag_24h_consec, lag_168h_dsh, lag_24h business-type mismatch, recent same business-type mean, lag-to-anchor gaps | tells the model when lag values are holiday-contaminated or crossed a business/non-business boundary |

The current feature set has 63 explicit LightGBM training features.

Cooling/heating degree balance points are configured in `config.yaml`:

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 18.0
```

Weather enrichment now prefers JMA AMeDAS observations for past/current hours and JMA official forecast temperatures for future hours. Open-Meteo JMA is kept as a humidity fallback only; it does not overwrite JMA forecast temperatures. Humidity-derived apparent temperature and discomfort index values are used to keep cooling-demand features stable when official forecast humidity is unavailable.

`temp_delta_24h` and `cooling_delta_24h` help the model decide how much to trust yesterday's same-hour demand when today's weather has shifted. `temp_delta_168h` and `cooling_delta_168h` do the same for the same-hour value from one week ago. `temp_delta_1h`, `temp_delta_2h`, `apparent_temp_delta_1h`, and `cooling_delta_1h` capture short-term weather direction. `cooling_degree_3h_mean`, `cooling_degree_6h_mean`, `heating_degree_3h_mean`, `heating_degree_6h_mean`, `temp_72h_mean`, `cooling_degree_72h_mean`, and `heating_degree_72h_mean` capture sustained heat or cold. `apparent_temp_c` and `apparent_cooling_degree` add a feels-like temperature signal when the weather source provides one.

`humidity_pct`, `discomfort_index`, `humidity_delta_24h`, and `discomfort_delta_24h` expose warm-humid discomfort directly instead of relying only on apparent temperature. The 24h deltas are clipped before model input so fallback humidity noise cannot dominate a forecast.

`business_morning_x_temp_delta_24h`, `business_morning_x_temp_anomaly_7d`, and `business_morning_x_temp_anomaly_doy` help business-day morning ramps respond to weather regime changes. `business_morning_x_humidity_delta_24h`, `business_morning_x_discomfort_delta_24h`, and `business_daytime_x_discomfort_index` add direct humid-morning and humid-daytime context. `business_late_afternoon_x_temp_delta_1h` and `business_late_afternoon_x_cooling_delta_1h` help the model avoid treating a cooling afternoon and a warming afternoon as the same demand state.

`lag_24h_business_type_mismatch` and `lag_24h_mismatch_x_business_hour` help the model treat Friday-to-Saturday and Sunday-to-Monday lag values more carefully, especially during daytime business hours. `recent_same_business_type_mean`, `lag_24h_to_last_biz_gap`, `lag_24h_to_same_business_type_gap`, and `lag_24h_gap_x_business_hour` provide broader same-hour anchors and gap signals from recent business or non-business days.

`lag_24h_hourly_delta`, `lag_168h_hourly_delta`, `recent_same_business_type_delta_mean`, `recent_same_business_type_delta_q25`, same-day latest actual hour/delta, and midday interaction context are built as inference-only context for internal diagnostics and local shape guards. They are not part of the LightGBM training feature set because validation showed that global hourly-delta training features could disturb unrelated morning hours.

---

## Intraday Correction

`python/forecast/intraday_correction.py` adjusts the remaining hours of today's forecast using recent residuals:

```text
residual = actualMw - modelForecastMw
```

It uses the latest observed same-day hours, applies shrinkage, caps extreme adjustments, and decays the adjustment across future hours.

The correction layer is no longer a plain residual carry-over. It also includes operational calibration rules for:

- day-boundary residual carry-over that skips TEPCO forecast fallback rows,
- day-level scale bias when overheated lag values conflict with cooler same-day conditions,
- business/non-business transition priors and observed transition correction,
- positive residual mitigation for overheated weekend ramps,
- negative residual recovery damping when a non-business day recovers toward its anchor,
- positive residual slope damping when recent actual demand is rolling over,
- morning ramp continuity guard for business-day near-term dips,
- evening decline continuity guard for near-term rebound spikes after actual demand starts falling.

Per-hour residual carry-over and guard metadata are written into operational calibration snapshots so that daily AI/Ops reports can explain why a served forecast changed.

At the final 23:00 hour, if TEPCO has not published the actual value by the 23:40 JST refresh, the pipeline may use TEPCO's forecast as a marked fallback:

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

This fallback is allowed as an operational forecast input, but is excluded from model validation metrics and anomaly actual checks.

## Daytime Heat Guard

`python/forecast/adjustment.py` applies a conservative post-processing guard before intraday correction. On business days, when the same-hour 168h lag points to a holiday/weekend and the current daytime temperature anomaly is high, the guard prevents analogous-day adjustment from pushing daytime forecasts downward. It also applies a smaller warm-business-day guard when daytime temperature is high for the season, even without holiday-lag contamination. Non-business-day heat is left to the LightGBM weather features rather than a manual upward guard.

The same post-processing stage also includes `LocalizedShapeSpikeGuard`, which dampens unsupported one-hour afternoon peaks after the midday guard but before intraday calibration. It only acts when neighboring hours, lag shape, recent same-business-type shape, same-day slope, and weather deltas do not support a real local peak.

See [Daytime Heat Guard Improvement](model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md) for the incident analysis, implementation details, and validation result.

See [Warm Daytime Bias Guard](model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md) for the follow-up warm-day generalization.

See [Lag Temperature Regime Features](model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md) for the feature-side follow-up.

See [24h Weather Delta and Apparent Temperature Features](model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md) for the next feature-side follow-up.

See [Business-Type Lag Features](model-improvements/model-improvement-2026-05-16-business-type-lag-features.md) for the weekend/weekday transition follow-up.

See [Midday Transition Guard](model-improvements/model-improvement-2026-05-20-midday-transition-features.md) and [Midday Transition Guard Re-enabled](model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md) for the 12:00 lag-shape follow-up.

See [Business Return Anchor Shortfall Guard](model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md), [Positive Residual Slope Damping](model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md), [Morning Ramp Continuity Guard](model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md), [Evening Decline Continuity Guard](model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md), [Negative Residual Continuity Floor](model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md), [Forecast Interval Tail Sanity Guard](model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md), [Morning Warm-Lag Overreaction Guard](model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md), [Morning Positive Residual Carryover Damping](model-improvements/model-improvement-2026-06-05-morning-positive-carryover-damping.md), [Actual JSON Cache Persistence](model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md), [Business-Return Shape Veto](model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md), and [Humidity/Discomfort Features and Localized Shape Spike Guard](model-improvements/model-improvement-2026-06-11-humidity-discomfort-shape-spike-guard.md) for the latest operational guard and data-continuity layers.

---

## Training and Inference Flow

1. ETL loads confirmed historical TEPCO data from monthly ZIP files.
2. Weather enrichment fills JMA AMeDAS observed weather, JMA official forecast temperatures, and humidity fallback fields.
3. LightGBM is trained and saved to `web/public/.lgbm_model.pkl`.
4. The status/intraday workflow reloads the model.
5. Recent actual JSON files are injected into the cache and persisted to fill gaps before the monthly ZIP is updated.
6. Today's forecast is generated and adjusted with intraday residual correction.
7. Tomorrow's forecast is generated using the same enriched cache.
8. JSON outputs are written under `web/public/forecast/`.

---

## Evaluation

Two reports are generated:

- `metrics/model_backtest.json`: offline LightGBM vs baseline backtest with train/test separation.
- `metrics/forecast_accuracy.json`: operational comparison against TEPCO's published forecast, including MAE, WAPE, RMSE, dominance hours, and max-error risk.

The operational comparison is a scorecard, not a claim that the project always beats TEPCO. TEPCO may use internal information unavailable to this project.
