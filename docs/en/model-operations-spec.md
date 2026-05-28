# Model Operations Specification

> Operational reference for the TokyoGridEMS LightGBM forecast model, feature set, calibration layers, validation metrics, and maintenance runbook.

Languages: [한국어](../ko/model-operations-spec.md) · [日本語](../ja/model-operations-spec.md)

---

## 1. Model Overview

### Timezone Principle

All pipeline logic is standardized on JST (UTC+9). TEPCO and JMA data are Japan-time sources, while GitHub Actions cron expressions are UTC-based, so scheduling and data interpretation must be kept separate.

Operational rules:

- data row timestamps, forecast dates, and actual dates are interpreted in JST,
- GitHub Actions cron is written in UTC, with JST comments or documentation beside it,
- ETL, intraday update, daily report, and snapshot generation are evaluated on JST dates,
- day-boundary residual carry-over uses the JST date boundary, not UTC midnight.

| Item | Current value |
|---|---|
| Model family | LightGBM quantile regression |
| Implementation | `python/forecast/lgbm_model.py` |
| Feature builder | `python/forecast/feature_builder.py` |
| Post-processing | `python/forecast/adjustment.py`, `python/forecast/intraday_correction.py` |
| Interval version | `q025_q50_q975_p95_v9_weather_direction` |
| Minimum training rows | `90 * 24 = 2160` hourly rows |
| Fallback | `baseline_dow_hour_mean` |

The model forecasts hourly Tokyo-area electricity demand and produces today's forecast, tomorrow's forecast, p95/p99 forecast bands, and expected demand values for anomaly detection.

Three quantile regressors are trained:

| Model | alpha | Role |
|---|---:|---|
| `q025` | 0.025 | lower p95 estimate |
| `q50` | 0.50 | point forecast |
| `q975` | 0.975 | upper p95 estimate |

The dashboard uses `q50` as the main forecast line. `q025/q975` form the p95 band, while a wider p99-style band is derived by extending the q025/q975 half-width. If one side collapses near q50, the system keeps only the configured minimum width on that side instead of mirroring the wider side.

---

## 2. Data Sources and Priority

### Power demand data

| Priority | Source | Role | Operational note |
|---:|---|---|---|
| 1 | TEPCO monthly ZIP CSV | confirmed historical actuals and training target | usually updated next morning; GitHub-hosted runners may receive HTTP 403 |
| 2 | TEPCO intraday CSV | same-day actual refresh | used for live dashboard and intraday residual correction |
| 3 | `actual/YYYY-MM-DD.json` | cache gap filling before monthly ZIP refresh | protects ETL when confirmed CSV is delayed |
| 4 | TEPCO forecast fallback | temporary value for unconfirmed late hours such as 23:00 | may stabilize lag inputs, but must not count as validation actual |

TEPCO forecast fallback is a continuity input. It may support lag construction, but it is excluded from residual calculation, model validation, and anomaly actual checks.

### Weather data

| Time range | Temperature priority | Humidity priority | Operational note |
|---|---|---|---|
| past/current | JMA AMeDAS observations | JMA AMeDAS observations | official observed weather first |
| near future | JMA official forecast | latest AMeDAS humidity forward fill | keep JMA forecast temperature authoritative |
| future humidity fallback | keep JMA forecast temperature | Open-Meteo JMA humidity fallback | Open-Meteo is humidity-only fallback |
| final fallback | existing value or conservative mean | monthly/hourly seasonal humidity | network failure protection |

`weather_source` is a key diagnostic field when forecast shape changes unexpectedly.

---

## 3. LightGBM Hyperparameters

| Parameter | Current value | Intent |
|---|---:|---|
| `objective` | `quantile` | quantile regression for forecast bands |
| `alpha` | `0.025 / 0.50 / 0.975` | lower, point, and upper models |
| `n_estimators` | `500` | enough boosting rounds for nonlinear demand patterns |
| `learning_rate` | `0.05` | stable boosting step |
| `num_leaves` | `31` | moderate tree complexity |
| `min_child_samples` | `20` | avoid tiny overfit splits |
| `subsample` | `0.8` | reduce variance through row sampling |
| `colsample_bytree` | `0.8` | reduce dependence on a single lag group |
| `min_p95_half_width_mw` | `500` | prevent unrealistically narrow bands |

Operational tuning should start with data quality, lag regime, and calibration behavior before changing LightGBM complexity.

---

## 4. Feature Catalog

The current LightGBM training feature set contains 56 explicit features. The implementation does not explicitly pass `categorical_feature` to LightGBM; most features are supplied as a numeric matrix. "Logical type" describes how humans should reason about the feature, while "model input type" describes how it is encoded for the model.

### Calendar

| No. | Feature | Logical Type | Model Input Type | Source | Meaning | Operational note |
|---:|---|---|---|---|---|---|
| 1 | `hour` | categorical-like integer | Integer/Numeric | timestamp | hour of day | primary daily rhythm |
| 2 | `dayofweek` | categorical-like integer | Integer/Numeric | timestamp | weekday index | weekday/weekend demand rhythm |
| 3 | `month` | categorical-like integer | Integer/Numeric | timestamp | month | seasonal pattern |
| 4 | `is_holiday` | binary flag | Integer/Numeric | `jpholiday` | Japanese public holiday | holiday demand shift |
| 5 | `is_weekend` | binary flag | Integer/Numeric | timestamp | Saturday/Sunday flag | non-business demand |
| 6 | `is_non_business_day` | binary flag | Integer/Numeric | weekend or holiday | combined non-business flag | key gate for transition logic |

### Lag and rolling statistics

| No. | Feature | Logical Type | Model Input Type | Source | Meaning | Operational note |
|---:|---|---|---|---|---|---|
| 7 | `lag_24h` | continuous lag | Float/Numeric | actual cache | previous-day same-hour demand | strongest short-term inertia; contaminated at business/non-business boundaries |
| 8 | `lag_48h` | continuous lag | Float/Numeric | actual cache | two-day same-hour demand | backup when yesterday is unusual |
| 9 | `lag_168h` | continuous lag | Float/Numeric | actual cache | one-week same-hour demand | weekly rhythm; sensitive to holidays/weather |
| 10 | `lag_336h` | continuous lag | Float/Numeric | actual cache | two-week same-hour demand | stable weekday/seasonal reference |
| 11 | `roll_4w_mean` | rolling statistic | Float/Numeric | actual cache | four-week same weekday/hour mean | robust baseline anchor |
| 12 | `roll_4w_std` | rolling statistic | Float/Numeric | actual cache | four-week variability | instability signal |

### Holiday and business-day context

| No. | Feature | Logical Type | Model Input Type | Source | Meaning | Operational note |
|---:|---|---|---|---|---|---|
| 13 | `lag_last_biz_hour` | continuous lag | Float/Numeric | actual + calendar | previous business-day same-hour demand | supports post-holiday return |
| 14 | `lag_last_nonhol_hour` | continuous lag | Float/Numeric | actual + calendar | previous non-public-holiday same-hour demand | reduces holiday distortion |
| 15 | `consec_holiday_len` | ordinal count | Integer/Numeric | calendar | length of preceding holiday sequence | Golden Week/long-holiday context |
| 16 | `days_since_holiday_end` | ordinal count | Integer/Numeric | calendar | days since holiday ended | separates first and second return days |
| 17 | `major_holiday_season` | categorical-like integer | Integer/Numeric | date range | GW/Obon/New Year zone | major seasonal holiday handling |

### Weather and environment

| No. | Feature | Logical Type | Model Input Type | Source | Meaning | Operational note |
|---:|---|---|---|---|---|---|
| 18 | `temp_c` | continuous weather | Float/Numeric | JMA/AMeDAS | temperature | core HVAC driver |
| 19 | `cooling_degree` | continuous derived | Float/Numeric | derived | `max(0, temp_c - 22)` | cooling demand |
| 20 | `heating_degree` | continuous derived | Float/Numeric | derived | `max(0, 18 - temp_c)` | heating demand |
| 21 | `apparent_temp_c` | continuous weather | Float/Numeric | humidity-derived | apparent temperature | humidity-aware comfort signal |
| 22 | `apparent_cooling_degree` | continuous derived | Float/Numeric | derived | apparent cooling degree | humid-day cooling signal |
| 23 | `temp_anomaly_7d` | continuous delta | Float/Numeric | weather history | temperature vs recent week | sudden warm/cold regime |
| 24 | `temp_anomaly_doy` | continuous delta | Float/Numeric | month/hour baseline | seasonal temperature anomaly | unusual temperature for season |
| 25 | `temp_delta_24h` | continuous delta | Float/Numeric | weather lag | temperature change vs yesterday | controls trust in `lag_24h` |
| 26 | `cooling_delta_24h` | continuous delta | Float/Numeric | weather lag | cooling change vs yesterday | breaks overheated yesterday inertia |
| 27 | `temp_delta_168h` | continuous delta | Float/Numeric | weather lag | temperature change vs last week | controls trust in `lag_168h` |
| 28 | `cooling_delta_168h` | continuous delta | Float/Numeric | weather lag | cooling change vs last week | weekly weather difference |
| 29 | `temp_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1-hour temperature direction | morning rise / afternoon fall |
| 30 | `temp_delta_2h` | continuous delta | Float/Numeric | weather sequence | 2-hour temperature direction | stabilizes short-term direction |
| 31 | `apparent_temp_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1-hour apparent temperature change | humidity-aware direction |
| 32 | `cooling_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1-hour cooling degree change | cooling load direction |
| 33 | `cooling_degree_3h_mean` | rolling weather | Float/Numeric | rolling weather | short cooling accumulation | near-term thermal inertia |
| 34 | `cooling_degree_6h_mean` | rolling weather | Float/Numeric | rolling weather | half-day cooling accumulation | building heat retention |
| 35 | `heating_degree_3h_mean` | rolling weather | Float/Numeric | rolling weather | short heating accumulation | near-term cold inertia |
| 36 | `heating_degree_6h_mean` | rolling weather | Float/Numeric | rolling weather | half-day heating accumulation | sustained cold |
| 37 | `temp_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72-hour average temperature | thermal memory |
| 38 | `cooling_degree_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72-hour cooling accumulation | heat-wave persistence |
| 39 | `heating_degree_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72-hour heating accumulation | cold-wave persistence |

### Interactions and lag context

| No. | Feature | Logical Type | Model Input Type | Source | Meaning | Operational note |
|---:|---|---|---|---|---|---|
| 40 | `business_morning_x_temp_delta_24h` | interaction | Float/Numeric | derived | business morning x 24h temp change | weather-sensitive morning ramp |
| 41 | `business_morning_x_temp_anomaly_7d` | interaction | Float/Numeric | derived | business morning x recent anomaly | sudden HVAC morning load |
| 42 | `business_morning_x_temp_anomaly_doy` | interaction | Float/Numeric | derived | business morning x seasonal anomaly | early/late seasonal HVAC |
| 43 | `business_late_afternoon_x_temp_delta_1h` | interaction | Float/Numeric | derived | business late afternoon x temp direction | separates warming and cooling afternoons |
| 44 | `business_late_afternoon_x_cooling_delta_1h` | interaction | Float/Numeric | derived | business late afternoon x cooling direction | cooling-load decay or growth |
| 45 | `holiday_x_heat` | interaction | Float/Numeric | derived | holiday length x heat | hot holiday demand distortion |
| 46 | `post_holiday_x_heat` | interaction | Float/Numeric | derived | post-holiday x heat | return-to-work heat load |
| 47 | `business_hour_x_post_holiday_heat` | interaction | Float/Numeric | derived | business hour x post-holiday x heat | daytime return demand |
| 48 | `lag_24h_dsh` | ordinal context | Integer/Numeric | calendar lag | yesterday's days-since-holiday-end | lag contamination context |
| 49 | `lag_24h_consec` | ordinal context | Integer/Numeric | calendar lag | yesterday's consecutive holiday length | prior-day holiday regime |
| 50 | `lag_168h_dsh` | ordinal context | Integer/Numeric | calendar lag | last week's days-since-holiday-end | weekly lag contamination |
| 51 | `lag_24h_business_type_mismatch` | binary flag | Integer/Numeric | calendar | target vs previous-day business type | Fri->Sat and Sun->Mon transitions |
| 52 | `lag_24h_mismatch_x_business_hour` | interaction | Float/Numeric | derived | mismatch focused on business hours | daytime transition impact |
| 53 | `recent_same_business_type_mean` | anchor statistic | Float/Numeric | actual history | same-hour business-type anchor | business/non-business anchor |
| 54 | `lag_24h_to_last_biz_gap` | continuous gap | Float/Numeric | derived | last business demand minus `lag_24h` | post-holiday return shortfall |
| 55 | `lag_24h_to_same_business_type_gap` | continuous gap | Float/Numeric | derived | same-business anchor minus `lag_24h` | business return guard input |
| 56 | `lag_24h_gap_x_business_hour` | interaction | Float/Numeric | derived | gap focused on business hours | daytime lag gap signal |

---

## 5. Inference-only Context and Guard Variables

These values are not LightGBM training features. They are generated at inference time for diagnostics and guard logic.

| Variable | Purpose |
|---|---|
| `lag_24h_hourly_delta` | previous-day hourly slope |
| `lag_168h_hourly_delta` | previous-week hourly slope |
| `recent_same_business_type_delta_mean` | recent same-business-type average hourly slope |
| `recent_same_business_type_delta_q25` | lower quantile for same-business-type slope |
| `same_day_latest_actual_hour` | latest same-day observed hour |
| `same_day_latest_hourly_delta` | latest same-day observed slope |
| `same_day_recent_hourly_delta_mean` | recent same-day average slope |
| `business_midday_x_lag_24h_delta` | business midday x lag24 slope |
| `business_midday_x_recent_delta_mean` | business midday x recent average slope |
| `business_midday_x_recent_delta_q25` | business midday x lower-quantile slope |
| `business_midday_x_same_day_recent_delta_mean` | business midday x same-day recent slope |

Do not promote these into training features without checking time-band side effects.

---

## 6. Post-processing Layers

### Execution Order

Post-processing is a sequential pipeline. Each stage consumes the previous stage's output, so order directly affects the served forecast shape.

```text
Raw LightGBM Forecast
  -> Analogous Day Adjustment
  -> Post-holiday / Timeband Guard
  -> Midday Transition Guard
  -> Intraday Residual Correction
  -> Forecast Snapshots / Operational Calibration / Reports
```

The current `run_batch.py` stage names are `raw_lgbm`, `analog_adjusted`, `post_holiday_guarded`, `midday_guarded`, and `pre_calibration`. Intraday residual correction runs after `pre_calibration` and applies same-day actual feedback.

| Layer | Implementation | Purpose |
|---|---|---|
| Analogous day | `AnalogousDayAdjuster` | shifts raw forecast using residuals from similar historical days |
| Post-holiday timeband | `PostHolidayTimeBandGuard` | blocks analogous-day shifts in the wrong direction |
| Business return anchor shortfall | `PostHolidayTimeBandGuard` | protects Monday/business-return morning ramps from non-business lag drag |
| Midday transition guard | `MiddayTransitionGuard` | restores business-day 12:00 lunch dip shape |
| Intraday residual correction | `IntradayResidualCorrector` | applies same-day actual residuals to future hours |
| Day-boundary carryover | intraday calibration | carries the last real residual across midnight |
| Business transition prior | intraday calibration | weak prior during business/non-business transition before observations accumulate |
| Negative residual recovery damping | intraday calibration | avoids over-propagating negative residuals during non-business recovery |
| Positive residual slope damping | intraday calibration | damps positive residuals when actual slope rolls over |
| Morning ramp continuity guard | intraday calibration | avoids near-term dips during confirmed business morning ramps |
| Evening decline continuity guard | intraday calibration | limits near-term rebound spikes during evening decline |

Every guard should have a cap, shrinkage, and metadata footprint.

---

## 7. Config and Validation

### Key config

| Area | Config Key | Current value | Operational guide |
|---|---|---:|---|
| weather | `cooling_base_temp_c` | 22.0 | Lower values activate cooling sensitivity earlier; higher values reduce early-summer overreaction. Validate across the full warm season. |
| weather | `heating_base_temp_c` | 18.0 | Higher values strengthen heating signals; lower values reduce winter over-sensitivity. |
| weather bias | `min_abs_bias_c` | 1.5 | Lower values apply forecast-bias correction more often; too low may chase weather noise. |
| interval | `min_p95_half_width_mw` | 500 | Prevents narrow bands. Raising it improves visual stability but may reduce alert sensitivity. |
| intraday | `lookback_hours` | 3 | Shorter windows react faster; longer windows are smoother but slower. |
| intraday | `decay_per_hour` | 0.92 | Higher values carry residuals farther into the day; lower values keep corrections near-term. Lower it when carryover contaminates shape. |
| intraday | `max_abs_adjustment_mw` | 1200 | Hard cap for same-day residual correction. Raising it follows large misses faster but increases overshoot risk. |
| forecast snapshots | `retention_days` | 21 | Public lead-time forecast history for operational review. |
| calibration snapshots | `retention_days` | 14 | Internal calibration history. Too short makes incident analysis harder. |
| reserve risk | warning | 92% | TEPCO reserve warning threshold. Lower values create more warnings; higher values reduce early warning behavior. |
| reserve risk | critical | 97% | TEPCO reserve critical threshold. Keep visually distinct from warning status. |

### Metrics

| Metric | Definition | Use |
|---|---|---|
| MAE | mean absolute error in MW | intuitive average error |
| WAPE | `sum(abs(error)) / sum(actual)` | scale-aware daily error |
| RMSE | root mean squared error | large miss risk |
| Max Error MW | largest absolute error | operational tail risk |
| Dominance Hours | hours where model beats TEPCO error | auxiliary comparison |

### Known Risks

| Risk | Symptom | Response |
|---|---|---|
| Seasonal transition | lag regime disagrees with today's weather | inspect `temp_delta` and day-level scale |
| Lunch dip | 12:00 bucket is too flat or too low | inspect midday guard and q25 deltas |
| Evening rebound | forecast rebounds while actual demand declines | inspect evening decline guard |
| Monday morning | Sunday lag drags down business ramp | inspect business return anchor shortfall |
| Saturday morning | Friday lag overheats non-business morning | inspect business transition prior |
| Late-hour actual delay | previous day lacks final actuals | inspect fallback source flags |
| TEPCO ZIP 403 | GitHub Actions ETL cannot fetch monthly CSV | use local ETL or a separate runner |
| Weather API issue | NaN weather or excessive fallback | inspect `weather_source` ratios |
| Batch retraining failure (dry rot) | data keeps accumulating but model is not retrained, or inference keeps using an old `.lgbm_model.pkl` | check the 90-day minimum, model save timestamp, interval version, and ETL training logs. Continue serving the latest valid model but record the retraining failure in the operations report. |

---

## 8. Modification Runbook

Feature changes:

- decide whether the value belongs in `FEATURE_COLS` or inference-only context,
- check missing rates and training-row loss,
- keep training and inference feature generation aligned,
- avoid leakage from future actuals or post-confirmation values,
- evaluate time-band WAPE/RMSE and shape side effects,
- update `lgbm-design.md`, this document, and model-improvement notes when needed.

Guard changes:

- separate raw model changes from residual carryover changes,
- avoid date-specific hardcoding,
- keep caps, shrinkage, and max lead-time limits,
- do not follow TEPCO forecasts directly,
- preserve forecast freeze semantics for observed past hours,
- record `...Applied`, `...MaxMw`, and `appliedRegimeReason` metadata,
- add unit tests and inspect operational calibration snapshots.

First diagnostics:

| Symptom | First artifact to inspect |
|---|---|
| sudden forecast jump | `reports/internal/operational-calibration/YYYY-MM-DD.json` |
| model high/low all day vs TEPCO | `reports/internal/daily-diagnostics/YYYY-MM-DD.json` |
| lunch-only shape issue | forecast snapshot and midday context |
| evening spike | evening guard metadata |
| morning ramp miss | business return / morning ramp metadata |
| narrow forecast band | `interval_calibration` |
| AI report issue | `reports/ai/daily/` generator metadata |

The operating rule is to inspect data source quality and residual carryover first, then feature behavior, and only then model complexity.
