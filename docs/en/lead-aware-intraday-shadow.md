# Lead-Aware Intraday Shadow

[한국어](../ko/lead-aware-intraday-shadow.md) | [日本語](../ja/lead-aware-intraday-shadow.md)

## Decision

The October 3, 2026 follow-up selects **PROMOTE L5 TO SHADOW**, not production. Frozen L2 remains a retained comparison challenger. Champion, published forecasts, serving policy, ETL, scheduler and production promotion thresholds are unchanged. No Jev or model API calls are involved.

The [original L1/L2/L3 results](learned-intraday-challenger.md) remain immutable: fixed L2 improved broad MAE by 9.01% but worsened closest MAE by 4.88%, with 3/7 closest daily wins/losses and increased issue-to-issue revisions. Original inputs, splits, models, replays and source-exact counterexamples are preserved.

## Architecture

| Candidate | Formulation | Training discipline |
|---|---|---|
| L2 reference | Post + learned remaining error | Independently refitted within each outer fold |
| L4 | Post + `sqrt(1+lead/60)` × learned normalized error | 46 original features + 10 continuous lead/context features |
| L5 | Post + learned weight × L2 correction | Gate uses chronological out-of-fold corrections only |

L4 adds log/sqrt lead, observed-path availability/age and lead-scaled residual/path interactions; target is `(actual-post)/sqrt(1+lead/60)`. L5 uses the training-only label `clip((actual-post)/OOF_correction,0,1)`, with zero weight for zero correction. Its 59 gate inputs are the 56 issue-time features plus predicted correction, absolute correction and normalized correction. Final actuals never enter inference. No handwritten hour or lead activation switch exists.

L2/L4 use the original LightGBM parameters. L5 gate uses squared-error regression, 100 trees, learning rate 0.035, 6 leaves, minimum child size 60 and regularization 20. Date/hour weighting is reciprocal capture count. Inner folds start with eight training dates, then predict three-day blocks using earlier dates only. No random split or outcome-driven retuning.

## Frozen Evaluation

Freeze: `2026-10-03T18:00:50.748933+09:00`; data revision `ea57d03155b4c5b3f86c97b1b8fb5cbcc3afd275`. Dataset SHA-256: `99aad1b55f6e5c1ada5f1aeae76faa906bde7ce85dff5e7a20231777f9409610`. Preregistration SHA-256: `5ffbac417837274c441a3e265da2971e8b602e031c9018724410d12d462687d4`.

| Fold | Training | Test | Pairs |
|---|---|---|---:|
| 1 | Aug 28–Sep 10 | Sep 11–17 | 760 |
| 2 | Aug 28–Sep 17 | Sep 18–24 | 1,357 |
| 3 | Aug 28–Sep 24 | Sep 25–Oct 1 | 1,588 |

All historical dates were already seen. This is chronological retrospective research, **not independent confirmation**. Historical finalized-label delivery is unproven. October 2/3 provisional observations and new live shadow outcomes do not train or select the candidates.

Baseline is same-run recorded post, not published or retrospective/latest. Closest selects one minimum positive lead per date/hour within `(0,120]`, not all near-lead issues. Historical champion artifact/policy identity and native challenger intervals remain unavailable.

Research-only criteria were registered before outcomes: broad MAE/WAPE gain >=3%; closest MAE no worse; all/closest RMSE growth <=2%; closest daily wins >= losses; each fold closest MAE growth <=10%; worsening p95/max and cross-issue revision mean/p95 no worse than matched refitted L2. Band/regime allowance is first-fold training champion median absolute error ×0.25. These do not change production thresholds.

## Matched Results

3,705 finalized pairs, 417 closest targets, 21 dates; errors in MW.

| Model | Broad MAE | RMSE | WAPE | Bias | Closest MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Champion | 838.3 | 1,158.7 | 2.792% | +156.8 | 558.6 | 730.7 | 1.906% | +72.5 |
| Refitted L2 | 809.5 | 1,178.9 | 2.696% | -138.0 | 594.2 | 789.4 | 2.028% | -66.4 |
| L4 | 856.2 | 1,237.3 | 2.851% | -191.9 | 573.4 | 753.9 | 1.957% | -73.5 |
| L5 | 791.3 | 1,138.8 | 2.635% | -16.6 | 557.6 | 732.8 | 1.903% | -7.6 |

L5's broad gain is 5.61%; closest gain is only 0.18%, not proof of meaningful superiority. Closest daily wins/losses are 12/9. Fold closest MAE is 593.2/461.2/621.7 versus champion 581.6/489.0/606.8: final-fold degradation remains 2.46%. L4 fails broad/near, tail and revision criteria. Criteria were not relaxed afterward.

Final-fold fixed L2 is 991.7 broad/624.3 closest versus L5 996.3/621.7. Training cutoffs differ (Sep 21 vs Sep 24); L5 is not uniformly better than frozen L2.

## Lead and Stability

Fixed L2 original holdout, with bins registered before candidate outcomes:

| Lead minutes | Pairs | Champion MAE | Fixed L2 MAE |
|---|---:|---:|---:|
| (0,30] | 136 | 628.1 | 654.2 |
| (30,60] | 34 | 500.0 | 495.5 |
| (60,120] | 170 | 781.1 | 768.3 |
| (120,180] | 160 | 977.9 | 947.3 |
| (180,360] | 460 | 1,142.4 | 1,084.1 |
| >360 | 1,309 | 1,043.2 | 909.4 |

There is no clean 120-minute switch; 30–60 minutes has few samples. L5 bucket-average weights are approximately 0.52–0.55: chiefly context-dependent shrinkage, not a proven monotonic lead-trust law.

Walk-forward worsening p90/p95/max drops from refitted L2 905.0/1,243.7/2,552.9 to L5 546.2/754.8/1,952.9 broadly; closest drops from 758.8/964.9/1,692.1 to 445.1/543.2/1,038.7. Zero regression is not claimed.

For 2,838 adjacent same-target issues with gap <=120 minutes, mean/p95 revision is champion 164.8/661.4, refitted L2 273.6/780.4, L5 209.3/670.0. L5 is steadier than L2, but not champion. Within-run shape and cross-issue revision remain separate metrics.

Retained L5 counterexamples include maximum added errors of Sep 14 09:00 +474.9, Sep 16 14:00 +603.7, Sep 22 20:00 +210.0 and Sep 26 21:00 +416.3 among corresponding issue runs. Old cases outside outer-test dates remain historical context, not independent tests.

## Worker and Contracts

For persistent collection, use the [isolated Docker multi-challenger service](docker-intraday-shadow.md). The terminal worker below and its 1.1 contracts remain historical/manual tools; independent live eligibility uses the new service's separate contract.

`feed.py` fetches only `data` into an isolated bare Git repository under `data/intraday_challenger/<workspace>`. It reads allowlisted snapshots/actuals/ETL state and preserves source bytes/hashes/revisions. It does not restore/write `web/public`, modify production Git refs, run ETL or call a model API.

Prediction `intraday-shadow/1.1.0` stores issue/capture time and both leads, target, raw/pre/post, cutoff, source pointer/hash and immutable identity. Started targets are retrospective. Old 1.0 captures remain readable and unchanged. Delayed captures are not on-time issues; inspect `captureDelayMinutes` and `capture_lead_minutes`.

Evaluation `intraday-shadow-evaluation/1.1.0` adds row-level actual state/hash, signed errors and absolute-error delta. Actual revisions create separate immutable evaluation versions. Identities, finalized/provisional and prospective/retrospective populations remain separate. Missing labels stay unavailable; forecast fallback is not an actual. Reports include lead/time bands, daily wins/losses, tails and revision stability. Sample readiness is not promotion readiness.

```text
python -m python.eval.intraday_challenger lead-research --dataset <dataset.jsonl> --registration-file <preregistration.json> --registration-sha <sha256> --code-revision <revision> --output-root data/intraday_challenger/<new-research>
python -m python.eval.intraday_challenger.feed --remote https://github.com/wonhongChang/tokyo-grid-ems --model-root <frozen-model> --identity-sha <sha256> --output-root data/intraday_challenger/<identity-shadow> --start-date 2026-10-03 --interval-seconds 300
```

Use `--cycles 1` for finite collection. Otherwise the standalone worker sleeps inside Python. Run in a user-owned terminal, keep it open and stop with Ctrl+C. No scheduler/service/boot registration. Exact historical reproduction requires the retained local frozen dataset/manifest, not included in Git.

## Identity and Next Gate

L5 trains on 5,235 finalized rows through Oct 1. Identity SHA-256: `e39715d5e956d6bb8f110df0b857f4af7baf94fa57fd3122fdce4f9e70a9a149`; combined fingerprint: `614486238b55aaec6e705a686905b6264b9284c6ef38ed0cc75f2a4de6b393be`. Native artifacts, dataset, feature schema, parameters, OOF periods and implementation hashes are pinned. Original L2 model/feature source identities and loader stay unchanged.

At the research-stage check, L2's finite worker cycle and L5's first prospective capture were verified without leaving a session background process. Those initial delayed captures are context, not finalized independent confirmation. Persistent collection now uses the separate Docker service; inspect its status rather than treating this historical check as live health.

Keep per-identity readiness: 14 finalized dates, >=8 business and >=4 non-business dates, >=300 finalized prospective pairs, >=150 closest targets. October 18 after ETL is a conditional checkpoint, not an automatic approval date. Native interval, champion identity and normal promotion limitations still apply.

Fourteen new tests and the original/relevant intraday/replay/batch suites pass: **258 total**. Coverage includes leakage/cutoff, identity/hash, immutable revisions, path isolation, serialization/determinism, chronological OOF/outer splits, matched populations, lead boundaries and unchanged-input workers. Generated datasets/models/captures, usage measurements and session notes stay ignored.
