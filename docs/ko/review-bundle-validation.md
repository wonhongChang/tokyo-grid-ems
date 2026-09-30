# Review Bundle 검증 요약

[사용법과 구조](review-bundle-cli.md) | [English](../en/review-bundle-validation.md) | [日本語](../ja/review-bundle-validation.md)

검증 대상은 리뷰 근거의 보존과 선택 조회다. 예측 정확도 개선, 후보 승격, 토큰 절감의 검증이 아니다. 저장 계약 `review-bundle/0.2.0-design`과 표시 계약 `review-bundle-batch/1.1.0`을 사용하며, 운영 예측 경로에 연결하지 않는다.

## 실패에서 수정까지

| 단계 | 발견한 문제 | 유지한 수정 원칙 |
|---|---|---|
| v0.1 offline | 초기 packet은 작았지만 followup/candidate 연결이 빠졌고 26개 경계 중 10개 실패 | 작은 반환량만으로 근거 보존을 판정하지 않음 |
| v0.1 예외 처리 | 빈 실측/fallback-only, 잘못된 날짜, advance 부재, pointer/원본 유실, overflow에서 불완전 처리 | 0오차 또는 최신 값 대신 structured unavailable과 locator 유지 |
| Q13 oracle 감사 | 가장 가까운 발행본이 후보 악화 반례와 다른 행이었음 | 기존 실패 기록을 남기고 Q13-v02에서 정확한 issue/target을 사전 지정 |
| v0.2 | 별도 scope, 모든 날짜/run, 후보 변경·악화 pair, notice/chunk/출처 인덱스 도입 | 근거 부재를 null로 보존하고 top-N 밖 반례도 접근 가능하게 함 |
| CLI | 초기 allowlist 누락, Windows stdout CRLF 계측 차이 발견 | 정확한 namespace와 UTF-8/LF 출력으로 수정, 무제한 경로 허용으로 해결하지 않음 |
| Batch/refinement | 반복 단일 조회와 긴 provenance; 일률적 deferral은 작은 목록을 오히려 확대 | 공유 registry, 다중 시간, 짧은 목록 inline, 긴 목록 명시적 expansion |

Q13-v02는 2026-09-06 12:25:35 JST 발행/14시 target을 사용했다. 기존 13:30 발행본으로 대체하지 않았다. Q16에서는 변경 4개와 악화 3개 pair 전체를 보존했지만, 악화 중 음수 lead 2개는 사후 기록이므로 선행 예측 실패로 세지 않는다. 이는 당시 별도 도구 검증 fixture이며 현재 Candidate A 또는 9/30 모델 연구 결과가 아니다.

v0.2 초기 시도의 문자열 model metadata 처리 오류와 경계 검사 자체의 기대 pointer 개수/키 오류도 로컬 기록에 남았다. 구현과 검사 오류를 고친 뒤 재검증했으며 처음부터 모두 통과했다고 소급해서 표현하지 않는다. 공개 문서는 이 최종 구조와 실패 교훈을 남기고 세션별 실행 기록을 중복 배포하지 않는다.

## 현재 코드 재검증: 2026-09-30

| 검사 | 실제 결과 |
|---|---:|
| 공개 synthetic core/CLI/security/batch/refinement pytest | **76 passed**, skip 0, 21.67초 |
| 동결 역사 fixture의 CLI 복원 질문 | **16/16** |
| 동결 경계/손실 검사 | **33/33** |
| 저장 artifact Draft 2020-12 검증 | **46개, 오류 0** |
| Batch schema/registry, compact/expanded 및 단일/다중 시간 동등성 | pytest 통과 |
| 동일 입력 bundle/details/index/access seal 재생성 | bytes/hash 동일 |
| 역사 입력·기존 v0.2 자료·query 전후 출력 | 변경 없음 |
| 이번 공개 작업의 모델 API 호출 | 0 |

Windows Python 3.14.4, pytest 9.0.3, 로컬 개발용 jsonschema 4.26.0에서 실행했다. 공개 테스트는 private 입력 없이 합성 fixture를 만든다. 신규 테스트의 최초 실행에서는 작은 fixture에 chunk manifest를 기대한 설정 오류와 필수 날짜 selector 누락이 발견됐다. 실제 overflow 입력과 명시적 날짜를 제공하도록 검사 설정을 수정했으며 기존 assertion·계산 규칙·bounds는 완화하지 않았다.

Schema 의존성은 `requirements-dev.txt`에만 추가했다. 공개 테스트 명령은 [사용 문서](review-bundle-cli.md#계측과-검증-범위)에 있다. CLI 계산·선택·보안 구현과 저장 schema는 공개 정리를 위해 변경하지 않았다.

### 복원과 경계 범위

16개 질문은 completeness/finalization, published/advance 표본 차이, MAE/RMSE/WAPE/bias, 반대 방향·시간대 구조, 동일 run raw/pre/post, 발행본 차이, interval 폭/coverage/exclusion, control 필드, issue-time weather 부재, 점심 delta, 후속 정정, 정책 변경, 후보 반례·gate 부재·전체 변경 pair와 governance를 포함한다.

33개 경계는 빈/fallback-only 실측, 0분모, NaN/Inf, 중복 timestamp, timezone/date 불일치, provisional revision, TEPCO 누락, 잔차 순서·작은 형상·gap·반대 극값, top-N 밖 악화, 정책 모집단 불일치, advance 부재, guard 누락, hash 변조, pointer/원본 유실, overflow, 최소 표본 변화, retained와 pass 구별, secret exclusion, cache/identity, 대체 run, failed gates, unavailable population, fact locator, schema mutant rejection을 다룬다.

누락 provenance를 null로 복원한 검사는 누락 정보를 알아냈다는 뜻이 아니다. 후보 gate 부재를 보존한 검사도 후보의 통과를 의미하지 않는다. 동일 입력의 결정성은 동일 로컬 경로에서 검증했다. Source index에 절대 로컬 locator가 있어 다른 기계로 옮긴 결과까지 byte 동일하다고 보장하지 않는다.

### 접근 경계

공개 테스트는 root/traversal 거부, content hash/size 검증, 원본 유실, source allowlist, query 무쓰기, build 범위 제한, `.env` read와 subprocess/socket 차단, full-detail dump 거부, Windows symlink/junction/hardlink를 확인했다. 다른 OS/권한에서 지원되지 않는 링크 생성 검사는 skip 사유를 표시한다.

이것은 신뢰된 Python의 command-body guard이며 OS sandbox가 아니다. Import 이전 실행, 적대적 도구 코드, 외부 프로세스의 동시 변경이나 동일 metadata cache 변조까지 증명하지 않는다. Raw detail/followup 내부의 모든 필드를 완전한 formal schema로 검증하는 것도 아니며 복원·의미 검사를 함께 사용한다.

## 수동 리뷰의 실제 관측

| 계측 | 첫 수동 리뷰 | 두 번째 수동 리뷰 | 두 번째 질문 집합의 refinement 재현 |
|---|---:|---:|---:|
| Evidence CLI 명령 | 83 | 13 | 11 |
| 반환 bytes | 328,849 | 255,913 | 218,477 |
| 내부 logical read bytes | 22,658,704 | 7,308,680 | 6,473,451 |
| File open events | 428 | 126 | 112 |
| 원본 read events | 2 | 3 | 3 |
| 원본 read bytes | 327,041 | 556,803 | 556,803 |
| Command-body 시간(초) | 44.739833 | 7.604760 | 5.921800 |

**83→13은 서로 다른 수동 리뷰의 관측이고, 13→11은 같은 13개 질문을 refinement 후 결정적으로 재현한 결과다.** 통제된 benchmark나 토큰 절감의 인과적 증명이 아니다. 첫 리뷰 83회에는 실패한 pointer 조회 1회가 포함되며 별도 help 1회는 제외했다.

두 번째 리뷰의 명시적 raw-source 명령은 0회였지만 hour-review가 cutoff 검증을 위해 원본을 자동으로 3회 읽었다. 따라서 직접적인 원본 탐색이 줄었다고 원본 I/O까지 감소했다고 주장하지 않는다. Refinement는 총 반환량과 반복 조회를 줄였지만 최대 단일 응답은 34,161→49,125 bytes로 증가했다. Membership 요약도 선택 interval 검증 때문에 단일 index 조회보다 내부 읽기가 늘 수 있다.

Refinement 비교에 별도 expansion/동등성/결정성 검증 10회를 숨겨 넣지 않았다. 그 검증 비용은 추가 반환 658,787 bytes, 내부 읽기 6,325,261 bytes였으며 기본 11회 리뷰 경로와 구분했다. OS cache는 통제하지 않았고 command-body 계측은 import/startup/로그 분석을 제외한다.

**Codex input/output/cached/reasoning token 및 model turn telemetry는 unavailable/null이다.** Bytes나 CLI 횟수로 환산하지 않는다. 주장할 수 있는 결과는 evidence retrieval interaction과 반복적인 근거 재구성 부담이 줄어든 관측이며 token/cost 절감률은 아니다.

## 재현성과 공개 범위

공개 패키지는 code/schema와 self-contained synthetic tests를 포함한다. 역사 검증은 보존된 로컬 사본으로 재실행했으며 manifest hash `e944f9e9f6861d90fe575acedb0ff7c91413ae1c22ed704aff1a2496520c03bf`, bundle seal `f80d7c74b0c3e57ebd84b2b631db924b3cfde01decba2ce063859dedc8e40a27`가 유지됐다. 전체 역사 corpus는 배포하지 않으므로 공개 checkout만으로 그 역사 실행 전체를 재현할 수 있다고 주장하지 않는다.

날짜별 bundle, query dump, capture/replay intermediate, HANDOFF/AS_OF_SEAL, private notes, Jev 상세 실험, Candidate A 및 9/30 연구 결과는 제외한다. 문서는 구조/사용법과 이 검증 요약 두 축으로 통합했다. 현재 권고는 독립적인 수동 리뷰 도구로 사용하되, 누락 근거와 반례를 계속 확인하는 것이다. 운영 예측이나 승격 판단을 대신하지 않는다.
