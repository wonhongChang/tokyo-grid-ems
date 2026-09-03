# 2026-09-03 v14-r2 Operational Model Review

Language: [한국어](../../ko/model-reviews/model-review-2026-09-03.md) / [日本語](../../ja/model-reviews/model-review-2026-09-03.md)

Review date: 2026-09-03 JST

Evidence window: 288 finalized hours from 2026-08-22 through 2026-09-02, 21 observed hours through 20:00 on 2026-09-03, matched forecast vintages, operational calibration snapshots, diagnostic features, and forecast intervals

Reproducibility baseline: `origin/data` commit `cb4e9c6d5`, forecast contract `v14-r2-source-robust-day-ahead`, artifact SHA `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`

Status: complete - keep v14-r2 temporarily, classify it as `review_required`, repair P0 evaluation/calibration defects, and develop a v15 challenger; no serving behavior changed

## Decision

- Do not roll v14-r2 back blindly. There is no replacement validated under the same contract, and Intraday correction improves aggregate accuracy.
- Do not classify the current Champion as healthy. Finalized served MAE is 693.6MW, but matched-vintage error is 26% to 51% higher than TEPCO in every lead bucket.
- September 3 through 20:00 has MAE 925.8MW and bias +821.9MW. Hours 16 and 17 missed high by 3.11GW and 3.48GW.
- Raw q50 is the dominant problem. At 0-2h lead, raw MAE of 1,201.7MW falls to 1,004.9MW after post-processing and Intraday correction.
- The intervals are excessively wide rather than well calibrated. P95 coverage is 100%, but mean half-width is about 3.70GW and 88% of rows hit the configured cap.
- Repair the same-regime snapshot parser, fixed-origin retention, and contract-scoped health reporting before changing forecast levels.
- Develop v15 to test lag/anchor dependence and weather-transition features. Do not add another hour-specific cap or guard without replay evidence.

## Evaluation Contract

| View | Purpose | Constraint |
|---|---|---|
| Final served forecast | Measures what users actually saw | Includes Published Forecast Freeze |
| Matched-vintage comparison | Compares model and TEPCO at the same `capturedAt` | Primary external benchmark |
| Latest TEPCO value | Mirrors the latest dashboard value | Context only because TEPCO revises historical forecasts |

TEPCO forecasts are never model inputs or calibration targets.

## Data Integrity

| Check | Result | Evidence |
|---|---|---|
| v14-r2 scope | Pass | August 21 is excluded as a transition day; one artifact SHA is used from August 22 |
| Final actuals | Pass | 12 complete days and 288 hours through September 2 |
| Current-day actuals | Pass | 21 hours through 20:00 on September 3 |
| Core diagnostics | Pass | No missing demand, weather, lag, or business-anchor fields in the finalized window |
| Stage reconstruction | Pass | 215 calibration snapshots and 2,851 future rows matched within 17 seconds |
| Weather-vintage lineage | Incomplete | Forecast issue time and full source lineage are not retained consistently |
| Immutable origin | Fail | The per-day snapshot cap can prune the true first-issued forecast |

## Finalized Daily Performance

| Date | Day type | MAE MW | WAPE | RMSE MW | Bias MW | Max error MW |
|---|---|---:|---:|---:|---:|---:|
| 2026-08-22 | Saturday | 682.6 | 2.08% | 903.2 | -98.0 | 1,966.2 |
| 2026-08-23 | Sunday | 503.0 | 1.64% | 721.1 | +95.5 | 2,510.0 |
| 2026-08-24 | Business | 687.7 | 1.79% | 866.1 | -129.7 | 1,973.9 |
| 2026-08-25 | Business | 446.3 | 1.09% | 601.1 | +19.0 | 1,810.0 |
| 2026-08-26 | Business | 698.4 | 1.68% | 877.5 | +114.8 | 2,170.7 |
| 2026-08-27 | Business | 1,140.3 | 3.18% | 1,473.4 | +1,037.7 | 3,634.7 |
| 2026-08-28 | Business | 972.1 | 2.66% | 1,113.2 | -218.4 | 2,150.9 |
| 2026-08-29 | Saturday | 1,173.3 | 4.15% | 1,355.5 | +763.6 | 2,490.0 |
| 2026-08-30 | Sunday | 473.1 | 1.79% | 651.9 | +9.4 | 1,507.3 |
| 2026-08-31 | Business | 815.7 | 2.60% | 1,007.8 | +341.8 | 2,129.3 |
| 2026-09-01 | Business | 334.7 | 1.02% | 491.6 | +43.5 | 1,635.1 |
| 2026-09-02 | Business | 395.6 | 1.11% | 557.4 | -159.7 | 1,650.0 |

The aggregate is MAE 693.6MW, WAPE 2.02%, RMSE 933.5MW, and bias +151.6MW. The first five days produced MAE 603.6MW, the latest seven 757.8MW, and the latest three 515.3MW. This is regime-dependent volatility rather than monotonic decay.

## September 3 Through 20:00

| Metric | Result |
|---|---:|
| Observed hours | 21 |
| MAE | 925.8MW |
| WAPE | 2.62% |
| RMSE | 1,292.8MW |
| Bias | +821.9MW |
| Maximum error | +3,480.0MW at 17:00 |
| Shape delta MAE | 782.1MW |

The main misses are +1.95GW at 11:00, +1.45GW at 15:00, +3.11GW at 16:00, and +3.48GW at 17:00. The 16:00 forecast was already 4.31GW high at 00:25 and rose to 6.05GW high after 05:30. This was not caused by one late Intraday run.

At 17:37, raw q50 for 18:00 fell from 42,359.6MW to 38,768.6MW and 19:00 fell from 40,181.9MW to 37,709.8MW. Their weather deltas changed from -0.7°C to -3.2°C and -0.5°C to -2.2°C. The update rescued later hours but arrived too late for 16:00-17:00. Incomplete issue-time lineage prevents attributing this conclusively to an upstream API.

## Time-Band Performance

| Band | Rows | MAE MW | Bias MW | RMSE MW | P95 absolute error MW |
|---|---:|---:|---:|---:|---:|
| 00-05 | 78 | 474.3 | +24.6 | 610.1 | 1,264.4 |
| 06-10 | 65 | 670.3 | -17.7 | 896.5 | 1,907.0 |
| 11-15 | 65 | 793.0 | +364.5 | 1,023.7 | 2,170.7 |
| 16-18 | 39 | 1,048.7 | +544.0 | 1,335.2 | 3,110.0 |
| 19-23 | 62 | 744.9 | +245.9 | 1,040.9 | 2,133.7 |

Late afternoon is the weakest band, followed by daytime and evening. The highest hourly MAEs occur at 18:00, 19:00, 17:00, 14:00, and 09:00.

## Matched-Vintage Benchmark

| Lead | Rows | Model MAE MW | Model WAPE | TEPCO MAE MW | Ratio |
|---|---:|---:|---:|---:|---:|
| 0-2h | 396 | 954.3 | 2.71% | 631.9 | 1.51 |
| 2-4h | 375 | 1,277.5 | 3.50% | 928.3 | 1.38 |
| 4-8h | 685 | 1,604.7 | 4.24% | 1,228.8 | 1.31 |
| 8-24h | 1,221 | 1,634.7 | 4.46% | 1,296.4 | 1.26 |

For 0-2h lead, date-block bootstrap gives a mean absolute-error difference of +315.8MW with a 95% interval of +130.0 to +506.4MW. The model wins on only 3 of 12 dates. The latest-published TEPCO MAE of 410.2MW remains contextual and is not a promotion gate.

## Stage Attribution

| Lead | Raw q50 MAE | Pre-Intraday MAE | Final MAE | Final bias | Intraday helped/hurt |
|---|---:|---:|---:|---:|---:|
| 0-2h | 1,201.7 | 1,231.1 | 1,004.9 | +458.2 | 281 / 144 |
| 2-4h | 1,538.5 | 1,526.0 | 1,393.2 | +871.0 | 257 / 147 |
| 4-8h | 1,847.7 | 1,820.2 | 1,754.6 | +1,227.8 | 416 / 319 |
| 8-24h | 1,818.1 | 1,805.6 | 1,774.9 | +1,047.3 | 731 / 554 |

Keep Intraday enabled, but do not raise its cap globally because it hurts 34% to 43% of rows. Raw q50 and regime representation are the primary targets.

For 0-2h morning forecasts, raw MAE is 1,074.3MW, pre-Intraday MAE 1,154.0MW, and final MAE 1,096.8MW. Post-holiday/timeband guards require trigger-only shadow-disable replay before any removal.

Keep Published Forecast Freeze. Served forecasts beat end-of-day recalculation on 194 rows and lost on 113. It preserves the real forecast vintage, and the September 3 miss existed before the affected hours closed.

## Root Causes

### Lag and anchor dependence

`recent_same_business_type_mean` accounts for 23.59% and `lag_24h` 20.78% of deployed q50 gain importance. Rows where lag_24h exceeds the same-business anchor by more than 5,000MW have MAE 970.5MW and bias +667.0MW.

### Cooldown and rising humidity

Rows at least 2°C cooler than the prior day have MAE 1,091.8MW and bias +930.5MW. Rows with humidity rising by at least 10 percentage points have MAE 1,122.9MW and bias +794.8MW. Signed temperature, cooling, humidity, and discomfort deltas need isolated ablation.

### Stale same-regime calibration

`python/forecast/same_regime_calibration.py` reads `forecastBuild.hourly`, while snapshots use `forecastBuild.series`. `metrics/same_regime_day_level_calibration.json` has not refreshed since August 21, leaving old +133MW business and -486.5MW non-business adjustments active.

A counterfactual improves aggregate raw MAE by only about 12.5MW, so this is not the main forecasting failure. It remains a P0 correctness defect. The per-day 16-snapshot cap also makes the earliest retained file an unstable origin.

### Mixed-contract health reporting

`model_promotion.json` reports `healthy`, but its 28-day replay mixes v11 and v14-r2. Health, promotion gates, and alerts must be scoped by artifact SHA and forecast contract.

### Weather-vintage lineage

Each run should persist `weather_source`, `forecast_issued_at`, `fetched_at`, AMeDAS residual, and fallback status so late revisions can be reproduced.

## Interval Review

P95 and P99 coverage are both 100%. P95 mean half-width is 3,703MW, and 272 of 309 rows, or 88.0%, hit the 3,750MW cap. The current floor-only conformal layer cannot narrow overwide native quantiles.

The next v14-specific shadow candidate must segment by lead and time band. Deployment gates are 93-97% overall P95 coverage, at least 90% in every major band, and at least 15% lower mean width, with hierarchical backoff for sparse segments.

## Required Changes

| Priority | Change | Reason | Acceptance condition |
|---|---|---|---|
| P0 | Read `forecastBuild.series` in same-regime calibration | State is stale after August 21 | Parse 24 rows and refresh through the latest finalized date |
| P0 | Preserve an immutable named origin outside rolling retention | Earliest retained snapshot is not fixed vintage | Origin ID and issue time survive pruning |
| P0 | Add calibration freshness guard and alert | Prevent silent stale adjustment | Bypass or mark degraded state and expose its age |
| P0 | Scope Champion health by artifact and contract | Mixed v11/v14 metrics hide current health | Aggregate same-SHA post-deployment rows only |
| P1 | Train and ablate v15 | Raw q50 dominates error | Compare isolated lag and weather candidates against exact v14 replay |
| P1 | Test dynamic lag/anchor regularization | Overheated-lag rows show +667MW bias | Improve large-gap regime without normal-regime regression |
| P1 | Ablate weather deltas and humidity | Cooldown/rising-humidity overforecast repeats | Compare clipping, source-robust, and no-humidity candidates |
| P1 | Persist weather lineage | Late revisions are not reproducible | Store source, issue/fetch time, fallback, and residual |
| P1 | Shadow-disable triggered timeband guards | Morning 0-2h may worsen | Report matched benefit and regression on triggered rows |
| P1 | Shadow v14 interval recalibration | 88% of rows hit the width cap | Meet coverage gates and reduce mean width by at least 15% |
| P2 | Add immutable D-1 24-48h scoring | Separate tomorrow and Intraday quality | Preserve and score a fixed D-1 origin |

## v15 Experiment Rules

1. Extend training through 2026-09-02 and compare under the same contract as v14-r2.
2. Isolate baseline, lag regularization, weather-delta clipping, no-humidity, and source-robust candidates.
3. Score business/non-business and 06-10, 11-15, 16-18, and 19-23 bands separately.
4. Use paired date/hour comparisons and block-bootstrap intervals against v14-r2. Latest TEPCO MAE is not a promotion gate.
5. Reject incident-only fixes. Use 28/56/84-day replay plus available post-deployment fixed origins.
6. Challenger generation may resume in shadow mode, but automatic promotion remains disabled.

## Next Review

Begin technical review as soon as P0 repairs and v15 replay are ready. If the serving contract remains unchanged, the next operational checkpoint is after the morning ETL on 2026-09-10, when seven more finalized days are available. A serving change starts a new observation window.

This review changed documentation only. It did not modify the model artifact, configuration, guards, or deployed data.
