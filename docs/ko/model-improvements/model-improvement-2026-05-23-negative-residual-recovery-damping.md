# 2026-05-23 음수 잔차 회복 감쇄
> 평일 lag 과열 뒤 비영업일 수요가 회복될 때, intraday 음수 잔차 이월을 약화하는 운영 보정입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md)

---

## 왜 필요했나

2026-05-23 토요일 라이브 예측에서는 비영업일 전환 prior를 추가한 뒤에도 다른 실패 패턴이 드러났습니다.

이른 오전에는 금요일 `lag_24h` 관성이 남아 있어 모델이 과대예측했습니다. 일반 intraday residual 보정은 이 오차를 보고 음수 보정을 만드는 것까지는 맞았습니다. 문제는 그 뒤였습니다. 실제 수요가 최근 같은 비영업일 anchor 쪽으로 빠르게 회복했는데도, 초반의 큰 음수 residual이 미래 시간까지 계속 이월되면서 이미 괜찮았던 raw 예측선까지 아래로 끌어내렸습니다.

이 문제는 특정 시간대의 문제가 아닙니다. residual 전파 문제입니다. 실측 흐름이 이미 회복을 증명했다면, 초반 음수 오차가 남은 시간 전체를 계속 지배하지 않도록 해야 합니다.

## 변경 내용

intraday 보정 레이어에 `negative_residual_recovery_damping`을 추가했습니다.

이 레이어는 raw LightGBM 예측값을 직접 수정하지 않습니다. 이미 계산된 음수 `base_adjustment_mw`가 미래 시간으로 이월되는 강도만 약화합니다.

다음 조건을 모두 만족할 때만 평가됩니다.

- 대상일이 비영업일입니다.
- 24시간 lag가 다른 영업/비영업 타입에서 왔습니다.
- residual 보정값이 음수입니다.
- 최근 실측 수요가 상승 중입니다.
- 최근 1시간 기울기 중 하나가 설정된 회복 기준을 넘습니다.
- 마지막 실측 수요가 같은 비영업일 anchor 근처까지 돌아왔습니다.
- 최근 residual이 명확히 개선 중입니다. 예: `-2400 -> -1600 -> -1100`

실측 수요가 올랐더라도 residual이 악화 중이면 이 레이어는 켜지지 않습니다. 진짜 낮은 수요일을 가짜 회복으로 오해하지 않기 위한 방어선입니다.

## 운영 파라미터

기본 설정:

- `recovery_slope_base_mw`: 1000
- `anchor_proximity_tolerance_mw`: 1200
- `damping_factor_default`: 0.4
- `damping_factor_strong`: 0.2
- `strong_recovery_mean_slope_mw`: 500

미래 시간의 보정은 다음 구조로 적용됩니다.

```text
base_adjustment_mw * recovery_damping_factor * decay_per_hour^(lead_hours - 1)
```

프로젝트 전체의 `max_abs_adjustment_mw` 상한은 이 레이어보다 먼저 적용됩니다. 기본 상한 기준으로 `-1200 MW`까지 잘린 residual에 strong recovery factor `0.2`가 적용되면, lead-time 감쇠 전 미래 보정은 `-240 MW`가 됩니다.

## 진단 메타데이터

보정 metadata에는 다음 값이 추가됩니다.

- `negResidualRecoveryDampingApplied`
- `negResidualRecoveryDampingFactor`
- `negative_residual_recovery_damping_triggered` (`appliedRegimeReason`)

이 필드로 intraday 레이어가 회복 중인 raw 예측선을 보존하기 위해 음수 residual 이월을 줄였는지 확인할 수 있습니다.

## 테스트

두 가지 회귀 테스트를 추가했습니다.

- 토요일 회복 케이스: 초반 음수 residual이 개선되고 실측 수요가 비영업일 anchor 쪽으로 회복하면 음수 residual 이월이 약화됩니다.
- 가짜 회복 방지 케이스: 실측 수요는 상승하지만 residual이 악화되면 감쇄 레이어가 켜지지 않습니다.
