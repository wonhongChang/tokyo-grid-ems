# 2026-06-09 afternoon observed anchor cap

> A near-term intraday cap for business-day afternoon plateaus when same-day observations already show that the model line is too high.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-09-afternoon-observed-anchor-cap.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-09-afternoon-observed-anchor-cap.md)

---

## Why

The 2026-06-09 live forecast exposed a different failure mode from the morning ramp issue.

The morning observed anchor cap was intentionally scoped to the late-morning window. It did not apply to the 13:00-15:00 plateau. By 12:00-15:00, however, observed demand had repeatedly come in below the model, while the raw/analog-adjusted forecast kept a high afternoon plateau.

This is not an evening decline case either. Demand was not sharply falling into evening; instead, the model kept an unsupported daytime level after same-day actuals had already rejected it.

## Change

Added `intraday_correction.afternoon_observed_anchor_cap`.

The guard only runs for near-term business-day afternoon buckets and only when recent observed residuals show persistent overforecasting. It does not use TEPCO forecasts and does not rewrite already observed/frozen hours.

For each target future hour, it computes a conservative cap:

```text
last observed actual
+ fractional lag/recent shape support
+ buffer
```

If the current forecast exceeds that cap, only part of the overhang is reduced, bounded by a maximum reduction.

## Safety Rules

- Requires same-day observed evidence in the afternoon window.
- Requires both latest and recent-average overforecast evidence.
- Targets only configured near-term hours.
- Uses only a fraction of lag/recent positive support, because this failure mode is specifically about the model over-trusting that shape support.
- Leaves one-slot lunch dips alone unless the broader recent residual context confirms a persistent high bias.

## Configuration

```yaml
intraday_correction:
  afternoon_observed_anchor_cap:
    enabled: true
    business_day_only: true
    target_hours: [14, 15, 16]
    min_reference_hour: 12
    max_reference_hour: 15
    max_lead_hours: 3
    lookback_observed_hours: 3
    min_latest_overforecast_mw: 500
    min_mean_overforecast_mw: 500
    cap_buffer_mw: 350
    support_fraction: 0.6
    shrinkage: 0.75
    max_reduction_mw: 1200
    min_reduction_mw: 100
```

## Diagnostics

The calibration metadata now exposes:

- `afternoonObservedAnchorCapApplied`
- `afternoonObservedAnchorCapMaxReductionMw`
- `afternoonObservedAnchorCapReductionMw`
- `afternoonObservedAnchorCapMw`
- `afternoonObservedAnchorCapCumulativeSupportMw`
- `afternoonObservedAnchorCapLatestResidualMw`
- `afternoonObservedAnchorCapMeanResidualMw`

The AI daily report feature catalog now includes `intraday_correction.afternoon_observed_anchor_cap`.

## Validation

- Added regression coverage for a 2026-06-09-like afternoon plateau overhang.
- Added a counter-test proving that a single lunch dip does not activate the guard.
- Targeted test result: `tests/test_intraday_correction.py` passed.
