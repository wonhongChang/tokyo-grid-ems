# 2026-06-05 오전 양수 잔차 carryover 감쇠

## 문제

2026-06-05 실전 예측에서는 전날의 warm-lag 과반응과 다른 실패 패턴이 드러났습니다.

- 07:00-08:00 실측 수요가 모델 예측보다 빠르게 상승했습니다.
- Intraday 보정은 이 과소예측을 양수 잔차 신호로 해석했습니다.
- 하지만 그 양수 잔차가 10:00-13:00까지 그대로 이월되면서, 이미 램프업이 둔화된 시간대까지 예측선을 밀어 올렸습니다.
- 이후 실행에서는 과대예측을 감지해 잔차가 음수로 돌아섰지만, 10:00-11:00 공개 예측선은 published forecast freeze 정책 때문에 화면에 그대로 남았습니다.

## 변경

`intraday_correction`에 `morning_positive_residual_carryover_damping` 레이어를 추가했습니다.

이 가드는 raw LightGBM 예측값을 직접 덮어쓰지 않습니다. 다음 조건이 동시에 맞을 때만 양수 intraday carryover 일부를 감쇠합니다.

- 영업일 오전 문맥,
- 강한 당일 실측 램프 때문에 양수 잔차가 생김,
- 대상 시간이 10:00-13:00,
- 대상 시간이 최소 2시간 이상 앞의 근거리 미래,
- `lag_24h_hourly_delta`와 `recent_same_business_type_delta_mean`이 더 이상 강한 상승 램프를 지지하지 않음.

## 운영 효과

초반 오전 과소예측이 점심 전후 plateau/dip 시간대까지 기계적으로 전파되는 것을 줄입니다. 반대로 target slot 자체가 강한 램프업 근거를 갖고 있으면 보정은 개입하지 않습니다.

## 진단 메타데이터

운영 보정 스냅샷에 다음 필드를 추가했습니다.

- `morningPositiveResidualCarryoverDampingFactor`
- `morningPositiveResidualCarryoverDampedMw`
- `morningPositiveResidualCarryoverSupportDeltaMw`

AI 운영 리포트 fact packet에도 이 신호를 포함해, 향후 리포트가 raw 모델 오차, residual carryover 과전파, published freeze 영향을 분리해서 설명할 수 있게 했습니다.

## 검증

- 2026-06-05 유형의 회귀 테스트를 추가했습니다.
- 강한 램프 근거가 있는 경우 감쇠하지 않는 bypass 테스트를 추가했습니다.
- `tests/test_intraday_correction.py`: 41 passed.
