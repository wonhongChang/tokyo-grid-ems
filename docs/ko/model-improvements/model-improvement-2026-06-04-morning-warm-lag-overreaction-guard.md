# 2026-06-04 오전 warm-lag 과반응 가드

> 따뜻해진 영업일 오전에 raw 모델이 lag/기상 상승 신호를 과하게 반영하고, 당일 실측은 그 수준을 확인해주지 않을 때 q50을 보수적으로 낮추는 intraday 가드입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)

---

## 현상

2026-06-04 라이브 예측에서는 영업일 오전 ramp 구간의 q50이 실제보다 높게 잡혔습니다. 이는 2026-06-03에 추가한 예측 구간 tail guard의 문제가 아닙니다. tail guard는 p95/p99 밴드 폭만 제한하며 q50 중심 예측선은 변경하지 않습니다.

raw LightGBM 예측은 전날 밤부터 이미 높은 상태였고, 당일 실측이 들어오면서 intraday residual 보정은 강한 음수로 바뀌었습니다. 다만 이미 게시된 시간대는 forecast freeze 정책으로 보존되므로 화면에는 과대예측이 남았습니다. 아직 닫히지 않은 가까운 오전 예측에는, lag/기상 상승 신호가 실측으로 확인되지 않을 때 추가 제동이 필요했습니다.

## 변경 내용

intraday 보정 레이어에 `morning_warm_lag_overreaction_guard`를 추가했습니다.

이 가드는 의도적으로 좁게 동작합니다.

- 설정된 오전 시간대에만 적용합니다.
- 영업일 문맥을 요구합니다.
- 당일 실측 기반 음수 residual 보정이 충분히 클 때만 작동합니다.
- `temp_delta_24h`, `cooling_delta_24h` 같은 warm-lag 신호를 요구합니다.
- 가까운 미래 시간대만 제어합니다.
- 이미 관측되었거나 freeze된 게시 예측선은 다시 쓰지 않습니다.

## 제어 방식

대상 시간에 대해 최신 실측 수요와 clipping된 당일 오전 slope로 상한선을 계산합니다.

post-calibration 예측선이 이 상한선보다 여전히 높게 남아 있으면, 초과분의 일부만 cap 범위 안에서 차감합니다. 따라서 TEPCO를 따라가는 규칙이 아니라, raw 모델의 과반응을 늦게라도 제동하는 장치입니다.

주요 설정:

```yaml
morning_warm_lag_overreaction_guard:
  enabled: true
  target_hours: [8, 9, 10, 11]
  min_base_adjustment_mw: 500
  min_temp_delta_24h_c: 2.0
  min_cooling_delta_24h_c: 0.8
  max_projected_slope_mw: 1800
  shrinkage: 0.75
  max_reduction_mw: 800
```

## 관측 가능성

운영 보정 JSON에 다음 필드를 남깁니다.

- `morningWarmLagOverreactionGuardApplied`
- `morningWarmLagOverreactionMaxReductionMw`
- `residualCarryoverByHour`의 시간별 cap/reduction 값
- `appliedRegimeReason`의 `morning_warm_lag_overreaction_guard`

운영 리포트 fact packet에도 새 가드를 feature catalog에 추가했습니다. 따라서 AI 리포트는 q50 warm-lag 과반응과 예측 밴드 문제를 구분해서 설명할 수 있습니다.

## 검증

다음 회귀 테스트를 추가했습니다.

- 2026-06-04와 유사한 따뜻해진 영업일 오전에서 가까운 미래 q50 과대예측을 낮추는지 검증
- 음수 residual은 있지만 warm signal이 약한 오전에는 가드가 작동하지 않는지 검증
