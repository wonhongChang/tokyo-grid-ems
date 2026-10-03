# Learned Intraday Challenger

[한국어](../ko/learned-intraday-challenger.md) | [日本語](../ja/learned-intraday-challenger.md)

## Status and Architecture

Separate L4/L5 follow-up research: [Lead-Aware Intraday Shadow](lead-aware-intraday-shadow.md). Original results below remain frozen.

The October 3, 2026 experiment concludes **RETAIN CHALLENGER: L2**. This is not production promotion. The champion, ETL, scheduler, published outputs and existing promotion policy are unchanged. No Jev or model API calls are involved.

`python/eval/intraday_challenger/` turns immutable issue-time calibration snapshots into observed-path/residual features, trains chronological error models and stores isolated shadow predictions. Finalized actuals later produce daily, time-band, lead and cumulative comparisons.

| Candidate | Forecast | Learning target |
|---|---|---|
| L1 | raw + learned error | actual - raw |
| L2 | recorded post + learned remaining error | actual - post |
| L3 | pre + latest raw residual + learned residual change | actual - pre - latest raw residual |

L3 bypasses intraday heuristics only in research. All use LightGBM L1 loss, 240 trees, learning rate 0.035, 12 leaves, minimum child size 45, L2 regularization 10, fixed seed and two CPU threads. Reciprocal capture-count weights balance each date/hour. Selection uses validation, then models refit on train+validation before one holdout evaluation. No holdout-driven retuning.

## Evidence Contract

Freeze: `2026-10-03T18:00:50.748933+09:00`; code `fe1eaa84a6cc70d061a4c4d8d56782e373d055c4`; data `ea57d03155b4c5b3f86c97b1b8fb5cbcc3afd275` plus hash-verified retained snapshots.

517 runs yield 5,622 prospective issue-target rows: 5,235 finalized labels, 294 provisional labels and 93 unobserved rows. The latter comprise 55 future, 11 incomplete intervals and 27 missing past observations. Repeated captures are not independent samples.

| Split | Dates | Finalized rows | Closest (0,120] minutes |
|---|---|---:|---:|
| Train | Aug 28–Sep 13 | 1,863 | 261 |
| Validation | Sep 14–21 | 1,103 | 140 |
| Holdout | Sep 22–Oct 1 | 2,269 | 229 |

46 numeric features describe forecast paths, lead/calendar, completed actual observations, residual trends and recorded lag/anchor deltas. Hour h is usable only after interval [h,h+1) ends and within the recorded observation cutoff. Forecast fallback is not observed demand. Final actuals enter labels only; TEPCO forecasts and unproven reconstructed weather are excluded. Missingness stays missing.

Rows retain source hash/pointer, issue/target/lead, cutoff and label hash. Historical champion artifact/policy identity remains null. This compares **recorded same-run post**, not published forecasts or a retroactive current-policy replay. Historical label delivery timestamps are unproven: this is a chronological retrospective experiment, not evidence of deployment at those dates. Some holdout dates were previously studied; fresh shadow evidence remains necessary. Native challenger intervals, 00:00 targets and next-day forecasting are not validated.

The first, pre-outcome preregistration hash is `3ede9079a0305e916add1883d580d08f693a8151601452f0159018185ebbc568`. Subsequent integrity/shadow-boundary fixes did not change candidates, periods, selection or acceptance criteria.

## Results

Finalized matched populations; errors in MW:

| Model | All-positive MAE | RMSE | WAPE | Closest MAE | Closest RMSE |
|---|---:|---:|---:|---:|---:|
| Recorded champion | 1,006.0 | 1,321.1 | 3.354% | 576.7 | 771.9 |
| L1 | 952.2 | 1,308.4 | 3.174% | 649.1 | 838.7 |
| L2 | 915.4 | 1,272.9 | 3.052% | 604.9 | 782.0 |
| L3 | 938.6 | 1,300.0 | 3.129% | 619.4 | 807.5 |

L2 improves all-positive MAE by 9.01% but worsens closest MAE by 4.88%. All-positive improved/worsened rows are 1,332/937 with 6/4 daily wins/losses; closest counts are 105/124 with 3/7 daily wins/losses. Worsened-row additional error p50/p90/p95/max is 299.4/715.6/845.3/1,513.8 MW overall and 234.7/583.5/695.1/1,264.3 MW closest.

Overall afternoon/evening/non-business MAE improves, but closest afternoon/evening worsens. The largest closest regression is Sep 24 at 13:00, issued 12:26. The Sep 22 20:00 guard-success counterexample worsens by 689.1 MW. Sixteen source-exact F/G/H checks are preserved separately; training-period cases are not independent confirmation.

Within-run adjacent target delta MAE improves 415.2 → 362.4, while mean same-target revisions between neighboring issues increase 167.7 → 284.4. These are distinct stability measures. October 3 provisional closest observations (14 pairs) show raw/champion/L2 MAE 629.2/702.6/781.5; no improvement claim is made for today.

Preregistered research-only acceptance requires at least 5% MAE/WAPE gain, at most 2% RMSE growth, date wins >= losses, and baseline-scaled band/tail allowances. L2 was selected before holdout by validation score and tail safety. It fails the holdout closest mean-improvement and date-win conditions. Criteria were not relaxed afterward; retain is not pass.

## Commands and Isolation

```text
python -m python.eval.intraday_challenger --help
```

All CLI outputs require a named `data/intraday_challenger/<workspace>` root, ignored by Git.

| Command | Inputs in addition to --output-root |
|---|---|
| prepare | --input-root, --input-sha, --periods |
| train-replay | --registration-sha |
| shadow-capture | --snapshot, --snapshot-sha, --model-root, --identity-sha |
| shadow-evaluate | --actual-root, --state-file |
| shadow-watch | --snapshots-root, --model-root, --identity-sha, --actual-root, --state-file |

`--periods` is JSON containing train/validation/holdout [start,end] pairs. Input manifest `intraday-input/1.0.0` contains asOf, runs and actuals. Sources have relative JSON paths and SHA-256; runs carry date/issuedAt and actuals date/state. Hash, vintage, duplicate-row and split failures stop execution.

Shadow records both source issue time and actual recordedAt. Targets already started at capture are retrospective and excluded from live confirmation. Predictions are immutable/idempotent; label revisions create separate hash-addressed evaluations. Different model identities never share a metric population. Native intervals remain unavailable, not copied from the champion.

The optional standalone worker sleeps inside Python for 300 seconds by default. Source synchronization remains external. It is not registered with ETL or a scheduler; starting it is a separate operational decision.

## Reproducibility and Next Decision

Forty-two new tests plus related intraday/replay/batch tests pass: 244 total. Source identity normalizes Windows Git LF/CRLF conversion only; data/model artifact hashes verify original bytes. Six native trained model files and numeric reports reproduce exactly. The finalized preregistration hash is `7fa4c6b5b6d0538c40e7c688f677ce5dfb7727669d2623da58ea764d14b34bf6`; selected model hash is `0bcd25b4133fa57fe446da5eb6beea537f65947aaa940d2c027718ac9b9a88f5`.

Reassess after at least 14 finalized dates, including 8 business and 4 non-business dates, 300 prospective pairs and 150 closest targets; October 18 ETL is the earliest planned checkpoint if collection is complete. These are sample-readiness requirements, not automatic promotion. Require the existing mean/tail/band/regime tests, revision stability, native interval validation and champion policy/artifact attestation. Production adoption needs an explicit serving-policy version change and normal promotion procedure.

Datasets, replay files, models and dated shadow records remain local ignored artifacts. Only code, tests and public design/results documentation are versioned.
