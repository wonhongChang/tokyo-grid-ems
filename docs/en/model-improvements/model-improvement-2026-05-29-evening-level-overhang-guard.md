# 2026-05-29 Evening Level-Overhang Guard
> An extension to the evening decline continuity guard for cases where the forecast stays too high even without a local rebound spike.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md)

---

## Why

The finalized 2026-05-29 forecast showed a persistent evening overprediction.

The model's daily MAE was `1106.2 MW` versus TEPCO's `755.0 MW`. The largest misses were concentrated in the evening decline window:

| Hour | Actual MW | Model MW | Model error MW | TEPCO error MW |
|---:|---:|---:|---:|---:|
| 15 | 35270 | 37451.7 | +2181.7 | +1040 |
| 16 | 34450 | 36690.0 | +2240.0 | +1170 |
| 17 | 33240 | 35375.0 | +2135.0 | +120 |
| 18 | 32520 | 34571.7 | +2051.7 | +200 |
| 19 | 31620 | 33686.6 | +2066.6 | +590 |

This was not the same shape as the 2026-05-27 evening rebound spike. On 2026-05-29 the forecast did not need to jump upward locally to be wrong; it simply stayed too high while observed demand was already falling.

## Root Cause

The raw LightGBM line and warm-day context preserved too much high-demand inertia into the evening. Intraday residual correction had already reached a strong negative adjustment, but the final served line still remained above the same-day actual decline path.

The original `evening_decline_continuity_guard` only acted when the near-term forecast rebounded by more than `min_forecast_rebound_mw`. That protected against spike-like shape risk, but it missed high-level overhangs where:

- same-day actual demand was clearly falling,
- near-term lead time was short,
- lag and same-business deltas did not support a rise,
- the final forecast stayed materially above the latest actual and same-business anchor reference.

## Change

Extended `evening_decline_continuity_guard` with a second mode: `level_overhang`.

The existing `rebound` mode still handles local upward spikes. The new mode handles high-but-flat evening lines. It uses the latest actual demand and same-business anchor as the level reference, then trims only the excess above the allowed buffer for near-term future buckets.

The guard still does not follow TEPCO forecasts. TEPCO values were used only for post-event comparison.

## Operating Parameters

New or adjusted configuration:

- `min_reference_hour`: 15
- `level_overhang_enabled`: true
- `min_level_overhang_mw`: 500
- `level_overhang_shrinkage`: 0.75

The guard remains limited by existing evening controls:

- `target_hours`: 16-20
- `max_lead_hours`: 2
- `max_reduction_mw`: 900
- `actual_reference_slack_mw`: 300
- weather allowance based on `temp_delta_1h`

This keeps the intervention local and conservative. It reduces level excess after a confirmed decline, rather than shifting the whole evening curve downward.

## Diagnostics

Per-hour calibration logs now distinguish the evening guard mode:

- `eveningDeclineContinuityMode`: `rebound` or `level_overhang`
- `eveningDeclineContinuityCapMw`
- `eveningDeclineContinuityReductionMw`
- `eveningDeclineContinuityWeatherAllowanceMw`

This lets the Ops Report explain whether an evening adjustment was caused by a spike-like rebound or a persistent high-level overhang.

## Test Coverage

Added a regression test for a 2026-05-29-style level-overhang case where:

- observed evening demand is falling,
- the next forecast bucket does not locally rebound,
- the served line remains above the allowed level reference,
- the guard trims the excess and records `level_overhang` in metadata.
