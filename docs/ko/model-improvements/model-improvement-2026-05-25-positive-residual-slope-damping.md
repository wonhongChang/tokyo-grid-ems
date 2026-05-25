# 2026-05-25 양수 잔차 슬로프 감쇠
> 양수 residual이 가까운 미래 피크를 과하게 들어올리지 않도록 실측 기울기를 함께 보는 intraday 보정입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md)

---

## 왜 필요한가

2026-05-25 월요일 예측에서는 12~15시 구간의 곡선 왜곡 위험이 드러났습니다.

원천 모델은 12~14시, 특히 점심 하락 이후의 복귀 수요를 낮게 보았습니다. 그 결과 intraday residual 보정에서 양수 `base_adjustment_mw`가 커졌습니다. 양수 residual 자체가 문제는 아닙니다. 실제 관측값이 모델보다 높으면 미래 예측을 일부 올리는 것은 필요합니다.

문제는 실측 수요의 상승세가 이미 둔화되고 있고 residual도 개선되는 상황에서도, 그 양수 residual이 다음 피크 시간대로 그대로 이월되었다는 점입니다.

즉 14시 전까지는 낮게 보다가, 15시에는 반대로 너무 높게 밀어 올리는 controller overshoot가 발생했습니다.

## 변경 내용

intraday 보정 레이어에 `positive_residual_slope_damping`을 추가했습니다.

이 레이어는 raw LightGBM 예측을 직접 수정하지 않습니다. 이미 관측되었거나 freeze된 과거 예측선도 건드리지 않습니다. 오직 미래 시간으로 넘어가는 양수 residual carry-over의 강도만 줄입니다.

다음 조건을 모두 만족할 때만 평가됩니다.

- residual 보정값이 양수이고 충분히 큼
- 실제 관측 residual이 최소 3개 이상 있음
- 최신 관측 시간이 설정된 기준 시간 이후임
- 최근 3개 residual이 모두 양수임
- 최신 residual이 직전 residual보다 개선됨
- 최근 실측 수요가 하락 중이거나 뚜렷하게 상승 둔화 중임
- 최신 실측이 같은 영업 타입 anchor 근처에 있음
- residual 적용 후 미래 예측이 최신 실측/anchor 기준보다 허용폭 이상 높아짐

## 운영 파라미터

기본 설정:

- `min_reference_hour`: 12
- `max_lead_hours`: 3
- `min_base_adjustment_mw`: 300
- `min_positive_residual_mw`: 300
- `min_residual_improvement_mw`: 300
- `min_slope_deceleration_mw`: 500
- `drop_slope_threshold_mw`: 300
- `latest_slope_max_mw`: 400
- `anchor_proximity_tolerance_mw`: 1200
- `peak_excess_allowance_mw`: 300
- `damping_factor`: 0.4

조건을 만족하는 가까운 미래 시간의 양수 residual 보정은 다음처럼 약해집니다.

```text
base_adjustment_mw * decay_per_hour^(lead_hours - 1) * positive_residual_slope_damping_factor
```

## 진단 메타데이터

보정 metadata에 다음 필드가 추가됩니다.

- `positiveResidualSlopeDampingApplied`
- `positiveResidualSlopeDampingFactor`
- `positiveResidualSlopeDampingMaxMw`
- `positive_residual_slope_damping_triggered` (`appliedRegimeReason`)
- `residualCarryoverByHour`: 시간별 decay, damping factor, 최종 residual 보정값

운영 calibration의 시간별 진단 행에도 `residualCarryover`가 붙습니다. 이를 통해 어느 intraday 실행이 어떤 미래 시간대를 얼마나 밀었는지 추적할 수 있습니다.

## 테스트

다음 회귀 테스트를 추가했습니다.

- 월요일 오후 상승 둔화 상황에서 양수 residual carry-over가 감쇠되는 케이스
- 실제 수요가 계속 강하게 상승하고 residual도 악화 중이면 양수 residual을 보존하는 케이스
