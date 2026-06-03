# 2026-06-03 Forecast Interval Tail Sanity Guard

> Caps rare one-sided p95 tail explosions without changing the q50 demand forecast.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)

---

## Why This Was Needed

During the 2026-06-03 intraday forecast, the displayed forecast band became visually abnormal even though the q50 line was mostly reasonable.

The issue appeared in the p95 upper side:

- 12:00 upper half-width: about `+4,831 MW`
- 13:00 upper half-width: about `+5,939 MW`
- 14:00 upper half-width: about `+6,108 MW`
- 15:00 upper half-width: about `+6,187 MW`

The lower side stayed much narrower, so the interval looked like an extreme upside-only risk cone. Snapshot analysis showed the jump began around the 11:14 JST intraday run.

The model file did not change between the previous snapshot and the abnormal one. The main input change was weather: future 12:00-14:00 temperature shifted from around `21.0 C` to around `18.0 C`. The q50 model only moved modestly, but the independent q975 model routed that weather-regime change into a much wider upper tail.

---

## Root Cause

Tokyo Grid EMS trains q025, q50, and q975 as separate LightGBM quantile regressors. This is useful because each quantile can learn its own risk shape, but it also means the upper quantile can occasionally become too wide relative to q50 and q025.

The existing interval calibration already prevented collapsed bands and avoided mirroring one-sided uncertainty into the opposite side. It did not yet cap a rare upper-tail explosion after a weather-regime shift.

Forecast freeze made the effect more visible: once an observed hour was preserved for fair evaluation, the abnormal interval for that hour remained visible even after later recalculations.

---

## Change

Added a shared interval calibration helper:

```text
python/forecast/interval_calibration.py
```

The helper now enforces:

- minimum p95 half-width,
- optional maximum p95 half-width,
- optional upper/lower asymmetry ratio cap,
- consistent p99 reconstruction from the calibrated p95 width.

The same calibration is applied in two places:

- `LGBMForecaster.predict()` for new q025/q50/q975 outputs,
- `build_forecast_json()` before writing or snapshotting forecast JSON, so preserved forecast hours are also normalized.

Production config:

```yaml
interval_calibration:
  min_p95_half_width_mw: 500
  max_p95_half_width_mw: 4500
  max_p95_asymmetry_ratio: 4.0
  asymmetry_reference_half_width_mw: 1000
  mirror_collapsed_side: false
```

---

## Expected Effect

The point forecast remains unchanged. Only unreasonable interval tails are constrained.

For the reproduced 2026-06-03 case:

| Hour | Before upper half-width | After upper half-width |
|---|---:|---:|
| 12:00 | `+4,830.8 MW` | `+4,500.0 MW` |
| 13:00 | `+5,939.2 MW` | `+4,500.0 MW` |
| 14:00 | `+6,107.7 MW` | `+4,380.8 MW` |
| 15:00 | `+6,187.2 MW` | `+4,000.0 MW` |

This keeps uncertainty visible while preventing the dashboard from displaying a misleading one-sided cone.

---

## Tests

Added regression coverage for:

- LGBM raw quantile output with an extreme one-sided upper interval.
- Forecast JSON normalization for already-built or preserved forecast points.

Validation:

```text
369 passed
```
