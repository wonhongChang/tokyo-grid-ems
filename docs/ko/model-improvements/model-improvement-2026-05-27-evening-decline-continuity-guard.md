# 2026-05-27 저녁 하락 연속성 가드
> 당일 수요가 이미 하락 중일 때 가까운 미래 예측선이 비정상적으로 반등하는 것을 막는 intraday 보정 가드입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md)

---

## 왜 필요했나

2026-05-27 실시간 예측에서 저녁 시간대 shape risk가 확인되었습니다.

17시 기준 실측 수요는 직전 시간 대비 크게 하락했습니다. 당일 실측 기울기, `lag_24h_hourly_delta`, 최근 같은 영업일 시간대 변화량도 모두 유지 또는 하락 쪽을 가리키고 있었습니다. 그런데 18시 모델 예측선은 강하게 다시 반등했습니다.

이때 intraday residual carry-over는 작았기 때문에, 주원인은 residual 폭주가 아니었습니다. raw 모델 예측선과 daytime warm-day guard가 실제 저녁 하락 흐름이 확인된 뒤에도 가까운 미래 반등을 허용한 것이 핵심 위험이었습니다.

## 변경 내용

intraday 보정 레이어에 `evening_decline_continuity_guard`를 추가했습니다.

이 가드는 TEPCO 예측값을 추종하지 않고, 18시만 하드코딩해서 누르지도 않습니다. 당일 실측이 이미 명확한 저녁 하락 흐름을 보였고 내부 shape 신호가 반등을 지지하지 않을 때만 가까운 미래의 과도한 반등폭을 제한합니다.

다음 조건을 모두 만족할 때만 평가됩니다.

- 최신 실측 시간이 설정된 저녁 기준 시간 이후임
- 최신 당일 실측 기울기와 최근 평균 기울기가 명확히 음수임
- 보정 대상 시간이 가까운 미래 구간임
- `lag_24h_hourly_delta`와 `recent_same_business_type_delta_mean`이 상승을 지지하지 않음
- 직전 최종 예측값 대비 미래 예측 반등폭이 설정 임계값을 초과함
- 기상 allowance를 포함해도 상단 buffer를 넘어서는 반등임

2026-05-29에는 두 번째 저녁 실패 패턴도 확인되었습니다. 예측선이 직전 값 대비 반등하지는 않았지만, 당일 실측 수요가 이미 내려가는데 가까운 미래 예측 레벨 자체가 너무 높게 남아 있었습니다. 그래서 `level_overhang` 경로를 추가했습니다. 이 경로는 최신 실측 수요와 같은 영업일 anchor를 기준 레벨로 삼고, 허용 buffer를 넘는 초과분만 다음 1-2개 미래 bucket에서 보수적으로 줄입니다.

## 운영 파라미터

기본 설정:

- `target_hours`: 16-20
- `min_reference_hour`: 15
- `max_lead_hours`: 2
- `latest_slope_max_mw`: -500
- `mean_slope_max_mw`: -300
- `max_supporting_delta_mw`: 200
- `min_forecast_rebound_mw`: 800
- `max_rebound_mw`: 600
- `actual_reference_slack_mw`: 300
- `weather_allowance_mw_per_c`: 120
- `hot_temp_c`: 30.0
- `max_weather_allowance_mw`: 400
- `max_reduction_mw`: 900
- `min_reduction_mw`: 100
- `level_overhang_enabled`: true
- `min_level_overhang_mw`: 500
- `level_overhang_shrinkage`: 0.75

가드는 보수적으로 동작합니다. 전체 예측선을 강제로 내리는 것이 아니라, 허용 가능한 반등폭 또는 레벨 과열 초과분만 줄입니다. 더운 저녁의 실제 수요 증가를 과하게 누르지 않도록 기상 allowance도 함께 둡니다.

## 진단 메타데이터

보정 metadata에 다음 필드를 추가했습니다.

- `eveningDeclineContinuityGuardApplied`
- `eveningDeclineContinuityMaxReductionMw`
- `evening_decline_continuity_guard` (`appliedRegimeReason`)
- `residualCarryoverByHour`의 시간별 cap, mode, rebound, weather allowance, reduction 정보

운영 calibration snapshot summary에도 가드 적용 여부를 남겨, 일일 리포트에서 저녁 예측선이 왜 제한되었는지 추적할 수 있게 했습니다.

## 테스트

다음 회귀 테스트를 추가했습니다.

- 2026-05-27과 같은 저녁 하락 상황에서 18시 비정상 반등을 제한하는 케이스
- 2026-05-29와 같은 level-overhang 상황에서 로컬 반등이 없어도 가까운 미래의 높은 저녁 레벨을 제한하는 케이스
- lag와 같은 영업일 shape가 실제 반등을 지지하는 경우에는 가드가 개입하지 않는 케이스
