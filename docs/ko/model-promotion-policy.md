# 모델 승격 및 성능 저하 Champion 정책

언어: [English](../en/model-promotion-policy.md) / [日本語](../ja/model-promotion-policy.md)

상태: v14 복구 후보를 격리 staging에 승격 완료; 원격 배포와 72시간 안정화 감시는 운영자 게시 후 시작

기준일: 2026-08-21 JST

## 목적

이 정책은 정상적인 Champion을 보호하면서도, 기존 모델의 성능이 장기간 저하됐을 때 더 나은 Challenger가 절대 기준 하나 때문에 무기한 차단되는 문제를 방지한다.

현재 구현은 Challenger를 seasonal baseline 및 고정 절대 상한과 비교하고, Champion과는 오늘·내일 예측 drift만 비교한다. 따라서 Challenger가 Champion보다 실질적으로 나아도 절대 상한이나 drift를 넘으면 더 나쁜 Champion이 계속 남을 수 있다.

## 버전 원칙

- 모델 버전은 재학습 횟수가 아니라 피처, target, 앙상블 또는 inference 계약이 바뀔 때 올린다.
- 최신 데이터로 같은 계약을 다시 학습하는 것은 같은 버전이다.
- v12는 v13에 흡수된 과거 후보로 보존하되 활성 후보 풀에서는 제외한다.
- v13은 v14가 성능 저하 v11만 이긴 것이 아님을 증명하기 위한 과거 Challenger 기준점이다.
- v14는 staging에서 승인된 차기 Champion 계약이다. 같은 계약을 최신 데이터로 다시 학습하는 것은 v14 build이며, 피처·target·ensemble·inference 계약이 바뀔 때만 다음 버전으로 올린다.

## 핵심 원칙

1. 정상 승격의 절대 품질 기준은 함부로 완화하지 않는다.
2. Champion과 Challenger는 같은 학습 종료점, 같은 holdout, 같은 입력 계약에서 직접 비교한다.
3. TEPCO 예측은 외부 benchmark와 진단 신호로만 사용하며 학습, 보정, 승격 target으로 사용하지 않는다.
4. 큰 prediction drift는 곧바로 성능 저하를 의미하지 않는다. 자동 승격을 멈추고 shadow 검증을 요구하는 신호로 해석한다.
5. 정상 승격과 성능 저하 Champion의 복구 승격을 분리한다.
6. 복구 승격은 재현 가능한 replay, 변경 불가능한 정확한 artifact, 명시적 운영자 승인, rollback 보호가 필요하다. 승격 전 shadow가 기본이며, 아래의 강화 조건을 만족하는 긴급 복구 경로만 이를 필수 승격 후 감시로 전환할 수 있다.

## 검증 관점

| 관점 | 목적 | 입력 조건 |
|---|---|---|
| Temporal model replay | 원천 모델의 일반화 성능 비교 | 후보별 동일 train cutoff와 28/56/84일 holdout |
| Frozen-origin replay | 당시 예보와 lag로 실제 운영 오차 재현 | 서빙 시점 weather/lag snapshot 사용 |
| As-served replay | Champion과 후처리 전체의 운영 상태 확인 | 실제 게시된 forecast와 확정 actual 사용 |
| Interval validation | q50 변경 후 밴드 안정성 확인 | 전체 및 regime/time-band별 p95 coverage |

최종 관측 기상만 사용한 replay는 모델 mapping 진단에는 유효하지만 실제 서빙 입력을 완전히 재현하지 못하므로 단독 승격 근거로 사용하지 않는다.

## 정상 승격 경로

원천 모델 temporal replay의 안전 상한과 실제 운영 품질 합격선을 분리한다. 기존 값은 temporal replay의 fail-closed 안전 상한으로만 유지하며, 정상 승격에는 더 엄격한 frozen-origin 또는 shadow 운영 품질 gate를 추가한다.

| Temporal replay 안전 기준 | 현재 값 |
|---|---:|
| 전체 MAE | 1,000MW 이하 |
| 전체 WAPE | 3.0% 이하 |
| Shape delta MAE | 750MW 이하 |
| 최대 오차 | 6,500MW 이하 |
| 구간별 MAE | 1,500MW 이하 |
| 구간별 Shape delta MAE | 1,100MW 이하 |
| Seasonal baseline 대비 MAE 개선 | 20% 이상 |

| 중간 운영 품질 기준 | 제안 값 |
|---|---:|
| Frozen-origin/shadow 전체 MAE | 750MW 이하 |
| Frozen-origin/shadow 전체 WAPE | 2.2% 이하 |
| 같은 기간 TEPCO MAE 대비 비율 | 2.0 이하 |
| Shape delta MAE | 700MW 이하 |
| 최대 시간 오차 | 4,500MW 이하 |

TEPCO 기준 근거는 다음과 같다.

| 기간 | TEPCO MAE | 자체 모델 as-served MAE |
|---|---:|---:|
| 최근 28일 | 420.9MW | 949.8MW |
| 최근 56일 | 363.8MW | 733.5MW |
| 최근 84일 | 352.7MW | 656.7MW |
| 2026-08-01~17 | 408.2MW | 1,031.1MW |

750MW는 최근 28일 TEPCO MAE의 약 1.78배이며, 56~84일 자체 모델의 정상 범위에도 여유를 둔다. 이 값은 v11보다 나은 모델로 안전하게 교체하기 위한 중간 운영 SLO이지, TEPCO 동급 인증 기준이 아니다.

### TEPCO 동급 및 우위 기준

프로젝트의 최종 목표는 TEPCO 동급 이상이므로 다음 benchmark 자격을 별도로 사용한다.

| 등급 | 기준 |
|---|---|
| Recovery Champion | 기존 Champion보다 28일 MAE/WAPE를 8% 이상 개선하고 모든 보조 위험 gate 통과 |
| Production Acceptable | 중간 운영 품질 gate 통과 |
| TEPCO Parity Qualified | 동일 발행시점·동일 리드타임에서 28일과 84일 모두 MAE ratio 및 WAPE ratio 1.10 이하 |
| TEPCO Superior | MAE ratio 1.00 미만이며 paired 일별 오차 차이의 95% 신뢰구간 상한이 0 미만 |

`MAE ratio = model MAE / TEPCO MAE`로 정의한다. 최근 28일 TEPCO MAE 420.9MW 기준의 10% 비열등 margin은 약 463MW다. 이는 고정 목표가 아니라 같은 기간 TEPCO 성능에 따라 움직이는 benchmark다.

10% margin은 초기 운영 허용치다. 공식 parity 인증 전에 과대·과소예측이 예비력과 운영비에 미치는 비용으로 margin을 환산하고, 평가 전에 값을 고정한다. 비용 근거가 확보되지 않으면 더 엄격한 ratio 1.00을 최종 목표로 사용한다.

Parity 판정에는 다음 조건을 모두 요구한다.

- TEPCO와 자체 모델 forecast를 동일한 발행시점과 동일한 lead-time bucket으로 비교
- day-ahead와 intraday를 분리 평가
- 모든 필수 lead bucket과 시간대에서 paired-hour coverage 80% 이상 확보
- 시간 상관을 고려해 날짜 단위 block bootstrap으로 paired absolute-error 차이의 95% 신뢰구간 계산
- MAE 비율의 95% bootstrap 신뢰구간 상한이 1.10 이하여야 하며, 유리한 점추정치만으로는 통과 불가
- 영업일·비영업일·오전·낮·늦은 오후·저녁 어느 핵심 구간도 TEPCO MAE의 1.25배를 초과하지 않음
- RMSE 비율은 1.15 이하, 최대 오차 비율은 1.25 이하를 요구한다. TEPCO의 불변 peak vintage가 확보되기 전까지 peak 시간 오차는 진단 지표로만 기록
- 자체 p95 밴드는 별도로 coverage와 pinball loss를 통과

동일 vintage 캡처는 이제 모든 ETL/Intraday 실행에서 append-only로 저장된다. TEPCO가 별도의 불변 `issuedAt`을 제공하지 않으므로 프로젝트의 `capturedAt`을 관측 vintage로 사용한다. 같은 실행에서 본 자체 모델과 TEPCO 값만 비교하고, 이후 TEPCO 수정값은 과거 캡처를 대체하지 않는다. 28일과 84일의 모든 lead bucket coverage가 찰 때까지 공식 parity 판정은 보류한다.

### 1,000MW 기준의 해석

`max_validation_mae_mw: 1000`은 2026-07-26 승격 보호를 처음 도입할 때 설정됐다. 당시 직전 28일 실제 서빙 MAE는 560.0MW였고, stage snapshot의 raw 모델 MAE는 910.8MW였다. 따라서 1,000MW는 당시 분포에 여유를 둔 운영 품질 상한으로는 설명할 수 있지만, 통계적 신뢰구간이나 장기 계절 분포에서 계산된 불변 기준은 아니다.

후보 temporal replay의 MAE와 실제 as-served MAE는 입력 기상과 후처리 조건이 다르므로 직접 같은 숫자로 취급하지 않는다. 예를 들어 2026-08-10의 실제 서빙 MAE는 1,730.2MW였지만, 이 값만으로 후보의 temporal gate를 통과 또는 탈락시키지 않는다. 대신 해당 날짜는 현재 Champion이 정상 품질 범위를 벗어났다는 운영 health 근거로 사용한다.

따라서 1,000MW를 단순히 높여 모든 후보를 통과시키지 않는다. 이 값은 temporal replay의 안전 상한이자 운영 critical 기준으로만 사용하고, 750MW는 중간 운영 승격 목표로 둔다. 최종 성공 기준은 동일 forecast vintage에서 TEPCO 대비 비열등 또는 우위를 증명하는 것이다.

다음 비교 조건을 추가한다.

- 같은 train cutoff로 재학습한 Champion 계약보다 전체 MAE가 최소 5% 좋아야 한다.
- 핵심 구간의 MAE 또는 shape가 Champion보다 5% 넘게 악화되면 자동 승격하지 않는다.
- 평균 drift 900MW, 시간 최대 drift 2,500MW 이하는 다른 gate 통과 시 자동 승격할 수 있다.
- drift 상한을 넘으면 `rejected`가 아니라 `shadow_required`로 분류한다.

## 성능 저하 Champion 판정

다음 무결성 조건 중 하나를 만족하면 즉시 `champion_degraded_review_required` 상태로 전환한다.

- artifact의 `trainingCutoff`이 없거나 검증할 수 없음
- artifact의 config fingerprint가 현재 inference 계약과 불일치
- artifact 호환성 또는 원본 commit 추적이 불완전

다음 성능 조건 중 두 개 이상이 연속 두 번의 주간 평가에서 재현되면 Champion을 `champion_degraded`로 판정한다.

- 28일 as-served MAE가 900MW 또는 WAPE가 2.7%를 초과
- 최근 14일 MAE가 이전 28일 기준보다 15% 이상 악화
- 오전, 낮, 늦은 오후, 비영업일 중 하나의 MAE가 1,500MW를 초과
- 같은 조건의 temporal replay에서 Challenger가 Champion 계약보다 전체 MAE를 8% 이상 개선
- 모델 우세 시간 비율이 장기간 35% 미만으로 떨어짐. TEPCO는 이 조건의 진단 benchmark일 뿐 승격 target이 아니다.

성능 저하 판정은 새 모델의 자동 승격을 의미하지 않는다. 정상 경로만으로는 기존 모델을 안전하게 교체할 수 없음을 나타내는 운영 상태다.

28일 as-served MAE가 1,000MW 또는 WAPE가 3.0%를 초과하면 연속 두 번을 기다리지 않고 즉시 critical degraded review를 시작한다.

## 복구 승격 경로

Champion이 `champion_degraded`일 때 Challenger는 절대 상한을 일부 넘더라도 다음 조건을 모두 만족하면 통제된 복구 후보가 될 수 있다.

- 동일 temporal replay에서 Champion 대비 전체 MAE와 WAPE를 각각 최소 8% 개선
- 최대 오차와 shape delta MAE가 Champion보다 5% 넘게 악화되지 않음
- 영업일, 비영업일, 오전, 낮, 늦은 오후, 저녁 중 어떤 핵심 구간도 Champion보다 MAE가 5% 넘게 악화되지 않음
- 현재 Champion의 취약 구간 중 하나 이상을 10% 이상 개선
- 56일과 84일 보조 창에서 전체 MAE가 Champion보다 악화되지 않음
- frozen-origin replay에서 데이터 coverage가 완전하고 동일 방향의 개선이 확인됨
- 최소 72개 forecast-hour shadow와 2개 확정 운영일에서 치명적 회귀가 없음
- artifact 저장·재로드, train cutoff, config fingerprint, rollback artifact 검증을 통과

복구 승격은 자동으로 실행하지 않는다. 결과를 `recovery_candidate_ready`로 기록하고 명시적인 운영 검토 후 `recovery_promoted`로 전환한다.

기본 구현은 이 근거를 `metrics/model_shadow_evaluation.json`에서 읽는다. `artifactSha256`은 보존된 shadow artifact, metadata, 이전 승격 보고서와 모두 일치해야 한다. 파일 누락·오래된 근거, 72시간 미만 또는 확정 2일 미만이면 `shadow_required`로 멈추며 일반 승인 환경변수만으로 우회할 수 없다. 승인은 새로 재학습한 후보가 아니라 검증된 바로 그 shadow artifact를 승격한다.

### 운영자 승인 긴급 복구

기존 Champion을 계속 유지하는 것 자체가 별도로 확인된 무결성·성능 위험일 때만 긴급 복구를 허용한다. 이 경로는 자동이 아니며 `python/eval/promote_recovery_candidate.py`와 명시적 복구 승인을 사용한다.

- 기존 Champion은 이미 degraded 상태이고 학습 cutoff 누락, config fingerprint 불일치 같은 artifact 무결성 결함이 있어야 한다.
- 정확한 v14 artifact가 28일 MAE와 WAPE를 v11 대비 각각 8% 이상 개선하고, 문서화된 취약 구간 중 하나 이상을 10% 이상 개선해야 한다.
- v13은 배포된 적 없는 참고 후보이므로, 28일·56일·84일 모두에서 v13 MAE와 WAPE를 악화시키지 않아야 한다. 별도의 5% 추가 개선 기준은 요구하지 않는다.
- 56일·84일 보조 창에서 v11 전체 MAE와 WAPE를 악화시키지 않아야 한다.
- artifact 저장·재로드 호환성과 오늘/내일 48시간 유한값 smoke test를 통과해야 한다.
- 자동 drift 한도를 넘으면 별도 `--allow-large-drift` 결정이 필요하며 수치와 이유를 승격 리포트에 기록해야 한다.
- 원자적 교체 전에 이전 Champion artifact와 metadata를 rollback 경로로 복사해야 한다.
- 승격 전 shadow를 생략한 대신 72시간 안정화 감시를 강제하고, 최소 48시간 확정 실적에서 유의한 퇴행이 보이면 rollback 검토를 시작한다.

이 경로는 결함 있는 Champion이 무기한 남는 정책 실패를 해소할 뿐, 운영 품질이나 TEPCO 동등성을 인증하지 않는다.

## Prediction Drift 처리

Prediction drift는 변화량 위험 지표이며 정확도 지표가 아니다.

- drift가 기준 이하이면 정상 자동 승격 조건 중 하나로 사용한다.
- drift가 기준을 넘지만 과거 holdout에서 오차를 줄였다면 `shadow_required`로 전환한다.
- 특정 시간의 큰 drift가 실제 오차 감소 방향인지, shape를 새로 왜곡하는지 frozen-origin replay에서 확인한다.
- drift만을 이유로 더 나쁜 Champion을 무기한 유지하지 않는다.

## 승격 후 감시와 롤백

- 이전 Champion artifact와 metadata를 최소 한 번의 안정화 기간 동안 보존한다.
- 새 Champion 배포 후 이전 Champion의 shadow 예측도 3개 확정 운영일까지 유지한다.
- 48개 이상 확정 시간에서 새 Champion MAE가 이전 Champion shadow보다 10% 이상 나쁘거나, 핵심 구간 MAE가 10% 이상 악화되면 rollback 검토를 시작한다.
- 데이터 출처, artifact 호환성 또는 예측 coverage 오류는 성능과 관계없이 즉시 rollback 사유다.
- rollback 결과와 원인은 `metrics/model_promotion.json`의 이력에 보존한다.

## 승격 리포트 계약

`metrics/model_promotion.json`은 최소한 다음을 보존해야 한다.

- 현재 Champion 버전, artifact SHA, train cutoff, config fingerprint
- Challenger 버전과 동일 항목
- 28/56/84일 Champion 대 Challenger 지표
- as-served Champion health와 취약 구간
- absolute gate와 recovery gate 결과
- prediction drift와 처리 결과
- `promoted`, `rejected`, `shadow_required`, `champion_degraded`, `recovery_candidate_ready`, `recovery_approval_rejected`, `recovery_promoted`, `rolled_back` 상태
- 마지막 정기 평가 결과와 다음 평가 시각

평가 요일이 아닌 ETL의 `not_scheduled` 결과가 마지막 정기 평가의 상세 내용을 덮어쓰면 안 된다.

## 현재 프로젝트에 대한 적용 판단

- v14 `q025_q50_q975_p95_v14_daily_level_calibration`을 학습 cutoff 2026-08-19로 생성해 2026-08-21 JST에 격리 staging에서 복구 승격했다. 원격 data 배포는 별도 운영자 작업이다.
- 최종 artifact는 v11 시간별 booster 4개를 바이트 수준으로 그대로 보존하고 비영업일 q50과 일간 레벨 보조 모델만 추가한다. 폐기한 전체 재학습 후보와 독립 D+1 모델은 포함하지 않는다.
- 동일 cutoff v14 MAE는 28일 1142.5MW, 56일 972.0MW, 84일 871.5MW였다. v11 대비 각각 8.29%, 3.36%, 3.27% 개선했고 미배포 v13 참고 계약도 악화시키지 않았다.
- 최신 `origin/data` 캐시 기준 오늘·내일 prediction drift는 평균 104.4MW, 최대 208.8MW여서 override가 필요하지 않았다. 오늘은 전날 확정 실측 23시간과 마지막 한 시간 fallback을 사용했고, coverage가 부족한 다음날은 v11과 정확히 같았다.
- staging artifact SHA-256은 `77a35437305d60de841d2277bc2ed636878f0170a2386d727312397ba1b8a3d3`, v11 rollback SHA-256은 `28b75352b8b13713aba04880111dd11b3450864a3580f355081072af4266a640`이다.

## 구현 상태

- 구현 완료: 동일 cutoff v11/v13/v14 replay, 절대/recovery gate, degraded health, 28/56/84일 검사, drift 분기, `lastEvaluation`, shadow/rollback artifact 보존, fail-closed 기본 shadow 승인, 명시적 긴급 복구 승인.
- 구현 완료: append-only matched-vintage 캡처, 120초 이내 과거 동일 실행 가져오기, lead bucket 지표, 날짜 block bootstrap.
- 수집 중: 28/84일 matched-vintage 이력. 완료 전 `forecast_accuracy.json`은 최신값 기반 운영 참고치로만 사용한다.
- 운영자 게시 전 남은 작업: 격리 staging의 정확한 artifact와 report를 data branch에 게시한다. 게시 후 72시간 안정화, 이전 Champion shadow 비교, 최소 48시간 확정 실적에서 유의한 퇴행이 확인될 때 rollback 검토를 시작한다.
