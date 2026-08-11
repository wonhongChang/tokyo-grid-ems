# Rolling Conformal Interval Floor

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-08-11-rolling-conformal-interval-floor.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-11-rolling-conformal-interval-floor.md)

## Problem

The independently trained q025/q975 tails can become unstable after a weather-regime shift. The existing 3,000 MW half-width cap prevents extreme bands from dominating the UI, but a fixed cap alone does not correct undercoverage. In the finalized 28-day operating replay, p95 coverage was 93.8% overall, 90.7% on non-business days, and 89.3% in the morning.

## Change

Published intervals now have a leakage-safe rolling conformal minimum floor. For each target date, the pipeline:

1. selects the latest 28 dates marked complete by ETL before the target date;
2. excludes incomplete 24-hour files and `tepco_forecast_fallback` values;
3. keeps only the target's business or non-business regime;
4. groups absolute served-q50 errors into overnight, morning, daytime, late-afternoon, and evening bands;
5. uses the finite-sample 95% upper quantile when a band has at least 24 samples;
6. applies that value only as a symmetric minimum p95 half-width.

The policy never narrows an existing interval and never exceeds the existing 3,000 MW operational cap. The target day's actuals and TEPCO forecast are not calibration inputs.

## Walk-Forward Replay

The candidate was evaluated causally for each of the latest 28 finalized dates, using only data available before each target date.

| Segment | Existing coverage | Candidate coverage |
|---|---:|---:|
| Overall | 93.8% | 95.8% |
| Business | 95.2% | 95.8% |
| Non-business | 90.7% | 95.8% |
| Overnight | 97.0% | 97.0% |
| Morning | 89.3% | 94.3% |
| Daytime | 91.4% | 95.7% |
| Late afternoon | 89.3% | 90.5% |
| Evening | 99.3% | 99.3% |

Average p95 half-width increased from 2,349.3 MW to 2,493.9 MW, or 144.6 MW. The maximum remained 3,000 MW.

## 2026-08-11 Sanity Check

The non-business profile used nine contributing dates. Its floors were 1,561.5 MW overnight, 2,949.6 MW in the morning, 2,230.6 MW in daytime, 3,000 MW in late afternoon, and 1,870 MW in the evening. At 07:00, the published lower bound would move from 24,613.6 MW to 24,186.3 MW and include the 24,350 MW actual. Hours already wide enough remain unchanged.

## Traceability And Failure Behavior

Each forecast JSON records the method, target regime, history range, contributing-date count, sample count, and floor by time band under `intervalCalibration`. Missing state, incomplete history, or fewer than 24 samples causes that band to fail closed without changing the interval.

## Remaining Risk

Late-afternoon coverage remains below target even at the 3,000 MW cap. That is primarily a centerline and shape-drift problem and must not be hidden by wider bands. Evening overcoverage also remains; this minimum-floor policy intentionally avoids narrowing existing intervals until a separate two-sided calibration experiment proves that safe.

## Verification

- Rolling-profile tests cover finite-sample rank, target-date leakage, finalized-source integrity, insufficient history, JSON provenance, and the 3,000 MW cap.
- Full suite: `500 passed`.
- The v11 Champion, q50, raw quantile models, intraday correction, and TEPCO-independent modeling policy are unchanged.
