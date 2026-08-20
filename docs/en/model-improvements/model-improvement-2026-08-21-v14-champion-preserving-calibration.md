# 2026-08-21 v14 Champion-Preserving Calibration

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-08-21-v14-champion-preserving-calibration.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-21-v14-champion-preserving-calibration.md)

## Decision

The first v14 draft retrained the complete hourly stack and added an independent D+1 model. It was rejected before deployment. Against the deployed v11 artifact, it lifted the current business-day 11:00-15:00 band by about 2.34GW and lowered the next non-business day by about 3.25GW on average. Those changes were too large to attribute safely to the intended daily-level correction.

The final v14 contract preserves the deployed v11 hourly q025, q50, q975, and lag-24 residual boosters exactly. It adds only:

- a dedicated non-business q50 estimator, blended 50:50 on weekends and holidays;
- a daily-level estimator trained on up to 730 complete days, applying 20% of the level disagreement with a +/-750MW cap.

There is no independent D+1 model. The v14 auxiliaries run only after either 24 confirmed preceding-day hours or confirmed hours 00:00-22:00 plus the known 23:00 TEPCO forecast fallback. Every other incomplete pattern follows the v11 q50 contract exactly, preventing a mostly unobserved current day from being treated as a complete lag day.

TEPCO forecasts remain excluded from model training, calibration, and feature inputs. The fallback value is only a lag-continuity substitute until confirmed CSV actuals arrive.

## Same-Cutoff Replay

Both arms retrained the same v11 hourly contract at each holdout cutoff. Only the v14 auxiliary estimators were added to the candidate.

| Window | v11 MAE / WAPE | v13 reference MAE / WAPE | v14 MAE / WAPE | v14 MAE gain vs v11 |
|---|---:|---:|---:|---:|
| 28 days | 1245.8MW / 3.623% | 1183.5MW / 3.442% | 1142.5MW / 3.322% | 8.29% |
| 56 days | 1005.8MW / 2.995% | 975.6MW / 2.905% | 972.0MW / 2.894% | 3.36% |
| 84 days | 901.0MW / 2.852% | 884.1MW / 2.799% | 871.5MW / 2.758% | 3.27% |

The 28-day business and non-business MAEs improved by 7.61% and 10.04%. Overnight, morning, daytime, late-afternoon, and evening improved by 10.12%, 9.05%, 4.38%, 9.75%, and 10.03%. Overall shape-delta MAE improved from 632.0 to 597.1MW. The 56-day maximum error rose only 4.8MW, while the 28-day and 84-day maxima fell.

The degraded-Champion recovery threshold is now 8% only when 56/84-day non-regression, segment risk, maximum-error/shape risk, exact-artifact, smoke, and drift gates all pass. This avoids tuning model strength merely to cross a single 10% cliff.

## D+1 Safety Replay

A frozen-origin missing-lag replay showed that the absolute D+1 error remains structurally high when the current day is incomplete. v14 therefore does not claim to solve D+1 forecasting. Its safety contract is narrower: an incomplete day cannot activate the new auxiliary estimators, so the candidate cannot be worse than v11 because of v14-specific logic.

Against the latest `origin/data` cache, the staged candidate changed the 2026-08-21 and 2026-08-22 forecasts by 104.4MW on average and 208.8MW at most. The current day had 23 confirmed preceding-day hours plus the permitted final-hour fallback. The next day had insufficient preceding-day coverage and matched v11 exactly.

Only 00:00-02:00 were confirmed when this staging check was run. On those three hours v11 MAE was 162.7MW and v14 MAE was 371.4MW because the common +208.8MW shift moved in the wrong direction. This partial-day result is not a promotion metric, but it is an explicit reason to keep remote deployment operator-controlled and to inspect the completed day before ending the stabilization window. It also motivated reducing the daily weight from 0.25 to 0.20.

## Data Coverage Audit

The local cache contained 31,897 hourly rows from 2023-01-01 through the current virtual forecast horizon. The audit found several information gaps that can explain part of the remaining gap to TEPCO:

- demand is hourly, while TEPCO AREA files expose 30-minute demand and generation values;
- weather observations use one Tokyo AMeDAS station rather than a regional multi-point field;
- humidity, discomfort, and weather-source metadata are complete only in the recent operating period and are missing for most older history;
- historical replay has final observed weather, not point-in-time weather-forecast vintages;
- the model has no cloud cover, solar irradiance, regional renewable output, industrial operating schedule, or event-operation feed.

Official TEPCO AREA data was used to build an offline fixed day-ahead benchmark, never a feature. Across all 353 available days from 2025-09-01 through 2026-08-19, the fixed TEPCO forecast had MAE 347.8MW and WAPE 1.117%; the 2026-only 231-day slice was 369.9MW and 1.188%. On 2,520 hours matched with stored served forecasts, TEPCO MAE was 359.1MW and the project MAE was 613.3MW. These are not identical forecast products, but they establish that a material quality gap remains.

A private experiment added five lagged renewable-generation features from AREA actuals. It improved the 28-day replay but regressed 56-day and 84-day performance, especially in the evening, so the features were rejected.

Based on TEPCO's public research pages, it is reasonable to infer that a utility forecaster can use broader regional weather context, larger weather datasets, renewable-generation forecasts, and finer temporal resolution. This is an inference from public material, not a claim about TEPCO's proprietary production feature set.

## Promotion Record

The candidate was recovery-promoted in an isolated staging directory on 2026-08-21 JST. Remote deployment remains a separate operator decision.

| Item | Value |
|---|---|
| Training cutoff | `2026-08-19` |
| v14 artifact SHA-256 | `77a35437305d60de841d2277bc2ed636878f0170a2386d727312397ba1b8a3d3` |
| Rollback SHA-256 | `28b75352b8b13713aba04880111dd11b3450864a3580f355081072af4266a640` |
| Current/tomorrow drift | mean 104.4MW, maximum 208.8MW |
| Smoke test | 48/48 finite forecasts |

The four hourly booster payloads are identical between v11 and v14. Rollback remains mandatory during the first 72 operating hours after deployment.
