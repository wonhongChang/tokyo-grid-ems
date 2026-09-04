# 2026-09-04 v15 Candidate Screening Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-04-v15-candidate-screening.md) / [日本語](../../ja/model-reviews/model-review-2026-09-04-v15-candidate-screening.md)

Review date: 2026-09-04 JST

Evidence: `origin/data` commit `829497eab80fb92a8526ee39ef773b1bb3a21930`, twelve v14-r2 fixed-origin days from 2026-08-22 through 2026-09-02, the matching D0 period, and a 2026-05-20 through 2026-08-21 development window

Decision: **reject v15 q50 promotion and retain v14-r2**

## Conclusion

The review tested a same-architecture retrain with newer data, lag weighting, weather input views, rolling training windows, origin-specific direct models, and residual stacking. No candidate passed both development and fixed holdout evidence. Results that improved only one holdout were rejected because of development degradation, segment regression, or bootstrap intervals that still included regression.

Keeping the current version is an explicit promotion decision, not an absence of work. All candidates were compared against the same deployed artifact and immutable origins. This review does not change q50 serving behavior.

## Baseline

| Evaluation | Deployed v14-r2 MAE | Same-architecture retrain MAE | Candidate change |
|---|---:|---:|---:|
| D-1 fixed origin, 12 days | 3,240.5MW | 3,407.3MW | 5.15% worse |
| D0, matching 12 days | about 1,468.1MW | 1,484.2MW | 1.10% worse |

Adding recent rows and retraining the current structure did not resolve the recent regime failures.

## Candidate Results

| Candidate family | Result | Rejection reason |
|---|---|---|
| lag/anchor configuration | best D0 gain 0.46% | immaterial gain with a date-bootstrap CI crossing 1; disabling the D-1 fallback collapsed MAE to 8,523.6MW |
| weather source and humidity views | all worse than D0 baseline | removing inputs did not generalize across repeated misses |
| 365/730/1,095-day training windows | D0 worse by 2.15-9.44%; D-1 worse by 3.15-5.59% | recency weighting alone did not improve stability |
| origin-conditioned direct q50 | D-1 holdout improved 3.96% | development worsened 3.45%, worst segment regressed 6.1%, CI upper bound 1.0295 |
| origin-conditioned residual stack | D0 holdout improved 1.81% | worst segment regressed 16.66%, CI upper bound 1.1056; D-1 was effectively unchanged |

## Operational Decision

1. Retain the v14-r2 q50 model and artifact.
2. Do not add a time-specific cap or another guard for individual failure dates.
3. Continue collecting immutable D-1 origins under the P0 evidence-integrity change.
4. Design the next q50 Challenger only after forecast-vintage weather lineage and stronger regime representation are available; another blind retrain is not justified.
5. Treat interval calibration separately from q50. Only the independently validated rolling conformal target policy is changed.

## Residual Risks

- The immutable D-1 holdout contains only twelve days and is too short to justify a model-architecture promotion.
- D0 and D-1 expose different inputs, so one candidate can move in opposite directions across origins.
- Latest-value TEPCO forecasts were not used as a promotion gate because historical values can be revised.
- Experimental artifacts and temporary datasets remain outside the deployed repository; only the decision and reproducible metrics are documented.
