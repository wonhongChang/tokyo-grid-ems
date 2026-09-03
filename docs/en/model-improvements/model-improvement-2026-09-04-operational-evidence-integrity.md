# 2026-09-04 Operational Evidence Integrity and Fail-Closed Calibration State

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-04-operational-evidence-integrity.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-04-operational-evidence-integrity.md)

## Problem

The September operational review found that `same_regime_day_level_calibration` had not refreshed after August 22. The calibrator was reading the legacy `forecastBuild.hourly` field instead of the canonical `forecastBuild.series`. Per-day snapshots are also pruned to a fixed count, so correcting the parser could not safely recover every historical first-published D-1 forecast.

Champion health also used one aggregate over the latest 28 days. That window can mix prior contracts and transition-day forecasts, so it is not a valid measure of the currently deployed artifact alone.

## Changes

- Read canonical `forecastBuild.series`, retaining `hourly` only for backward compatibility.
- Persist the first D-1 raw LightGBM forecast once at `forecast_origins/<date>/<artifact>.json`.
- Retain fixed origins for 120 days, independently of the rolling intraday snapshot cap.
- Never relabel a same-day recalculation as a D-1 origin; require both model contract and artifact hash to match.
- Fail closed when the latest finalized residual exceeds `max_state_lag_days`.
- Add a `championScope` to operational replay that includes only the exact current contract and artifact. Measurement starts on the first full day after promotion to avoid a mixed transition date.
- Make Champion health validate contract-scoped coverage plus calibration compatibility and freshness.
- Record calibration status, latest residual date, lag, and applied adjustment in forecast snapshots.

## Migration

D-1 origins already removed by rolling retention are not reconstructed from same-day recalculations. Immediately after deployment, same-regime calibration can remain bypassed as `stale_state` or `insufficient_same_regime_history` until trustworthy new origins and finalized actuals accumulate. This is safer than treating an unknown forecast vintage as a genuine pre-observation residual.

## Impact

This change does not alter LightGBM weights, q50, intervals, or guard coefficients. It establishes reproducible evidence and exact Champion health before v15 experiments, while preventing stale state from silently shifting forecasts.

## Verification

- Canonical `series` residual refresh
- Immutable first D-1 origin, independent of rolling snapshot pruning
- Fail-closed stale calibration state
- Contract- and artifact-scoped operational replay
- Calibration freshness in Champion health
- Full test suite: 577 passed
