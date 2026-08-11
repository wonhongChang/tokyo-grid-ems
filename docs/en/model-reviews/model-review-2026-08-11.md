# 2026-08-11 Operational Model Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-08-11.md) / [日本語](../../ja/model-reviews/model-review-2026-08-11.md)

Review date: 2026-08-11 JST

Evidence cutoff: finalized actuals through 2026-08-10 and intraday observations through the 2026-08-11 morning

Status: completed

## Decision

- Retain the v11 `lag24_residual_ensemble` Champion.
- Reject promotion of the current v13 Challenger. It passes the supplemental 84-day view but fails the recent 28-day MAE, WAPE, and daytime-segment limits.
- Accept two isolated operational changes: extend the observed morning anchor cap to non-business days, and add a leakage-safe rolling conformal minimum interval floor after a separate band replay.
- Keep q50 features, training window, raw quantile models, business-day lunch logic, and global intraday limits unchanged. The interval floor changes published width only.
- TEPCO remains an external benchmark only. It is not an input, anchor, target, or calibration source.

## Data Integrity

| Check | Result | Evidence |
|---|---|---|
| Final actual coverage | Pass | `actual/2026-08-10.json` has 24 observed hours |
| Actual-source integrity | Pass | No `tepco_forecast_fallback` value was scored as final actual |
| Calendar path | Pass | 2026-08-11 is Mountain Day with `is_holiday=1` and `is_non_business_day=1` |
| Holiday guard isolation | Pass | Business-only q50 and `MiddayTransitionGuard` paths were inactive |
| Weather inputs | Pass | No unexplained NaN or source discontinuity caused the 2026-08-11 morning miss |
| Public artifacts | Pass | Public status, actual, forecast, report, and promotion files validated |

The 2026-08-11 final daily score is intentionally excluded because the day was still open. Its morning snapshots were used only for stage attribution and candidate behavior checks.

## Recent Live Performance

These rows evaluate the forecast that was actually served for each finalized date.

| Date | Regime | MAE MW | WAPE | RMSE MW | Bias MW | Max error MW | TEPCO MAE MW |
|---|---|---:|---:|---:|---:|---:|---:|
| 2026-08-05 | Business | 643.3 | 1.85% | 762.6 | -223.7 | 1,731.4 | 347.5 |
| 2026-08-06 | Business | 960.4 | 2.57% | 1,219.8 | -897.5 | 3,234.7 | 308.8 |
| 2026-08-07 | Business | 1,119.1 | 2.85% | 1,364.1 | -374.6 | 3,829.9 | 272.1 |
| 2026-08-08 | Weekend | 853.4 | 2.44% | 1,125.2 | +654.8 | 2,570.0 | 334.6 |
| 2026-08-09 | Weekend | 1,362.9 | 4.24% | 1,626.7 | +1,344.2 | 3,111.1 | 517.5 |
| 2026-08-10 | Business return | 1,730.2 | 5.30% | 2,113.3 | +1,721.4 | 4,929.9 | 578.8 |

The sign reversal from business-day underprediction on August 6-7 to non-business and return-day overprediction on August 9-10 shows a regime problem rather than one global level offset. A global q50 shift or a larger intraday cap would therefore trade one failure direction for the other.

## 28-Day Operational Replay

Period: 2026-07-14 through 2026-08-10, 672 served hours.

| Segment | MAE MW | WAPE | RMSE MW | Shape delta MAE MW |
|---|---:|---:|---:|---:|
| Overall | 890.1 | 2.399% | 1,182.1 | 705.0 |
| Business | 889.4 | 2.328% | 1,199.4 | 729.6 |
| Non-business | 891.6 | 2.564% | 1,144.8 | 653.0 |
| Morning | 970.2 | 2.618% | 1,295.7 | 997.6 |
| Daytime | 960.4 | 2.111% | 1,231.4 | 725.8 |
| Late afternoon | 1,152.8 | 2.654% | 1,529.7 | 898.3 |

The served system remains better than the raw-model-only snapshot path, but morning and late-afternoon shape are still the highest-risk operational segments.

## Challenger Validation

The same v13 contract was trained only on data before each holdout window.

| Window | MAE MW | WAPE | RMSE MW | Max error MW | Shape delta MAE MW | Decision |
|---|---:|---:|---:|---:|---:|---|
| Recent 28 days | 1,208.1 | 3.256% | 1,532.8 | 5,050.8 | 628.3 | Reject |
| Supplemental 84 days | 790.6 | 2.526% | 1,114.5 | 5,432.4 | 481.3 | Pass supplemental view only |

Recent 28-day segment MAE was 1,290.7 MW on business days, 1,033.6 MW on non-business days, and 1,549.4 MW in daytime. The last value exceeds the fixed 1,500 MW segment ceiling. The recent-window MAE and WAPE also exceed the fixed 1,000 MW and 3.0% limits. Long-window averaging cannot override these failures.

Training-window reductions to 730, 548, and 365 days, q50 blend changes, and a business residual-weight change did not produce a stable recent-window gain. They were rejected.

## Lunch-Dip Audit

The 12:00 bucket is the 12:00-13:00 interval. On the reviewed business days, the actual 11-to-12 changes were +60, +40, -550, and -290 MW for August 5, 6, 7, and 10. The raw-model changes were -1,014.4, +608.5, -111.5, and -1,209.6 MW.

`MiddayTransitionGuard` applied `0 MW` on all four dates because its additional evidence gate did not pass. This was correct: the raw model already contained a dip on three dates, and two dates had no actual 11-to-12 decline. The guard must not manufacture a fixed weekday lunch drop. No lunch parameter was changed.

## 2026-08-11 Holiday Diagnosis

The calendar and guard routing were correct, but raw q50 was too high in the morning. At 09:00 the pre-calibration forecast was about 33.0 GW while actual demand was 28.56 GW. Intraday residual correction reached its -1.2 GW limit, yet the remaining near-term forecast was still elevated.

The existing observed morning anchor cap was restricted to business days. This left a gap on weekends and holidays: clear same-day overprediction evidence existed, but the extra near-term level cap was unavailable. The problem was not a missing holiday flag or an active business-day lunch guard.

## Accepted Operational Change

`morning_observed_anchor_cap.non_business_extension` is enabled with these constraints:

- only weekend or holiday forecasts;
- only after the latest observed hour is 08:00 or 09:00;
- latest model residual must show at least 400 MW of overprediction;
- only target hours already supported by lag-24 or recent same-business shape;
- at most four lead hours and 1,000 MW reduction;
- 0.75 shrinkage rather than a hard clamp;
- veto when the latest observed ramp is at least 4,000 MW, its two-step mean is at least 2,500 MW, and cumulative shape support is at least 2,500 MW;
- automatic handoff after the latest observed hour passes 09:00.

This layer uses only TokyoGridEMS model output, finalized demand history, same-day TEPCO actual demand, calendar state, and internal lag/shape features. It never reads the TEPCO forecast value.

## Candidate Replay

Historical calibration snapshots from nine non-business mornings between 2026-07-18 and 2026-08-09 supplied 68 comparable forecast-hour records.

| Metric | Existing behavior | Candidate | Result |
|---|---:|---:|---|
| Morning snapshot MAE | 1,456.2 MW | 1,282.9 MW | -173.3 MW (-11.9%) |
| Records changed | 0 | 13 | Narrow intervention |
| Maximum reduction | 0 MW | 1,000 MW | Configured cap respected |
| Confirmed explosive ramp on 2026-08-08 | Preserved | Preserved | Ramp veto worked |

One affected 2026-07-18 record worsened slightly, so the candidate is not described as universally improving every hour. The aggregate gain, limited intervention count, hard cap, strong-ramp veto, and post-09:00 handoff support deployment as an operational guard rather than a model promotion.

## Interval Review

The 28-day p95 coverage was 93.8% overall. Coverage was 90.7% on non-business days, 89.3% in the morning, 91.4% in daytime, 89.3% in late afternoon, and 99.3% in the evening.

A separate causal walk-forward experiment applied the finite-sample 95% absolute-error quantile from the previous 28 finalized dates, split by business regime and time band, only as a minimum half-width. Overall coverage improved to 95.8%, non-business coverage to 95.8%, morning to 94.3%, and daytime to 95.7%. Average half-width increased by 144.6 MW and the existing 3,000 MW maximum remained intact. The target date, fallback actuals, and TEPCO forecasts are excluded.

Late-afternoon coverage improved only to 90.5% at the cap, confirming a centerline/shape issue rather than a band-width issue. Evening remained overcovered at 99.3%; the safe minimum-floor policy does not narrow existing intervals.

## Verification

- `155` focused intraday, batch, and interval tests passed.
- Full suite in the primary workspace: `500 passed`.
- Public artifact validator passed.
- Production-equivalent `run_batch.py --status-only` completed.
- The v11 Champion artifact and promotion thresholds remain unchanged.

## Residual Risk And Next Review

- The extension cannot repair hours already frozen or forecasts before enough same-day evidence exists.
- Final 2026-08-11 accuracy must be scored after the August 12 ETL; the open day is not backfilled into this decision.
- Late-afternoon p95 coverage remains below target and requires centerline/shape work; it must not be hidden with a wider-than-3,000 MW band.
- Evening overcoverage requires a separate two-sided narrowing experiment before any production reduction.
- Recheck after the next finalized weekend, on 2026-08-17 JST. Earlier changes are limited to deterministic data, calendar, or pipeline defects.
