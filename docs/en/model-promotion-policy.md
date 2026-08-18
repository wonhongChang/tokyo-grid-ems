# Model Promotion and Degraded Champion Policy

Languages: [한국어](../ko/model-promotion-policy.md) / [日本語](../ja/model-promotion-policy.md)

Status: core controls implemented; matched-vintage qualification is collecting data

Effective reference date: 2026-08-18 JST

## Purpose

This policy protects a healthy Champion without allowing an aging or degraded model to remain indefinitely because a better Challenger misses one absolute threshold.

The current implementation compares a Challenger with a seasonal baseline and fixed absolute limits. It compares the Champion only through today/tomorrow prediction drift. A Challenger can therefore be materially more accurate than the Champion and still be rejected while the weaker Champion remains active.

## Version Semantics

- A model version changes when the feature, target, ensemble, or inference contract changes, not on every retraining run.
- Retraining the same contract with newer data keeps the same version.
- v12 is retained as historical lineage but removed from the active candidate pool because v13 supersedes it.
- v13 is the current Challenger reference.
- A structural correction to the v13 contract becomes v14.

## Principles

1. Do not casually loosen the absolute-quality limits used for normal promotion.
2. Compare Champion and Challenger under the same training cutoff, holdout, and input contract.
3. Use TEPCO only as an external benchmark and diagnostic signal, never as a training, calibration, or promotion target.
4. Large prediction drift does not itself mean worse accuracy. It should stop automatic promotion and require shadow validation.
5. Separate normal promotion from degraded-Champion recovery.
6. Recovery promotion still requires reproducible replay, shadow evaluation, and rollback protection.

## Evidence Views

| View | Purpose | Input contract |
|---|---|---|
| Temporal model replay | Compare raw model generalization | Same train cutoff and 28/56/84-day holdouts |
| Frozen-origin replay | Reproduce serving-time weather and lag error | Weather and lag snapshots available at forecast time |
| As-served replay | Measure the complete production Champion | Published forecasts and finalized actuals |
| Interval validation | Check uncertainty after q50 changes | Overall and regime/time-band p95 coverage |

A replay based only on final observed weather is useful for model-mapping diagnostics, but it does not fully reproduce production input conditions and cannot be the sole promotion evidence.

## Normal Promotion Path

Separate raw temporal-replay safety limits from production-quality acceptance. Retain the existing values only as fail-closed temporal safety limits, and add a stricter frozen-origin or shadow operational gate for normal promotion.

| Temporal replay safety gate | Current limit |
|---|---:|
| Overall MAE | at most 1,000MW |
| Overall WAPE | at most 3.0% |
| Shape delta MAE | at most 750MW |
| Maximum error | at most 6,500MW |
| Segment MAE | at most 1,500MW |
| Segment shape delta MAE | at most 1,100MW |
| MAE improvement versus seasonal baseline | at least 20% |

| Intermediate operational-quality gate | Proposed limit |
|---|---:|
| Frozen-origin/shadow overall MAE | at most 750MW |
| Frozen-origin/shadow overall WAPE | at most 2.2% |
| MAE ratio versus TEPCO over the same window | at most 2.0 |
| Shape delta MAE | at most 700MW |
| Maximum hourly error | at most 4,500MW |

The TEPCO evidence is:

| Period | TEPCO MAE | Project as-served MAE |
|---|---:|---:|
| Latest 28 days | 420.9MW | 949.8MW |
| Latest 56 days | 363.8MW | 733.5MW |
| Latest 84 days | 352.7MW | 656.7MW |
| 2026-08-01 through 17 | 408.2MW | 1,031.1MW |

The 750MW limit is about 1.78 times the latest 28-day TEPCO MAE and still allows headroom over the project's 56-84-day normal range. It is an intermediate SLO for safely replacing v11, not a certification of TEPCO parity.

### TEPCO Parity and Superiority

Because the project's final objective is TEPCO-level or better accuracy, use a separate benchmark qualification.

| Grade | Requirement |
|---|---|
| Recovery Champion | Improve MAE and WAPE by at least 10% versus the incumbent and pass recovery gates |
| Production Acceptable | Pass the intermediate operational-quality gate |
| TEPCO Parity Qualified | MAE ratio and WAPE ratio at most 1.10 over both 28-day and 84-day windows at matched issuance time and lead time |
| TEPCO Superior | MAE ratio below 1.00 and the upper 95% confidence bound of paired daily error differences below zero |

Define `MAE ratio = model MAE / TEPCO MAE`. With the recent 28-day TEPCO MAE of 420.9MW, a 10% non-inferiority margin corresponds to approximately 463MW. This is a moving benchmark, not a fixed target.

The 10% margin is an initial operating tolerance. Before formal parity certification, translate over- and underforecast errors into reserve and operating-cost impact and pre-register the margin before evaluation. If no defensible cost basis is available, use the stricter ratio of 1.00 as the final objective.

Parity qualification requires all of the following.

- Compare TEPCO and project forecasts at the same issuance time and lead-time bucket.
- Evaluate day-ahead and intraday forecasts separately.
- Require at least 80% paired-hour coverage in every required lead bucket and time band.
- Use a date-level block bootstrap for the 95% confidence interval of paired absolute-error differences to respect hourly dependence.
- Require the upper 95% bootstrap bound of the MAE ratio to be at most 1.10; a favorable point estimate alone is insufficient.
- Keep every critical business, non-business, morning, daytime, late-afternoon, and evening segment within 1.25 times TEPCO MAE.
- Keep RMSE ratio at or below 1.15 and maximum-error ratio at or below 1.25. Peak-timing error remains diagnostic until an immutable TEPCO peak vintage is available.
- Validate the project's p95 interval separately through coverage and pinball loss.

Matched-vintage capture is now append-only at every ETL/Intraday run. TEPCO does not provide a separate immutable `issuedAt`, so `capturedAt` is the observable vintage: only model and TEPCO values seen by the same run are compared, and later TEPCO revisions never replace an earlier capture. Formal parity remains unavailable until both 28-day and 84-day windows have complete lead-bucket coverage.

### Interpreting the 1,000MW Limit

`max_validation_mae_mw: 1000` was introduced with the first guarded promotion workflow on 2026-07-26. At that time, the preceding 28-day as-served MAE was 560.0MW and raw-model MAE in the available stage snapshots was 910.8MW. The 1,000MW value can therefore be understood as a rounded operational-quality ceiling with headroom for that period, but it was not derived from a statistical confidence interval or a long-term seasonal distribution.

Temporal-candidate MAE and as-served MAE must not be treated as directly interchangeable because their weather inputs and post-processing differ. For example, as-served MAE on 2026-08-10 was 1,730.2MW, but that value alone does not pass or fail a candidate temporal gate. It is instead evidence that the current Champion left its normal operating-quality range.

Do not simply raise 1,000MW to admit every candidate. Use it only as a temporal-replay safety ceiling and operational critical threshold, with 750MW as an intermediate promotion target. Final success requires demonstrated non-inferiority or superiority to TEPCO under matched forecast vintages.

Add the following relative checks.

- The Challenger must improve overall MAE by at least 5% versus the Champion contract retrained at the same cutoff.
- Automatic promotion stops if a critical segment MAE or shape metric regresses by more than 5% versus the Champion.
- Mean drift at or below 900MW and hourly maximum drift at or below 2,500MW permits automatic promotion when every other gate passes.
- Drift above either limit produces `shadow_required`, not an unconditional rejection.

## Degraded Champion Detection

Set `champion_degraded_review_required` immediately when any integrity condition is true.

- The artifact has no verifiable `trainingCutoff`.
- The artifact config fingerprint is incompatible with the current inference contract.
- Artifact compatibility or source-commit traceability is incomplete.

Set `champion_degraded` when at least two performance conditions recur in two consecutive weekly reviews.

- 28-day as-served MAE exceeds 900MW or WAPE exceeds 2.7%.
- Recent 14-day MAE is at least 15% worse than the preceding 28-day reference.
- MAE exceeds 1,500MW in morning, daytime, late afternoon, or non-business segments.
- A Challenger improves overall MAE by at least 10% versus the Champion contract under the same temporal replay.
- The model remains ahead in fewer than 35% of hours for a sustained period. TEPCO is only the diagnostic benchmark for this signal, not a promotion target.

Degraded status does not automatically promote a new model. It means the normal path can no longer safely resolve the incumbent problem by itself.

If 28-day as-served MAE exceeds 1,000MW or WAPE exceeds 3.0%, start a critical degraded review immediately rather than waiting for two consecutive weekly reviews.

## Recovery Promotion Path

When the Champion is degraded, a Challenger may become a controlled recovery candidate even if it misses an absolute gate, but only when every condition below passes.

- Improve both overall MAE and WAPE by at least 10% versus the Champion on identical temporal replay.
- Do not regress maximum error or shape delta MAE by more than 5%.
- Do not regress MAE by more than 5% in any critical business, non-business, morning, daytime, late-afternoon, or evening segment.
- Improve at least one known Champion weakness by 10% or more.
- Do not regress overall MAE in the supporting 56-day and 84-day windows.
- Complete frozen-origin replay with full coverage and consistent improvement direction.
- Complete at least 72 shadow forecast-hours and two finalized operating days without a critical regression.
- Pass artifact save/reload, training-cutoff, config-fingerprint, and rollback-artifact checks.

Recovery promotion is not automatic. Record `recovery_candidate_ready`, require explicit operational review, and then transition to `recovery_promoted`.

The implementation reads this evidence from `metrics/model_shadow_evaluation.json`. Its `artifactSha256` must match the preserved shadow artifact, metadata, and prior promotion report. Missing or stale evidence, fewer than 72 hours, or fewer than two finalized days produces `shadow_required`; the approval environment flag cannot bypass those failures. Approval promotes that exact preserved artifact rather than a newly retrained candidate.

## Prediction Drift

Prediction drift is a change-risk measure, not an accuracy metric.

- Drift within limits remains part of normal automatic promotion.
- Drift above a limit with historical error reduction becomes `shadow_required`.
- Frozen-origin replay must determine whether large hourly drift corrects error or creates new shape distortion.
- Drift alone must not preserve a demonstrably worse Champion indefinitely.

## Post-promotion Monitoring and Rollback

- Retain the previous Champion artifact and metadata through the stabilization period.
- Continue generating previous-Champion shadow predictions for three finalized operating days.
- Start rollback review when at least 48 finalized hours show new-Champion MAE more than 10% worse than the previous Champion shadow, or critical-segment MAE more than 10% worse.
- Data-source, artifact-compatibility, or forecast-coverage defects permit immediate rollback regardless of accuracy.
- Preserve rollback decisions and causes in model-promotion history.

## Promotion Report Contract

`metrics/model_promotion.json` must preserve at least:

- Champion version, artifact SHA, training cutoff, and config fingerprint;
- the same fields for the Challenger;
- 28/56/84-day Champion-versus-Challenger metrics;
- as-served Champion health and weak segments;
- absolute-gate and recovery-gate results;
- prediction drift and its disposition;
- `promoted`, `rejected`, `shadow_required`, `champion_degraded`, `recovery_candidate_ready`, `recovery_approval_rejected`, `recovery_promoted`, and `rolled_back` states;
- the latest scheduled decision and next evaluation time.

A non-scheduled ETL result must not overwrite the detailed result of the latest scheduled evaluation.

## Current Project Decision

- v11 remains the deployed Champion, but its missing training cutoff and config-fingerprint mismatch require a degraded-Champion review.
- The same-cutoff replay measured v13 versus v11 at 5.62% MAE improvement over 28 days, 3.17% over 56 days, and 2.75% over 84 days. This is directionally better but below the 10% recovery threshold.
- A 365-day training window and conservative LightGBM complexity search did not produce a promotable candidate. The best result had 1,207.9MW MAE and 3.456% WAPE over 28 days.
- v13 is rejected for promotion rather than force-promoted. It may enter shadow only after it passes the recovery gate.
- If correcting v13 changes the feature or inference contract, evaluate the result as v14.

## Implementation State

- Implemented: same-cutoff Champion replay, absolute and recovery gates, degraded health, 28/56/84-day checks, drift routing, `lastEvaluation`, shadow/rollback artifact preservation, fail-closed 72-hour/two-day shadow evidence, and explicit recovery approval.
- Implemented: append-only matched-vintage capture, 120-second legacy same-run import, lead-bucket metrics, and paired date-block bootstrap.
- Collecting: 28/84-day matched-vintage history. Until complete, `forecast_accuracy.json` remains an operational latest-value reference only.
- Pending before any recovery promotion: at least 72 shadow forecast-hours, two finalized operating days, and operator review of frozen-origin evidence.
