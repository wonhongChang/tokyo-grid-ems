# 2026-08-21 v14-r2 Source-Robust Day-Ahead Champion

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-08-21-v14-r2-source-robust-day-ahead.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-21-v14-r2-source-robust-day-ahead.md)

## Decision

`v14-r2-source-robust-day-ahead` replaced the degraded v11 Champion. The earlier v14-r1 staging candidate was not deployed: when most target-day demand lags were unavailable, it either retained the v11 missing-value path or applied an unsafe whole-day shift. v14-r2 instead trains a dedicated q50 path for the information that genuinely exists at a D-1 forecast origin.

The promoted artifact is independent of TEPCO forecasts. TEPCO values remain an external benchmark and the temporary 23:00 lag-continuity fallback only; they are not training targets or calibration anchors.

## Contract

- The normal D0 path retains the absolute-demand, lag-24 residual, and non-business q50 structure.
- Two source views reduce sensitivity to missing historical humidity and short-horizon weather fields. Their output is constrained to within 500 MW of the legacy q50.
- When `lag_24h`, last-business-day demand, or last-non-business-day demand is unavailable at the forecast origin, dedicated source-robust q50 models take over. These models exclude the six unfinalized demand-lag features and the weather fields that cannot be reconstructed consistently at D-1.
- The D-1 non-business specialist receives full weight because it was selected on the July development window before the August holdout was opened.
- A same-regime day-level residual calibrator uses the three most recent finalized days, 0.25 shrinkage, and a 1,000 MW absolute cap. It is artifact-scoped and never learns from the target day.
- The p95 half-width is multiplied by 1.25 after interval sanity calibration. The pre-scale cap is 3,000 MW and the final cap is 3,750 MW; q50 is unchanged.

## Fixed-Origin Validation

Every replay removes observations that were not available at the simulated publication time. In particular, target-day actuals are blanked and source commits captured after the simulated hour cannot leak later actuals. Holdout comparisons use the exact deployed v11 artifact SHA, not a newly retrained approximation.

| Evaluation | Period | v14-r2 MAE improvement | RMSE improvement | Max-error improvement | Shape improvement | Better days |
|---|---|---:|---:|---:|---:|---:|
| D0 development | 2026-07-01 to 2026-07-31 | 5.13% | 4.63% | 2.03% | 10.16% | 24 / 31 |
| D0 exact-Champion holdout | 2026-08-01 to 2026-08-20 | 18.76% | 16.54% | 15.51% | 16.01% | 16 / 20 |
| D-1 development | 2026-07-01 to 2026-07-31 | 68.87% | 64.32% | 55.87% | 44.84% | 31 / 31 |
| D-1 exact-Champion holdout | 2026-08-01 to 2026-08-20 | 39.82% | 46.96% | 44.39% | 30.22% | 13 / 20 |

On the D0 holdout, MAE fell from 1,725.4 MW to 1,401.8 MW. On the D-1 holdout, it fell from 5,018.9 MW to 3,020.3 MW. No operating segment exceeded the non-regression limit. The paired date-bootstrap upper bounds for the MAE ratios were 0.9095 and 0.8383, respectively.

An additional 84-day finalized-weather support replay reduced central MAE from 902.3 MW to 883.9 MW and shape error from 534.7 MW to 512.6 MW across all time bands. Its maximum single-hour error increased by 437.1 MW, still within the 500 MW source-view trust region; both fixed-origin holdouts reduced maximum error.

## Promotion and Monitoring

The current/tomorrow drift was intentionally large because the v11 D-1 curve followed a structurally broken missing-lag branch. The largest correction was +9,654.8 MW. Large-drift approval was therefore allowed only after both exact-Champion holdouts passed strict recovery gates and exceeded the independent 8% D0 and 20% D-1 MAE thresholds.

| Item | Value |
|---|---|
| Contract | `v14-r2-source-robust-day-ahead` |
| Interval contract | `q025_q50_q975_p95_v14_source_robust_day_ahead` |
| Training cutoff | `2026-08-01` |
| Champion SHA-256 | `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3` |
| Rollback v11 SHA-256 | `28b75352b8b13713aba04880111dd11b3450864a3580f355081072af4266a640` |
| Promotion status | `recovery_promoted` |
| Stabilization review | after 3 finalized operating days |

The D-1 holdout WAPE is still about 9.15%, so this promotion is a structural recovery from v11 rather than parity with TEPCO. The previous artifact must remain available during stabilization. Rollback review starts immediately for source-integrity failure, non-finite or incomplete forecasts, or a material regression against the v11 shadow after finalized evidence is available.
