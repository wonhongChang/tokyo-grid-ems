# 2026-07-16 Morning Ramp Slope Overreaction Guard

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md)

## Background

The 2026-07-16 chart exposed a recurring 09:00 JST issue. The served line jumped above the actual demand even though the following 10:00-12:00 section was much closer.

Key rows from the final diagnostics:

| Hour | Actual | Pre-calibration | Error | Forecast delta | Lag24 delta | Recent same-business delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 08:00 | 41,540 MW | 42,369.9 MW | +829.9 MW | +7,275.7 MW | +6,120.0 MW | +4,867.5 MW |
| 09:00 | 45,800 MW | 48,196.1 MW | +2,396.1 MW | +5,826.2 MW | +4,760.0 MW | +3,863.8 MW |
| 10:00 | 47,790 MW | 49,695.6 MW | +1,905.6 MW | +1,499.5 MW | +2,060.0 MW | +1,486.2 MW |

This was not primarily an intraday residual problem. The raw/pre-calibration morning curve already overestimated the 08:00 to 09:00 ramp. Earlier guards mostly worked after enough same-day observations had arrived, so they could not reliably prevent a pre-observation 09:00 shape spike.

## Change

Enabled and extended the existing `localized_shape_spike_guard.morning_spike` path with a separate `slope_overreaction` mode.

The new mode targets warm morning ramp overreaction only when all of the following are true:

- target hour is in the morning ramp band (`08:00-10:00`)
- forecast hour-to-hour rise is large
- forecast rise exceeds lag/recent same-business support by a material margin
- weather or discomfort delta indicates a warm-up regime
- the shape can be capped using neighboring forecast hours without flattening the whole morning

Operational config:

```yaml
localized_shape_spike_guard:
  morning_spike:
    enabled: true
    hours: [8, 9, 10]
    neighbor_buffer_mw: 400
    shrinkage: 0.75
    max_reduction_mw: 1400
    slope_overreaction:
      enabled: true
      min_forecast_delta_mw: 4000
      min_forecast_delta_over_support_mw: 900
      min_weather_delta_c: 1.5
      min_discomfort_delta: 2.0
      max_weather_delta_c: 6.0
```

## Safety

The guard does not use TEPCO forecast values as input. It only compares the model's own forecast slope with internal lag/recent-business shape signals and weather/discomfort deltas.

The regression suite includes a cooler, well-matched 2026-07-15 style case. Even with a large 09:00 ramp, the guard stays off when the weather/discomfort regime does not support warm-ramp overreaction.

## Validation

- `python -m pytest tests/test_adjustment.py tests/test_intraday_correction.py tests/test_run_batch.py -q`
- `python -m py_compile python\forecast\adjustment.py python\etl\run_batch.py`

Result:

- `191 passed`
