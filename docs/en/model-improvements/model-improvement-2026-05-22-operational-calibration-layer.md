# 2026-05-22 Operational Calibration Layer

> A structural post-processing layer for midnight and early-intraday forecasts. It keeps LightGBM unchanged and separates data-source confidence from residual correction.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-22-operational-calibration-layer.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-22-operational-calibration-layer.md)

---

## Why This Was Needed

The previous approach added several hour-specific guards to protect particular failure modes. That helped some days, but it also made the operational forecast harder to reason about.

The midnight failure on 2026-05-22 showed a cleaner structural problem:

- 22:00-23:00 actuals can be missing until the next morning.
- Those missing rows may temporarily use `tepco_forecast_fallback` so lag features remain populated.
- Fallback values are useful as lag inputs, but they are not real observed demand.
- If fallback rows are treated as residual observations, the model can believe it performed well just before midnight.
- At 00:00, intraday correction resets because same-day observed rows are still sparse.
- The model can then over-trust an overheated `lag_24h` value.

## What Changed

The intraday post-processing layer now has three explicit responsibilities.

1. Source-aware residuals

`tepco_forecast_fallback` rows remain available for lag features, but residual correction ignores them. Only real observed actuals can steer the intraday residual loop.

2. Day-boundary residual carry-over

When the new day has too few real observed rows, the corrector can carry the last real observed residual from the previous day across midnight. Fallback hours are skipped, and the carried residual decays quickly by elapsed hour.

3. Day-level scale calibration

Before enough same-day observed rows exist, the layer checks whether `lag_24h` is much higher than the recent same business-type demand level while the current day is cooler than the previous day. If so, it applies a capped, fading downward bias to the affected future hours. This is a calibration layer, not a new LightGBM feature.

## What Was Disabled

The active configuration disables the earlier time-band style intraday guards:

- midday residual deweighting
- shape guard
- ramp guard
- midday transition guard
- afternoon-only negative residual damping

The code paths remain testable, but the active operating pipeline now prioritizes source confidence and day-level scale calibration over hour-specific patches.

## Debug Metadata

Each intraday run writes:

`reports/internal/operational-calibration/YYYY-MM-DD.json`

The report includes:

- `source_confidence`
- `applied_regime_reason`
- `applied_day_bias`
- residual carry-over metadata
- ignored fallback residual count

This makes midnight failures explainable without exposing internal diagnostics in the dashboard UI.

## Tests

- Intraday correction now ignores fallback rows for residual calculation.
- Day-boundary carry-over skips fallback rows and uses the latest real observed residual.
- Day-level scale calibration applies only when lag overheat and cooler-day signals align.

