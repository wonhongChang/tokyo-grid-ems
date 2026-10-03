# Docker Multi-Challenger Shadow

[한국어](../ko/docker-intraday-shadow.md) | [日本語](../ja/docker-intraday-shadow.md)

## Role and Isolation

The production champion keeps serving unchanged. `intraday-shadow` independently reads the public GitHub `data` branch. Its outputs never feed forecasting, ETL, scheduling, serving policy or promotion. No OpenAI/Jev calls or API keys are required.

```text
data branch -> dedicated shallow bare Git -> allowlisted source cache
  snapshot -> one issue-time feature reconstruction -> up to 3 ACTIVE models -> immutable predictions
  actual + ETL-state -------------------------------------------------------> immutable evaluations
read-only registry/model mount                         shadow-only writable named volume
```

Only evaluation modules and pinned dependencies are copied into the image. No `.env`, checkout, production output, ETL code, host HOME or Docker socket is mounted/copied. Root filesystem and `/shadow-input` are read-only. UID/GID `10001:10001`, dropped capabilities, `no-new-privileges` and ephemeral `/tmp` are used. Named volume `tokyo-grid-ems-intraday-shadow` contains `/app/data/intraday_challenger/live`.

The isolated bare repo fetches `refs/heads/shadow-data`; production refs stay untouched. Public HTTPS fetches do not read host credential helpers/config.

## Sources and Polling

| Source | Purpose | Missing state |
|---|---|---|
| `reports/internal/operational-calibration/snapshots/<date>/*.json` | Completed issue-time observations/cutoff, raw/pre/post and champion reference | Prediction unavailable |
| `actual/<date>.json` | Later matched evaluation labels | Null/unavailable errors |
| `.etl_state.json` / `okDates` | Date finalization and coverage | Do not infer finalized |

Published forecasts, general metrics and latest weather are not read. Champion reference is **same-run recorded post**, not published/advance. Unattested champion artifact/policy identities and native challenger intervals remain null/unavailable.

Polling is **600 seconds**. Sources are mainly two-hourly, with hourly morning, rollover and late catch-up runs. Ten minutes is shorter than cadence without production coupling. An approximately five-minute average delay under steady timing does not replace actual capture timestamps. Unchanged revisions skip tree/blob/evaluation processing; unchanged blobs in updated revisions are reused. Event-driven notifications remain a future option, not a production hook.

## Registry and Admission

Contract `intraday-shadow-registry/1.0.0`; [schema](../../docker/shadow-registry.schema.json). Pin name/version, identity SHA, artifact fingerprint/path, feature schema/dataset identity, cutoff, activation, research exclusions, qualification and legacy references.

- Champion is separate; **at most 3 ACTIVE challengers**. Statuses are `ACTIVE`, `PAUSED`, `RETIRED`. Exceeding the limit is rejected; retirement is manual, never automatic deletion.
- Registry updates require higher versions; old bytes remain. Existing identity metadata cannot change/disappear; only status can change. Changed artifacts require a new identity even with the same name.
- Admission/resumption records a real adoption-time active epoch. Earlier snapshots cannot retroactively become independent evidence.
- Current loaders support frozen L1/L2/L3 and L4/L5 contracts. A different L6/L7 architecture needs its own validated loader without changing L5 source hashes.

Before research, preregister baseline-distribution criteria for broad replay, chronological/walk-forward, overall/targeted benefit, tails, known counterexamples, deterministic identity and isolation. Zero regression is not required. Hash-pinned qualification gates and dataset identity are checked. Passing allows **shadow admission only**, not production.

See [lead-aware research](lead-aware-intraday-shadow.md) for frozen L5 identity/results/limitations. Old model bytes and legacy captures remain read-only context, not new independent counts. L6/L7 research/replay can proceed immediately while L5 collects.

## Capture and Independent Population

Contract `intraday-multi-shadow-capture/1.0.0`. Parse/reconstruct issue-time features once, then infer per model. Only completed recorded observations inside the cutoff enter inference; later labels never do. `recordedAt` is **each model's inference completion time**.

Preserve issue/capture time, target, both leads, delay, raw/pre/post/reference, challenger, cutoff, source revision/hash/pointer, identity and exclusions. Filenames use complete record SHA; every record pins identity. Identity+snapshot dedup survives restarts. A different source revision at the same issue is rejected/unavailable, not an overwrite or double-count.

`targetTiming` is prospective/retrospective at completion. `captureStatus` is delayed above 15 minutes, otherwise prospective/retrospective. Independent live inclusion requires issue after activation/active epoch, completion before target, delay <=**900 seconds**, and dates outside training/research ranges. This collection policy is 600-second poll +180-second Git timeout +120-second margin, not a forecast threshold. It is frozen per workspace; different policies cannot mix.

Offline backlogs, delayed, retrospective, pre-activation and research-used dates remain context-only, not pretend issue-time live predictions. Each candidate starts its own independent period.

## Evaluation and Readiness

Contract `intraday-multi-shadow-evaluation/1.0.0`. Record actual state/hash/revision, both signed/absolute errors and absolute-error delta. Missing/future values and forecast fallback are not observations. Actual value/finalization revisions create new immutable evaluations; earlier predictions/evaluations remain.

Keep identity, independent/context-only, finalized/provisional, all-positive/closest `(0,120]` populations distinct. Compute MAE/RMSE/WAPE/bias, time/lead bands, daily wins/losses, improve/worsen counts, worsening p90/p95/max, same-target issue revisions and same-run target transitions. Retired history remains.

Sample readiness: >=14 finalized dates, >=8 business, >=4 non-business, >=300 finalized prospective pairs, >=150 closest targets. **Promotion readiness is separate and always false.** Native interval/champion identity/policy limitations remain. Adoption needs an explicit serving-policy identity/version change and normal validation/promotion. Oct 18 is a conditional checkpoint, not automatic approval.

## Prepare and Run

Trained artifacts, qualification and generated evidence are not in Git. Stage local frozen artifacts as follows; preparation does not train or call APIs.

```powershell
python scripts/prepare_intraday_shadow.py --model-root data/intraday_challenger/<model> --identity-sha <sha256> --qualification data/intraday_challenger/<research>/RESULTS.json --qualification-sha <sha256> --research-range <first-used-date> <last-used-date> --name L5 --version 1
docker build -f docker/shadow.Dockerfile -t tokyo-grid-ems-intraday-shadow:1.0.0 .
docker compose run --rm --no-deps -T intraday-shadow python -m python.eval.intraday_challenger.service run --cycles 1
docker compose up -d intraday-shadow
```

Research ranges may repeat. Existing deployment is not overwritten. New candidates use separate artifact/qualification paths and a higher registry version retaining old entries. Each cycle checks the registry. [Configuration example](../../docker/shadow-config.example.json).

## Monitoring and Recovery

```powershell
docker compose ps intraday-shadow
docker compose logs --tail 50 -f intraday-shadow
docker compose exec intraday-shadow python -m python.eval.intraday_challenger.service status
docker compose exec intraday-shadow python -m python.eval.intraday_challenger.service health
docker compose restart intraday-shadow
docker compose stop intraday-shadow
```

Status records service start, last loop/sync/revision/snapshot/prospective prediction/actual/evaluation, active identities, counts, errors and health. Logs distinguish startup/sync/no-change/snapshot/prediction/duplicate/delayed/actual-revision/evaluation/identity-change/recoverable/fatal/shutdown, never credentials or remote stderr. Docker logs rotate at 10 MiB x3.

Health rejects loop/status age >2100 seconds, fatal/stopped or inaccessible workspace. **No new source is not a failure.** Network errors retry inside the next 600-second Python cycle. Docker does not restart merely unhealthy containers; investigate/restart actual hangs.

`unless-stopped` resumes a running service when the engine restarts; manual stop persists. No Windows startup/scheduler registration is added. Enable Docker Desktop **Settings → General → Start Docker Desktop when you sign in to your computer**. See [startup settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/) and [restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/). PC/engine downtime prevents live collection.

The shared-volume OS lock rejects duplicate workers across Compose projects. Never use `docker compose down -v` or delete the volume. Evidence is not auto-pruned: manage disk capacity. Missing current label provenance after source retention becomes unavailable; old immutable evaluations/cache remain.

## Validation and Limits

The 2026-10-03 implementation passes **291 relevant tests**: registry/Draft 2020-12 schema, identity, active limit, retirement/history, shared parsing, leakage/cutoff, completion boundary, timing/activation/research exclusions, actual revisions, immutable/dedup, unchanged/network/health, path/secret isolation and unchanged ETL Compose configuration. Schema validation is local dev/test only; production dependencies are unchanged.

Real Linux Docker checks verify finite sync/capture/evaluation, read-only write rejection, no API keys/ETL code, and frozen Windows/Linux L5 equality. Process/restart/health/no-change checks are deployment verification. Development-PC availability, publication delay, native interval/historical provenance limitations remain. Review Bundle is human-review evidence access, not this collection service.
