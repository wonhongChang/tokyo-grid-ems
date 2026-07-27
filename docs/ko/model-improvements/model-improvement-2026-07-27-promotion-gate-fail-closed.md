# 모델 승격 게이트 Fail-Closed 보강

작성일: 2026-07-27 (JST)

## 장애

2026-07-27 07:31 JST의 정기 재학습에서 Challenger가 `promoted`로 기록됐지만, `predictionDrift.meanAbsDeltaMw`와 `maxAbsDeltaMw`가 `NaN`이었습니다. Python의 `NaN > threshold` 비교가 거짓이 되어 drift 상한을 우회했고, 비표준 JSON 토큰도 그대로 게시됐습니다.

추가 감사에서 다음 문제도 확인했습니다.

- 28일 검증이 672시간이 아니라 중복 timestamp를 포함한 696시간으로 집계됨
- Challenger 전체 학습에 target date의 부분 실측이 포함되어 metadata의 `trainingCutoff`이 2026-07-27로 기록됨
- 오늘·내일 drift가 실제 서빙과 다른 weather/lag cache로 계산됨
- lag-24 residual ensemble의 lag가 없으면 q50이 `NaN`이 될 수 있음

## 수정

- 승격 학습은 `target_date` 이전 행만 사용합니다.
- 저장된 hourly cache를 다시 로드해 timestamp당 한 행으로 정규화한 뒤 검증합니다.
- 28일 검증은 정확히 `28 × 24 = 672`시간이어야 합니다.
- drift는 실제 서빙과 같은 오늘·내일 weather/lag cache에서 48개 유한값을 요구합니다.
- 누락, `NaN`, `Infinity`가 하나라도 있으면 `prediction_drift_invalid`로 승격을 거부합니다.
- lag-24가 없는 시간은 residual ensemble 대신 독립 q50으로 안전하게 fallback합니다.
- public JSON은 `allow_nan=False`로 원자적 저장하며 게시 전 validator도 비유한 토큰을 거부합니다.
- 승격 artifact는 임시 파일로 저장·재로드 검증한 뒤에만 Champion 경로로 교체합니다.

## 실데이터 재검증

07:31 이전 Champion을 임시 복원하고 동일한 운영 데이터로 다시 실행했습니다.

| 항목 | 수정 전 | 수정 후 |
|---|---:|---:|
| 검증 시간 | 696 | 672 |
| Drift 유효 시간 | 48 중 일부 `NaN` | 48 / 48 |
| 평균 절대 drift | `NaN` | 1,104.4 MW |
| 최대 절대 drift | `NaN` | 4,763.6 MW |
| 최종 판단 | 잘못된 승격 | 거부 |

설정 상한은 평균 900MW, 시간 최대 2,500MW이므로 수정된 게이트는 `mean_prediction_drift_exceeded`와 `hour_prediction_drift_exceeded`를 기록하고 이전 Champion을 유지했습니다.

## 검증

- 전체 테스트: 480개 통과
- 실제 28일 temporal validation: 672시간 확인
- 실제 오늘·내일 drift: 48개 유한값 확인
- public artifact validation 통과

## 운영 원칙

비유한값과 불완전한 검증 coverage는 경고가 아니라 승격 거부 사유입니다. 모델 품질이 좋아 보이더라도 승격 계약을 우회하지 않습니다.
