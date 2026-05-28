# 2026-05-27 오전 램프 연속성 가드
> 영업일 오전 수요 상승이 실측으로 확인된 뒤, 음수 잔차 이월이 가까운 미래 예측선을 비정상적으로 꺾지 못하게 하는 intraday 가드입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md)

---

## 왜 필요했나

2026-05-27 실시간 예측에서 오전 시간대 shape risk가 확인되었습니다.

영업일 오전 ramp 구간에서 당일 실측 수요는 초반부터 강하게 상승하고 있었습니다. 그런데 이전 시간대의 음수 intraday residual 보정이 가까운 미래 시간대로 이월되면서, 다음 예측 시간이 부자연스럽게 아래로 꺾이는 위험이 있었습니다.

이는 TEPCO 예측을 따라가야 하는 문제가 아니라 보정 제어의 연속성 문제입니다. 당일 실측이 강한 상승 ramp를 이미 증명했다면, 일시적인 음수 잔차가 근거리 예측 곡선을 깨뜨리지 않도록 해야 합니다.

## 변경 내용

intraday 보정 레이어에 `morning_ramp_continuity_guard`를 추가했습니다.

이 가드는 raw LightGBM 예측선을 원래 pre-calibration 값보다 높게 끌어올리지 않습니다. 최근 당일 실측이 강한 오전 ramp를 보일 때, 과도하게 적용된 음수 잔차의 일부만 되돌려 가까운 미래 예측선의 국소적인 꺾임을 완화합니다.

다음 조건에서만 평가됩니다.

- 당일이 영업일임
- base residual adjustment가 음수임
- 연속된 당일 실측 3개 이상이 존재함
- 최근 실측 기울기가 설정된 ramp 기준을 초과함
- 대상 시간이 설정된 오전 시간대에 포함됨
- 대상 시간이 가까운 lead-time 범위 안에 있음

## 운영 파라미터

기본 설정:

- `target_hours`: 6-11
- `min_reference_hour`: 7
- `max_lead_hours`: 2
- `min_recent_slope_mw`: 1000
- `min_mean_slope_mw`: 1000
- `floor_slope_fraction`: 0.25
- `max_floor_delta_mw`: 900
- `max_restore_mw`: 700
- `min_restore_mw`: 100

가드는 보수적으로 동작합니다. 새 수요를 임의로 추가하지 않고, raw 모델선 안에서 오전 ramp의 국소적인 연속성만 보호합니다.

## 진단 메타데이터

보정 metadata에 다음 필드를 추가했습니다.

- `morningRampContinuityGuardApplied`
- `morningRampContinuityMaxRestoreMw`
- `morning_ramp_continuity_guard` (`appliedRegimeReason`)
- 시간별 forecast delta, lag delta, same-day actual slope, residual adjustment, weather delta

## 테스트

다음 회귀 테스트를 추가했습니다.

- 영업일 오전 ramp가 강하게 확인된 상황에서 음수 잔차 이월로 인한 국소 꺾임을 완화하는 케이스
- 비영업일 또는 상승 근거가 부족한 상황에서는 가드가 개입하지 않는 케이스
