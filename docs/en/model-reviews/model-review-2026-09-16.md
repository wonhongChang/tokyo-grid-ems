# 2026-09-16 Evening Forecast and Report Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-16.md) / [日本語](../../ja/model-reviews/model-review-2026-09-16.md)

## Decision

September 16 has lower errors than September 15, but advance forecasts still trail the captured TEPCO reference. Two candidates were tested against historical inputs and rejected because other periods deteriorated. **Forecast model and serving configuration remain unchanged; only evidence-linking and localization defects in the AI report generator were repaired.** Retention does not mean the model is performing adequately.

## 1. Evidence Boundary

- Capture: 2026-09-16 20:09:32 JST. Work resumed on September 17 without mixing in September 17 data.
- Data revision: `18acd145ed3e80014b487d45685d87cdf82c8497`. Pages status and both days' actual/forecast files matched this revision.
- September 15: 24 finalized CSV hours. September 16: 19 provisional hours, 00:00-18:00. Hours 19:00-23:00 were not scored. Chart hour 18 means 18:00-19:00.
- ETL completed normally at 07:30-07:43, publishing the previous-day CSV results and reports. ETL failure does not explain these errors.
- Model: `v14-r2-source-robust-day-ahead`; training cutoff `2026-08-01`; artifact SHA256 `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`.
- Serving fingerprint: `d788cbbcd3d956a5344bf0ce2fb7d960da425390c148516acfbd40b8f9b94ee4`.

## 2. Performance and Stage Separation

Values are MW unless stated otherwise. Positive bias means overprediction. Displayed-line scores and pre-target snapshot scores are separate contracts.

| Period | Hours | Displayed MAE | WAPE | Bias |
|---|---:|---:|---:|---:|
| September 15 | 24 | 673.2 | 2.06% | +234.8 |
| September 16, 00:00-18:00 | 19 | 499.3 | 1.64% | -214.2 |

| Advance lead band | Sep 15 samples | Model / TEPCO MAE | Sep 16 samples | Model / TEPCO MAE |
|---|---:|---:|---:|---:|
| 0-2 h | 23 | 774.7 / 208.7 | 18 | 493.0 / 204.4 |
| 2-4 h | 21 | 1329.9 / 237.6 | 16 | 455.4 / 285.0 |
| 4-8 h | 19 | 1801.7 / 317.9 | 14 | 434.5 / 287.1 |
| 8-24 h | 15 | 2205.0 / 246.7 | 10 | 636.5 / 444.0 |

Within each lead band, select the nearest positive-lead snapshot per target and compare model/TEPCO values collected together. Their original publication times are not necessarily identical. TEPCO remains a benchmark, never a calibration target or model input.

- **September 15 afternoon:** 15:00-18:00 MAE 1593.1, all overpredictions. The displayed 17:00 error was +2336.7.
- **September 16 overnight:** 00:00-05:00 MAE 643.0. At the 00:21 run, hour-00 raw was already 830.6 below actual; boundary/cooler-day corrections lowered it another 402.2. This run is after hour 00 started, not an advance forecast score.
- **Morning:** 06:00-10:00 MAE 450.1. For 09:00, the 08:31 run's raw was 33715.6 versus actual 34570. Calibration alone cannot explain the miss.
- **Lunch:** The pre-12:00 run's raw 33787.4 was close to actual 33730. A dip already existed in raw; a stronger lunch guard is not supported by this evidence.
- **Afternoon:** 15:00-18:00 MAE 535.6, all underpredictions. Hour 16 raw 33856.2 became 33684.9 after calibration, versus actual 34580. Error direction is opposite to the previous afternoon.

Freeze preserves what was forecast; it does not explain away raw or calibration errors already present before the target.

## 3. Intervals

Displayed P95 coverage was 24/24 and 19/19, with mean full widths 5868.4 and 5217.9 respectively. Coverage alone is not evidence of a useful interval.

September 16 lead calibration remained `insufficient_history`: 78 selected samples do not guarantee at least 24 samples per lead/timeband and four days. Another 294 samples were excluded for policy incompatibility. Excluding the immediately previous day is an intentional leakage precaution when historical final-CSV publication time cannot be established, not a simple date bug. No arbitrary narrowing or relaxed sample gate was applied.

## 4. Candidate Tests and Rejections

### A. Weather-Input Sensitivity Averaging

Perturb future forecast temperatures by +/-0.5 or +/-1.0 degrees C, rebuild dependent features, and average with the original raw forecast. Observed temperatures stay unchanged. This is a bounded sensitivity experiment, not a calibrated weather-error distribution.

- Reconstructed 28 D0 origins from August 14-September 10 and 26 captured runs from September 14-16; all 54 baseline checks passed.
- On 639 positive-lead raw rows across the 28 days, MAE **1385.9 -> 1392.2 / 1391.6**. Both business and non-business subsets deteriorated.
- Recent runs' 297 future rows improved 1118.6 -> 1109.6 / 1117.4, but this did not generalize. Multiple vintages are included; these are not daily displayed-line scores.
- **Rejected:** the raw screening gate failed, so no full post-processing replay or deployment followed.

### B. Forecast-Aware Limit on Cooler-Day Prior

Limit the existing lag-overheat negative prior to the positive excess of forecast over the matching-business-type anchor, testing whether duplicated downward correction can be reduced.

- Found ten active runs in retained August 19-September 16 records; all ten baseline outputs were reproduced exactly.
- Among 15 unique date/hour targets at 0-2 h lead, September 16 MAE improved 550.7 -> 494.6; September 10 improved 705.6 -> 461.5.
- However, all 215 positive-lead rows with actuals worsened **1002.9 -> 1032.6**. September 10 worsened 1315.6 -> 1483.1; removing useful daytime correction increased some errors by about 700 MW.
- **Rejected:** near-term improvements do not justify all-day deployment or removal of the existing prior.

## 5. Accepted Report Repairs

September 15 inputs exposed clock-based attribution: Tuesday hour 08 was routed to a business-transition guard, while hours 16-17 received decline-cap tickets without evidence of a clear actual decline and forecast rebound.

1. Morning candidates now request comparisons of lag, matching-type support, weather and calibration stages. Transition-specific copy requires explicit mismatch evidence; a mismatch is context, not causal proof.
2. Automatic evening decline-cap candidates require positive error, an actual decline and a forecast rise together.
3. Korean/Japanese generated repair text no longer falls back to English on the repaired paths.
4. Report-regeneration commands are no longer presented as model-replay commands.

**74 related tests passed with network disabled.** The real September 15 inputs also passed an offline three-language context check. This is neither a paid AI regeneration nor a guarantee of an overall report quality score. Existing public report JSON was not overwritten. See [AI Report Guardrails](../ai-report-guardrails.md).

## 6. Next Decision

The next comprehensive review is **Sunday September 20 after ETL**, covering finalized September 14-18 weekdays and Saturday September 19. Further model experiments should address forecast-vintage-aware raw response and residual coupling, checking overnight, daytime and weekend regressions in both directions. Neither another one-direction guard nor a calendar date alone justifies promotion.

No paid API calls, ETL rerun, retraining, artifact replacement or serving configuration changes were made in this review.
