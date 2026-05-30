# 2026-05-30 음수 잔차 연속성 floor
> 비영업일에 초반 음수 잔차가 평평한 당일 수요 곡선을 최신 실측 레벨보다 과하게 낮추지 못하게 막는 intraday 보정 가드입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md)

---

## 왜 필요했나

2026-05-30 토요일 실시간 예측에서는 2026-05-29 저녁 케이스와 반대 방향의 controller overshoot가 보였습니다.

모델은 오전 후반 일부 구간을 과대예측했고, intraday 보정은 그 음수 잔차를 오후로 이월했습니다. 그런데 11:00-13:00 부근의 당일 실측 수요는 더 내려가는 흐름이 아니라 거의 평평한 plateau였습니다. 이 상태에서 음수 잔차가 가까운 오후 예측선을 최신 실측 plateau보다 아래로 밀어 14:00-16:00 과소예측을 만들었습니다.

## 변경 내용

intraday 보정 레이어에 `negative_residual_continuity_floor`를 추가했습니다.

가드는 좁은 조건에서만 동작합니다.

- 기본적으로 비영업일에만 적용
- 충분한 당일 실측 이력이 있을 때만 평가
- 최신 실측 기울기와 평균 기울기가 평평하거나 강한 하락이 아닐 때만 적용
- 가까운 미래 bucket에만 적용
- 최신 실측 기준의 보수적 floor를 지키는 데 필요한 만큼만 복원
- 설정된 가드 범위 밖의 생산 동작을 자동으로 바꾸지 않음

## 운영 파라미터

기본 설정:

- `target_hours`: 10-17
- `min_reference_hour`: 10
- `max_lead_hours`: 2
- `latest_slope_min_mw`: -300
- `mean_slope_min_mw`: -300
- `floor_slack_mw`: 500
- `floor_slope_fraction`: 0.25
- `max_floor_slope_mw`: 300
- `max_restore_mw`: 900
- `min_restore_mw`: 100

## 진단 메타데이터

보정 metadata에 다음 필드를 기록합니다.

- `negativeResidualContinuityFloorApplied`
- `negativeResidualContinuityFloorMaxRestoreMw`
- 시간별 `negativeResidualContinuityFloorMw`
- 시간별 `negativeResidualContinuityRestoreMw`

이 필드는 운영 리포트 fact packet에도 압축해 전달하므로, AI 리포트가 residual overshoot와 raw 모델 bias를 구분할 수 있습니다.

## 테스트

초반 음수 잔차가 14시 예측을 최신 실측 수요 문맥보다 과하게 낮추는 2026-05-30형 토요일 plateau 회귀 테스트를 추가했습니다.
