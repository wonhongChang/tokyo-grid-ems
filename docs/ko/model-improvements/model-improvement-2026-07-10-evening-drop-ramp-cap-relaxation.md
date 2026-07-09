# 2026-07-10 저녁 하락 구간 ramp cap 완화

언어: [English](../../en/model-improvements/model-improvement-2026-07-10-evening-drop-ramp-cap-relaxation.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-10-evening-drop-ramp-cap-relaxation.md)

## 배경

2026-07-09 예측은 저녁 후반 shape에서 문제가 컸다. 13:00-16:00 구간은 비교적 받아들일 수 있었지만, 21:00 예측은 당일 실측이 이미 하락하고 있었음에도 너무 높게 남았다.

중요한 점은 기존 하락 방어 로직이 아예 빠진 것이 아니었다는 점이다. 20:22 JST 운영 보정 스냅샷에서는 이미 다음 보정이 켜져 있었다.

- `afternoon_positive_residual_carryover_damping`
- `evening_decline_continuity_guard`

21:00의 pre-calibration 예측은 이미 낮은 저녁 경로에 가까웠고, evening decline guard도 추가로 값을 낮췄다. 하지만 마지막 `ramp_guard`가 직전 실측 수요를 기준으로 근거리 하한선을 강하게 적용하면서, 최종 서빙 예측선을 다시 끌어올렸다. 즉, 저녁 하락 가드는 제 역할을 했지만 마지막 ramp cap이 하락 폭을 지나치게 제한한 구조였다.

## 변경 내용

기존 observed-drop relaxation 경로 안에 `ramp_guard.observed_drop_relaxation.decline_support`를 추가했다.

이 규칙은 예측을 직접 낮추는 보정이 아니다. 아래 조건을 모두 만족할 때만 ramp guard의 drop cap을 조금 더 넓게 허용한다.

- 실측 수요가 이미 빠르게 하락해 `observed_drop_relaxation`이 활성화된 상태
- 예측 lead time이 최소 2시간 이상
- 영업일
- 대상 시간의 shape 신호가 모두 강한 하락을 지지
  - `lag_24h_hourly_delta`
  - `recent_same_business_type_delta_mean`

기본 운영 설정:

| Config key | 값 |
| --- | ---: |
| `enabled` | `true` |
| `business_day_only` | `true` |
| `min_lead_hours` | `2` |
| `max_support_delta_mw` | `-1000` |
| `max_decrease_mw_by_lead_hour` | `[1600, 4000, 5600]` |

## 기대 효과

저녁 실측이 이미 하락 중이고 대상 시간의 lag/recent shape도 하락을 가리킬 때, 마지막 ramp guard가 예측선을 직전 실측 수준으로 과하게 되돌리는 문제를 줄인다.

보수성은 유지한다.

- lead-1 예측은 기존 근거리 cap을 유지
- 비영업일에는 적용하지 않음
- lag와 최근 동종 영업일 shape가 모두 하락을 지지해야 함
- TEPCO 예측값은 입력 피처로 사용하지 않음

## 관측성

운영 보정 메타데이터에 다음 필드를 추가했다.

- `rampGuardDeclineSupportRelaxationApplied`
- `rampGuardDeclineSupportRelaxationMaxExtraDropMw`

AI 운영 리포트 fact packet에도 같은 제어 플래그를 노출한다. 이후 리포트는 "하락 가드가 꺼져 있었다"와 "하락 가드는 작동했지만 마지막 ramp cap이 서빙선을 제한했다"를 구분할 수 있다.

## 검증

- `python -m pytest tests/test_intraday_correction.py -k "ramp_guard_relaxes_drop_cap or ramp_guard_keeps_drop_cap or observed_demand_drop"`

결과:

- `3 passed`

## 메모

이 변경은 21:00 전용 하드코딩이 아니다. 실측 수요가 이미 하락하고 있고, 독립적인 lag/recent shape 신호가 강한 저녁 하락을 지지할 때만 마지막 cap을 완화하는 후처리 안전장치다.
