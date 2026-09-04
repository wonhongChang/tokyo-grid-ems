# 2026-09-04 Rolling Conformal Target Interval

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-04-rolling-conformal-target-interval.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-04-rolling-conformal-target-interval.md)

## Problem

The previous rolling conformal policy was only a **minimum-width floor**. It could widen an interval but could not reduce an already oversized native quantile band. On the twelve-day v14-r2 fixed-origin holdout, P95 coverage was 100% while mean half-width reached 3,700.2MW and most hours saturated at the 3,750MW cap. The interval no longer distinguished risk by time band.

## Change

A serving-only P95 target policy now sits outside the model artifact.

1. Use finalized dates strictly before the target date.
2. Compute same-business-regime absolute-error q95 values by time band over the latest 28 finalized days.
3. Compute all-regime q95 values by time band over the latest ten days as a drift safeguard.
4. Take the larger value, multiply by a 1.05 safety factor, and cap it at 3,750MW.
5. Replace P95 with a symmetric q50-centered target only when every time band is available.
6. Fail closed to the existing floor/native interval when history is incomplete.

The policy is configured under `served_interval_calibration`. It does not change the trained quantile estimators, the LightGBM artifact fingerprint, or the q50 model contract.

## Validation

All results use causal walk-forward reconstruction that excludes the target date from calibration history.

| Period | Previous P95 coverage | New coverage | Previous mean half-width | New mean half-width | Change |
|---|---:|---:|---:|---:|---:|
| twelve-day v14-r2 fixed origin | 100.00% | 98.61% | 3,700.2MW | 2,455.5MW | 33.6% narrower |
| latest 28 days | 97.92% | 97.17% | 3,200.0MW | 2,675.6MW | 16.4% narrower |
| latest 84 days | 95.19% | 96.08% | 2,373.0MW | 2,139.6MW | 9.8% narrower |
| 106 days, 2026-05-20 to 09-02 | 94.73% | 96.78% | 2,168.6MW | 2,199.0MW | 1.4% wider |

Over 84 days, business-day coverage was 95.83%, non-business coverage was 96.63%, and the lowest time-band coverage was 94.44% overnight. The policy widens under-covered daytime and late-afternoon periods while shrinking over-covered overnight and evening periods. The objective is restored P95 meaning, not uniform narrowing.

## Operational Traceability

Each forecast JSON records the following under `intervalCalibration.servedTarget`:

- same-regime and recent all-regime history windows;
- sample counts and q95 widths by time band;
- safety factor and final target widths;
- target availability and fallback state.

## Limits

- P95 is a long-run marginal coverage target, not a promise that every individual day covers 95% of its hours. Abrupt regime shifts can still produce low daily coverage.
- P99 continues to extend one additional final P95 half-width.
- This change does not improve q50. The v15 q50 candidates were rejected in a separate review.
