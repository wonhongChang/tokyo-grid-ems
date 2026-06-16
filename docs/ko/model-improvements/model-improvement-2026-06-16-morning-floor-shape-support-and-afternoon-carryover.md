# 2026-06-16 오전 floor shape 지지와 오후 carryover 감쇠

언어: [English](../../en/model-improvements/model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md)

## 문제

2026-06-16 서빙 차트에서는 서로 다른 두 가지 컨트롤러 문제가 드러났습니다.

- 10시 부근에서는 `morning_observed_anchor_cap`이 약한 음수 잔차에도 너무 강하게 반응해, 공개 예측선을 이후 재계산선보다 낮게 눌렀습니다.
- 11시 부근에서는 `morning_observed_ramp_floor`가 당일 실측 램프를 강하게 보고 가까운 미래 구간을 과하게 들어 올렸습니다. 하지만 해당 목표 시간의 `lag_24h_hourly_delta`와 `recent_same_business_type_delta_mean`은 그 정도 상승을 지지하지 않았습니다.
- 오후에는 12~14시에 쌓인 양수 intraday 잔차가 15~19시로 전파되었고, 목표 시간대의 lag/recent shape 지지가 약하거나 음수인 구간에서도 상방 압력이 남았습니다.

10~11시의 최종 재계산 raw/pre-calibration 선은 실제 수요에 훨씬 가까웠습니다. 따라서 이번 문제는 LightGBM 원천 곡선만의 문제가 아니라, 컨트롤러 간 충돌과 예측선 보존 정책이 결합된 문제로 판단했습니다.

## 변경

- `morning_observed_anchor_cap.min_latest_overforecast_mw`를 `200 MW`에서 `500 MW`로 올렸습니다.
  - 작은 최신 잔차만으로는 큰 오전 anchor cap이 가까운 미래를 자르지 못하게 했습니다.
- `morning_observed_ramp_floor`에 `max_floor_delta_over_support_mw`를 추가했습니다.
  - 실제 오전 램프가 강하면 floor는 계속 작동합니다.
  - 다만 floor가 사용하는 시간당 상승폭은 목표 시간의 `lag_24h_hourly_delta` / `recent_same_business_type_delta_mean` 지지값에 작은 여유폭을 더한 수준으로 제한됩니다.
  - 이렇게 해서 11시가 최근 관측 slope만 따라 과도하게 튀는 것을 막습니다.
- `afternoon_positive_residual_carryover_damping`을 추가했습니다.
  - 양수 residual carryover만 감쇠합니다.
  - 운영 설정에서는 영업일에만 작동하도록 제한해, 비영업일 저녁 전용 가드와 중복 감쇠되지 않게 했습니다.
  - base adjustment가 양수이고, 15~19시 목표 시간의 lag/recent shape 지지가 약할 때만 작동합니다.
  - raw 모델 자체를 직접 cap하지 않고, TEPCO 예측을 보정 타깃으로 쓰지도 않습니다.

## 기대 효과

2026-06-16 패턴 기준으로는 다음을 기대합니다.

- 10시는 약한 잔차에 의해 성급하게 아래로 잘리는 위험이 줄어듭니다.
- 11시는 당일 램프 실측을 반영하되, 목표 시간대 shape 지지를 넘어 과하게 들어 올리는 일을 줄입니다.
- 15~19시는 오후/저녁 shape 지지가 약할 때 이전 시간의 양수 잔차가 그대로 얹히는 현상이 줄어듭니다.

이번 변경은 보수적입니다. 컨트롤러가 만든 울퉁불퉁한 sawtooth를 줄이는 것이 목적이며, 모든 낮 시간대 raw 모델 오차를 해결했다고 보지는 않습니다.

## 검증

```text
tests/test_intraday_correction.py::test_intraday_correction_caps_observed_morning_ramp_floor_by_target_shape_support
tests/test_intraday_correction.py::test_intraday_damps_afternoon_positive_carryover_when_shape_support_is_weak

Full suite: 398 passed
```
