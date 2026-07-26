# Model Governance and Source Integrity

Date: 2026-07-26 (JST)

## Why this change was needed

The production model was previously retrained and overwritten during each full ETL run. A successful training process did not prove that the new artifact preserved weekday, non-business-day, and time-band quality. The hourly cache also lacked an explicit distinction between confirmed demand and TEPCO forecast fallback values.

## Evidence

The 28-day served-forecast replay for 2026-06-28 through 2026-07-25 covered 672 hours:

| Metric | Result |
|---|---:|
| MAE | 560.0 MW |
| WAPE | 1.642% |
| RMSE | 761.7 MW |
| Shape delta MAE | 491.4 MW |
| P95 coverage | 96.1% |
| Average P95 half-width | 1,867.1 MW |

The latest 13 days with stage snapshots showed that analogous-day adjustment degraded raw-model MAE from 910.8 MW to 957.1 MW and increased shape error. Analog adjustment is therefore disabled in production while its stage remains measurable as a shadow candidate.

## Changes

### Champion/challenger promotion

- Full ETL keeps the current champion on ordinary days.
- Monday is the default challenger evaluation day; `TOKYO_GRID_EMS_FORCE_MODEL_TRAIN` can request an explicit evaluation.
- Every evaluation uses the latest rolling 28 complete days. This is not a 28-day retraining interval.
- The challenger must beat the baseline and satisfy absolute MAE, WAPE, maximum-error, shape-error, regime, and time-band limits.
- A challenger that changes the near-term prediction curve beyond configured drift limits is rejected.
- A missing or incompatible champion does not bypass a failed gate; the normal baseline fallback remains available.
- Promotion metadata and the gate result are written to `metrics/model_promotion.json`.

### Demand and weather source integrity

- `actual_source` is persisted in the hourly cache.
- `tepco_forecast_fallback` remains available only for lag continuity where required.
- Fallback demand is excluded from training targets, same-day observed slopes, residual calibration, analogous-day residuals, and validation actuals.
- Confirmed CSV observations always outrank fallback values.
- Recent forecast weather is replaced by `AMEDAS_ACTUAL` when the official observation becomes available.

### Operational replay

`metrics/operational_replay.json` now reports:

- served MAE, WAPE, RMSE, maximum error, and shape error;
- business/non-business and time-band metrics;
- TEPCO reference metrics without using TEPCO as a model input;
- latest-snapshot stage comparisons;
- interval coverage and empirical interval-width recommendations in shadow mode.

Stage comparisons use the latest available snapshot for each date and must not be interpreted as an exact reconstruction of every historical intraday run.

### CI

The new CI workflow runs the complete Python test suite and the React production build independently on pushes to `main` and pull requests.

## Rollback

- Set `model_promotion.enabled: false` only for an intentional emergency bypass.
- Re-enable `adjustment.analogous_day.enabled` only after a replay shows consistent improvement across business type and time bands.
- The current champion remains untouched when a challenger fails any gate.
