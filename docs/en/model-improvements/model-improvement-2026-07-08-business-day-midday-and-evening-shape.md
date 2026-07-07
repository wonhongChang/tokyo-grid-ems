# 2026-07-08 Business-Day Midday and Evening Shape Controls

## Context

The 2026-07-07 operating day exposed a broad business-day shape issue. The daily report covered 22 comparable observed hours because 22:00 and 23:00 were still TEPCO forecast fallback rows at report time.

Observed scorecard:

| Metric | Model | TEPCO |
| --- | ---: | ---: |
| MAE | 427.1 MW | 215.0 MW |
| WAPE | 1.43% | 0.72% |
| RMSE | 479.7 MW | 289.5 MW |
| Advantage hours | 5 / 22 | 17 / 22 |

Largest model misses:

| Hour | Actual | Model | Error | Main diagnosis |
| --- | ---: | ---: | ---: | --- |
| 12:00 | 33,630 MW | 34,420.9 MW | +790.9 MW | Noon dip was under-damped even though lag/recent business-day shape pointed down. |
| 16:00 | 34,420 MW | 33,670.2 MW | -749.8 MW | A stale negative residual carried into the first future afternoon bucket too strongly. |
| 21:00 | 29,510 MW | 30,549.0 MW | +1,039.0 MW | Evening raw level stayed above the recent same-business anchor during a strong decline regime. |

## Changes

- Increased the business-day `midday_transition_guard` shrinkage from `0.5` to `0.75`.
  - This still requires negative lag/recent shape evidence; it does not create a fixed lunch dip.
- Tightened `negative_residual_near_term_floor.actual_reference_slack_mw` from `500` to `150`.
  - The first near-term future bucket is protected from being pushed far below the latest observed level by stale negative residuals.
  - Existing decline-support damping still limits restoration when observed demand is already falling hard and lag/recent shape also supports a decline.
- Extended `evening_decline_continuity_guard` to hour `21`.
- Added `strong_decline_level_anchor` inside the evening guard.
  - When both `lag_24h_hourly_delta` and `recent_same_business_type_delta_mean` show a strong evening decline, level-overhang caps can use the recent same-business anchor instead of the latest observed level.
  - Weather allowance remains active, so genuinely hot evening demand is not blindly suppressed.

## Expected Effect

Using the 2026-07-07 snapshots as a replay guide:

- 16:00 near-term overcorrection improves from roughly `-750 MW` to about `-390 MW`.
- 21:00 strong-decline overhang improves from roughly `+1,039 MW` to about `+560 MW`.
- 12:00 is handled at the pre-intraday shape stage, so the improvement appears when the next forecast is rebuilt with the updated midday guard config.

## Validation

- `python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py::test_midday_transition_guard_dampens_unsupported_noon_jump tests/test_adjustment.py::test_midday_transition_guard_uses_lower_recent_quantile_when_same_day_softens tests/test_adjustment.py::test_midday_transition_guard_does_not_use_quantile_without_same_day_softening -q`
- Result: `79 passed`

## Notes

This change does not use TEPCO forecast values as model inputs. TEPCO remains a benchmark only. The controls are based on observed same-day residuals, recent same-business demand anchors, lag/recent shape deltas, and weather allowance.
