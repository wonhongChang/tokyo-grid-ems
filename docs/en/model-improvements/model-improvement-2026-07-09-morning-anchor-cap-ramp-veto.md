# 2026-07-09 Morning Anchor Cap Ramp Veto

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-09-morning-anchor-cap-ramp-veto.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-09-morning-anchor-cap-ramp-veto.md)

## Context

The finalized 2026-07-08 forecast was not a random spike problem. The main miss was a broad under-forecast after the real morning ramp accelerated.

Observed scorecard:

| Metric | Model | TEPCO |
| --- | ---: | ---: |
| MAE | 376.3 MW | 172.9 MW |
| WAPE | 1.18% | 0.54% |
| RMSE | 441.1 MW | 231.9 MW |
| Advantage hours | 3 / 21 | 18 / 21 |

The largest shape miss was the 08:00 -> 09:00 transition. Actual demand rose by about `+3,810 MW`, while the model rose by only about `+2,542 MW`. The 09:32 JST intraday snapshot then applied `morning_observed_anchor_cap`, which further suppressed 09:00-12:00 even though the same-day observed ramp was already very strong.

## Change

Added a conservative `ramp_veto` sub-rule to `intraday_correction.morning_observed_anchor_cap`.

The cap is skipped only when all of these are true:

- the latest observed same-day slope is very strong
- the two-hour mean observed slope is also very strong
- the target path has enough cumulative lag/recent shape support
- the latest over-forecast is modest, so this is not a confirmed severe overprediction case

Default production config:

| Config key | Value |
| --- | ---: |
| `min_latest_slope_mw` | 3000 |
| `min_mean_slope_mw` | 3000 |
| `min_cumulative_support_mw` | 2500 |
| `max_latest_overforecast_mw` | 650 |

## Expected Effect

This does not lift forecasts by itself. It only prevents the morning anchor cap from cutting a confirmed explosive ramp that is still supported by lag/recent shape context.

For a 2026-07-08-like run, the 09:00 and 10:00 buckets are no longer reduced by the morning cap after the 06:00-08:00 observed ramp confirms the high-slope regime. Existing severe over-forecast cases still keep the cap because the veto is blocked when the latest miss is too large.

## Validation

- `python -m pytest tests/test_intraday_correction.py -k "morning_observed_anchor_cap"`
- `python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py`
- `python -m pytest tests/test_ai_daily_report.py tests/test_daily_operation_report.py tests/test_feature_builder.py tests/test_lgbm_model.py`

Results:

- `4 passed` for the targeted morning anchor cap tests
- `129 passed` for intraday correction and adjustment
- `136 passed` for report, feature-builder, and LGBM tests

## Notes

This change does not use TEPCO forecast values as model inputs. TEPCO remains a benchmark only. The veto is based on same-day observed demand slope, lag/recent shape support, and the latest model residual.
