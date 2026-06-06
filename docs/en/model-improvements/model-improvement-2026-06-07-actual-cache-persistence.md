# 2026-06-07 Actual JSON Cache Persistence

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md)

---

## Problem

The weekend forecast review exposed two separate issues.

On 2026-06-06, the finalized Saturday report showed a real shape problem: the model overestimated the morning ramp, then undercut 10:00-13:00, and finally overreacted around 15:00. That remains a controller/model-shape case to monitor.

The 2026-06-07 Sunday forecast had an additional data-continuity problem. `actual/2026-06-06.json` already contained Saturday actual demand, but `.hourly_cache.parquet` still stored 2026-06-06 as forecast-weather rows with `actual_mw = NaN`. As a result, Sunday inference could lose `lag_24h` and lean too heavily on older lags, recent same-business averages, and warm weather signals.

## Change

Moved hourly cache persistence after actual JSON injection in both execution paths:

- status/intraday refresh
- full ETL

The pipeline already injected recent actual JSON rows in memory before forecasting. The bug was that the persisted cache was saved before that injection. Now the cache saved to `.hourly_cache.parquet` includes the same observed or temporary fallback actuals used by the forecast run.

## Operational Effect

When the monthly TEPCO ZIP has not yet confirmed yesterday's CSV, the system still uses `actual/YYYY-MM-DD.json` as the continuity bridge for lag features. This keeps the next day's `lag_24h` input aligned with the dashboard's own actual series.

This is not a TEPCO-aware calibration layer. TEPCO forecast values are not used to tune the model or chase TEPCO's curve. The only temporary fallback behavior is the existing operational rule for missing late-night actual rows until the confirmed CSV arrives.

## Diagnostics

The incident signature was:

- `actual/2026-06-06.json`: 24 actual values available
- `.hourly_cache.parquet`: 2026-06-06 rows present, but `actual_mw` count was 0
- 2026-06-07 inference: `lag_24h` unavailable for all hours

The fix adds a regression test that injects actual JSON, saves the hourly cache, reloads it, and verifies that demand, TEPCO forecast reference, usage, supply, and weather fields remain intact.

## Validation

- Added `test_injected_actuals_can_be_persisted_to_hourly_cache`.
- Verified that cache persistence now happens after `_inject_today_actuals(...)`.

