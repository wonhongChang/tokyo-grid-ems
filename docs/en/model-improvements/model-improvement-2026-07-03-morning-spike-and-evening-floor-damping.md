# 2026-07-03 morning spike and evening floor damping

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-03-morning-spike-and-evening-floor-damping.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-03-morning-spike-and-evening-floor-damping.md)

## Background

The 2026-07-02 served forecast showed three separate failure modes:

- 08:00 JST under-forecasted the business-day morning ramp.
- 10:00-12:00 JST then over-corrected upward after the morning actuals arrived.
- 20:00-23:00 JST remained too high because the negative residual near-term floor restored too much downward correction while actual demand and lag/recent shape were already declining.

The next pre-observation forecast for 2026-07-03 also exposed a single-hour 09:00 JST spike. The raw/analog-adjusted curve jumped much more sharply than the lag/recent shape support and then dropped immediately at 10:00 JST.

This change does not use TEPCO forecasts as an input. TEPCO remains an external benchmark only.

## Changes

### Morning observed ramp floor support cap

`intraday_correction.morning_observed_ramp_floor` now has two additional support controls:

- `min_support_delta_mw`
- `support_delta_fraction`

The floor can still protect a strong observed morning ramp, but it no longer lifts the next hour all the way to the latest observed slope when the target-hour lag/recent shape is already flattening or declining. This targets the 2026-07-02 pattern where 09:00 actuals were strong, but 10:00-11:00 support was not strong enough to justify a full +1,200MW lift.

### Decline-aware negative residual floor damping

`intraday_correction.negative_residual_near_term_floor` now accepts `decline_support_damping`.

When:

- the latest same-day actual slope is clearly negative, and
- target-hour lag/recent shape also points downward,

the floor restores only a fraction of the downward residual correction. This prevents the floor from fighting an actual evening decline, which was the main 20:00-23:00 issue on 2026-07-02.

The calibration snapshot now records:

- `negativeResidualNearTermSupportDeltaMw`
- `negativeResidualNearTermDeclineDampingFactor`

These fields are also included in the compact AI report fact packet.

### Pre-observation morning localized spike guard

`adjustment.localized_shape_spike_guard.morning_spike` was added for unsupported pre-observation morning spikes.

It only acts when a morning hour:

- is a local peak relative to both neighbor hours,
- rises much more than lag/recent shape support,
- immediately drops in the next hour, and
- is not strongly justified by the 24h weather delta.

This is intended for the 2026-07-03 09:00 forecast shape, where the curve jumped by roughly 4.6GW and then fell by roughly 1.6GW before any same-day actuals were available.

## Validation

Added regression coverage for:

- fractional support limiting on the observed morning ramp floor
- decline-aware damping of the negative residual near-term floor
- pre-observation business-morning localized spike reduction

Targeted tests:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_observed_morning_ramp_floor_uses_fractional_support_and_skips_weak_targets tests/test_intraday_correction.py::test_intraday_near_term_floor_damps_restore_when_evening_shape_points_down tests/test_adjustment.py::test_localized_shape_spike_guard_dampens_business_morning_pre_observation_spike -q
```

Result: `3 passed`.

Related suite:

```powershell
python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py tests/test_ai_daily_report.py -q
```

Result: `155 passed`.

## Operational Notes

This is a conservative shape-control change. It does not try to make the model follow TEPCO, and it does not rewrite already served forecast points.

The next monitoring focus is whether the morning floor still protects genuine ramp-up days without creating the 10:00-12:00 over-lift seen on 2026-07-02.
