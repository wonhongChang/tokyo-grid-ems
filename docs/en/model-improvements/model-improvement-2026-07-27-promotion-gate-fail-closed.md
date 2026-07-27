# Fail-Closed Model Promotion Gate

Date: 2026-07-27 (JST)

## Incident

The scheduled retraining run at 07:31 JST recorded the challenger as `promoted` even though `predictionDrift.meanAbsDeltaMw` and `maxAbsDeltaMw` were `NaN`. In Python, `NaN > threshold` evaluates to false, so both drift limits were bypassed and non-standard JSON tokens were published.

The follow-up audit found additional issues:

- the 28-day validation counted 696 hours instead of 672 because a duplicate timestamp remained in memory;
- full challenger training included partial observations from the target date, producing a `trainingCutoff` of 2026-07-27;
- today/tomorrow drift used caches that differed from production weather and provisional-lag inputs;
- the lag-24 residual ensemble could emit `NaN` when lag-24 was unavailable.

## Changes

- Promotion training now uses rows strictly before `target_date`.
- The persisted hourly cache is reloaded before validation so every timestamp is unique.
- A 28-day validation must contain exactly `28 × 24 = 672` hours.
- Drift uses production-equivalent weather and lag caches and requires 48 finite today/tomorrow values.
- Any missing, `NaN`, or infinite value causes `prediction_drift_invalid` and rejects promotion.
- When lag-24 is unavailable, the residual ensemble falls back to independent q50.
- Public JSON uses atomic writes with `allow_nan=False`, and the publish validator rejects non-finite tokens.
- A challenger artifact is staged and reloaded successfully before replacing the Champion path.

## Production-Data Replay

The pre-07:31 Champion was restored in an isolated worktree and the same operational inputs were replayed.

| Item | Before | After |
|---|---:|---:|
| Validation hours | 696 | 672 |
| Finite drift hours | Partial, with `NaN` | 48 / 48 |
| Mean absolute drift | `NaN` | 1,104.4 MW |
| Maximum absolute drift | `NaN` | 4,763.6 MW |
| Decision | Incorrect promotion | Rejected |

The configured limits are 900MW mean and 2,500MW maximum hourly drift. The corrected gate records `mean_prediction_drift_exceeded` and `hour_prediction_drift_exceeded` and retains the previous Champion.

## Verification

- Full test suite: 480 passed
- Production-data temporal validation: exactly 672 hours
- Production-equivalent today/tomorrow drift: 48 finite values
- Public artifact validation passed

## Operating Rule

Non-finite values and incomplete validation coverage are rejection conditions, not warnings. Apparent model quality never overrides the promotion contract.
