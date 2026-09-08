# 2026-09-09 Serving Calibration Contracts

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-09-09-serving-calibration-contracts.md) · [日本語](../../ja/model-improvements/model-improvement-2026-09-09-serving-calibration-contracts.md)

## Scope

This implements three operational corrections identified in the [September 8 review](../model-reviews/model-review-2026-09-08.md): lead-matched interval evidence, same-regime origin/freshness validation, and terminal guard attribution. It does not use TEPCO forecasts as calibration inputs or blame preservation for pre-target point-forecast errors.

The trained `v14-r2-source-robust-day-ahead` artifact is unchanged. Interval calculations and logging do not change q50, but restricting the D-1 prior to D-1 issuance **can change the served center line**. This is not a new model promotion or proof of whole-pipeline MAE improvement.

## 1. Lead-Matched Intervals

`build_lead_conformal_profile()` reads actual pre-target issuances from `forecast_snapshots/` and `forecast_origins/`, not overwritten final `forecast/` values.

- Require the current artifact SHA and `servingPolicyFingerprint`. Reject missing/naive timestamps and interpret aware timestamps in JST.
- Use positive leads only: `(0,2]`, `(2,4]`, `(4,8]`, `(8,24]`, `(24,48]` hours before the target bucket starts.
- Require ETL `okDates` and all 24 genuine actuals. TEPCO forecast fallback is not an actual.
- Use the last 28 calendar days, through issue-date D-2. Without historical CSV-finalization timestamps, excluding D-1 avoids assuming morning final data existed at midnight during replay.
- Keep the latest pre-target issuance per date/target hour/lead bucket. Repeated runs cannot inflate sample weight.

Existing target time bands remain: `overnight` 00-05, `morning` 06-10, `daytime` 11-15, `late_afternoon` 16-18, `evening` 19-23. These group interval errors; they do not force demand up or down.

For each lead/time band, build same-regime and all-regime groups separately. Each eligible group needs **24 samples across at least four dates**. Use the larger eligible finite-sample error q95 times 1.05. All-regime evidence can back off an undersampled same-regime group, but other leads cannot.

### Rollout and Missing Evidence

Insufficient evidence or an unsupported lead retains normalized/capped native intervals (`native_fallback`). A required half-width over 3,750MW records `native_fallback_cap_exceeded` and `requiredHalfWidthMw`; clipping must not be advertised as reaching the coverage target.

Old unversioned snapshots are not retroactively assigned a policy fingerprint. The audited data had zero compatible samples for the new contract, so targets initially remain inactive and bands may widen. `availability: ok` means some hours have targets; `detailsByHour` is authoritative. Neither native fallback nor the p95 name guarantees measured 95% coverage.

Default preservation also retains published p95/p99 values for observed hours. New widths must not rewrite historical scores. The fingerprint includes q50-related settings and `servingSemanticsVersion`, not interval width settings. A q50 code-semantics change without a configuration change must increment that version.

## 2. Same-Regime Scope and Evidence

`SameRegimeDayLevelCalibrator` uses `application: day_ahead_only` and `require_day_ahead_origin: true`.

- Apply only when issued on the preceding JST date. D0 returns `origin_horizon_mismatch` for this layer while retaining normal intraday correction.
- Require finalized actual residuals linked to the same artifact's `immutable_day_ahead_origin`. D0 holdout seeds and legacy retained snapshots are excluded under this policy.
- Exclude issue-day and later finalized actuals. Global residual freshness must be within two days of issuance.
- Separately derive the three recent expected same-regime dates using the Japanese business/holiday calendar. The selected cohort must match these dates: a fresh other-regime entry cannot validate stale business-day evidence. Normal gaps between weekends remain valid.
- Missing evidence returns zero with `insufficient_same_regime_history`; stale matching dates return `stale_same_regime_history`. Record `expectedHistoryDates` and `rejectedOriginEntries`.

When eligible, retain the median of three daily mean residuals times 0.25, capped at +/-1,000MW. Removing D-1 prior reuse on D0 can change q50, so subsequent evaluation must separate D0 and D-1.

## 3. Terminal Attribution and AI Facts

Operational-calibration hourly rows gain `terminalAdjustments`; metadata gains `terminalAdjustmentsByHour`.

| Field | Meaning |
|---|---|
| `preCalibrationMw` | value entering intraday correction |
| `preTerminalAdjustmentMw` | all changes before terminal shape/ramp guards, not residual alone |
| `shapeGuardDeltaMw` | terminal shape-guard delta |
| `rampGuardDeltaMw` | terminal ramp-guard delta |
| `postCalibrationMw` | result after terminal guards |
| `totalAdjustmentMw` | net change from pre-calibration |

```text
preCalibrationMw + preTerminalAdjustmentMw
  + shapeGuardDeltaMw + rampGuardDeltaMw = postCalibrationMw
```

The existing `residualCarryover.finalAdjustmentMw` keeps its original meaning. In the September 8 13:32 run, target hour 14 had pre 42,870.1MW, residual -112.1MW and post 40,880MW. Reconstructing the terminal stage from recorded inputs identifies the remaining -1,878.0MW as ramp-guard movement, without rewriting the published forecast.

Only four numerical deltas are added to the bounded AI `focusedRows`. No narrative conclusion, extra API call, model change, or full-day input expansion is introduced. Existing AI reports are not automatically regenerated.

## 4. Verification and Limits

- All 609 tests passed in a test process with external networking blocked; no paid API calls.
- Cases cover lead separation, duplicate runs, future/naive timestamps, artifact/policy mismatch, unfinalized/fallback actuals, UTC-to-JST indexing and published-band preservation.
- Same-regime cases cover D0 seeds, stale matching cohorts, normal weekend gaps and D-1/D0 isolation. Terminal sums and AI packet transmission are tested.
- At pinned data revision `0e9a67dcb`, **61 reconstructable runs / 1,464 rows matched recorded terminal results within 0.2MW rounding tolerance**. Eight runs were excluded because older logs could not isolate an earlier prior. Seven rows had nonzero terminal movement.

This is a terminal-stage reconstruction, **not a whole-pipeline counterfactual MAE backtest**. No new-policy interval coverage claim can be made from the audited sample with zero compatible history. Raw weather sensitivity and unnecessary extra correction by morning anchor/residual guards remain separate experiments.

## 5. Rollout and Follow-Up

After code deployment, subsequent Intraday/ETL runs collect new policy/lead/terminal evidence. Retraining and historical-forecast refresh are unnecessary. This verification did not overwrite live or local public JSON.

1. Inspect `intervalCalibration.servedTarget.detailsByHour` for lead, native/target status, sample counts and date counts.
2. Check the D-1 prior is bypassed on D0 and its D-1 history matches `expectedHistoryDates`.
3. Verify terminal delta sums, published center/band preservation and unchanged model artifact.
4. Once compatible evidence accumulates, evaluate coverage, width and MAE by identical issuance lead. Never relabel an old policy's history as the new one.
5. Replay raw weather sensitivity and individual guard on/off cases separately, covering lunch dip, holidays and evening decline. TEPCO forecasts remain a benchmark only.

Rollback must not reintroduce all-lead narrowing from final-served errors or mixed D0 seeds. Observe explicit native status first and manage center-line guard changes as separate evidence-backed work.

Code: [`rolling_interval_calibration.py`](../../../python/forecast/rolling_interval_calibration.py), [`same_regime_calibration.py`](../../../python/forecast/same_regime_calibration.py), [`intraday_correction.py`](../../../python/forecast/intraday_correction.py), [`run_batch.py`](../../../python/etl/run_batch.py), [`ai_daily_report.py`](../../../python/eval/ai_daily_report.py).
