# 2026-09-14 Business-Return Forecast Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-14.md) / [日本語](../../ja/model-reviews/model-review-2026-09-14.md)

## Decision

**ETL and deployment succeeded. Monday's daytime underprediction is actionable, but excessive post-processing at 09:00 and raw-model underprediction at 13:00-14:00 are different problems.** Yesterday's Saturday morning floor change does not apply to this business day. Finalized Sunday performance was relatively good, so a blanket upward adjustment is not justified.

This is an investigation and reproduction, not an accepted model change. Model, guard, and interval settings are unchanged. No retraining, ETL dispatch, or paid AI call was performed. The experiments below have not yet passed acceptance checks.

## 1. Evidence and Timing

- At 19:58 JST, Pages status and September 13-14 actual/forecast JSON matched data commit `1ad954d4184a6021bf9c26c70ff9959a2dfbc67c`. The latest forecast was published at 19:30:23 JST.
- September 13 has 24 finalized hours. September 14 has 19 provisional actual hours, 00-18. Hour 13 means 13:00-14:00. Unobserved hours 19 onward are not scored.
- The 07:30 ETL finished at 07:45, with finalized CSV coverage through September 13. Later morning runs did not repeat the completed ETL.
- Champion: `v14-r2-source-robust-day-ahead`; artifact SHA256 `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`; training cutoff 2026-08-01. Serving fingerprint: `d788cbbcd3d956a5344bf0ce2fb7d960da425390c148516acfbd40b8f9b94ee4`.
- Git caches and observations known at four runs were reconstructed. Targets 08-17 at 08:31, 12:28, 13:35, and 15:55 reproduced all 40 saved raw q50 values with a 0.0 MW difference. This is component/input reconstruction, not a full retraining replay.
- Forecast fallback values are excluded from evaluation actuals. TEPCO comparisons use paired values from the same captured snapshot, selecting the nearest positive pre-start lead per target. This does not establish equal original TEPCO issuance times.

## 2. Displayed and Advance Performance

| Date | Actual coverage | Displayed MAE MW | WAPE | Bias MW | Maximum absolute error MW |
|---|---|---:|---:|---:|---:|
| Sep 13 Sun | 24 finalized hours | 242.6 | 0.93% | -38.6 | 924.7 |
| Sep 14 Mon | Provisional 00-18 | 594.4 | 1.75% | -331.9 | 2,155.3 |

| Date / pre-start lead | Paired hours | Model MAE MW | TEPCO MAE MW |
|---|---:|---:|---:|
| Sep 13 / 0-2h | 23 | 305.1 | 357.8 |
| Sep 14 / 0-2h | 18 | 648.0 | 269.4 |
| Sep 14 / 2-4h | 16 | 759.0 | 398.1 |
| Sep 14 / 4-8h | 14 | 994.4 | 479.3 |
| Sep 14 / 8-24h | 10 | 1,469.8 | 568.0 |

Monday displayed MAE was 196.8 MW at 00-05, 541.6 at 06-10, **1,477.5 at 11-14**, and 373.9 at 15-18. Daytime is the main problem; the whole evening cannot yet be judged. Displayed, pre-start, and retrospective recalculated forecasts are not interchangeable evaluation series.

## 3. 09:00: Post-Processing Suppressed a Real Ramp

At the 08:31 run, target 09 actual demand was 38,730 MW:

| Stage | Forecast MW | Change from preceding stage MW |
|---|---:|---:|
| Raw q50 | 39,204.2 | - |
| After timeband guard | 38,891.9 | -312.3 |
| After localized shape guard | 37,896.9 | -995.0 |
| After Intraday | 37,719.6 | -177.3 |

Raw error +474.2 MW became pre-start error -1,010.4 MW. The displayed error, -1,109.2 MW, is a separate observation.

`LocalizedShapeSpikeGuard._morning_warm_slope_overreaction_active()` uses lag24/matching-type slopes and weather changes. This path does not use the generic shape guard's same-day observed ramp support check. The latest known actual was hour 07 at 29,000 MW, with **+3,640 MW** last-hour growth and +2,675 MW recent mean growth. Temperature change from the previous day was +7.5 C; discomfort-index change +8.0 independently supported activation.

There is a concrete case of suppressing a genuine business-return ramp. However, globally disabling the guard can restore earlier warm-day spikes. First replay a candidate that checks whether **observation level, residuals, and sustained growth known at issuance** support the model ramp. Do not add a date-specific exception or assume one slope threshold solves it.

## 4. 13:00-14:00: Raw-Level Shortfall

| Run / target | Actual MW | Raw MW | Before Intraday MW | After correction MW |
|---|---:|---:|---:|---:|
| 12:28 / 13 | 44,100 | 41,437.8 | 41,687.8 | 42,454.5 |
| 13:35 / 14 | 44,080 | 41,191.5 | 41,441.5 | 42,542.0 |

Raw forecasts were already 2,662.2 and 2,888.5 MW low. Intraday increased them; correction was not disabled and ETL data was not missing.

Sunday lag24 was 28,210 MW at 13 and 28,640 at 14. Recent matching-business-type means were also below today's demand, at 38,852.5 and 38,835.0 MW. Business-day and mismatch features were correct. Weather inputs were present: 32.6 C / 61% humidity at 13, and 30.87 C / 68% at 14. Sources were JMA forecast temperature and short-horizon AMeDAS humidity persistence; target 14 also included temperature continuity correction.

This does not prove lag24 alone caused the misses:

| Target / run | Direct q50 MW | Lag24 residual-model implied demand MW | Blend weight |
|---|---:|---:|---:|
| 13 / 12:28 | 42,078.6 | 41,010.3 | 50% each |
| 14 / 13:35 | 40,791.9 | 41,153.6 | 50% each |

The residual model lowers the direct prediction at 13 but raises it at 14. Both components still miss the actual level at 14. Subsequent source-robust feature-view blending explains why final raw differs from their simple mean. **Removing all lag24 blending, forcing the matching anchor, or declaring fresh training a solution is not justified.**

Separate weather-vintage effects from model-level adaptation. A controlled ablation holding other inputs fixed is needed to quantify weather-update effects; a weather-provider fault is not established. The August 1 training cutoff motivates adaptation experiments, not a presumption that retraining will pass.

## 5. Lunch, Afternoon Correction, and Intervals

- Actual demand fell only **90 MW** from 42,710 at 11 to 42,620 at 12, then recovered to 44,100 at 13. Forcing a deep weekday lunch dip would worsen this day. The absence of an additional Midday cut is not itself a defect.
- At 15:55, baseAdjustment hit +1,200 MW. Yet target 17 raw was only 291.9 MW below actual at 39,448.1 MW, while the corrected advance prediction reached 41,004.4 MW, **1,264.4 MW above actual**. Raising the global residual cap to fix midday is unsafe.
- Mean displayed P95 full width over the 19 observed hours was approximately 6,075.5 MW, covering 19/19 actuals. `intervalCalibration` reported `insufficient_history`, `selectedSamples=0`, and 312 policy-mismatched snapshots excluded. With no eligible history for the new fingerprint, it used `native_fallback`. Full coverage does not establish accurate centers or appropriately sharp intervals.
- A Saturday-specific change still changes the global policy fingerprint and affects Monday's interval cohort. Do not ignore fingerprints; investigate whether compatibility can be demonstrated for unaffected regimes/stages before reusing older samples.

## 6. Secondary AI Report Check

The September 13 report was generated and published, using `gpt-4o-mini` for analysis and localization. Its relatively positive daily summary matches the data, and ticket hypothesis links were not dangling.

However, evidence concerned published/recalculated gaps at 18, 21, and 22, while the recommendation proposed a policy experiment at 15-17. Replacing past forecasts with later recalculations is not advance forecast improvement. **Do not adopt this recommendation.** Separate model experiments from serving-policy checks and align suggested hours with evidence. No regeneration was performed.

## 7. Experiments and Acceptance

| Priority | Work | Acceptance / exclusions |
|---|---|---|
| 1 | Observed-support checks within the existing morning slope guard | Issuance-time inputs only; replay prior overforecast days, cool days, and weekend non-intervention, not just today's 09. No blanket disabling. |
| 2 | Raw level adaptation on warm business-return days | Separate direct, lag-residual, feature-view, and weather-vintage effects. Score all 24 hours and lead bands for MAE/WAPE, bias, max error, and shape deltas; check 14-17 overprediction reversals. |
| 3 | Interval cohort compatibility and recovery | Preserve policy identity; record sample/day counts and lead-specific coverage/width. Do not narrow bands to fit one day. |
| 4 | AI evidence alignment | Match recommendation hours to evidence; do not treat retrospective serving gaps as proof of a model defect. |

September 20 is for checking the next Saturday after the new Saturday guard. **It is not a reason to postpone today's business-day guard and raw-model experiments.** Candidate replay can start from current evidence. Finalize today's provisional scores and evening side-effect checks after the September 15 ETL. This review is not a completed-fix or promotion claim.
