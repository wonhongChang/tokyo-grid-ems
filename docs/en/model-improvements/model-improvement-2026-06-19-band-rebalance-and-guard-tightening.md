# 2026-06-19 Band Rebalance and Guard Tightening

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md)

## Problem

The 2026-06-19 morning forecast exposed two related operational issues.

- The 09:00-11:00 p95 band was strongly one-sided. For example, 09:00 and 10:00 had roughly `-2250 / +500 MW` around q50, so the displayed band looked detached from the central forecast.
- The 2026-06-18 10:00 serving snapshot showed `morning_observed_ramp_floor` stacking too much lift on top of a positive residual carryover.
- The 2026-06-18 afternoon snapshot showed `afternoon_observed_anchor_cap` suppressing 14:00-16:00 even though same-day actuals were already recovering.

## Change

- Added optional interval rebalancing for extreme p95 asymmetry. It preserves total p95 width, but redistributes the lower/upper half-widths when one side collapses too far.
- Raised `morning_positive_residual_carryover_damping.weak_support_delta_mw` so weakly supported 10:00-13:00 morning carryover is damped more often.
- Set `morning_observed_ramp_floor.max_floor_delta_over_support_mw` to `0`, so the floor cannot lift above target-hour lag/recent shape support.
- Added `afternoon_observed_anchor_cap.max_latest_slope_mw`; the cap now skips when latest same-day actual demand is already recovering strongly.

## Expected Effect

The central forecast is unchanged by the band rebalance. The dashboard band should look less lopsided when q50 has been moved by post-processing or when one quantile side collapses.

Morning ramp protection remains available, but it no longer stacks aggressively when the target slot lacks enough lag/recent shape support. Afternoon plateau caps remain available, but they no longer fight a clear same-day recovery slope.

## Validation

```text
tests/test_run_batch.py::test_build_forecast_json_rebalances_extreme_one_sided_band
tests/test_intraday_correction.py::test_intraday_damps_morning_positive_carryover_before_ramp_floor_lift
tests/test_intraday_correction.py::test_intraday_afternoon_observed_anchor_cap_skips_when_actuals_are_recovering

Full suite: 402 passed
```
