# 모델 승격 관리와 데이터 출처 무결성

작성일: 2026-07-26 (JST)

## 개선 배경

기존에는 전체 ETL이 실행될 때마다 LightGBM을 다시 학습하고 기존 모델 파일을 즉시 덮어썼습니다. 학습 성공만으로는 새 모델이 평일, 비영업일, 시간대별 품질을 유지한다고 보장할 수 없었습니다. 시간별 캐시도 확정 실측과 TEPCO 예측 대체값을 명시적으로 구분하지 않았습니다.

## 검증 근거

2026-06-28부터 2026-07-25까지 28일, 672시간의 실제 서빙 예측을 리플레이한 결과입니다.

| 지표 | 결과 |
|---|---:|
| MAE | 560.0 MW |
| WAPE | 1.642% |
| RMSE | 761.7 MW |
| Shape delta MAE | 491.4 MW |
| P95 포함률 | 96.1% |
| 평균 P95 반폭 | 1,867.1 MW |

Stage snapshot이 존재하는 최근 13일에서는 Analog 보정이 raw 모델 MAE를 910.8MW에서 957.1MW로 악화시키고 shape 오차도 키웠습니다. 따라서 Analog 보정은 운영에서 끄되, stage 비교는 shadow 후보로 계속 측정합니다.

## 변경 내용

### Champion/Challenger 승격

- 일반 날짜의 전체 ETL은 현재 Champion을 유지합니다.
- 기본 후보 평가일은 월요일이며, `TOKYO_GRID_EMS_FORCE_MODEL_TRAIN`으로 명시적인 평가를 요청할 수 있습니다.
- 평가할 때마다 최근 확정 28일을 rolling window로 사용합니다. 28일마다 한 번 교체한다는 뜻이 아닙니다.
- Challenger는 baseline 개선뿐 아니라 절대 MAE, WAPE, 최대 오차, shape 오차, 영업 구분, 시간대별 상한을 모두 통과해야 합니다.
- 가까운 미래 예측선이 설정된 drift 한도를 넘게 바뀌면 승격을 거부합니다.
- 호환 가능한 Champion이 없어도 실패한 gate를 우회하지 않으며, 정상 baseline fallback을 사용합니다.
- 승격 결과와 메타데이터는 `metrics/model_promotion.json`에 기록합니다.

### 전력·기상 출처 무결성

- 시간별 캐시에 `actual_source`를 저장합니다.
- `tepco_forecast_fallback`은 필요한 lag 연속성 확보에만 사용합니다.
- 대체값은 학습 target, 당일 실측 slope, residual 보정, Analog residual, 검증 actual에서 제외합니다.
- 확정 CSV 실측은 항상 fallback보다 높은 우선순위를 갖습니다.
- 최근 시간의 예보 기상은 공식 관측이 도착하면 `AMEDAS_ACTUAL`로 교체합니다.

### 운영 리플레이

`metrics/operational_replay.json`에는 다음 내용이 기록됩니다.

- 실제 서빙 MAE, WAPE, RMSE, 최대 오차, shape 오차
- 영업일/비영업일 및 시간대별 지표
- TEPCO를 모델 입력으로 사용하지 않는 독립적인 참고 성능
- 날짜별 최신 snapshot 기준 stage 비교
- 밴드 포함률과 shadow 상태의 경험적 밴드 폭 권고값

Stage 비교는 날짜별 최신 snapshot을 사용하므로 모든 과거 Intraday 실행을 완전히 복원한 결과로 해석하면 안 됩니다.

### CI

새 CI workflow는 `main` push와 pull request에서 Python 전체 테스트와 React production build를 독립적으로 실행합니다.

## 롤백

- 긴급 우회가 명확히 필요한 경우에만 `model_promotion.enabled: false`를 사용합니다.
- `adjustment.analogous_day.enabled`는 영업 구분과 시간대별 리플레이에서 일관된 개선이 확인된 뒤 다시 켭니다.
- Challenger가 하나라도 gate를 통과하지 못하면 현재 Champion을 그대로 유지합니다.
