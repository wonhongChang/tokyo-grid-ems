# 2026-09-13 Weekend Forecast Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-13.md) / [日本語](../../ja/model-reviews/model-review-2026-09-13.md)

## Decision

Saturday's displayed full-day forecast was reasonably stable, but **06-07 overprediction from post-processing and 09-14 underprediction need improvement**. Sunday's initial capture covered provisional actuals through 06; the closing follow-up extends through 12, not the unobserved afternoon or evening.

Unconditionally excluding cross-business-type lag24 slope regressed earlier Saturdays and was rejected. A subsequent conditional rule was replayed and implemented: exclude that support only when pre-guard observations support the lower forecast level. The trained artifact is unchanged; serving-guard support selection and an AI report evidence-linking defect are repaired. This is not raw-model promotion or a claim that forecast improvement is complete.

## 1. Evidence and Operations

- Pages updated at 07:48:34 JST matched data commit `2c5fd2b98b7c64230ae28857e4c545be3948c325` for status and September 11-13 actual/forecast JSON. Separate evidence copies and a SHA256 manifest were retained.
- The 07:30 ETL finished at 07:45, with finalized CSV coverage through September 12 and no failed dates. This review did not rerun ETL or push data.
- Champion: `v14-r2-source-robust-day-ahead`; artifact `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`.
- `tepco_forecast_fallback` is excluded from actual-based evaluation and residuals. Finalized demand evaluates errors; replay uses the provisional observations known at each historical run.
- TEPCO comparisons select the smallest positive lead per target within each bucket, with both forecasts present in the same capture. This does not establish identical original TEPCO issuance times.

## 2. Displayed Versus Advance Forecasts

| Date | Actual coverage | Displayed MAE MW | WAPE | Bias MW | Max absolute error MW |
|---|---|---:|---:|---:|---:|
| Sep 11, Fri | Final 24 hours | 384.7 | 1.34% | +52.2 | 1,084.5 |
| Sep 12, Sat | Final 24 hours | 305.4 | 1.16% | -71.8 | 1,089.3 |
| Sep 13, Sun | Provisional 00-06 | 233.3 | 1.08% | +233.3 | 475.9 |

Saturday MAE was 179.7MW at 15-18 and 185.0MW at 19-23, versus 631.5MW at 06-10. Neither a full-day failure label nor a blanket downward shift is justified.

| Date / pre-start lead | Targets | Model MAE MW | TEPCO MAE MW |
|---|---:|---:|---:|
| Sep 11 / 0-2h | 23 | 520.3 | 386.1 |
| Sep 12 / 0-2h | 23 | 400.1 | 189.6 |
| Sep 12 / 2-4h | 21 | 526.2 | 230.5 |
| Sep 12 / 4-8h | 19 | 640.7 | 243.2 |
| Sep 12 / 8-24h | 15 | 624.7 | 248.0 |
| Sep 13 / 0-2h | 6 | 308.7 | 126.7 |

Saturday's first D-1 origin was issued September 11 at 00:22. Its 24-hour raw MAE was 863.7MW and post-processing MAE 882.7MW. These roughly 24-48-hour leads are not interchangeable with same-day near-term forecasts. Better displayed errors do not establish TEPCO-level advance skill.

## 3. Saturday Attribution

These are **pre-start** snapshots, not necessarily the final displayed points. Hour `06` means demand for 06:00-07:00 JST.

| Run / target | Actual MW | Raw MW | Pre-intraday MW | Post MW |
|---|---:|---:|---:|---:|
| 05:29 / 06 | 22,930 | 23,074.8 | 23,840.2 | 23,843.0 |
| 06:24 / 07 | 24,150 | 24,502.6 | 24,982.0 | 24,963.0 |
| 08:31 / 09 | 27,170 | 27,078.6 | 27,078.6 | 26,618.9 |
| 09:31 / 10 | 28,340 | 27,813.0 | 27,813.0 | 27,274.0 |
| 10:34 / 11 | 28,670 | 28,106.9 | 28,106.9 | 27,765.2 |
| 12:24 / 13 | 28,920 | 27,960.7 | 27,960.7 | 28,093.8 |

At 06, `non_business_morning_shape_floor_guard` selected the larger of lag24 slope +1,550MW and recent same-business-type slope +287.5MW. Friday's steeper ramp added 765.4MW to Saturday's floor, increasing a raw error of only +144.8MW. The same selection added 479.4MW at 07.

At 09 the raw forecast was only 91.4MW low, but residual correction subtracted another 459.7MW. At 10-11 both raw level and residual correction were low. Earlier guard lifts affect residuals computed against the current run's pre-calibration curve; simply subtracting a guard from the final output does not replay this interaction.

Raw underprediction remained at 13-14. At 13 its error was -959.3MW, partially repaired by intraday correction. Fixing the morning floor alone does not solve the daytime raw error.

The September 11 sustained-decline change was deployed according to the serving fingerprint. No activation of `negativeResidualNearTermDeclineEvidenceBasis` was found in the retained September 11-13 snapshots. Saturday's aggregate result cannot be attributed to that patch.

## 4. Candidate Comparison and Conditional Repair

The candidate excludes lag24 slope from the morning floor on business-type mismatch, retaining recent matching-type support. It adds no date-specific adjustment, cap or TEPCO forecast input.

Saved August 14-September 10 D0 and D-1 origins, 672 hours each, were reused. D-1 was unchanged; D0 regressed in some morning hours on August 22, August 29 and September 5. Previously rejected plain retraining and specialist-mixture searches were not repeated.

We also replayed 51 morning runs across four Saturdays and today, using historical Git caches and then-known observations. Captured raw/upper-level/analog stages were fixed; timeband, midday, shape and intraday stages were recomputed together. The table includes only the 48 runs whose baseline pre/post matched the recorded values within rounding tolerance. Three runs were excluded because subsequent controller semantics differed. Synthetic interval bounds were used for this q50 screen: it is neither an interval replay nor a full Champion promotion test.

| Date | Matched-run 0-2h targets | Baseline MAE MW | Candidate MAE MW |
|---|---:|---:|---:|
| Aug 22 | 12 | 968.9 | 884.7 |
| Aug 29 | 10 | 1,020.9 | 1,133.3 |
| Sep 5 | 12 | 463.4 | 482.2 |
| Sep 12 | 12 | 545.1 | 404.3 |
| Sep 13 | 3 | 296.9 | 296.9 |

September 12's 10:00 candidate recovered to 27,510.9MW but remained below actual demand. August 29's 06:00 forecast fell from 25,305.1 to 24,505.1MW against an actual 25,600MW. Explaining one error mechanism does not establish multi-day safety. The candidate is not deployed.

### Additional Conditional Screen

The implemented rule prefers matching-type slope only when the latest two consecutive observations before the first guarded target are not more than the existing 250MW slack above their same-hour pre-guard forecasts. Missing observations, genuine level shortfall or missing matching-type slope preserve existing behavior. Observations at or after 06 cannot authorize the 06-07 support choice.

On the same replay samples, conditional MAE was 968.9, 1,020.9, 463.4, 404.3 and 296.9MW for Aug 22, Aug 29, Sep 5, Sep 12 and Sep 13 respectively. Earlier Saturdays and today were unchanged; September 12 improved. All 672 saved D0 and 672 D-1 origins were unchanged. September 12 target 08 worsened slightly, so this is not improvement at every hour. See the [implementation contract, validation and rollback](../model-improvements/model-improvement-2026-09-13-observed-weekend-shape-support.md).

## 5. Intervals and AI Report

Saturday's displayed P95 mean full width was 4,620.5MW with 24/24 coverage. Retained pre-start 0-2h snapshots had 20 targets, mean width 4,924.0MW and 100% coverage. Snapshot retention differs from the TEPCO ledger, hence different sample counts. One fully covered day does not validate long-run 95% calibration.

The new fingerprint correctly reports `insufficient_history` and retains native bands. The four-day/24-sample requirements were not relaxed or populated with incompatible-policy residuals. Deploying the conditional setting changes fingerprint again, so compatible history must be checked from deployment onward. No fixed interval-activation date is promised.

The September 12 AI report used `gpt-4o-mini` for analysis and localization, with `localizationStatus=ok`. However, it created an evening model-cap ticket from a 863.7MW retrospective recalculation gap at 17, where the displayed actual-demand error was only -4.9MW. Its `event.freeze_gap_h17` link did not identify the surviving grouped hypothesis. A 15:00 freeze gap similarly produced a midday-feature ticket.

This defect is fixed: `published_recalculated_gap` events do not generate model-tuning tickets, including from cached fact packets. Tickets link to actual surviving hypothesis IDs. Real demand-error events and freeze explanations remain available. No OpenAI model/API setting changed, paid call was made, or published report overwritten. This is evidence-integrity repair, not comprehensive validation of AI narrative quality.

### Sunday Follow-up: 15:42 JST

At completion, Pages' 13:32:34 publication matched status/actual/forecast at data commit `2502fbe3f56a236bd8ec33dfe37cb50cbbd48a8f`. Actuals cover 00-12, 13 targets: displayed MAE 265.7MW, WAPE 1.13%, bias +51.7MW, max absolute error 507.2MW. Same-capture pre-start 0-2h comparison has 12 targets, model MAE 372.0MW versus TEPCO 320.0MW. These later samples are kept separate from the morning tables.

Displayed errors at 11 and 12 were -507.2 and -489.8MW. In the 11:36 run, target 12 raw demand of 27,034.2MW was already 805.8MW below actual 27,840MW; residuals subtracted another 71.2MW. A weekday lunch guard did not activate on Sunday. Targets after 12 are not evaluated yet. P95 covers 13/13 with mean full width 4,329.8MW, still broad.

## 6. Next Work

1. Review Sunday's finalized daytime/evening observations after the September 14 ETL. This does not mean root-cause work must wait for that date.
2. After deploying the conditional morning floor, check genuine high-demand weekends and residual side effects at 08-11. Reuse the saved replay features rather than repeatedly tuning date-specific constants.
3. Treat D0 09-14 raw underprediction and D-1 regime bias as separate experiments; gains in one lead do not prove gains in another.
4. Evaluate interval width and coverage on compatible-policy positive-lead samples, separately from q50 accuracy.

Changes include the conditional morning guard, AI ticket evidence checks, tests and documentation. The review did not replace the trained model, trigger an automatic run or update production data. Source push and deployment status are verified separately.

Verification: **678 Python tests passed** with external networking blocked. Modified-document links and diff whitespace are also checked.
