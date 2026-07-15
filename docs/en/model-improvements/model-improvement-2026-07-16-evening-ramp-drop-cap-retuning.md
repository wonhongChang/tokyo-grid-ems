# 2026-07-16 Evening Ramp Drop-Cap Retuning

## Background

The 2026-07-15 forecast was mostly acceptable from morning through the daytime peak, but the evening section exposed a clear post-processing issue.

Observed-only metrics:

| Window | Model MAE | TEPCO MAE | Note |
| --- | ---: | ---: | --- |
| Full observed day | 503.9 MW | 438.6 MW | Narrow model loss |
| 05:00-12:00 | 456.3 MW | 555.0 MW | Model was better in the morning block |
| 17:00-20:00 | 1,038.6 MW | 500.0 MW | Main failure window |

The worst row was 18:00 JST:

| Hour | Actual | Model | Error | TEPCO |
| --- | ---: | ---: | ---: | ---: |
| 17:00 | 46,980 MW | 48,080 MW | +1,100 MW | 47,390 MW |
| 18:00 | 44,940 MW | 47,080 MW | +2,140 MW | 45,780 MW |

The issue was not a raw LightGBM spike. In the 18:04 JST calibration snapshot, the pre-calibration forecast for 18:00 was 45,687.2 MW, already much closer to the final actual. The final served line rose to 47,080 MW because the last-stage `ramp_guard` enforced a near-term lower bound from the latest observed 16:00 demand.

## Change

Retuned the final ramp drop-cap relaxation path:

```yaml
ramp_guard:
  observed_drop_relaxation:
    min_recent_drop_mw: 500
    decline_support:
      min_lead_hours: 1
      max_support_delta_mw: -900
      max_decrease_mw_by_lead_hour: [2600, 4800, 6500]
```

This keeps the protection conservative:

- same-day actual demand must already show a material decline
- the target hour's `lag_24h_hourly_delta` and `recent_same_business_type_delta_mean` must both support decline
- the change only widens the final drop cap; it does not use TEPCO forecast values as input

## Reproduction

Using the 2026-07-15 18:04 JST snapshot with the updated config:

| Hour | Previous served | Retuned served | Final actual |
| --- | ---: | ---: | ---: |
| 17:00 | 48,080.0 MW | 47,094.7 MW | 46,980 MW |
| 18:00 | 47,080.0 MW | 45,620.2 MW | 44,940 MW |
| 19:00 | 46,080.0 MW | 45,225.6 MW | 43,560 MW |

The retuned path preserves the evening decline instead of forcing the curve back toward the 16:00 actual level.

## Validation

- `python -m pytest tests/test_intraday_correction.py -k "ramp_guard_relaxes_drop_cap or supported_evening_decline or ramp_guard_keeps_drop_cap or observed_demand_drop" -q`
- `python -m py_compile python\forecast\intraday_correction.py python\etl\run_batch.py`

Result:

- `4 passed`

## Notes

This is a post-processing safety retune, not a new model feature. The intent is to prevent the final ramp cap from undoing an otherwise plausible evening decline when both observed demand and target-hour shape signals agree with that decline.
