# 2026-09-21 Holiday Forecast and Post-Change Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-21.md) / [日本語](../../ja/model-reviews/model-review-2026-09-21.md)

## Decision and Evidence

**No additional model change.** This follows the September 20 review and the subsequent [observed evening recovery change](../model-improvements/model-improvement-2026-09-21-observed-evening-recovery.md). Remaining errors warrant investigation, but one incomplete day under the new policy does not justify another feature, correction or interval-threshold change. This is not a health certification or promotion pass.

- Pages updated at **19:31 JST on September 21**; pinned data revision: `068296bcb629a2229bb2adb18b156656cfa7017a`.
- Public status and both days' actual/forecast JSON match the revision. September 20 is finalized with 24 hours; September 21 has **19 observed hours, 00-18**. Hours 19-23 are not evaluated.
- Since the previous review, September 20 hours 21-23 arrived and some provisional actuals were revised. The previously observed 00-20 published center line is unchanged.
- Champion remains `v14-r2-source-robust-day-ahead`, training cutoff 2026-08-01, artifact `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`.

## Performance

MW unless stated otherwise. Advance comparisons choose each target's nearest strictly positive 0-2h lead with both forecasts in the same capture. TEPCO's independent issuance time is unavailable; this is not formal parity qualification. Published and advance populations differ.

| Date | Actual hours | Published MAE / WAPE | Advance pairs | Model advance MAE | TEPCO advance MAE |
|---|---:|---|---:|---:|---:|
| 09-20 finalized | 24 | 291.5 / 1.14% | 23 | 352.5 | 307.4 |
| 09-21 provisional | 19 | 392.5 / 1.48% | 18 | 442.1 | 443.3 |

Today's similar average to TEPCO conceals opposing errors. Published bias is **-589.4MW at 06-10** and **+535.7MW at 15-18**. Neither supports moving the whole day uniformly.

## Stage Attribution

Raw and post values below come from the same advance run, not retrospective recalculation. September 20's 23 and September 21's 18 selected calibration rows match the corresponding capture within 0.2MW. This checks record consistency, not full model replay.

| September 21 target / calculation | Actual | Raw | Post-calibration | Observation |
|---|---:|---:|---:|---|
| 10 / 09:31 | 29010.0 | 27681.6 | 27871.2 | Low raw level; +189.6 recovers only part |
| 12 / 11:41 | 29590.0 | 29146.7 | 30466.6 | +519.9 residual plus +800.0 lift reverses the error upward |
| 14 / 13:36 | 30260.0 | 28558.7 | 29680.8 | +1122.1 reduces a large raw shortfall |
| 17 / 15:59 | 30620.0 | 30465.5 | 31196.7 | +731.2 residual worsens a relatively close raw forecast |
| 18 / 17:40 | 30490.0 | 31133.9 | 31429.8 | +295.9 adds to raw overprediction |

Hour 10's final published value is 27816.0MW, error -1194.0MW. Hour 12's publication, 29703.6MW, is better than its advance value, but cannot erase the 11:41 overshoot. Hour 18 was already high before target start; forecast preservation did not create that error.

At hour 18, existing non-business damping reduces +657.6MW carryover to +295.9MW. The new `observed_recovery_veto` does not activate: the latest observed change at hour 16 is only +40MW. None of the 16 retained September 21 calibration runs records this recovery exception. This day therefore does not demonstrate its effectiveness or justify removing existing damping.

## Calendar, Weather and Intervals

September 21 is Monday but a Japanese holiday, Respect for the Aged Day. All 24 feature rows rebuilt from the pinned current cache and current code have `is_holiday=1`, `is_non_business_day=1`, and previous-day business-type mismatch=0. This is reconstruction, not archived historical feature vectors. All 16 retained forecast runs have zero hour-12 weekday midday-guard adjustment. Actual 11-to-12 demand rises 100MW; forcing a business-day lunch dip is unsupported.

The latest cache contains temperature and humidity for all 24 hours: 19 AMeDAS sources, four JMA plus short-horizon humidity persistence, and one JMA plus Open-Meteo JMA humidity supplement. Current observations must not be substituted for historical forecast inputs. Weather/lag causal attribution still requires issue-time input replay.

| Date | Advance interval rows / P95 covered | Mean P95 full width | Application |
|---|---|---:|---|
| 09-20 | 20 / 20 | 3663.2MW | 15 lead targets, 5 native |
| 09-21 | 18 / 18 | 4757.8MW | 18 native |

Interval snapshot retention differs from the center-line ledger. Selected advance and published intervals have no P99/P95/q50 ordering errors. Today's published mean width is 4859.9MW and hour 13 reaches 7500.0MW. Short-period coverage alone cannot certify appropriate width.

The important change is **policy-compatible calibration history**. `servingPolicyFingerprint` changed from `d788cbbc...` to `ba4d1431...`, first seen at 01:29. The latest profile excludes 319 old-policy snapshots and records `selectedSamples=0`, `insufficient_history`. This is policy exclusion, not simply a shortage of holiday observations. The 24-sample/four-day requirements and policy separation remain unchanged. Calibration resumes only with sufficient compatible lead/timeband history.

## Follow-Up

September 20 AI reports exist in Korean, English and Japanese with `gpt-4o-mini` analysis/localization. Generation status only was checked; no OpenAI regeneration or prose-quality reassessment was performed.

Review the finalized September 21-23 holiday days **after the September 24 morning ETL**. Integrity defects such as missing data or crossed intervals remain actionable earlier. Examine morning raw shortfalls, noon lift overshoot versus afternoon recovery, evening damping/recovery activation and policy-specific interval samples together. Reaching that date is not automatic authorization to change the model.

No new candidate or promotion was run. The [runbook](../operations-runbook.md), [promotion policy](../model-promotion-policy.md), replay/validation rules, scheduler and production forecasts remain unchanged.
