# 2026-07-18 Declining-Shape Analog Uplift Cap

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-07-18-declining-analog-uplift-cap.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-18-declining-analog-uplift-cap.md)

## Background

The final 2026-07-17 report used 21 observed hours. The model captured the morning ramp well, but retained a broad positive bias after lunch.

| Window | Model MAE | TEPCO MAE | Result |
| --- | ---: | ---: | --- |
| 00:00-20:00 | 835.0 MW | 510.5 MW | TEPCO lower |
| 06:00-10:00 | 428.0 MW | 546.0 MW | Model lower |
| 11:00-15:00 | 1,087.6 MW | 1,084.0 MW | Close |
| 16:00-18:00 | 1,762.2 MW | 293.3 MW | Main model miss |

The stage snapshots showed that the analogous-day adjustment was adding demand while the demand-shape references were already declining.

| Hour | Actual | Raw LGBM | Analog adjusted | Analog shift | Served error |
| --- | ---: | ---: | ---: | ---: | ---: |
| 15:00 | 44,390 | 47,149 | 47,603 | +454 | +680 |
| 16:00 | 44,060 | 47,378 | 48,316 | +939 | +1,652 |
| 17:00 | 42,570 | 44,657 | 45,213 | +556 | +1,443 |
| 18:00 | 41,490 | 43,723 | 44,085 | +363 | +2,191 |
| 19:00 | 40,250 | 42,525 | 43,616 | +1,092 | +1,266 |
| 20:00 | 38,210 | 40,236 | 40,724 | +488 | +685 |

At these hours, both `lag_24h_hourly_delta` and `recent_same_business_type_delta_mean` supported a flat-to-declining path, and the current day was not warmer than the previous day. Intraday correction reduced the served line later, but it had to fight an avoidable positive analog shift first.

## Change

Added `business_declining_analog_uplift_cap` inside `PostHolidayTimeBandGuard`. It limits only the analogous-day positive shift; it does not lower the raw LightGBM forecast.

The cap requires all of the following:

- ordinary business-day sequence with no business-type mismatch
- target hour between 13:00 and 20:00
- positive analog shift of at least 300 MW
- both lag-24 and recent same-business deltas at or below +200 MW
- temperature/cooling deltas at or below 0°C

When all gates match, the analog uplift is limited to +100 MW. Weekend, holiday-transition, warmer-day, rising-shape, and incomplete-feature cases bypass the guard.

The duplicated `localized_shape_spike_guard.morning_spike` YAML key was also consolidated. The existing 08:00-11:00 local-peak settings remain intact, while the 08:00-10:00 slope-overreaction mode now has its own cap parameters and is no longer discarded by YAML parsing.

## Replay Check

A directional replay over available July business-day calibration snapshots found 12 matching rows between 13:00 and 20:00.

| Metric | Before | After |
| --- | ---: | ---: |
| Matching-row MAE | 1,916.2 MW | 1,437.9 MW |
| Improved rows | - | 12 / 12 |

This is a stage-level replay of stored recalculation snapshots, not a replacement for the full rolling backtest. The rule remains deliberately narrow for that reason.

## 2026-07-19 Forecast Review

The target is Sunday, so this business-day guard changes all 24 forecast hours by 0.0 MW. The current peak is 34,439.9 MW at 18:00. A recent hot Sunday, 2026-07-12, reached 34,780-34,850 MW at 18:00-19:00, so the level and evening peak timing are plausible.

The P95 half-width stays between 1.74 GW and 3.00 GW with no interval inversion. The 07:00-08:00 forecast ramp (+3.54 GW) is sharper than the recent Sunday samples, but the cumulative 06:00-09:00 ramp is close to 2026-07-12. It should be monitored rather than hard-capped before actual evidence arrives.

## Validation

- `python -m pytest tests/test_adjustment.py -q`
- full repository test suite
- production-config parse check for the merged morning guard
- local status-only regeneration from the latest `origin/data`

TEPCO forecasts remain evaluation references only and are not used by this guard.
