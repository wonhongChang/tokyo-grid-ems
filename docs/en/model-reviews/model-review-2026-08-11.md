# 2026-08-11 Operational Model Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-08-11.md) / [日本語](../../ja/model-reviews/model-review-2026-08-11.md)

Created: 2026-08-10 JST  
Scheduled review: after the 2026-08-11 morning ETL  
Status: not started

## 1. Purpose

This review follows two cases where a multi-day review was followed by changes that made the live forecast worse. The review therefore pre-registers its evidence, gates, and stop conditions.

- Do not change the model merely because more days are available.
- Do not let aggregate improvements hide date-level or shape regressions.
- Evaluate the forecast that was actually served.
- Separate raw-model, post-processing, intraday, and freeze effects.
- Use the TEPCO forecast only as an external benchmark, never as an input or calibration target.
- Do not relax acceptance gates after seeing the results.
- Retain the Champion when causality or regression safety is not established.

## 2. Fixed Facts

- Current production Champion: v11 lag24 residual ensemble.
- Current Challenger contract: v13 transition cooling blend.
- On 2026-08-04, v13 passed the 84-day gate but was not promoted because its 28-day MAE was `1,036.6 MW`, above the `1,000 MW` ceiling.
- 2026-08-11 is Japan's Mountain Day holiday despite being a Tuesday.
- It must be represented as `is_holiday=1` and `is_non_business_day=1`.
- The chart's 12:00 bucket represents demand from 12:00 to 13:00.
- The business-day lunch dip is evidence-driven, not a fixed downward offset.
- `MiddayTransitionGuard` must skip non-business days.

## 3. Evaluation Scope

| Regime | Dates | Purpose |
|---|---|---|
| Business days | 2026-08-05 to 2026-08-07 | Baseline shape, morning ramp, lunch dip, afternoon and evening |
| Weekend | 2026-08-08 to 2026-08-09 | Non-business q50 and weekend shape |
| Business return | 2026-08-10 | Weekend-to-business lag contamination and return ramp |
| Holiday forecast | 2026-08-11 | Holiday calendar path, non-business behavior, midday bypass |

Final accuracy for 2026-08-11 will be assessed after the 2026-08-12 ETL.

Long-window checks:

- 28 complete days: exactly `672` hours.
- 84 complete days: exactly `2,016` hours.
- Report business, non-business, and business-type transition segments separately.
- Do not cancel opposite recent and long-window errors through a single average.

## 4. Data Integrity Gate

Stop model comparison if any required input is invalid.

- [ ] Local ETL completed successfully and recorded its execution time.
- [ ] The latest ETL commit exists on the `data` branch.
- [ ] `actual/2026-08-10.json` contains 24 non-null actual values.
- [ ] `tepco_forecast_fallback` is not treated as validation actual.
- [ ] The 2026-08-10 daily and internal diagnostic reports exist.
- [ ] The 2026-08-11 forecast and forecast snapshots exist.
- [ ] Model artifact, training cutoff, metadata, and interval version agree.
- [ ] Weather data contains no unexplained source transition, NaN, or extended forward-fill.
- [ ] Missing snapshots caused by Actions/Pages incidents are explicitly recorded.
- [ ] Final actual coverage is not confused with stage-snapshot coverage.

| Item | Result | Evidence | Decision |
|---|---|---|---|
| ETL |  |  |  |
| 24-hour actual |  |  |  |
| Weather sources |  |  |  |
| Forecast snapshots |  |  |  |
| Model metadata |  |  |  |
| Actions/Pages |  |  |  |

## 5. Daily Live Performance

Use the model/config and snapshots that were active for each date.

| Date | Day type | Model/config | MAE | WAPE | RMSE | Bias | Max error | TEPCO MAE | Notes |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-05 | Business |  |  |  |  |  |  |  |  |
| 2026-08-06 | Business |  |  |  |  |  |  |  |  |
| 2026-08-07 | Business |  |  |  |  |  |  |  |  |
| 2026-08-08 | Weekend |  |  |  |  |  |  |  |  |
| 2026-08-09 | Weekend |  |  |  |  |  |  |  |  |
| 2026-08-10 | Business return |  |  |  |  |  |  |  |  |

- [ ] Identify dates with all-day one-sided bias.
- [ ] Identify dates with repeated error-sign changes and unstable shape.
- [ ] Keep TEPCO dominance hours as a secondary reference only.
- [ ] Do not compare dates as if they used the same serving version when they did not.
- [ ] Record each day's worst window and its likely stage.

## 6. Time-Band Review

| Hours | Primary question | Model MAE/WAPE | Shape delta error | Decision |
|---|---|---:|---:|---|
| 00-05 | Did day-boundary carryover or lag24 distort the base level? |  |  |  |
| 06-11 | Was the morning ramp jagged or directionally biased? |  |  |  |
| 12 | Did the business-day lunch dip act only with evidence? |  |  |  |
| 13-16 | Did rebound or local spike processing distort the curve? |  |  |  |
| 17-19 | Was there an unsupported evening rebound? |  |  |  |
| 20-23 | Were late decline and the 23:00 fallback boundary stable? |  |  |  |

## 7. Business-Day Lunch-Dip Audit

Review dates: 2026-08-05, 2026-08-06, 2026-08-07, and 2026-08-10.

- [ ] `is_non_business_day` equals 0.
- [ ] Record `business_midday_x_lag_24h_delta`.
- [ ] Record `business_midday_x_recent_delta_mean`.
- [ ] Record `business_midday_x_recent_delta_q25`.
- [ ] Record `business_midday_x_same_day_recent_delta_mean`.
- [ ] Confirm whether lag and recent same-business shape actually support a dip.

| Date | Actual 11->12 | Actual 12->13 | Raw 11->12 | Midday delta | Pre-calibration | Served | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-05 |  |  |  |  |  |  |  |
| 2026-08-06 |  |  |  |  |  |  |  |
| 2026-08-07 |  |  |  |  |  |  |  |
| 2026-08-10 |  |  |  |  |  |  |  |

Expected behavior:

- Do not manufacture a fixed dip when recent business-day evidence is weak.
- Apply only a capped downward adjustment when supported shape is negative and the forecast is materially elevated.
- Do not carry a one-slot noon shock into a persistent afternoon decline.
- Do not let intraday residuals propagate the lunch shock across the afternoon.
- Attribute a served-versus-midday-stage difference to freeze or prior snapshots instead of the guard itself.

## 8. 2026-08-11 Holiday Path

- [ ] `jpholiday` identifies Mountain Day.
- [ ] `is_holiday=1` and `is_non_business_day=1`.
- [ ] Business-only q50 paths and guards remain inactive.
- [ ] `MiddayTransitionGuard` is bypassed.
- [ ] Business-morning and business-daytime interactions are zero or inactive.
- [ ] Non-business anchors and lag mismatch context are valid.
- [ ] The 2026-08-10 business-day lag does not over-elevate holiday demand.
- [ ] No fixed holiday downward offset is introduced.

## 9. Stage Attribution

Record the value and delta for each affected hour:

1. `raw_lgbm`
2. `analog_adjusted`
3. `post_holiday_guarded`
4. `midday_guarded`
5. `localized_shape_guarded`
6. `pre_calibration`
7. Intraday residual correction
8. `served_forecast`
9. Published Forecast Freeze gap

| Date/hour | Raw | Analog delta | Guard delta | Intraday delta | Served | Actual | Primary stage |
|---|---:|---:|---:|---:|---:|---:|---|
|  |  |  |  |  |  |  |  |

Use one of: `data_quality`, `raw_model_level`, `raw_model_shape`, `weather_regime`, `calendar_regime`, `analog_adjustment`, `shape_guard`, `intraday_carryover`, `freeze_artifact`, or `insufficient_evidence`.

## 10. Interval Review

- [ ] Compute p95 coverage by date and time band.
- [ ] Verify the interval remains centered on q50.
- [ ] Record minimum-width and maximum-tail-cap effects.
- [ ] Inspect q025/q975 asymmetry and rebalancing.
- [ ] Do not hide a centerline error by widening the band.

| Band | Coverage | Mean width | Maximum width | Miss direction | Decision |
|---|---:|---:|---:|---|---|
| All |  |  |  |  |  |
| 00-05 |  |  |  |  |  |
| 06-11 |  |  |  |  |  |
| 12-16 |  |  |  |  |  |
| 17-23 |  |  |  |  |  |

## 11. Champion/Challenger Gates

Compare Champion v11 and Challenger v13 before introducing another candidate.

| Gate | Fixed limit | Result | Pass |
|---|---:|---:|---|
| 28-day coverage | 672/672 hours |  |  |
| MAE improvement vs baseline | at least 20% |  |  |
| 28-day MAE | at most 1,000 MW |  |  |
| 28-day WAPE | at most 3.0% |  |  |
| Shape delta MAE | at most 750 MW |  |  |
| Maximum error | at most 6,500 MW |  |  |
| Segment MAE | at most 1,500 MW |  |  |
| Segment shape delta MAE | at most 1,100 MW |  |  |
| Segment MAE regression | at most 10% |  |  |
| Mean 48-hour prediction drift | at most 900 MW |  |  |
| Maximum hourly prediction drift | at most 2,500 MW |  |  |

Regression segments must include consecutive business days, business-to-weekend, weekend, weekend/holiday-to-business, a midweek holiday, rapid warming, rapid cooling, and humidity transitions.

Any failed gate blocks promotion.

## 12. Change Policy

Immediate fixes are limited to calendar errors, actual-source contamination, stage-order bugs, ignored config, metadata/snapshot defects, and deterministic calculation bugs.

Model features, guard thresholds, caps, shrinkage, lag blend weights, and interval widths require an isolated experiment and replay first.

Prohibited:

- Using TEPCO forecasts as calibration input.
- Fitting already observed demand back into the same forecast date.
- Date-specific conditions.
- Relaxing promotion thresholds to pass a candidate.
- Accepting a recent gain that regresses the 28/84-day or another regime.
- Changing the model and operational post-processing in one experiment.

## 13. Additional Review Items

New evidence may add review items, but cannot change the pre-registered gates.

| Added item | Reason | Required evidence | Result | Follow-up |
|---|---|---|---|---|
|  |  |  |  |  |

## 14. Execution Record

| Run | Command/tool | Start | End | Output | Status |
|---|---|---|---|---|---|
| Public data validation | `python scripts/validate_public_before_publish.py` |  |  |  |  |
| Python tests | `python -m pytest -q` |  |  |  |  |
| 28-day operational replay | Internal evaluator |  |  | `metrics/operational_replay.json` |  |
| Challenger validation | Promotion evaluator |  |  | `metrics/model_promotion.json` |  |
| Prediction drift | Champion/Challenger 48h |  |  |  |  |

## 15. Final Decision

- [ ] Retain Champion with no code change.
- [ ] Fix only a data or operational defect.
- [ ] Keep a post-processing candidate in shadow evaluation.
- [ ] Keep a model candidate as Challenger.
- [ ] Promote only after every gate passes.

Record:

- Primary cause:
- Why a change is or is not required:
- Areas intentionally unchanged:
- Regression results:
- Residual risk:
- Next review date:

Before publication:

- [ ] The user confirmed the final change and promotion scope.
- [ ] Model behavior and documentation agree.
- [ ] A model-improvement document exists only when an implementation change was accepted.
