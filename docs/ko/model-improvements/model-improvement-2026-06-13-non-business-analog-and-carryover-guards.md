# 2026-06-13 비영업일 analog 및 carryover 가드

Languages: [English](../../en/model-improvements/model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md)

## 문제

2026-06-13 토요일 서빙 차트에서는 서로 다른 두 가지 비영업일 shape 문제가 드러났습니다.

- 오전 raw LightGBM 자체가 가장 큰 문제는 아니었습니다. analogous-day 보정이 08:00-13:00을 약 500-1,100MW 낮추면서, 실제로 상승하던 토요일 수요 곡선을 더 낮게 만들었습니다.
- 16:37 JST 기준으로 intraday residual correction은 낮 시간대 과소예측 때문에 약 +963MW의 양수 base adjustment를 만들었습니다. 이 carryover가 18:00에 약 +815MW, 19:00에 약 +750MW까지 남아 있었지만, 주말 저녁의 lag/recent shape는 그 정도 반등을 강하게 지지하지 않았습니다.

## 변경 사항

- `PostHolidayTimeBandGuard`에 `non_business_analog_downshift_guard`를 추가했습니다.
  - 비영업일에만 적용합니다.
  - 07:00-13:00에서 lag/recent same-business delta 또는 anchor 문맥이 raw ramp를 지지할 때, analog 보정의 큰 음수 shift가 raw 흐름을 지워버리지 못하게 제한합니다.
  - 기본 최대 하방 shift 허용폭은 300MW입니다.
- `IntradayResidualCorrector`에 `non_business_evening_positive_residual_damping`을 추가했습니다.
  - 현재는 비영업일 18:00-20:00에만 적용합니다.
  - lag/recent delta가 반등을 강하게 설명하지 못할 때만 양수 intraday residual carryover를 감쇠합니다.
  - 16:00-17:00은 반응성을 유지하고, 리드가 더 긴 저녁 overhang을 주로 제어합니다.
- calibration metadata를 추가했습니다.
  - `nonBusinessEveningPositiveResidualDampingApplied`
  - `nonBusinessEveningPositiveResidualDampingFactor`
  - `nonBusinessEveningPositiveResidualDampingMaxMw`
  - `residualCarryoverByHour`의 시간별 support delta 및 감쇠 MW 필드

## 기대 효과

2026-06-13 공개 calibration snapshot에 새 규칙을 메모리에서 적용했을 때 다음 변화가 확인되었습니다.

- 08:00-13:00 pre-calibration 라인이 강하게 낮아진 analog 라인보다 raw LGBM에 가까워졌습니다.
- 최근 observed residual이 analog 하방 shift로 과장되는 정도가 줄어, intraday base adjustment가 약 +963MW에서 약 +913MW로 낮아졌습니다.
- 18:00-19:00 양수 carryover가 각각 약 425MW, 391MW 줄었습니다.

이 변경은 TEPCO 추종이 아닙니다. TEPCO는 진단 기준으로만 보며, 실제 가드는 raw, analog, lag, recent same-business shape, observed residual 신호로만 작동합니다.

## 검증

```text
tests/test_adjustment.py + tests/test_intraday_correction.py: 92 passed
```

추가한 단위 테스트는 다음을 확인합니다.

- ramp support가 있는 토요일 오전 analog downshift 제한
- 실제로 하락 shape인 주말 오후 analog downshift 유지
- 비영업일 저녁의 약한 shape support 구간에서 양수 residual carryover 감쇠
