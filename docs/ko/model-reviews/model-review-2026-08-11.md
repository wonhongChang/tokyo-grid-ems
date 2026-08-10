# 2026-08-11 모델 운영 점검표

언어: [English](../../en/model-reviews/model-review-2026-08-11.md) / [日本語](../../ja/model-reviews/model-review-2026-08-11.md)

작성일: 2026-08-10 JST  
점검 예정: 2026-08-11 오전 ETL 완료 후  
상태: 점검 전

## 1. 점검 목적

이번 점검은 최근 며칠을 모아 평가한 뒤 적용한 변경이 오히려 운영 예측을 악화시킨 사례가 두 번 반복된 상황에서 수행한다.

이번에는 다음 원칙을 고정한다.

- 데이터가 모였다는 이유만으로 수정하지 않는다.
- 전체 평균 개선만으로 날짜별, 시간대별 형상 회귀를 덮지 않는다.
- 실제 게시된 served forecast를 기준으로 평가한다.
- `raw model`, 후처리, Intraday, Freeze 영향을 분리한다.
- TEPCO 예측은 외부 비교 기준일 뿐 피처, 보정값, 정답 대용으로 사용하지 않는다.
- 합격 기준은 결과를 본 뒤 완화하지 않는다.
- 원인이 확정되지 않으면 기존 Champion을 유지한다.

## 2. 사전 고정 사실

- 현재 운영 Champion: v11 lag24 residual ensemble
- 현재 Challenger 계약: v13 transition cooling blend
- 2026-08-04 평가에서 v13은 84일 게이트를 통과했지만 최근 28일 MAE가 `1,036.6 MW`로 상한 `1,000 MW`를 넘어서 승격되지 않았다.
- 2026-08-11은 화요일이지만 일본 공휴일 `山の日`이다.
- 2026-08-11은 반드시 `is_holiday=1`, `is_non_business_day=1`로 처리되어야 한다.
- 차트의 12시 bucket은 `12:00~13:00` 수요를 의미한다.
- 평일 점심 dip은 고정 하락값이 아니다. 최근 영업일 shape가 하락을 지지하고 forecast가 이를 무시할 때만 Midday Guard가 개입한다.
- 비영업일에는 Midday Guard가 작동하지 않는 것이 정상이다.

## 3. 평가 대상

### 3.1 확정 실측 구간

| 구간 | 날짜 | 목적 |
|---|---|---|
| 평일 | 2026-08-05~2026-08-07 | 평일 기본 shape, 오전 ramp, 점심 dip, 오후/저녁 평가 |
| 주말 | 2026-08-08~2026-08-09 | 비영업일 q50 및 주말 shape 평가 |
| 평일 복귀 | 2026-08-10 | 비영업일에서 영업일로 전환되는 lag 오염과 복귀 ramp 평가 |
| 공휴일 예측 | 2026-08-11 | 화요일 공휴일 캘린더, 비영업일 경로, 점심 guard 우회 확인 |

2026-08-11의 최종 정확도는 2026-08-12 ETL 이후 별도로 확정한다.

### 3.2 장기 회귀 구간

- 최근 확정 28일: 정확히 `28 x 24 = 672`시간
- 최근 확정 84일: 정확히 `84 x 24 = 2,016`시간
- 영업일, 비영업일, 영업 타입 전환일을 별도 집계
- 최근 구간과 장기 구간에서 오차 방향이 반대이면 전체 평균으로 상쇄하지 않음

## 4. 점검 전 데이터 무결성

아래 항목 중 하나라도 실패하면 모델 비교를 중단하고 데이터 문제부터 해결한다.

- [ ] 로컬 ETL 최종 상태가 성공이며 실행 시각이 기록되어 있다.
- [ ] `data` 브랜치에 최신 ETL 커밋이 존재한다.
- [ ] 2026-08-10 actual JSON이 24시간이며 `actualMw` 결측이 없다.
- [ ] 확정 실측에 `tepco_forecast_fallback`이 actual로 섞이지 않았다.
- [ ] 2026-08-10 일일 리포트와 내부 진단 JSON이 생성됐다.
- [ ] 2026-08-11 forecast와 forecast snapshot이 존재한다.
- [ ] 모델 artifact와 metadata의 버전, 학습 종료일, interval version이 일치한다.
- [ ] 기상 데이터에 비정상적인 source 전환, NaN, 장시간 forward-fill이 없다.
- [ ] GitHub Actions와 Pages 장애로 served forecast snapshot이 누락된 시간을 표시한다.
- [ ] 누락된 stage snapshot과 actual coverage를 혼동하지 않는다.

### 데이터 상태 기록

| 항목 | 결과 | 근거 파일/커밋 | 판정 |
|---|---|---|---|
| ETL |  |  |  |
| Actual 24h |  |  |  |
| Weather source |  |  |  |
| Forecast snapshots |  |  |  |
| Model metadata |  |  |  |
| Actions/Pages |  |  |  |

## 5. 날짜별 운영 성능

각 날짜는 서로 다른 코드나 config로 생성됐을 수 있다. 반드시 해당 날짜의 snapshot과 적용 버전을 함께 기록한다.

| 날짜 | Day type | Model/Config | MAE | WAPE | RMSE | Bias | Max error | TEPCO MAE | 비고 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-05 | 영업일 |  |  |  |  |  |  |  |  |
| 2026-08-06 | 영업일 |  |  |  |  |  |  |  |  |
| 2026-08-07 | 영업일 |  |  |  |  |  |  |  |  |
| 2026-08-08 | 주말 |  |  |  |  |  |  |  |  |
| 2026-08-09 | 주말 |  |  |  |  |  |  |  |  |
| 2026-08-10 | 영업 복귀 |  |  |  |  |  |  |  |  |

### 필수 판정

- [ ] 하루 전체가 같은 방향으로 치우친 날짜를 식별했다.
- [ ] 오차 부호가 반복해서 바뀌는 shape 불안정 날짜를 식별했다.
- [ ] TEPCO dominance hours는 참고 지표로만 기록했다.
- [ ] 최근 변경 전후 날짜를 같은 운영 버전으로 오해하지 않았다.
- [ ] 날짜별 최악 구간과 최대 오차 원인을 별도로 기록했다.

## 6. 시간대별 평가

| 시간대 | 핵심 질문 | Model MAE/WAPE | Shape delta error | 판정 |
|---|---|---:|---:|---|
| 00~05 | 날짜 경계 carryover와 lag24가 기저를 띄우거나 누르는가 |  |  |  |
| 06~11 | 오전 ramp가 울퉁불퉁하거나 한 방향 편향인가 |  |  |  |
| 12 | 평일 점심 dip이 근거에 맞게 작동하는가 |  |  |  |
| 13~16 | 점심 이후 rebound와 국소 spike가 왜곡되는가 |  |  |  |
| 17~19 | 퇴근/기온 하강 구간의 과대 반등이 있는가 |  |  |  |
| 20~23 | 야간 하락과 23시 fallback 경계가 안정적인가 |  |  |  |

## 7. 평일 점심 dip 전용 감사

평가 날짜: 2026-08-05, 2026-08-06, 2026-08-07, 2026-08-10

### 7.1 캘린더와 입력

- [ ] 대상 날짜의 `is_non_business_day`가 0이다.
- [ ] `business_midday_x_lag_24h_delta` 값을 기록했다.
- [ ] `business_midday_x_recent_delta_mean` 값을 기록했다.
- [ ] `business_midday_x_recent_delta_q25` 값을 기록했다.
- [ ] `business_midday_x_same_day_recent_delta_mean` 값을 기록했다.
- [ ] lag/recent shape가 실제로 하락 근거를 제공했는지 확인했다.

### 7.2 단계별 형상

| 날짜 | Actual 11->12 | Actual 12->13 | Raw 11->12 | Midday delta | Pre-calibration | Served | 판정 |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-05 |  |  |  |  |  |  |  |
| 2026-08-06 |  |  |  |  |  |  |  |
| 2026-08-07 |  |  |  |  |  |  |  |
| 2026-08-10 |  |  |  |  |  |  |  |

### 7.3 정상 판정 기준

- 최근 영업일 shape가 충분히 하락하지 않으면 고정 dip을 만들지 않는다.
- 최근 shape가 명확히 하락하고 forecast가 과도하게 높을 때만 설정된 cap과 shrinkage 안에서 하향한다.
- 12시 단발성 dip을 13시 이후의 지속 하락 추세로 전파하지 않는다.
- Intraday residual이 점심 shock를 오후 전체에 오염시키지 않는다.
- served forecast가 midpoint guard 결과와 다르면 Freeze 또는 이전 실행 snapshot 영향으로 분리한다.

## 8. 2026-08-11 공휴일 경로 점검

- [ ] `jpholiday`가 `山の日`으로 판정한다.
- [ ] `is_holiday=1`이다.
- [ ] `is_non_business_day=1`이다.
- [ ] 영업일 전용 q50/guard가 잘못 활성화되지 않는다.
- [ ] MiddayTransitionGuard가 우회된다.
- [ ] business return, business morning, business daytime interaction 값이 0 또는 비활성 상태다.
- [ ] non-business anchor와 lag mismatch가 정상적으로 구성된다.
- [ ] 2026-08-10 평일 lag가 공휴일 수요를 과도하게 끌어올리지 않는지 확인한다.
- [ ] 공휴일이라고 무조건 낮추는 고정 offset은 적용하지 않는다.

## 9. 단계별 원인 분해

각 문제 시간에 대해 다음 순서의 값과 delta를 기록한다.

1. `raw_lgbm`
2. `analog_adjusted`
3. `post_holiday_guarded`
4. `midday_guarded`
5. `localized_shape_guarded`
6. `pre_calibration`
7. Intraday residual correction
8. `served_forecast`
9. Published Forecast Freeze 차이

| 날짜/시간 | Raw | Analog delta | Guard delta | Intraday delta | Served | Actual | 주원인 단계 |
|---|---:|---:|---:|---:|---:|---:|---|
|  |  |  |  |  |  |  |  |

### 원인 분류

- `data_quality`
- `raw_model_level`
- `raw_model_shape`
- `weather_regime`
- `calendar_regime`
- `analog_adjustment`
- `shape_guard`
- `intraday_carryover`
- `freeze_artifact`
- `insufficient_evidence`

## 10. 예측 밴드 점검

- [ ] 날짜별 p95 coverage를 계산했다.
- [ ] 오전, 점심, 오후, 저녁 coverage를 분리했다.
- [ ] 밴드 중심선이 q50과 함께 이동하는지 확인했다.
- [ ] 최소 폭 때문에 과도하게 넓어진 구간을 확인했다.
- [ ] tail explosion cap에 걸린 시간을 기록했다.
- [ ] q025/q975 비대칭과 재균형 영향을 확인했다.
- [ ] 중심선 오류를 밴드 확대만으로 덮지 않는다.

| 구간 | Coverage | 평균 폭 | 최대 폭 | 이탈 방향 | 판정 |
|---|---:|---:|---:|---|---|
| 전체 |  |  |  |  |  |
| 00~05 |  |  |  |  |  |
| 06~11 |  |  |  |  |  |
| 12~16 |  |  |  |  |  |
| 17~23 |  |  |  |  |  |

## 11. Champion/Challenger 검증

### 11.1 비교 대상

- Champion v11
- Challenger v13
- 새 실험 후보는 v11/v13 원인 분해 이후에만 추가

### 11.2 고정 승격 게이트

| 항목 | 기준 | 결과 | 통과 |
|---|---:|---:|---|
| 28일 coverage | 672/672시간 |  |  |
| Baseline 대비 MAE 개선 | 20% 이상 |  |  |
| 28일 MAE | 1,000 MW 이하 |  |  |
| 28일 WAPE | 3.0% 이하 |  |  |
| Shape delta MAE | 750 MW 이하 |  |  |
| Max error | 6,500 MW 이하 |  |  |
| Segment MAE | 1,500 MW 이하 |  |  |
| Segment shape delta MAE | 1,100 MW 이하 |  |  |
| Segment MAE 회귀 | 10% 이하 |  |  |
| 오늘/내일 평균 drift | 900 MW 이하 |  |  |
| 오늘/내일 시간 최대 drift | 2,500 MW 이하 |  |  |

### 11.3 추가 회귀 구간

- [ ] 평일 연속일
- [ ] 평일에서 주말 전환
- [ ] 주말 연속일
- [ ] 주말/공휴일에서 영업일 복귀
- [ ] 평일 중간 공휴일
- [ ] 급격한 기온 상승일
- [ ] 급격한 기온 하락일
- [ ] 고습도/저습도 전환일

게이트 하나라도 실패하면 강제 승격하지 않는다.

## 12. 수정 허용 기준

### 즉시 수정 가능

- 날짜/공휴일 분류 오류
- actual source 오염 또는 결측 처리 오류
- 명백한 stage 순서 오류
- config가 코드에서 무시되는 결함
- metadata 또는 snapshot 기록 오류
- 동일 입력에서 재현 가능한 계산 버그

### 실험 후에만 수정 가능

- 특정 날짜의 MAE 악화
- 특정 시간대의 반복 shape 오차
- 새로운 학습 피처
- guard threshold, shrinkage, cap 변경
- lag blend weight 변경
- 밴드 폭 변경

### 금지

- TEPCO 예측을 보정 입력으로 사용
- 특정 날짜의 실측을 보고 해당 날짜 예측을 사후 맞춤
- `8월 10일 9시` 같은 날짜 고정 조건
- 합격을 위해 승격 임계값 완화
- 최근 며칠만 좋아지고 28/84일 또는 다른 레짐이 악화되는 변경
- 모델과 운영 후처리를 한 번에 바꾸고 효과를 합산해서 보고

## 13. 내일 추가 점검 등록란

내일 새 증거가 나오면 아래 표에 먼저 등록한 뒤 분석한다. 기존 합격 기준은 변경하지 않는다.

| 추가 점검 | 추가 이유 | 필요한 증거 | 결과 | 후속 조치 |
|---|---|---|---|---|
|  |  |  |  |  |

## 14. 검증 실행 기록

| 실행 | 명령/도구 | 시작 | 종료 | 결과 파일 | 상태 |
|---|---|---|---|---|---|
| Public data validation | `python scripts/validate_public_before_publish.py` |  |  |  |  |
| Python tests | `python -m pytest -q` |  |  |  |  |
| Operational replay 28d | 내부 evaluator |  |  | `metrics/operational_replay.json` |  |
| Challenger validation | 내부 promotion evaluator |  |  | `metrics/model_promotion.json` |  |
| Prediction drift | Champion/Challenger 48h |  |  |  |  |

## 15. 최종 결정

### 판정

- [ ] Champion 유지, 코드 변경 없음
- [ ] 데이터/운영 결함만 수정
- [ ] 후처리 후보를 shadow 검증으로 유지
- [ ] 모델 후보를 Challenger로 유지
- [ ] 모든 게이트 통과 후 승격

### 근거

- 핵심 원인:
- 변경이 필요한 이유:
- 변경하지 않는 영역:
- 회귀 검증 결과:
- 남은 위험:
- 다음 점검일:

### 배포 전 확인

- [ ] 사용자가 최종 변경 범위와 승격 여부를 확인했다.
- [ ] 모델 변경과 문서 변경이 일치한다.
- [ ] 공개 model-improvement 문서는 실제 코드 변경이 확정된 경우에만 작성했다.
- [ ] 비공개 점검 문서는 커밋 대상에 포함하지 않았다.
