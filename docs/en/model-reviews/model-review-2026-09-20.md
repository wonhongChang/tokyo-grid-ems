# September 20, 2026 Forecast Review

Languages: [한국어](../../ko/model-reviews/model-review-2026-09-20.md) / [日本語](../../ja/model-reviews/model-review-2026-09-20.md)

## Findings

Weekday errors decreased from the preceding week, but advance forecasts still trail TEPCO substantially. September 20 is not a whole-day failure: published MAE through hour 20 is 296.4MW. Morning and evening underprediction remain. Raw-model error and calibration side effects vary by date, so neither a global upward shift nor blanket damping removal is justified.

This is an evidence review, not a candidate replay or promotion test. No model, configuration, or published data was changed. Retaining the model does not constitute renewed performance approval.

## Evidence

- Pages timestamp: **2026-09-20 21:37:00 JST**; data revision `12dc8a2952de19f572489f9b36d8880b36cfeaa9`. Status and September 7-20 actual/forecast files matched the pinned revision.
- Finalized CSV coverage ends September 19, with no failed dates. September 20 has **21 provisional observations, hours 00-20**. Hours 21-23 are not evaluated. Hour 20 represents 20:00-21:00.
- Champion: `v14-r2-source-robust-day-ahead`, training cutoff August 1; artifact `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`; serving policy `d788cbbcd3d956a5344bf0ce2fb7d960da425390c148516acfbd40b8f9b94ee4`.
- Advance comparisons select the nearest positive lead in **0-2 hours before target start**, pairing both models from the same capture. This does not establish identical original issuance times. Forecast substitutes are excluded from actuals.
- All 319 comparable September 7-20 calibration/ledger rows matched post-calibration q50 within 0.2MW, with ledger capture within 120 seconds after calibration generation. This checks record consistency, not counterfactual replay.

## Results

All MAEs are MW. Published WAPE and advance metrics have separate sample populations.

| Date | Actual hours | Published MAE | Published WAPE | Advance samples | Advance model MAE | Advance TEPCO MAE |
|---|---:|---:|---:|---:|---:|---:|
| 09-14 | 24 | 590.1 | 1.74% | 23 | 635.7 | 267.4 |
| 09-15 | 24 | 673.2 | 2.06% | 23 | 774.7 | 208.7 |
| 09-16 | 24 | 498.1 | 1.65% | 23 | 514.6 | 170.9 |
| 09-17 | 24 | 303.2 | 1.03% | 23 | 389.5 | 273.5 |
| 09-18 | 24 | 566.3 | 1.94% | 23 | 582.9 | 410.9 |
| 09-19 | 24 | 355.7 | 1.37% | 23 | 440.1 | 158.3 |
| 09-20 provisional | 21 | 296.4 | 1.15% | 20 | 369.7 | 337.5 |

From September 7-11 to 14-18, published weekday MAE improved **595.0 to 526.2MW** over 120 hours, and advance MAE **770.9 to 579.5MW** over 115 targets. TEPCO advance MAE also improved **368.8 to 266.3MW**. Weather differs across weeks; these changes cannot be attributed to a patch alone. Current-week published MAEs remain 722.1MW at 11-14 and 738.1MW at 15-18.

## Stage Attribution

| Target / calculation time | Actual | Raw | Post-calibration | Observation |
|---|---:|---:|---:|---|
| 09-19 08 / 07:48 | 24910.0 | 26424.1 | 26085.8 | Residual correction helps but does not remove raw overprediction |
| 09-19 12 / 11:35 | 28580.0 | 28908.5 | 28128.4 | A -780.1MW residual turns a small positive raw error negative |
| 09-19 18 / 17:32 | 29780.0 | 28839.7 | 28741.2 | A -98.5MW residual further lowers an already low raw forecast |
| 09-20 09 / 08:31 | 26630.0 | 25582.0 | 25789.3 | Raw underprediction is partially recovered |
| 09-20 12 / 11:37 | 27770.0 | 27704.2 | 28403.6 | Residual plus sustained-underforecast lift adds 699.4MW |
| 09-20 18 / 17:34 | 29240.0 | 28393.2 | 28548.7 | Low raw level and weekend positive-residual damping limit recovery |

Saturday 06-09 advance snapshots have identical raw and pre-calibration levels: the prior week's morning shape-floor failure is not demonstrated here. Lag or weather attribution still requires replay of saved inputs.

At Sunday hour 18, the +375.7MW base residual decays to +345.6MW; weekend damping at 0.45 suppresses **190.1MW**, leaving +155.5MW. The latest observed slope at hour 16 is +710MW. This guard uses the maximum lag/same-type delta, 502.5MW against a 600MW threshold, rather than that observed rise. However, it reduced overprediction at September 12 hour 19. Blanket removal is not validated.

Aggregate advance raw/post MAEs are **526.4/440.1MW** on September 19 and **451.4/369.7MW** on September 20, but **422.0/514.6MW** on September 16. Correction is beneficial overall on the weekend, not universally beneficial.

## Lunch Shape and Publication

| Date | Actual 11-to-12 delta | Same-run raw delta | Hour-12 midday guard delta | Published delta |
|---|---:|---:|---:|---:|
| 09-14 | -130.0 | +696.9 | 0.0 | +53.4 |
| 09-15 | -700.0 | -255.6 | 0.0 | -1270.0 |
| 09-16 | -1240.0 | -771.1 | 0.0 | -582.9 |
| 09-17 | -690.0 | -70.0 | -633.3 | -365.0 |
| 09-18 | -1440.0 | -1239.4 | 0.0 | -307.6 |
| 09-19 | +260.0 | +240.0 | 0.0 | +152.7 |
| 09-20 | +720.0 | +853.3 | 0.0 | +360.6 |

Raw/guard columns use each day's 11-hour run; published points may originate from different runs. There is no observed weekday-midday-guard activation on the weekend.

On September 18, the raw model already had a lunch dip. Hour 12 post-calibration was 32002.4MW at 11:38, but a 12:25 recalculation raised raw to 33115.4MW and publication to 32920.7MW. Published errors of -761.7MW at 11 and +370.7MW at 12 flatten the displayed dip. An inactive midday guard alone does not explain it.

For September 20 hour 13, the 12:26 advance value was 27975.9MW versus actual 27820MW. At 13:32, raw fell to 26866.7MW and residual +165.1MW yielded publication 27031.8MW. **Recalculation after target start but before actual arrival** must be distinguished from the later preservation of that result. Repainting history is not a forecasting improvement.

## Intervals

- Published P95 mean full widths are 4406.0MW on September 19 and 4430.1MW on September 20, covering 24/24 and 21/21. Coverage alone does not establish calibrated uncertainty.
- Retained 0-2h interval snapshots applied `lead_target` to 5/20 targets on September 19 and 12/19 on September 20. Mean widths are 4427.7MW and 3717.8MW. Snapshot retention differs from the comparison ledger.
- All 141 selected September 14-20 interval rows have correct P99/P95/q50 ordering and contain actuals. Short duration and wide intervals do not establish long-run nominal 95% calibration.
- September 20 hour 18 has only 16 compatible 0-2h late-afternoon samples over six days, below the minimum 24; native bands are retained. Hour 19 has 30 evening samples over six days and is calibrated. Total `selectedSamples=446` does not imply coverage of every subgroup.

## Next Experiments

1. Replay weather/input revisions and the residual reference together, including September 19 lunch, September 20 noon, and September 16 underprediction. Do not substitute future observed weather into historical forecast inputs.
2. Test observed-support conditions for weekend evening damping against both rising-demand cases and cases where existing damping prevented overshoot. Run the full correction chain; simply adding suppressed MW back is not a candidate result.
3. Evaluate raw level errors jointly across Saturday overprediction, Sunday underprediction, and September 14-16 direction reversals. Do not add time-specific constants or TEPCO forecast inputs.
4. Assess lead/timeband interval width, coverage, and interval score separately from q50. Do not mix serving policies or relax sample gates solely to activate calibration.

September 18-19 AI reports are present in all three languages and use `gpt-4o-mini` for analysis/localization. Generation status, not prose quality, was checked. No ETL rerun, paid API call, training, promotion, or production-data edit was performed.
