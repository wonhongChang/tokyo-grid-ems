# 2026-09-10 Observed-Support Bound for Negative Residual Restoration

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-10-observed-support-floor.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-10-observed-support-floor.md)

## Diagnosis

The September 10 Pages snapshot at 19:29 JST contains genuine actuals for 00-18: MAE 957.4MW, WAPE 3.27%, bias +591.0MW. These are partial-day published-line metrics, not a completed-day score. Source data revision: `165cc843d40f1c6f0cc02c568153d8239df284f4`.

The near-term negative-residual floor could restore up to 700MW using a historical demand level even when the corrected forecast was already above current actual demand. At 15:43, last actual was 33,400MW but the historical floor for hour 15 was 38,506.2MW. The chain was:

```text
pre-calibration 35,672.1 - residual 1,200 + restoration 700
  - afternoon cap 1,500 = 33,672.1 MW
```

Restoration and the later cap were opposing one another. This is a control conflict, not evidence that forecast preservation caused the original error. Saved per-run calculations and published forecasts are evaluated separately. TEPCO forecasts remain comparison data only.

## Change

`IntradayResidualCorrector._negative_residual_near_term_floor_restore()` now bounds historical support by observed demand, with a limited allowance for a corroborated rising pattern:

```text
observed_base = last_actual - existing_drop_allowance
actual_floor = observed_base - actual_reference_slack

ramp_allowance = 0 by default
if both consecutive actual slopes > 0
   and target lag24 delta > 0 and target same-business delta > 0:
    ramp_allowance = min(latest_actual_slope, mean_two_actual_slopes,
                         target_lag24_delta, target_same_business_delta) * lead

historical_floor = min(recent_mean - anchor_slack,
                       observed_base + ramp_allowance)
floor = max(actual_floor, historical_floor)
```

Missing history retains the actual-derived floor. Missing/nonpositive shape support or a missing preceding observation disables the rising allowance, not the actual floor. Tiny positive historical deltas cannot authorize a large ramp allowance.

The existing negative-only trigger, 1-2 observation-relative lead hours, 700MW restoration cap, minimum restoration and decline damping remain. Restoration cannot exceed the removed negative adjustment, so this layer cannot lift above its pre-calibration input. Existing target hours are not expanded. `negativeResidualNearTermRampAllowanceMw` records the allowance when restoration occurs; otherwise it is null.

## Retained-Evidence Check

104 saved runs across September 5-10 were inspected; copied checkout files were verified against the pinned data-tree blob hashes, allowing only CRLF normalization. Of 22 active floor rows, four floors were unchanged; the other 18 original restoration amounts were reconstructed, and 14 restoration amounts decreased.

For changed rows, later recorded morning/afternoon cap bounds and their configured reduction rules were reapplied. This is a **fixed-context floor/cap reconstruction**, not retraining or a full counterfactual serving replay. Unrecorded newly activated stages and run-to-run feedback are not validated by this calculation. Current-interval updates are excluded from the following positive-issuance-lead comparison; repeated runs use the latest eligible issuance per target.

| Date | Changed positive-lead targets | Old MAE | Candidate MAE | Improved / worse / unchanged |
|---|---:|---:|---:|---:|
| September 5 | 2 | 560.4MW | 332.8MW | 1 / 1 / 0 |
| September 10 | 5 | 881.0MW | 559.6MW | 4 / 0 / 1 |

These are selected affected-target metrics, **not whole-day MAE improvements**. September 6-9 had no restoration changes in the retained runs.

The trade-off is explicit: September 5 hour 13 moves from 30,121.2 to 30,035.0MW versus actual 30,130MW; absolute error increases from 8.8 to 95.0MW. A naive last-actual-only bound would instead fall to 29,613.3MW. The observed/shape allowance avoids most of that regression without preserving the old number by a date-specific exception.

On September 10, the 15:43 issuance for hour 16 changes from 34,088.9 to 33,400MW versus actual 33,250MW. The 17:36 issuance for hour 18 changes from 33,948.5 to 33,248.5MW versus actual 32,740MW. Remaining errors are material; this does not solve the raw model's entire high-demand bias.

## Verification and Rollout

All **628 tests passed** with external networking blocked; the focused floor/cap/interval suite passed 126 tests. The configured downstream-cap fixture yields 33,400MW for both hours 15 and 16, rather than blindly subtracting 700MW from their old outputs.

Regression tests cover cold plateaus, genuine observed ramps, weak/missing/disagreeing support, observation gaps, fall allowances, restoration limits, unchanged input/observed rows and consistent p95/p99 shifts. A policy-fingerprint regression rejects old unbounded-floor semantics. External networking is blocked in the test process; no paid API calls, ETL reruns or training are needed.

The trained `v14-r2-source-robust-day-ahead` artifact and model weights remain unchanged. `servingSemanticsVersion` becomes **2** because q50 post-processing changes. Old policy snapshots must not seed the new compatible interval profile. Native normalized/capped bands remain until compatible evidence is sufficient; this patch does not promise narrower bands or 95% empirical coverage.

After deployment, a normal Intraday run uses the new rule for unobserved targets. Do not rewrite published observed predictions or historical scores to demonstrate an improvement. Verify restoration/ramp-allowance logs, band ordering and positive-lead errors under the new fingerprint.

## Unresolved Work

- A later, separate Pages actual check at 22:29 JST supplied hours 19-20 after the design was fixed. Their actuals were 31,570 and 29,990MW. In the retained 19:29 calculation, the candidate still restores 700MW, leaving 32,145.6 and 31,156.3MW: unchanged errors of +575.6 and +1,166.3MW. Hour 19 is a current-interval update; hour 20 is a positive-lead forecast. The corrected input is already below the observed-support floor, so bounding excessive historical levels alone does not solve anticipated evening decline. These rows are not included as improvements in the affected-target table above.
- The afternoon cap has separate target-hour, lead and last-observation boundaries. At the 17:36 run, `lastObservedHour=16` exceeded its configured maximum 15, while the evening decline trigger did not match the flat observed slope. This explains an additional release of downward control. Extending hours or leads would move the boundary, not establish a safe handoff; no such extension is included here.
- Morning raw-model weather/lag sensitivity and the earlier midnight prior remain separate ablation experiments. Do not attribute all of today's error to this floor.
- Further tests must cover supported rebounds, a one-slot lunch dip, cooling weekdays and weekends using inputs available at issuance. Keep long-run and whole-day regression checks alongside affected-hour diagnostics.

Code: [intraday correction](../../../python/forecast/intraday_correction.py), [policy fingerprint](../../../python/forecast/rolling_interval_calibration.py), [regression tests](../../../tests/test_intraday_correction.py).
