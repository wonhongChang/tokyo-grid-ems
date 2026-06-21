# 2026-06-21 비영업일 shape와 저녁 carryover

언어: [English](../../en/model-improvements/model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md)

## 문제

2026-06-21 일요일 서빙 예측은 하나의 residual loop 실패라기보다, 시간대별로 서로 다른 문제가 섞인 케이스였다.

- 오전: 06:00은 약 `1.37 GW` 과소예측이었다. `lag_24h_hourly_delta`와 `recent_same_business_type_delta_mean`은 평탄하거나 완만한 하락 정도만 지지했는데, 예측선은 05:00에서 06:00으로 과하게 꺾였다.
- 오후: 14:00-15:00은 과소예측이었다. raw LightGBM 레벨은 더 가까웠지만 `analog_adjusted`가 비영업일 오후를 과하게 낮췄다. 기존 비영업일 analog downshift guard는 13:00까지만 보므로 오후 plateau를 보호하지 못했다.
- 저녁: 18:00-19:00은 약하게 높았다. 17:01 실행에서 14:00-16:00 과소예측 residual이 저녁으로 이월됐지만, non-business evening damping의 진입 기준이 조금 높아 작동하지 않았다.

TEPCO 예측은 분석용 외부 비교로만 사용했다. 보정 입력으로는 사용하지 않는다.

## 변경

- `PostHolidayTimeBandGuard`에 `non_business_morning_shape_floor_guard`를 추가했다.
  - 비영업일 오전 전환 구간에서만 작동한다.
  - forecast slope가 lag-24h 및 최근 같은 영업형태 slope 지지와 충돌하는지 본다.
  - 근거 없는 급락만 shrinkage와 lift cap 안에서 완화한다.
- `non_business_analog_downshift_guard` 범위를 07:00-13:00에서 07:00-15:00으로 확장했다.
  - raw 수요가 최근 비영업일 anchor 근처에 있을 때 오후 plateau를 analog 하방 shift로 지우지 않게 한다.
  - anchor가 plateau를 지지하지 않는 하락형 오후에는 기존처럼 analog 하방 shift를 유지할 수 있다.
- `non_business_evening_positive_residual_damping.min_base_adjustment_mw`를 `500 MW`에서 `350 MW`로 낮췄다.
  - 오후 과소예측 residual이 극단적이지 않아도 저녁 carryover 브레이크가 걸릴 수 있게 한다.
- AI 운영 리포트 feature catalog에 새 가드명을 추가했다.

## 리스크 제어

- 오전 가드는 06:00 값을 고정하지 않는다. 최근 비영업일 shape 근거와 맞지 않는 깊은 trough만 제한한다.
- 오후 analog guard는 raw 예측이 비영업일 anchor보다 충분히 높거나 lag/recent delta가 하락을 지지하면 하방 shift를 그대로 허용한다.
- 저녁 수정은 양수 residual carryover만 감쇠한다. raw 모델 자체를 직접 낮추지는 않는다.

## 검증

```text
tests/test_adjustment.py::test_guard_lifts_non_business_morning_shape_floor_when_drop_is_unsupported
tests/test_adjustment.py::test_guard_caps_non_business_afternoon_analog_downshift_when_anchor_supports_plateau
tests/test_adjustment.py::test_guard_keeps_non_business_analog_downshift_without_shape_support
tests/test_intraday_correction.py::test_intraday_damps_non_business_evening_positive_carryover_when_shape_is_weak
```
