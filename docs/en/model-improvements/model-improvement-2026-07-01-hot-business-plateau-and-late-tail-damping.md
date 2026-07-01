# 2026-07-01 hot business plateau and late-tail damping

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-01-hot-business-plateau-and-late-tail-damping.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-01-hot-business-plateau-and-late-tail-damping.md)

## Background

The 2026-06-30 business-day forecast had a clear failure mode:

- the 02:18 JST intraday snapshot still placed the afternoon peak near the actual level
- after the 07:31 JST ETL rebuild, the raw LGBM curve reinterpreted the afternoon much lower
- 14:00-17:00 JST then under-forecast the hot/humid plateau
- after the afternoon miss, a positive residual carried into 21:00-23:00 JST even though lag/recent shape was already declining

The fix remains TEPCO-independent. TEPCO is used only as an external benchmark for diagnosis.

## Changes

### Business-day absolute heat context for daytime lift

`intraday_correction.daytime_sustained_underforecast_lift` now accepts business-day absolute heat/humidity context:

- `business_min_discomfort_index`
- `business_min_apparent_temp_c`

Previously, the business-day path mostly relied on 24h weather deltas. That missed cases where the day was already hot/humid enough to sustain the afternoon plateau, even if the hour-to-hour or 24h delta was no longer extreme.

The guard still requires observed residual evidence. It does not lift a forecast only because the day is humid.

### Later afternoon handoff

The daytime underforecast lift can now use observations through 15:00 JST and can protect 17:00 JST. This matches the 2026-06-30 pattern where the evidence of a sustained peak was only clear after 14:00-15:00 actuals arrived.

### Late-evening positive residual damping after 20:00

`afternoon_positive_residual_carryover_damping` now:

- covers 23:00 JST
- can remain active when the latest observed hour is 20:00 JST

This prevents a daytime under-forecast residual from mechanically lifting the whole late-evening tail when lag/recent shape indicators point downward.

## Validation

Added regression coverage for:

- a 2026-06-30-like hot/humid business plateau where 16:00-17:00 JST should be lifted only after observed underforecast evidence
- a 20:00-observed late-evening case where positive residual carryover should be damped across 21:00-23:00 JST

Targeted tests:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_daytime_lift_uses_business_discomfort_plateau_after_hot_afternoon_miss tests/test_intraday_correction.py::test_intraday_damps_business_late_evening_positive_carryover_after_20_observed_hour -q
```

Result: `2 passed`.

## Operational Notes

The important learning from 2026-06-30 is that ETL rebuilds can materially change the raw LGBM curve. The retained forecast snapshots were enough to prove that the early intraday curve was closer to the final afternoon peak, while the later ETL rebuild lowered the peak too much.

The next thing to watch is whether future AI/Ops reports distinguish:

- served forecast error caused by freeze
- latest recalculated forecast error
- raw LGBM shape error introduced after ETL rebuild
