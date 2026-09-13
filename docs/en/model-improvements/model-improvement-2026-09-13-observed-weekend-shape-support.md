# 2026-09-13 Observed Support for Weekend Morning Shape Floors

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-13-observed-weekend-shape-support.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-13-observed-weekend-shape-support.md)

## Problem and Scope

The [September 13 review](../model-reviews/model-review-2026-09-13.md) traced Saturday's 06-07 overprediction to `non_business_morning_shape_floor_guard`, not just the raw model. The guard selects the larger of yesterday's slope and recent matching-business-type slope. Friday's workday ramp can therefore support Saturday's floor.

For target 06 in the September 12 05:29 run, raw demand was 23,074.8MW against finalized actual 22,930MW. Selecting yesterday's +1,550MW slope added 765.4MW, while recent matching-type slope was only +287.5MW.

Unconditionally removing yesterday's slope regressed other Saturdays and was rejected. The implemented change excludes cross-business-type slope **only when pre-guard observations support the lower forecast level**. The trained model, 63 training features and TEPCO forecast input policy are unchanged.

## Application Contract

Configuration: `adjustment.post_holiday_timeband_guard.non_business_morning_shape_floor_guard.prefer_matching_support_when_observed: true`. Missing or false disables only this change.

1. Retain the existing non-business-day gate and target hours `[6, 7]`.
2. Read existing inference context only before the first guarded target. The latest two distinct observed hours must be consecutive. Observations inside or after guarded targets cannot authorize this support choice.
3. Each observation must satisfy `actual - same-hour forecast before this guard <= support_slack_mw`, using the existing 250MW slack. If either supports a materially higher demand level, retain the original slope selection.
4. Exclude lag24 slope only when `lag_24h_business_type_mismatch == 1` and matching-type slope is finite. Missing matching-type evidence preserves existing behavior.
5. Apply the original floor formula to the remaining support. An unsupported real dip can still be softened. No fixed demand floor or TEPCO forecast following is introduced.

The existing 700MW shortfall threshold, 250MW slack, 0.75 shrinkage, 800MW maximum lift and 100MW minimum lift remain. Equal shifts preserve the guard's p95/p99 widths. The feature builder excludes `tepco_forecast_fallback` from observation context; same-day actual context is not added to training features.

New observations can also affect recalculated past pre-calibration values. Intraday recomputes residuals against the current run's pre-calibration curve, so downstream feedback was replayed together. Published past-forecast preservation is unchanged.

## Replay Results

Historical Git caches, then-known observations and captured raw/upper-level/analog outputs were used. Of 51 runs replayed from timeband through intraday, 48 reproduced baseline pre/post and were evaluated; three mismatched runs with changed controller semantics were excluded. Select one nearest pre-start issuance per target within 0-2h.

| Date | Targets | Baseline MAE MW | Unconditional exclusion | Adopted conditional rule |
|---|---:|---:|---:|---:|
| Aug 22 Sat | 12 | 968.9 | 884.7 | 968.9 |
| Aug 29 Sat | 10 | 1,020.9 | 1,133.3 | 1,020.9 |
| Sep 5 Sat | 12 | 463.4 | 482.2 | 463.4 |
| Sep 12 Sat | 12 | 545.1 | 404.3 | 404.3 |
| Sep 13 Sun, provisional | 3 | 296.9 | 296.9 | 296.9 |

For the same September 12 targets, WAPE changed from 2.06% to 1.53% and max absolute error from 1,066.0 to 829.1MW. Target 06 changed from 23,843.0 to 23,077.6MW and 07 from 24,963.0 to 24,483.6MW. Reducing earlier artificial floors also reduced negative residual propagation into 09-11. Target 08 instead rose from 26,021.2 to 26,154.1MW against actual 25,710MW: not every hour improved.

September 12 2-4h lead MAE improved from 671.3 to 519.8MW; 4-8h from 685.8 to 649.4MW. Other reviewed dates were unchanged in these lead bands. All saved August 14-September 10 D0/D-1 origins, 672 values each, were unchanged.

This is a **fixed-raw q50 post-processing replay**, not a 28-day promotion test for a new trained artifact. Synthetic band bounds were used for residual feedback, so full interval calibration quality is not established. The conditional rule's active benefit was observed on one Saturday, not demonstrated across seasons.

## Verification and Operations

- Test genuine early underprediction, missing/one/nonconsecutive observations, missing/nonfinite values, same business type and switch off.
- Test retained matching-type dip protection, unchanged band widths, input immutability, exclusion of later observations and fallback exclusion from context.
- The new configuration changes serving fingerprint. After deployment, compatible interval history must accumulate again; do not mix older-policy errors to force narrower bands. Native bands may remain until four days and 24 samples per lead bucket are available.
- Roll back by setting the switch false or removing it. Other guards and the trained model remain intact. Restoring the previous fingerprint requires removing the new key and keeping all other settings identical.
- Next weekend, inspect 06-07 overprediction and residual-feedback side effects at 08-11. Raw 09-14 underprediction and D-1 regime bias remain separate work.

## AI Report Evidence Repair

All 678 Python tests passed with external networking blocked. Policy fingerprint changes from `853044a84f4e160432f5784503df71de0621978c4ecac19183f169be052fc28b` to `d788cbbcd3d956a5344bf0ce2fb7d960da425390c148516acfbd40b8f9b94ee4`; the trained artifact hash does not change.

`published_recalculated_gap` alone no longer creates model-tuning tickets. This prevents a nearly accurate 17:00 served forecast from becoming an evening-guard defect recommendation merely because retrospective recalculation differs. Genuine demand-error events remain eligible; tickets link to surviving hypothesis IDs. The path is shared by en/ko/ja. OpenAI models, call counts and cost settings are unchanged.
