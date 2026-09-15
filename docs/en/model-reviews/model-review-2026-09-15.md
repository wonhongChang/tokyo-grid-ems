# 2026-09-15 Warm-to-Cool Forecast Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-15.md) / [日本語](../../ja/model-reviews/model-review-2026-09-15.md)

## Decision

**Today's afternoon overprediction materialized; TEPCO was not the anomalous forecast.** Yesterday underpredicted a warmer business-return day, while today overpredicted a cooler consecutive business day. A uniform upward or downward adjustment based on either day alone is inappropriate.

ETL and deployment succeeded. Candidates were tested on retained inputs and models, but **no model/guard change was accepted**. Neither observed-supported morning guard removal/halving nor a blanket feature-view trust-bound expansion was applied. Weights, settings, published forecasts, and AI reports remain unchanged. No paid API calls or retraining were performed.

## 1. Evidence

- The 20:15 JST capture is pinned to data commit `98056e6ca2d41fa2b4e7df5e07732dd4b41d4f7b`. Pages status and September 14-15 actual/forecast JSON matched. Today's latest forecast generation time was 19:30:54 JST.
- September 14 has 24 finalized actual hours; September 15 has 19 provisional hours, 00-18. Hour 15 means 15:00-16:00 demand. Unobserved hours 19 onward are not scored.
- ETL completed at 08:44-09:00 and published September 14 finalized data and the AI report. Champion remains `v14-r2-source-robust-day-ahead`, artifact `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`, training cutoff 2026-08-01.
- Serving fingerprint is `d788cbbcd3d956a5344bf0ce2fb7d960da425390c148516acfbd40b8f9b94ee4`. The Saturday floor changed on September 13 did not change these business days' raw forecasts.
- Advance comparisons pair both models from the same captured snapshot and select the nearest positive lead in each band per target. This does not establish equal original TEPCO issuance times. Fallback actuals are excluded.
- Morning and evening captures are retained separately. Retrospective observed-weather substitution below is explicitly excluded from candidate performance and deployment claims.

## 2. Finalized and Provisional Scores

| Date | Actual coverage | Displayed MAE MW | WAPE | Bias MW | Maximum absolute error MW |
|---|---|---:|---:|---:|---:|
| Sep 14 Mon | 24 finalized hours | 590.1 | 1.74% | -381.7 | 2,205.3 |
| Sep 15 Tue | Provisional 00-18 | 744.3 | 2.26% | +364.5 | 2,356.7 |

The finalized September 14 CSV revises some provisional values, explaining differences from the [previous review](model-review-2026-09-14.md). Finalized 11-14 MAE is 1,517.5 MW; displayed hour-20 error is -1,220 MW.

Today's displayed MAE is 206.6 MW at 00-05, 632.1 at 06-10, 832.5 at 11-14, and **1,603.1 at 15-18**. All four afternoon hours are high. Hour 13 displayed error is only +190 MW, so not every hour failed equally.

| Date / pre-start lead | Paired hours | Model MAE MW | TEPCO MAE MW |
|---|---:|---:|---:|
| Sep 14 / 0-2h | 23 | 635.7 | 267.4 |
| Sep 15 / 0-2h | 18 | 843.3 | 225.6 |
| Sep 15 / 2-4h | 16 | 1,604.0 | 216.2 |
| Sep 15 / 4-8h | 14 | 2,107.3 | 313.6 |
| Sep 15 / 8-24h | 10 | 2,502.0 | 287.0 |

Errors existed before target start. Published forecast preservation is not their origin, and replacing past lines with retrospective recalculations would not fix advance performance.

## 3. Attribution

### Morning Weather Refresh and Afternoon Raw Level

At 09:01, raw forecasts for 12, 13, and 15 were 41,056.0, 42,295.3, and 42,372.1 MW. Pre-calibration values were identical; Intraday added only about 50-70 MW. The morning daytime gap originated in the raw model, not residual overshoot.

Conversely, the 06:26 run's hour-08 raw forecast, 33,788.6 MW, was close to the eventual 33,900 MW actual. After weather refresh at ETL, raw fell to 31,930.3 MW. Inputs changed without a model-version change; this was not ETL failure.

| Run / target | Actual MW | Raw MW | Corrected MW |
|---|---:|---:|---:|
| 09:32 / 10 | 37,490 | 37,585.7 | 38,765.7 |
| 13:33 / 15 | 38,370 | 41,989.9 | 40,420.0 |
| 15:45 / 16 | 38,130 | 41,379.4 | 39,763.5 |
| 15:45 / 17 | 37,530 | 39,744.0 | 38,917.8 |
| 17:37 / 18 | 36,960 | 39,441.9 | 38,337.9 |

At 10, positive residual carryover and the morning floor raised an already close raw forecast too far. Afternoon corrections reduced raw overprediction, but insufficiently. Hour-17 advance error +1,387.8 MW and displayed error +2,356.7 MW belong to different vintages.

### Retrospective Weather Substitution

Morning 07-09 humidity at 99% matched AMeDAS observations; it was not demonstrably a bad input. The 28 C daytime forecast exceeded observed temperatures of 25.7 C at 12, 26.9 C at 13, and 26.4 C at 14. Forecast temperature plus high humidity produced apparent temperatures around 35 C in morning inputs.

A **retrospective attribution experiment substituted later AMeDAS weather** while retaining the 09:01 demand inputs and weights. No later actual demand was added to model inputs. These were not forecasts available at issuance and are not promotion evidence. Hour 17 was excluded because its retained weather source was not an observation.

| Target | Actual demand MW | Original raw MW | Raw with later observed weather MW |
|---|---:|---:|---:|
| 12 | 37,420 | 41,056.0 | 37,973.5 |
| 13 | 38,730 | 42,295.3 | 39,494.6 |
| 14 | 38,420 | 42,328.5 | 39,362.1 |
| 15 | 38,370 | 42,372.1 | 41,066.2 |
| 16 | 38,130 | 41,868.6 | 39,910.3 |

Weather error substantially affected 12-14. Replacing temperature alone and recomputing derived fields with the original humidity already reduced raw to 38,054.9, 39,588.5, and 39,407.1 MW. **This does not support removing humidity as the primary remedy.** Conversely, even full observed weather left +2,696.2 MW at 15, identifying a remaining model-level/shape problem. The same substitution caused underprediction at 10-11, showing error cancellation in some hours.

### Lunch and Intervals

Actual 11-to-12 demand fell 730 MW today. At morning issuance, Midday did not activate because lag24 delta -130 MW and recent matching-type mean -483.75 MW both missed the -500 MW threshold. Yesterday's finalized actual dip was only 130 MW. These two days do not justify forcing a fixed weekday dip or simply lowering the threshold.

Displayed P95 mean full width is 5,836.0 MW over 19 observed hours, covering 19/19. Latest calibration reports `insufficient_history`, 12 selected samples, requirements of 24 samples and four days, and 309 policy-mismatched snapshots excluded. Coverage from wide native intervals is not evidence of accurate centers.

## 4. Candidate Experiments Performed

### A. Feature-View Trust Bound: Blanket Expansion Rejected

The current 500 MW bound was compared with 1,500 MW and no bound. The existing artifact and August 14-September 10 D0/D-1 inputs were reused, plus four September 14 runs and one September 15 morning run. **All 61 baseline runs reproduced raw within 0.2 MW.** This excludes retraining and full Intraday feedback replay.

- D0 pre-start targets, n=639: raw MAE 1,385.9 to 1,377.5 MW. D-1, n=672: unchanged.
- Today's 09:01 forecast, hours 10-18 subsequently observed, n=9: raw MAE 2,813.0 to 2,448.3 MW; substantial error remains.
- August 24 D0 MAE worsened from 644.0 to 731.4 MW; hour-17 absolute error increased 534.9 MW. September 9 hour 13 worsened by 530.1 MW.
- Aggregated future rows from yesterday's four runs also worsened from raw MAE 870.0 to 878.8 MW. This includes multiple issuances for the same targets and is not displayed daily MAE.

Today's partial gain does not justify a global trust-bound expansion.

### B. Observed-Supported Morning Slope Relaxation: Standalone Change Rejected

Among 327 retained runs, 50 rows had shape reductions at 08-10. Twenty-two runs on two days satisfied a candidate's three-consecutive-observation ramp/level support checks and were replayed with recorded raw/upstream stages fixed and **both shape and residual feedback recalculated**. Baseline pre/post values reproduced within rounding tolerance for 22/22 runs. Synthetic symmetric intervals were used; this was q50 testing, not interval validation.

Full exemption and 50% relaxation were both tested, separately from the existing isolated-peak guard, using only observations known at each run.

| Date / candidate | Pre-start 0-2h targets | Baseline MAE MW | Candidate MAE MW | Baseline / candidate max error MW |
|---|---:|---:|---:|---:|
| Sep 09 / full exemption | 15 | 1,040.5 | 1,013.6 | 2,430.0 / 2,430.0 |
| Sep 14 / full exemption | 15 | 794.6 | 770.3 | 1,695.5 / 2,138.1 |
| Sep 09 / half relaxation | 15 | 1,040.5 | 987.6 | 2,430.0 / 2,430.0 |
| Sep 14 / half relaxation | 15 | 794.6 | 801.4 | 1,695.5 / 2,056.5 |

Full exemption improved yesterday's hour 09 from 37,719.6 to 38,714.6 MW, but hour 11 fell from 41,208.5 to 40,641.9 MW against actual 42,780 MW. **Changing pre-calibration values at observed hours changes subsequent residuals and other lift triggers.** Adding a guard reduction back at 09 alone is insufficient validation. Published observed-hour lines were not rewritten for scoring.

## 5. Next Work

1. **Weather-vintage-robust raw candidate:** inspect differences in derived-weather definitions and error distributions between observed and forecast inputs. Evaluate robustness training using available forecast vintages or weather errors estimated strictly within training data. Do not score retrospective observed-weather substitution as a valid forecast.
2. **Residual reference and hourly level adaptation together:** test the morning candidate's 11-13 side effects, the remaining hour-15 error under observed weather, and daytime residual propagation into evening in the same execution sequence. Do not substitute larger common caps or forced hourly lifts.
3. **Explicit coverage:** include warming business-return days, subsequent cooling days, normal weekdays, and weekends. Evaluate all 24 hours and lead-specific MAE/WAPE, bias, maximum error, shape error, and interval width/coverage. Publish deterioration cases alongside gains.
4. **Next work after September 16 ETL and data push:** replace today's provisional actuals, add hours 19-23, and continue implementing and validating the weather-input robustness and residual-coupling candidates above. Finalizing the data is not a reason to postpone candidate experiments until September 20.
5. **Comprehensive review after ETL on Sunday, September 20:** evaluate finalized September 14-18 business days together with Saturday, September 19. Review the Friday-to-Saturday transition guard, weekend regressions from weekday candidates, and lead-specific central forecasts and intervals. This is separate from the next weekday improvement work; the date alone does not trigger lengthy full retraining or automatic promotion.

The conclusion is not that the model is healthy: **the problem is confirmed, and two simple classes of changes did not pass as remedies**. Next work should address raw-input robustness and residual coupling, rather than adding more guards. No Model Improvement Log entry is added because no implementation was accepted.
