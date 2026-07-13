# 2026-07-13 Non-Business Late Morning Ramp Floor

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-13-non-business-late-morning-ramp-floor.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-13-non-business-late-morning-ramp-floor.md)

## Context

The 2026-07-10 to 2026-07-13 review showed that the most actionable failure was 2026-07-11, a Saturday.

Summary from the published data:

| Date | Status |
| --- | --- |
| 2026-07-10 | Model MAE 383.8 MW, TEPCO MAE 375.0 MW. Nearly tied, with a morning shape miss and one 11:00 over-forecast. |
| 2026-07-11 | Model MAE 639.3 MW, TEPCO MAE 316.7 MW. Clear model failure, mainly from 00:00-10:00 under-forecasting. |
| 2026-07-12 | Model MAE 384.4 MW, TEPCO MAE 326.2 MW. Main issue was non-business midday over-level around 12:00-14:00. |
| 2026-07-13 | Partial same-day data showed the model ahead of TEPCO so far, with no broad corrective patch needed yet. |

For 2026-07-11, the actual morning ramp started late but then jumped hard:

- 05:00 -> 06:00: +430 MW
- 06:00 -> 07:00: +2,430 MW
- 07:00 -> 08:00: +3,440 MW
- 08:00 -> 09:00: +3,250 MW

The existing `morning_observed_ramp_floor` required both of the last two observed slopes to exceed the same threshold. That was too strict for a weekend late-start ramp: the first slope was weak, but the latest slope already showed the real demand turn.

## Change

The non-business branch of `morning_observed_ramp_floor` can now use the latest observed slope as its floor basis when explicitly configured.

Production config now uses:

| Config key | Value |
| --- | ---: |
| `non_business_min_latest_slope_mw` | `2000` |
| `non_business_min_mean_slope_mw` | `1200` |
| `non_business_floor_basis` | `latest` |
| `non_business_floor_slope_fraction` | `1.0` |
| `non_business_max_lift_mw` | `700` |

The guard is still narrow:

- it only applies after real same-day actuals are observed
- it only protects near-term targets within `max_lead_hours`
- the latest observed bucket must not already be materially over-forecast
- target-hour lag/recent shape support must still exist
- the final lift remains capped by `non_business_max_lift_mw`

## Why This Is Not a Weekend Hard-Code

The rule does not lift every Saturday or Sunday. It only changes how the observed-ramp floor is constructed after a non-business day has already proved a strong same-day ramp in actual demand.

This patch intentionally does not add a broad non-business midday cap for 2026-07-12. That day had the opposite shape problem, with 12:00-14:00 over-level forecasts. Solving both with one aggressive rule would increase the risk of fighting true weekend demand. The safer path is to fix the confirmed late-ramp under-forecast first and keep the midday over-level case under observation.

## Observability

Residual adjustment rows now include:

- `morningObservedRampFloorBasis`

This makes it visible whether the ramp floor was built from the normal `mean` slope or the non-business `latest` slope basis.

## Validation

- `python -m pytest tests/test_intraday_correction.py -k "weekend_morning_ramp_floor or observed_morning_ramp_floor"`

Results:

- `5 passed`

The added regression tests verify:

- a 2026-07-11-style late-start weekend ramp is lifted for the nearest hours only
- a weaker 2026-07-12-style early ramp does not trigger the non-business latest-slope floor
