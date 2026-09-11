# 2026-09-11 Review and Sustained-Decline Restoration

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-11-review-and-sustained-decline.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-11-review-and-sustained-decline.md)

## Evidence and Scope

Pages was updated at **15:43 JST on September 11**, with finalized CSV coverage through September 10 and September 11 actuals for hours 00-14. Evidence was pinned to data revision `3f4df36c077529a8e5f6a6377e1d4ede388d719f`. Hour 14 means the 14:00-15:00 demand bucket. September 10 figures below use the newly finalized CSV, which revises some intraday actuals used in the previous review.

| Published line | Hours | MAE | WAPE | Bias |
|---|---:|---:|---:|---:|
| September 7 | 24 | 543.8MW | 1.80% | +271.4MW |
| September 8 | 24 | 479.9MW | 1.46% | -45.4MW |
| September 9 | 24 | 746.8MW | 2.16% | -108.1MW |
| September 10 | 24 | 819.9MW | 2.81% | +520.7MW |
| September 11, partial | 15 | 404.7MW | 1.46% | +104.8MW |

Published lines can include updates after a target bucket starts. For the latest retained, **strictly positive 0-120 minute lead** paired captures, September 10 model/TEPCO MAE is **820.8/314.8MW** over 23 hours; September 11 is **576.6/461.4MW** over 14 hours. TEPCO is a comparison only, never a calibration target. A partial-day score is not a completed-day result.

September 11 overnight MAE is 85.8MW. Hours 06-08 underpredict by 599.4, 651.3 and 842.0MW, while hour 11 overpredicts by 1,104.5MW. Hours 12-14 overpredict by 649.1, 776.2 and 161.1MW. A blanket downward adjustment would damage the morning. The lunch dip is present today; the observed 11-to-12 fall is 1,000MW and the published fall is 1,455.4MW. This is not evidence that every lunch correction is satisfactory.

### Evening Follow-Up

At 23:41 JST, Pages exposed the **21:39 update with 21 observations, hours 00-20**. This capture was retained separately from the afternoon evidence. Published-line MAE was **389.8MW**, WAPE **1.35%**, and bias **+52.9MW**. Hours 21-23 had no observations and were not scored. The paired, same-capture comparison at strictly positive issuance leads up to 120 minutes gave model **538.3MW** versus TEPCO **402.5MW** MAE across 20 hours.

| Additional window | Published MAE | Bias | Interpretation |
|---|---:|---:|---|
| 15-18 | 428.6MW | -215.8MW | Hour 18 underpredicted by 675.1MW; do not lower the entire evening |
| 19-20 | 200.6MW | +200.6MW | Overprediction, but smaller errors than the morning/daytime windows |

The published p95 band covered 21/21 observations with mean width 4,719.0MW. Full coverage from a wide band does not establish a good central forecast or correct probability calibration. These are results of the existing deployed code, not effects of the local changes below.

## Raw-Model Experiments

A single candidate was retrained under the existing v14-r2 configuration, using data strictly before **August 28**. It was screened against the exact deployed artifact on **August 28-September 10**, separately at D0 and D-1 origins. Historical Git caches, not today's weather values, supply the inputs. Target-day actuals are masked. Current deterministic feature/weather transformations are applied equally to both artifacts.

| Raw q50, 336 targets per horizon | D0 MAE | D-1 MAE |
|---|---:|---:|
| Deployed v14-r2 | 1,446.2MW | 2,658.1MW |
| Same-contract retraining | 1,513.7MW | 2,783.6MW |
| Deployed model with lag24 blend weight set to zero, ablation only | 1,550.4MW | 2,658.1MW |

These are **initial-origin raw-model screens**, not published-line scores, a full serving replay, or a promotion gate. Intraday correction and the D-1 day-level correction are not included. The no-lag ablation changes inference configuration only; it does not retrain trees. Its unchanged D-1 result is consistent with the lag-unavailable specialist path.

Retraining worsens both horizons by approximately 4.7%; it is not promoted or renamed v15. Removing the lag24 mixture also worsens D0, so this evidence does not support treating lag24 as the sole cause. The D-1 non-business raw MAE of 3,829.3MW is a priority for the next model-design experiment, not an acceptable operating target. Today's better published score does not validate the underlying day-ahead model.

Artifact SHA-256:

- Deployed: `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`
- Rejected retraining screen: `38693cc3069ab48ad307c99e32915899eed395d77809675dd37d928f10f93a61`

### D-1 Weekend Specialist Ablation

The missing-lag path mixes a general model and a non-business specialist. The deployed specialist weight 1.0 was compared with fixed weights 0.5 and 0.0 on **August 14-September 10: 672 target hours per D0/D-1 horizon**, separating the recent and preceding fortnights.

| D-1 non-business raw MAE | Deployed 1.0 | Candidate 0.5 | Candidate 0.0 |
|---|---:|---:|---:|
| August 14-27 | 1,982.1 | 1,964.0 | 2,120.3MW |
| August 28-September 10 | 3,829.3 | 3,347.4 | 2,868.0MW |
| All 28 days | 2,905.7 | 2,655.7 | 2,494.2MW |

The specialist amplified recent weekend overprediction, but removing it was not consistently better. On **August 23**, MAE rose from 596.2MW to 827.8MW at weight 0.5 and 1,449.7MW at weight 0.0. Neither fixed change was adopted. This demonstrates a risk of uniformly lowering forecasts to fit recent conditions, not that this weight explains every error.

After the existing timeband/midday/local shape guards, all-day D-1 MAE over 28 days was 3,096.3 / 3,024.5 / 2,978.4MW. **Learned same-regime day-level calibration, intraday feedback, issued-history interval calibration, and freeze were excluded**: this is not full operational replay. All three D0 outputs were identical, but none of the 672 D0 rows selected the missing-lag path. This does not establish safety during D0 collection failures.

Missing historical weather-correction evidence was not filled with a new API response. These runs combine preserved caches with current transforms, and the preceding fortnight may have informed earlier development; it is not claimed as an untouched promotion holdout. The next model experiment should address **why missing-lag model bias changes with issuance-time lag availability and weather/demand level**, rather than repeat plain retraining, lag removal, or a uniform reduction of the weekend-specialist weight.

## Adopted Control Change

The [September 10 observed-support bound](model-improvement-2026-09-10-observed-support-floor.md) does not fully address a gradual decline. At the retained 19:29 run, actuals fell **33,250 → 32,900 → 32,740MW**. The latest fall, -160MW, did not meet the existing -500MW single-interval damping threshold, even though two intervals together fell 510MW. Floor restoration still added 700MW at both target hours 19 and 20.

Keep the existing single-interval rule. Add an alternative evidence path inside the same negative-restoration layer:

1. Two consecutive, genuine actual slopes must both be negative, with their sum at or below the existing decline threshold (-500MW).
2. Every unobserved interval through the target must have **both** lag24 and recent-same-business deltas at or below the existing support threshold (-500MW). Missing, nonfinite, weak, or rebound support blocks this alternative.
3. Apply the existing restoration factor **0.25**. Do not increase downward residual strength or modify raw q50. The negative-only gate, 1-2 observation-relative lead hours, existing target hours, restoration cap and observed-row preservation remain unchanged.

`negativeResidualNearTermDeclineEvidenceBasis` identifies `latest_interval`, `two_interval_decline_with_supported_path`, or null when no restoration evidence is applied. This rule is not restricted to a new evening clock window and does not turn a one-slot lunch dip into a continuing decline.

## Bounded Verification

246 retained calibration runs across August 29-September 11 were inspected and verified against pinned Git blob hashes, allowing only checkout CRLF normalization. Two rows satisfy the additional rule: September 10 hours 19 and 20. The calculation holds other stages fixed and reapplies recorded cap bounds; it is **not a full feedback-trajectory replay**.

| Target | Previous-rule result | Candidate result | Final actual | Absolute error, before → after |
|---|---:|---:|---:|---:|
| 19, already-started interval at issuance | 32,145.6 | 31,620.6 | 31,540 | 605.6 → 80.6MW |
| 20, positive issuance lead | 31,156.3 | 30,631.3 | 29,990 | 1,166.3 → 641.3MW |

Restoration changes from 700 to 175MW. The hour-19 result is not counted as a pre-start forecast improvement. The effect is narrow and does not establish broad model accuracy. A full configured-controller test reproduces both candidate values, checks all terminal deltas, preserves observed rows and input objects, and verifies unchanged interval offsets. Negative tests cover gaps, one-slot dips, intermediate rebounds, weak/missing/nonfinite support, positive adjustments and out-of-range leads.

## Replay and Operations Fixes

The full test suite passed **650 tests** with external networking blocked. A regression case also verifies that today's cumulative -420MW decline over hours 16-18 does not activate the new sustained-decline condition.

`fixed_origin_model_replay._origin_commit()` now uses `git log --no-renames`. Snapshot retention can make Git classify a new timestamped file as a rename; `--diff-filter=A` without this flag missed real D0 input commits, including September 10. A temporary-repository regression reproduces snapshot rotation and verifies the correct origin is found. Earlier replay evidence should be rerun when it relied on a missing or late origin; the fix itself does not prove any model is better.

ETL now distinguishes **scheduled candidate training disabled** from **not the scheduled weekday**. Automatic candidate training remains disabled; model promotion and the deployed weights are unchanged.

`servingSemanticsVersion` becomes **3**. Previous-policy observations must not seed an allegedly compatible new interval profile. Existing normalized/capped native intervals remain while new-policy evidence accumulates. September 11 published p95 coverage is 15/15 with mean width 4,578.3MW; September 10 is 23/24 with mean width 5,070.0MW. Neither small sample establishes 95% calibration. This change does not artificially narrow bands.

## Remaining Work

- Evaluate D0 cooling-day level sensitivity and the D-1 lag-unavailable specialist separately. A fresher artifact alone is not enough; no new trained model was promoted here.
- The afternoon cap still has separate target/lead/reference boundaries. Extending its hours would move the discontinuity, not prove a safe handoff. No extension is included.
- A promotion experiment must include the serving feedback trajectory, D0/D-1, weekdays/weekends, band coverage and independent holdout days. This 14-day rejection screen cannot replace it.
- After an explicitly approved deployment, use a normal Intraday update for unobserved targets. Do not rewrite observed forecasts or historical scores. No paid OpenAI calls, ETL reruns or published-data replacements were required for this review.

Code: [controller](../../../python/forecast/intraday_correction.py), [replay](../../../python/eval/fixed_origin_model_replay.py), [regression tests](../../../tests/test_intraday_sustained_decline_floor.py).
