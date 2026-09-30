# 모델 리뷰 근거 패키지와 읽기 전용 CLI

Tokyo Grid EMS의 Review Bundle은 동결된 로컬 근거를 계산·색인하고 선택적으로 조회하는 프로젝트 내부 evidence package다. 모델 추론, Jev, OpenAI, ETL 또는 정상 리뷰 자동화를 호출하지 않는다. Bundle의 수치 계산과 선택 규칙은 검증한 `review-bundle/0.2.0-design`을 유지한다. 공개 도구로 배포하되 운영 파이프라인에 자동 연결하지 않는다.

[English](../en/review-bundle-cli.md) | [日本語](../ja/review-bundle-cli.md) | [검증 결과](review-bundle-validation.md)

## 배경과 구조

기존 리뷰에서는 reasoning model이 여러 날짜의 actual/forecast, 발행 시점별 snapshot, calibration, interval history, replay 결과를 반복해서 찾아 모집단과 시점을 다시 맞춰야 했다. 작은 모델의 advisory로 조사 순서를 정하는 실험도 했지만, 근거를 재구성하는 반복 작업은 별도로 남았다.

이 도구는 다른 판단 모델을 추가하는 대신 Python이 수치·선택 규칙·출처를 결정적으로 준비한다. 대형 raw artifact 전체를 기본 context로 쓰지 않고, 먼저 작은 안내 packet을 읽고 질문에 필요한 근거만 펼친다. 요약은 판단 권한이 아니며, 미강조 구간도 검토 대상이다.

```text
동결된 사본 + hash manifest
  -> Python builder: 계산, scope/date/run 인덱스, null/notice 보존
  -> Bundle: 초기 packet + sealed sections/details/indexes
  -> batch/read-only CLI: 질문별 context/state/value
  -> 리뷰 담당자 또는 reasoning model
  -> 필요한 경우에만 selective detail/source drill-down
```

| 구현 | 역할 |
|---|---|
| `core.py` | 검증된 계산·선택·chunk 규칙. 과거 계약 문자열도 호환성을 위해 유지 |
| `access.py` | 명시적 root/manifest/hash 확인과 command-body 접근 제한 |
| `cli.py` | build, 선택 조회, 구조화된 오류와 I/O 계측 |
| `batch.py` | 이미 계산된 근거의 질문 중심 표현, 공통 registry |
| `review-bundle.schema.json` | 저장 artifact의 Draft 2020-12 계약 |
| `review-view.schema.json` | batch 응답의 Draft 2020-12 계약 |

코드는 [python/eval/review_bundle](../../python/eval/review_bundle)에 있다. 런타임 의존성은 표준 라이브러리뿐이며 private 폴더나 생성된 실험 파일을 import하지 않는다.

## 모집단과 수동 리뷰 순서

| Basis | 해석 원칙 |
|---|---|
| published | 해당 scope revision에 보존된 공개 예측선. 최초 발표본임을 보증하지 않음 |
| advance | 같은 capture에서 최소 양수 lead, 120분 이내. TEPCO와 동일 발행 시점인지 unknown |
| stages | 같은 run의 raw/pre/post. 다른 run 또는 사후 값으로 교체 금지 |
| retrospective | lead가 0 이하인 보존 단계. 선행 예측 검증과 구별 |
| interval | 별도로 선택한 retained interval snapshot의 모집단 |
| followup | 별도 revision의 추가/정정. 원래 as-of를 덮어쓰지 않음 |
| candidate | 모든 기록된 issue/target pair. 성능 gate 또는 승격 승인 아님 |

권장하는 수동 순서는 initial → notices/scopes → metrics inventory → direction screening → stage/interval → 이상 시간의 hour review → 필요한 상세/원본 조회다. 데이터 확정 여부, 상쇄되는 bias, 형상, 보정 반례, interval, 발행본 차이, artifact/policy, 누락 provenance, governance를 빠뜨리지 않는다. 원본을 읽을 때는 어떤 질문을 CLI 요약으로 답할 수 없었는지 기록한다. 모델 변경 판단은 기존 검증/replay 정책에 남는다.

## 설치와 입력

Python 3.12 이상을 사용한다(Windows junction 확인 포함). 저장소 최상위에서 다음과 같이 실행한다. API 키나 `.env`가 필요하지 않다.

```powershell
python -B -X utf8 -m python.eval.review_bundle --help
```

입력은 명시적으로 준비한 **전용 사본**이어야 한다. 운영 디렉터리나 사용자 홈을 입력 루트로 지정하지 않는다.

```text
local-workspace/
  review-inputs/
    manifest.json
    sources/<sha256>.json
    sources/<sha256>.md
  review-bundles/
    <bundle-name>/
```

`review-inputs`, `review-bundles`라는 루트 이름은 접근 제한 계약의 일부다. 부모 디렉터리는 먼저 만들어 둔다. 두 루트는 중첩할 수 없다. 입력 디렉터리는 동결 manifest에 명시된 내용 주소 방식의 파일만 허용한다. 임의 폴더 검색·최신 파일 탐색·Git history 접근·자동 입력 다운로드는 제공하지 않는다.

입력 manifest의 구조:

```json
{
  "schemaVersion": "review-bundle-input/0.2.0",
  "scopes": [
    {
      "id": "primary",
      "role": "primary",
      "captureKey": "20",
      "revision": "captured-source-revision",
      "asOf": "2026-09-20T21:37:00+09:00",
      "capturedAt": "2026-09-20T22:09:33.046986+09:00",
      "finalizedThrough": "2026-09-19"
    }
  ],
  "inputs": {
    "20:actual/2026-09-20.json": {
      "path": "sources/<actual-file-sha256>.json",
      "sha256": "<actual-file-sha256>",
      "bytes": 1234
    }
  }
}
```

위 예시는 구조 설명용이다. 실제 SHA256과 실제 파일 bytes를 넣어야 한다. 실제 리뷰용 manifest에는 forecast, 필요한 snapshot/ledger, scope metadata 및 governance 근거를 함께 등록한다. 누락된 근거는 다른 날짜나 최신 값으로 대체하지 않는다.

지원 scope role은 `primary`, `followup`, `candidate_validation`이다. Follow-up은 `parentScope`를 지정한다. Candidate는 기록된 `expectedIdentity`를 선택적으로 갖는다. 날짜·revision·cutoff·확정 여부를 지어내서 채우면 안 된다.

v0.2 builder의 기존 logical key 계약을 유지한다. 후보는 `candidate:lift_replay.json`, governance는 `extra:metrics/model_promotion.json`과 `extra:metrics/operational_replay.json`을 사용한다. 이들은 **로컬 사본을 읽는 식별자**일 뿐 실제 모델 승격이나 replay를 실행하는 경로가 아니다.

## Build

```powershell
$inputRoot = 'C:\local-workspace\review-inputs'
$outputRoot = 'C:\local-workspace\review-bundles'
$inputSha = (Get-FileHash -Algorithm SHA256 "$inputRoot\manifest.json").Hash.ToLowerInvariant()
$common = @('--input-root', $inputRoot, '--input-sha', $inputSha,
            '--output-root', $outputRoot, '--bundle', 'review-2026-09-20')

$built = python -B -X utf8 -m python.eval.review_bundle build @common 2> build-io.json
if ($LASTEXITCODE -ne 0) { throw 'Bundle build failed' }
$seal = ($built | ConvertFrom-Json).value.bundleSealSha256
$query = $common + @('--bundle-sha', $seal)
```

`build`만 지정 출력 루트 아래의 새 bundle 폴더에 쓴다. 기존 bundle을 덮어쓰지 않는다. 다른 bundle 이름으로 재생성한다. 실패 시 부분 생성 폴더가 남을 수 있다. 완료된 `access.json`과 성공한 build 결과의 hash가 없으면 완료 bundle로 취급하지 않는다.

`--input-sha`는 입력 manifest 원본 bytes를 고정한다. `--bundle-sha`는 build가 반환한 `access.json`의 hash다. 변경된 파일을 통과시키기 위해 기존 hash를 새 파일 hash로 바꾸면 안 된다. 새 입력은 새 bundle로 만들어 별도 capture로 관리한다.

## 조회 명령

모든 조회는 위 `$query` 인자를 공통으로 사용한다.

```powershell
python -B -X utf8 -m python.eval.review_bundle initial @query
python -B -X utf8 -m python.eval.review_bundle scopes @query
python -B -X utf8 -m python.eval.review_bundle facts @query --scope primary --date 2026-09-20 --limit 5

python -B -X utf8 -m python.eval.review_bundle fact @query --fact-id primary:2026-09-20:metrics --pointer /value/mae
python -B -X utf8 -m python.eval.review_bundle metadata @query --fact-id primary:2026-09-20:metrics
python -B -X utf8 -m python.eval.review_bundle provenance @query --fact-id primary:2026-09-20:metrics

python -B -X utf8 -m python.eval.review_bundle indexes @query --scope primary --date 2026-09-20 --hour 13
python -B -X utf8 -m python.eval.review_bundle resolve @query --kind detail --fact-id primary:2026-09-20:stages --pointer /stages --hour 9
python -B -X utf8 -m python.eval.review_bundle notices @query
python -B -X utf8 -m python.eval.review_bundle manifests @query --kind chunks
python -B -X utf8 -m python.eval.review_bundle manifests @query --kind sections
python -B -X utf8 -m python.eval.review_bundle chunk @query --chunk 0
```

| 명령 | 반환 대상 |
|---|---|
| `initial` | 초기 packet, 작은 review overview, notice/section/chunk 참조 |
| `scopes` | 시각·revision·role을 포함한 scope 목록 |
| `facts` | scope/date별 fact ID와 context 목록 |
| `fact` | fact 또는 JSON pointer의 부분 값과 context |
| `indexes` | 전체 날짜 또는 필터한 run/target 목록 |
| `metadata` | method/population/state 등 의미 문맥 |
| `provenance` | source ID/hash/pointer 및 detail 참조 |
| `notices` | mandatory notice 목록 |
| `manifests` | section 또는 chunk 목록과 전체 사실 참조 |
| `chunk` | 지정한 초기 fact chunk |
| `resolve --kind detail` | 한 fact에 연결된 상세 JSON의 선택 부분 |
| `resolve --kind source` | 명시적으로 연결된 원본의 선택 부분 |

배열 조회는 `--offset`, `--limit`과 `paging.nextOffset`을 사용한다. 기본 limit은 20, 최대 200이며 수치 평가 threshold가 아닌 조회 페이지 크기다. `nextOffset`이 null일 때 마지막 페이지다. 전체 결과를 묵시적으로 잘라내지 않는다.

상세 배열은 `--hour`, `--date`, `--issued-at`으로 필터할 수 있다. Pointer는 RFC 6901의 `/key/0/field` 형태다. 잘못된 escape, 음수 배열 index 및 선행 0 index는 허용하지 않는다. Detail/source는 비어 있지 않은 pointer를 요구한다. 전체 sidecar 파일을 여는 명령은 제공하지 않는다.

원본 조회는 index/provenance에서 얻은 source와 pointer를 사용한다.

```powershell
python -B -X utf8 -m python.eval.review_bundle resolve @query `
  --kind source --fact-id primary:2026-09-20:stages `
  --source '20:reports/internal/operational-calibration/snapshots/2026-09-20/2026-09-20T13-32-40-09-00.json' `
  --pointer /hourlyDiagnostics/13/forecastMwByStage/raw_lgbm
```

Raw source를 조회했다고 그 값이 부모 fact의 metric 모집단에 포함된다고 해석하면 안 된다. 응답에는 parent population과 실제 run의 basis/lead/identity를 구별해서 표시한다. Nonpositive lead는 retrospective로 표시한다. 연결 관계가 확인되지 않는 source는 거부한다.

## 리뷰용 배치 조회

저장된 v0.2 계산 결과와 선택 규칙은 그대로 두고, 조회 시에만 `review-bundle-batch/1.1.0` 형식으로 묶는다. 기존 bundle을 다시 만들 필요가 없다. 개별 `fact`/`resolve`/`indexes` 명령도 유지한다.

```powershell
python -B -X utf8 -m python.eval.review_bundle review-summary @query --scope followup --date 2026-09-21
python -B -X utf8 -m python.eval.review_bundle metrics-inventory @query --scope primary --from 2026-09-07 --to 2026-09-20
python -B -X utf8 -m python.eval.review_bundle direction-screen @query --scope primary --dates 2026-09-16,2026-09-18,2026-09-19
python -B -X utf8 -m python.eval.review_bundle stage-interval-review @query --scope primary --dates 2026-09-16,2026-09-18,2026-09-19
python -B -X utf8 -m python.eval.review_bundle hour-review @query --scope followup --date 2026-09-21 --hour 12
python -B -X utf8 -m python.eval.review_bundle hour-review @query --scope followup --date 2026-09-21 --hours 9,12,18
python -B -X utf8 -m python.eval.review_bundle membership-summary @query --scope followup --date 2026-09-21 --hour 0
python -B -X utf8 -m python.eval.review_bundle stage-interval-review @query --scope primary --date 2026-09-19 --expand-details --expand-provenance
python -B -X utf8 -m python.eval.review_bundle paths @query --fact-id followup:2026-09-21:metrics
python -B -X utf8 -m python.eval.review_bundle paths @query --fact-id followup:2026-09-21:stages --pointer /stages
```

| 명령 | 범위 |
|---|---|
| `review-summary` | 한 날짜의 coverage/metrics/bands/shape/noon/stages/advance/interval/weather와 관련 notice |
| `metrics-inventory` | 여러 날짜의 coverage와 공개선 지표, 개별 fact ID와 identity 참조 |
| `direction-screen` | bands/sign runs/noon 및 실제 반대 방향 transition 중 최대 delta error 항목 |
| `stage-interval-review` | raw/post 요약, 개선·악화 시간 수, 양방향 극값과 전체 악화 목록 참조, interval/profile 및 advance |
| `hour-review` | 하나 또는 여러 목표 시간의 독립된 published/advance/stages/interval 행, control/run/cutoff와 대체 run 인덱스 |
| `membership-summary` | basis/lead별 보존 index 행 수, 양수 lead advance 시간, interval 후보와 실제 선택 시간의 구별 |
| `paths` | 유효한 detail 자식 pointer, 배열 길이·필드 이름. 실제 값을 모두 펼치지 않음 |

여러 날짜는 `--dates` 또는 `--from`/`--to`로 선택한다. 범위 선택은 등록된 날짜만 나열하며, 전체 달력 날짜의 데이터 확보를 보증하지 않는다. 명시적으로 요청한 미등록 날짜는 unavailable section으로 남긴다. 한 페이지는 기본 20일, 최대 31일이다. `paging.nextOffset`과 동일한 selector를 사용해 다음 페이지를 읽는다. 이 제한은 수요 예측 임계값이 아니다. 단일 날짜 summary/hour 명령에는 `--date`를 사용한다.

`registry`는 동일한 identity/provenance/detail/notice를 참조로 공유한다. 각 section의 method, population ID, n, state는 독립적이다. `scopeContext`나 `publishedContext`의 artifact/policy를 stage/interval 행의 unknown identity에 채우면 안 된다. Stage/interval/advance의 `rowIdentityCohorts`는 선택된 행에 기록된 identity별 시간 목록이며, 서로 다른 cohort의 우열을 계산하지 않는다. Interval profile은 공개 forecast 파일의 profile이고 선택된 모든 과거 snapshot의 profile이 아니다.

`hour-review`는 부모 population과 선택된 행 수를 분리한다. 누락된 선행 행에 retrospective 행을 대신 넣지 않는다. 하루 전체 provenance는 `parentProvenanceQuery`로 유지하고 응답에는 선택된 행의 provenance만 포함한다. 대체 run은 count와 `indexes` 명령 참조로 남으며 자동으로 나열하지 않는다.

`--hours`는 0~23의 서로 다른 시간을 쉼표로 지정하며 `--hour`와 동시 사용하지 않는다. 다중 시간 응답은 `dates[].targets[]`에서 각각 확인한다. 없는 시간도 결과에 남는다. 이 옵션은 `hour-review`와 `membership-summary`에서 사용한다. `membership-summary`에서 시간 선택을 생략하면 24시간 전체를 조사한다. Membership은 보존 index의 존재 확인일 뿐이며, missing positive lead를 전역 부재로 해석하거나 retrospective로 대체하면 안 된다.

배치 출처는 기본적으로 접되 짧은 목록은 그대로 유지한다. `registry.provenance`의 `deferred` 필드로 구별한다. 접힌 목록의 `sealedFactRef.fileRef`는 `registry.files`의 hash 참조이며, source hash 목록은 `sourceInventoryRef`로 연결된다. `--expand-provenance` 또는 개별 `provenance` 명령으로 출처를 펼친다. `stage-interval-review --expand-details`는 요약의 전체 시간 목록과 기존 top adjustment를 복원한다. `evidenceQueries.allAdverseHours`는 생략 없는 악화 시간 목록이다.

관측 cutoff는 선택된 stage가 가리키는 원본의 `/correction/lastObservedHour`를 hash 검증 후 읽는다. 기존 frozen bundle의 fact/detail 파일은 변경하지 않는다. 이 자동 원본 읽기도 `rawSourceBytes`에 포함되므로, 명시적인 source 명령이 줄었다고 원본 I/O가 줄었다고 해석하지 않는다. 원본 누락/hash 오류/필드 부재는 cutoff의 structured unavailable로 반환하며 다른 시간이나 최신 파일로 대체하지 않는다. 조회 자체가 exit 0이어도 cutoff가 unavailable일 수 있다.

`initial.reviewOverview`에는 scope별 focus 날짜의 작은 요약과 governance/candidate/followup 상태가 들어간다. 전체 raw 행은 넣지 않는다. 각 날짜의 scope metadata는 상위 `scopes`를 참조한다. Coverage 제외 행과 raw/post 일부 중복 지표는 `fullFactQuery`로 펼치며, 작은 packet의 중복 inline facts도 `inlineFactsDeferred`로 연결한다. `initial --expand-details`는 이 compact 처리를 해제하되 32,768-byte 목표는 유지한다. 목표를 초과하면 overview도 명시적 overflow/continuation으로 전환한다. 원래 저장된 packet과 seal은 바꾸지 않는다.

기계 검증 스키마는 [review-view.schema.json](../../python/eval/review_bundle/review-view.schema.json)을 참고한다.

### 배치 표현 계약

`value.schemaVersion`은 `review-bundle-batch/1.1.0`이다. `dates[].sections`와 날짜 없는 `scopeSections`가 각자의 `factId/method/population/sampleCount/state/value/provenanceRef/detailRef/noticeRefs`를 유지한다. 다중 시간은 `dates[].targets[]`다. Registry의 짧은 ID는 같은 응답 안에서만 유효하므로 서로 다른 응답의 `i0`/`p0`를 연결하지 않는다. Null identity는 다른 section의 값으로 채우지 않는다.

출처는 직렬화 크기에 따라 짧은 목록을 inline, 긴 목록을 deferred로 표현한다. 이는 중요도 선별이 아니다. Deferred는 `referenceListSha256`, source/locator count, sealed fact 참조와 expansion query를 남긴다. `sourceCount`는 출처 ID 수이지 실측 표본 수가 아니다. 공유된 출처가 호환 모집단을 뜻하지 않는다.

Stage의 `absErrorDelta = post 절대오차 - raw 절대오차`이므로 음수는 개선이다. 양방향 극값은 전체 선택 행에서 찾고 동률은 저장 순서를 따른다. `evidenceQueries`의 `fullSummary/allHours/allAdverseHours`로 누락 없이 펼친다. `presentationProjection`이나 `overviewProjection`이 있으면 표시용 부분 요약이다.

`hour-review`의 parent population과 `selection.rowCount/state`는 별개다. Source/pointer가 정확히 일치하는 run context만 붙이며, cutoff가 없으면 추정하지 않는다. `lead`는 분 단위의 발행/capture 기준이고 `leadHours`는 원본 control 필드라 동일하다고 간주하지 않는다.

Membership의 method는 `index_membership_not_comparable`, population/sampleCount는 null이다. `eligibleRetainedIntervalHours`는 양수 120분 이내의 interval 보존 후보이며 실측 결합이 끝난 `selectedIntervalHours`와 다르다. Candidate pair는 별도 index를 사용한다. `--expand-provenance`가 membership의 모든 run을 펼치는 것은 아니며 `indexes` 참조를 따른다.

Raw cutoff 조회는 변경/유실 검증을 위해 계속 hash를 확인한다. 빌드 시 캐시로 대체하지 않는다. Initial만 32,768-byte 목표가 있고 일반 batch는 byte cap이 아니다. 큰 응답은 날짜 페이지나 단일 시간으로 나누며, 잘못된 pointer를 다른 경로로 자동 교정하지 않는다.

## 결과 문맥과 오류

표준 출력은 한 개의 UTF-8 JSON이다. `value`만 추출해서 판단하지 말고 `context`와 `state`를 함께 사용한다.

- Scope와 as-of/capture 시각, date/window
- Method와 정의, population identity, sample count
- Evidence state 및 조회 state
- Mandatory notice 참조, provenance/source/detail 참조
- `compatibleBasesAssumed: false`, `promotionAuthorization: false`

Published, advance, same-run stages, retrospective/latest, interval, candidate, follow-up을 자동 비교하지 않는다. Missing metric은 null이며 0오차로 대체하지 않는다. 존재하는 fact가 unavailable 또는 partial이어도 조회 자체는 성공할 수 있다. 따라서 exit code만 보고 evidence가 충분하다고 판단하면 안 된다.

CLI 조회 실패는 exit code 2와 structured unavailable JSON으로 반환한다. 예: `SOURCE_HASH_MISMATCH`, `RETENTION_LOSS`, `MISSING_POINTER`, `SOURCE_NOT_REGISTERED`, `PATH_TRAVERSAL`, `UNAUTHORIZED_ROOT`. 잘못된 명령 구문은 argparse의 usage error다. 원본 오류 때문에 최신 파일을 찾거나 다른 basis를 빌려 쓰지 않는다.

## Candidate와 overflow

후보 index에는 모든 기록된 issue-time/target pair가 남는다. Changed/degraded pair는 별도 pointer로 조회 가능하다. Negative lead 기록은 선행 예측의 성능으로 해석하지 않는다. Artifact/training/holdout/gate가 없으면 unknown/null이며 approval이 아니다.

특정 발행본을 선택하는 예(해당 자료가 입력 manifest에 등록되어 있어야 한다):

```powershell
python -B -X utf8 -m python.eval.review_bundle resolve @query `
  --kind detail --fact-id candidate:scope:candidate_validation `
  --pointer /changedPairs --date 2026-09-06 --hour 14 `
  --issued-at '2026-09-06T12:25:35+09:00'
```

Nearest/latest 발행본을 대신 고르지 않는다. 이 원칙의 배경인 Q13-v02 정정 이력은 [검증 문서](review-bundle-validation.md)에 요약했다.

초기 목표는 32,768bytes다. 넘으면 mandatory notices와 명시적 chunk/section manifest로 이어진다. CLI context envelope 때문에 초과하는 경우도 `CLI_ENVELOPE_OVERFLOW`로 paging한다. 초기 packet만 읽은 것을 전체 근거를 읽은 것으로 간주하지 않는다. 단일 큰 fact는 삭제하지 않고 기존 oversized record 계약을 유지한다.

## 읽기 전용 경계

- 원본은 manifest의 logical ID, content-addressed 상대 경로와 SHA256 allowlist로 제한한다.
- 절대 경로/`..`/역슬래시/drive injection, symlink/junction/hardlink, UNC 루트를 거부한다.
- `.env`, credential/history/Codex/Jev 경로는 허용하지 않는다. Secret loader나 환경 파일 로딩을 사용하지 않는다.
- Query는 쓰기 금지다. Build도 지정한 새 bundle 폴더 밖 쓰기를 금지한다.
- Command 본문에는 Python audit hook을 적용해 허용 밖 open, filesystem mutation, subprocess와 socket 호출을 차단한다.
- 원본 및 bundle 구성 파일의 hash를 확인한다. Bundle 자체의 hash 기준점은 build 반환 seal이다.

이것은 도구 내부의 접근 제한이지 OS sandbox나 적대적인 Python 코드 실행 환경이 아니다. Python interpreter/import 초기화 이전 활동은 계측 범위 밖이다. 신뢰할 수 있는 로컬 Python과 표준 라이브러리, 변경되지 않은 도구 코드를 사용해야 한다. 다른 프로세스의 동시 파일 변경, mapped network drive, kernel 수준의 우회까지 차단했다고 주장하지 않는다. 동결된 로컬 디스크 사본을 사용한다.

## 계측과 검증 범위

표준 오류는 별도의 measurement JSON이다. Evidence packet에 실행 시각/시간을 섞지 않는다.

- 실제 stdout 반환 bytes
- Command 본문에서 허용된 file-open event와 고유 파일 수
- 내부 파일 read bytes와 raw source drill-down bytes
- Command 본문 elapsed time
- Model tokens: unavailable/null

선택 반환은 작아도 JSON 파싱을 위해 내부적으로 해당 sidecar 전체를 읽을 수 있다. 반환 bytes, 내부 read bytes, source bytes를 서로 바꿔 부르지 않는다. Python startup을 포함한 subprocess 시간은 외부 검증 harness에서 따로 측정한다. Bytes를 모델 토큰으로 환산하지 않는다.

테스트:

```powershell
python -m pip install pytest "jsonschema>=4.18,<5"
python -B -X utf8 -m pytest tests/test_review_bundle_core.py tests/test_review_bundle_cli.py tests/test_review_bundle_batch.py tests/test_review_bundle_refinement.py -q -p no:cacheprovider
```

역사 fixture는 공개 저장소에 복사하지 않는다. 로컬 검증에서는 동결 v0.2 질문 16개를 실제 CLI 호출로 확인하고, 원본 33개 경계 검사를 변경 없이 core port에 재사용한다. 별도의 CLI 보안 검사, schema 검사 및 동일 입력의 byte/hash 재생성을 함께 확인한다. 일반 모델 테스트나 승격 검증을 대신하지 않는다.

Schema 검사는 Draft 2020-12를 지원하는 개발용 `jsonschema`를 요구하며 누락 시 조용히 skip하지 않는다. 운영 의존성은 추가하지 않는다. 선택 query로 반환량이 줄어도 내부에서 section/index 전체를 파싱할 수 있다. 특히 membership 요약은 선택 interval 확인을 추가하므로 개별 index 조회보다 내부 읽기량이 늘 수 있다. 다중 시간은 전체 반환량을 줄여도 개별 응답의 최대 크기를 늘릴 수 있다. 측정 시 기본 조회와 선택적 expansion 비용을 따로 기록한다.

현재 범위는 **수동 bundle-first 리뷰를 위한 독립 도구**다. AGENTS, scheduler, ETL, 모델 설정 및 정상 리뷰 자동화에 연결하지 않는다. 날짜별 생성 bundle과 쿼리 로그는 공개 코드가 아니며 로컬 작업 공간에 보관한다.
