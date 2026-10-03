# Docker Multi-Challenger Shadow

[English](../en/docker-intraday-shadow.md) | [日本語](../ja/docker-intraday-shadow.md)

## 역할과 격리

Production champion은 기존 예측을 그대로 제공한다. `intraday-shadow`는 public GitHub `data` branch를 읽는 독립 sidecar이며, 결과를 forecasting/ETL/scheduler/serving policy/promotion에 전달하지 않는다. OpenAI/Jev 호출과 API key는 필요 없다.

```text
data branch -> 전용 shallow bare Git -> allowlisted source cache
  snapshot -> issue-time 피처 1회 생성 -> 최대 3 ACTIVE 모델 -> immutable prediction
  actual + ETL-state -------------------------------------> immutable evaluation
read-only registry/model mount                 shadow-only writable named volume
```

Image에는 평가 모듈과 pinned dependency만 복사한다. `.env`, Git checkout, production output, ETL code, host HOME, Docker socket은 mount/copy하지 않는다. Root filesystem과 `/shadow-input`은 read-only다. UID/GID `10001:10001`, capability 제거, `no-new-privileges`, ephemeral `/tmp`를 사용한다. Writable named volume은 `tokyo-grid-ems-intraday-shadow`, workspace는 `/app/data/intraday_challenger/live`다.

전용 bare repo의 `refs/heads/shadow-data`만 fetch하며 production refs는 변경하지 않는다. Public HTTPS source에서 host credential helper/config를 사용하지 않는다.

## Source와 Polling

| Source | 용도 | 누락 시 |
|---|---|---|
| `reports/internal/operational-calibration/snapshots/<date>/*.json` | Issue-time 완료 실측/cutoff, raw/pre/post, 피처와 champion reference | Prediction unavailable |
| `actual/<date>.json` | 나중에 짝지을 실측 평가 | Error null/unavailable |
| `.etl_state.json`의 `okDates` | 확정 날짜와 coverage | Finalized로 추정하지 않음 |

Published forecast, 일반 metrics, latest weather는 추가로 읽지 않는다. Champion reference는 **same-run recorded post**이며 published/advance가 아니다. 확인되지 않은 champion artifact/policy identity, native challenger interval은 null/unattested다.

Polling은 **600초**다. Source는 주로 2시간 간격이고 오전 hourly, 자정/late catch-up도 있다. 10분은 cadence보다 짧고 production과 결합하지 않는다. 일정한 조건에서 평균 detection delay가 약 5분일 수 있지만 실제 capture 시각을 대체하지 않는다. 변경 없는 revision은 tree/blob/평가를 재처리하지 않고, 새 revision의 동일 blob도 재사용한다. Event-driven notification은 future option이며 production hook은 추가하지 않았다.

## Registry와 진입

계약은 `intraday-shadow-registry/1.0.0`, [schema](../../docker/shadow-registry.schema.json)를 제공한다. Name/version, identity SHA, artifact fingerprint/path, feature schema/dataset identity, training cutoff, activation timestamp, research exclusion ranges, qualification/legacy references를 고정한다.

- Champion은 별도 reference이며 **ACTIVE challenger 최대 3개**다. `ACTIVE`, `PAUSED`, `RETIRED`를 사용한다. 상한 초과는 거부하고 retirement는 사람이 결정한다. 자동 삭제는 없다.
- Registry 변경은 version을 올리고 이전 bytes를 보존한다. 기존 identity의 metadata는 바꾸거나 제거할 수 없고 status만 변경할 수 있다. Artifact가 달라지면 같은 name이라도 새 identity다.
- 추가/재개 시 실제 adoption 이후 active epoch를 기록한다. 과거 snapshot을 소급해 독립 표본으로 세지 않는다.
- Loader는 현재 frozen L1/L2/L3 및 L4/L5 계약을 지원한다. 다른 L6/L7 architecture는 해당 계약의 검증된 loader를 추가해야 하며 기존 L5 구현 hash를 바꾸면 안 된다.

새 후보는 baseline distribution에 근거한 기준을 연구 전에 preregister하고 broad replay, chronological/walk-forward, 전체 또는 표적 개선, regression tail, known counterexamples, deterministic identity, 격리 테스트를 검증한다. Zero regression은 요구하지 않는다. Registry는 hash-pinned qualification gates와 dataset identity를 확인한다. 이 통과는 **shadow admission**이지 production 승격이 아니다.

L5의 frozen identity/성능/한계는 [lead-aware 연구](lead-aware-intraday-shadow.md)에 있다. 기존 모델 bytes와 legacy 기록은 read-only context로 보존하며 새 독립 표본에 합산하지 않는다. L5 수집 중에도 L6/L7 연구·replay는 즉시 가능하다.

## Capture와 독립 표본

계약은 `intraday-multi-shadow-capture/1.0.0`이다. Snapshot parsing/issue-time 피처는 공유하고 모델별 추론만 수행한다. 완료 관측/cutoff만 사용하며 나중에 받은 actual은 inference에 들어가지 않는다. `recordedAt`은 **각 모델 inference 완료 시각**이다.

Issue/capture 시각, target, issue/capture lead, delay, raw/pre/post/reference, challenger, cutoff, source revision/hash/pointer, identity, 제외 사유를 보존한다. Filename은 완전한 record SHA이며 record 내부에 identity가 고정된다. Identity+snapshot dedup은 재시작 후에도 유지한다. 같은 issue의 다른 source revision은 unavailable/rejection으로 남기고 기존 예측을 덮어쓰거나 이중 계산하지 않는다.

`targetTiming`은 완료 시각 기준 prospective/retrospective다. `captureStatus`는 15분 초과 지연이면 delayed, 아니면 prospective/retrospective다. 독립 live inclusion은 issue가 activation/active epoch 이후, target 전에 추론 완료, delay <= **900초**, training/research 사용 날짜가 아님을 모두 요구한다. 900초는 600초 polling +180초 Git timeout +120초 처리 여유의 **수집 정책**이지 forecast threshold가 아니다. Workspace에 고정하며 다른 정책을 섞지 않는다.

Offline backlog, delayed, retrospective, pre-activation, research-used date는 context-only다. 계산한 시각을 과거 live prediction으로 가장하지 않는다. 신규 후보는 자신의 activation 이후부터 따로 표본을 모은다.

## Evaluation과 Readiness

계약은 `intraday-multi-shadow-evaluation/1.0.0`이다. Actual state/hash/revision, champion/challenger signed·absolute error, absolute-error delta를 기록한다. Forecast fallback·미래·결측 actual은 실측이 아니다. Provisional→finalized와 값의 revision마다 새 immutable 평가를 만들고 이전 예측/평가는 보존한다.

Identity별 independent/context-only, finalized/provisional, all-positive/closest `(0,120]`를 분리한다. MAE/RMSE/WAPE/bias, time/lead band, 일별 우위/열위, 개선/악화 개수, 악화 p90/p95/max, same-target issue revision, same-run target transition을 계산한다. Retired identity도 history를 유지한다.

Sample readiness는 확정 날짜 >=14, 영업일 >=8, 비영업일 >=4, 확정 prospective pair >=300, closest target >=150다. **Promotion readiness는 별도이며 항상 false**다. Native interval/champion identity/policy 부족은 남아 있다. 실제 도입은 explicit serving-policy identity/version 변경과 기존 validation/promotion을 요구한다. 10/18은 조건부 검토일이지 자동 승인일이 아니다.

## 준비와 실행

Trained artifacts, qualification, generated evidence는 Git에 포함하지 않는다. 로컬 frozen 모델을 아래처럼 준비한다. Script는 학습/API 호출을 하지 않는다.

```powershell
python scripts/prepare_intraday_shadow.py --model-root data/intraday_challenger/<model> --identity-sha <sha256> --qualification data/intraday_challenger/<research>/RESULTS.json --qualification-sha <sha256> --research-range <first-used-date> <last-used-date> --name L5 --version 1
docker build -f docker/shadow.Dockerfile -t tokyo-grid-ems-intraday-shadow:1.0.0 .
docker compose run --rm --no-deps -T intraday-shadow python -m python.eval.intraday_challenger.service run --cycles 1
docker compose up -d intraday-shadow
```

Research range는 반복 지정 가능하다. 기존 deployment는 덮어쓰지 않는다. 새 모델은 mount 아래의 별도 artifact/qualification path에 준비하고 기존 entry를 보존한 registry version을 올린다. Service는 각 cycle에 registry를 확인한다. [Configuration example](../../docker/shadow-config.example.json).

## Monitoring과 복구

```powershell
docker compose ps intraday-shadow
docker compose logs --tail 50 -f intraday-shadow
docker compose exec intraday-shadow python -m python.eval.intraday_challenger.service status
docker compose exec intraday-shadow python -m python.eval.intraday_challenger.service health
docker compose restart intraday-shadow
docker compose stop intraday-shadow
```

Status는 service start, last loop/sync/revision/snapshot/prospective prediction/actual/evaluation, active identities, sample counts, error count/last error/health를 기록한다. Logs는 startup/sync/no-change/snapshot/prediction/duplicate/delayed/actual-revision/evaluation/identity-change/recoverable/fatal/shutdown을 구분하며 credential/remote stderr를 출력하지 않는다. Docker log rotation은 10 MiB x3다.

Health는 loop/status age >2100초, fatal/stopped, workspace 접근 실패를 감지한다. **새 source가 없다는 이유만으로 unhealthy가 되지 않는다.** Network failure는 다음 Python 내부 600초 cycle에 재시도한다. Docker는 unhealthy만으로 자동 restart하지 않으므로 실제 hang은 조사/수동 restart한다.

`unless-stopped`는 engine 재시작 시 실행 중이던 서비스를 복구한다. Manual stop은 유지된다. Windows boot/scheduler 등록은 하지 않았다. Docker Desktop **Settings → General → Start Docker Desktop when you sign in to your computer**를 켜야 한다. [Startup 설정](https://docs.docker.com/desktop/settings-and-maintenance/settings/), [restart 정책](https://docs.docker.com/engine/containers/start-containers-automatically/). PC/engine offline에는 live 수집이 불가능하다.

공유 volume의 OS lock은 다른 Compose project의 중복 worker도 차단한다. `docker compose down -v`나 volume 삭제는 기록을 잃으므로 사용하지 않는다. Evidence는 자동 삭제하지 않으니 디스크 용량을 관리한다. Source retention으로 최신 label provenance가 없어지면 unavailable로 표시하며 이전 immutable 평가/cache는 보존한다.

## 검증과 제한

2026-10-03 관련 suite **291개 통과**: registry/Draft 2020-12 schema, identity, ACTIVE 상한, retirement/history, shared parsing, leakage/cutoff, 완료 시각 boundary, delayed/activation/research 제외, actual revision, no-overwrite/dedup, no-change/network/health, path/secret 격리, ETL compose 불변성. Schema validator는 local dev/test 전용이며 production dependency는 바꾸지 않는다.

실제 Linux Docker에서 유한 sync/capture/evaluation, read-only 쓰기 거부, API key/ETL absence, frozen L5 Windows/Linux 예측 일치를 확인했다. Process/restart/health/no-change는 배포 검증으로 별도 확인한다. 개발 PC의 가동률, source publication delay, native interval/historical provenance 제한은 남는다. Review Bundle은 사람의 근거 조회 도구이고 이 지속 수집 서비스와 역할이 다르다.
