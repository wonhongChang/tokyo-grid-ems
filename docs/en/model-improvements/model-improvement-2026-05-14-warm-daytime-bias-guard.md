# 2026-05-14 Warm Daytime Bias Guard

> Follow-up operational improvement after repeated warm-day under-forecasting in the 09:00-18:00 JST window.

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md)

---

## Why This Was Needed

After the holiday-lag daytime guard was added, recent live data still showed a daytime under-forecast pattern on warm business days.

For 09:00-18:00 JST:

| Date | Model bias | Model MAE | Note |
|---|---:|---:|---|
| 2026-05-11 | -1,294 MW | 1,294 MW | broad daytime under-forecast |
| 2026-05-13 | -704 MW | 751 MW | warm afternoon remained low |
| 2026-05-14 | -866 MW | 930 MW | partial day, 09:00-11:00 observed |

The pattern was not only a Golden Week lag problem. Ordinary warm weekdays also needed a small operational guard until the model has more warm-season training data.

## Forecasting Change

`python/forecast/adjustment.py` now supports an ordinary warm-day daytime guard.

It activates only when all of these are true:

- the hour is in the configured daytime window,
- the target date is a business day,
- `temp_anomaly_doy >= warm_day_min_temp_anomaly_doy`,
- the analogous-day adjustment is not already raising the forecast.

When activated, it applies a small upward offset to q50 and forecast bands.

Relevant config:

```yaml
adjustment:
  post_holiday_timeband_guard:
    daytime:
      activate_on_warm_day: true
      warm_day_min_temp_anomaly_doy: 1.0
      warm_day_upward_offset_mw: 250
```

## Design Boundary

This is intentionally smaller than the holiday-lag guard.

- It does not use TEPCO forecast values as model inputs.
- It is based on seasonal temperature anomaly instead of a fixed absolute temperature cutoff.
- It does not add extra offset when analogous-day adjustment is already moving upward.
- It does not add a manual warm-day offset on weekends or public holidays; non-business-day heat remains handled by model weather features.

The goal is to reduce repeated warm-day daytime under-forecasting without turning the model into a manual high-bias forecast.
