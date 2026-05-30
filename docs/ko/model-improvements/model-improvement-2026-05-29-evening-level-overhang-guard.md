# 2026-05-29 저녁 레벨 overhang 가드
> 로컬 반등 spike가 없어도 예측선이 저녁 하락 국면에서 높은 레벨로 계속 버티는 경우를 잡기 위한 evening decline continuity guard 확장입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md)

---

## 왜 필요했나

2026-05-29 확정 예측에서는 저녁 시간대 과대예측이 지속적으로 발생했습니다.

모델 일간 MAE는 `1106.2 MW`, TEPCO MAE는 `755.0 MW`였습니다. 가장 큰 오차는 저녁 하락 구간에 몰렸습니다.

| 시각 | 실측 MW | 모델 MW | 모델 오차 MW | TEPCO 오차 MW |
|---:|---:|---:|---:|---:|
| 15 | 35270 | 37451.7 | +2181.7 | +1040 |
| 16 | 34450 | 36690.0 | +2240.0 | +1170 |
| 17 | 33240 | 35375.0 | +2135.0 | +120 |
| 18 | 32520 | 34571.7 | +2051.7 | +200 |
| 19 | 31620 | 33686.6 | +2066.6 | +590 |

이는 2026-05-27의 저녁 rebound spike와는 다른 형태였습니다. 2026-05-29에는 예측선이 직전 값 대비 크게 튀지 않아도 이미 틀렸습니다. 당일 실측 수요가 내려가고 있는데 예측 레벨 자체가 계속 높게 남아 있었기 때문입니다.

## 원인

raw LightGBM 예측선과 warm-day 문맥이 저녁 시간대까지 높은 수요 관성을 너무 오래 유지했습니다. Intraday residual correction은 이미 강한 음수 보정을 적용하고 있었지만, 최종 서빙선은 여전히 당일 실측 하락 경로보다 위에 남았습니다.

기존 `evening_decline_continuity_guard`는 가까운 미래 예측이 `min_forecast_rebound_mw` 이상 반등할 때만 동작했습니다. 이 방식은 spike형 shape risk에는 효과적이었지만, 다음 조건의 high-level overhang은 잡지 못했습니다.

- 당일 실측 수요가 명확히 하락 중임
- 보정 대상이 가까운 미래 bucket임
- lag와 같은 영업일 delta가 상승을 지지하지 않음
- 최종 예측선이 최신 실측 및 같은 영업일 anchor 기준보다 크게 높게 남아 있음

## 변경 내용

`evening_decline_continuity_guard`에 두 번째 모드인 `level_overhang`을 추가했습니다.

기존 `rebound` 모드는 로컬 upward spike를 처리합니다. 새 `level_overhang` 모드는 높게 버티는 저녁 예측선을 처리합니다. 최신 실측 수요와 같은 영업일 anchor를 기준 레벨로 삼고, 허용 buffer를 넘는 초과분만 가까운 미래 bucket에서 줄입니다.

이 가드는 TEPCO 예측을 추종하지 않습니다. TEPCO 값은 사후 비교 지표로만 사용했습니다.

## 운영 파라미터

새로 추가하거나 조정한 설정:

- `min_reference_hour`: 15
- `level_overhang_enabled`: true
- `min_level_overhang_mw`: 500
- `level_overhang_shrinkage`: 0.75

기존 저녁 가드의 제한도 그대로 유지합니다.

- `target_hours`: 16-20
- `max_lead_hours`: 2
- `max_reduction_mw`: 900
- `actual_reference_slack_mw`: 300
- `temp_delta_1h` 기반 weather allowance

이렇게 해서 개입 범위를 가까운 미래로 제한하고 보수적으로 유지합니다. 전체 저녁 곡선을 강제로 내리는 것이 아니라, 하락이 확인된 뒤의 레벨 초과분만 줄입니다.

## 진단 메타데이터

시간별 calibration log에서 저녁 가드 모드를 구분합니다.

- `eveningDeclineContinuityMode`: `rebound` 또는 `level_overhang`
- `eveningDeclineContinuityCapMw`
- `eveningDeclineContinuityReductionMw`
- `eveningDeclineContinuityWeatherAllowanceMw`

이를 통해 Ops Report가 저녁 보정이 spike형 반등 때문인지, 높은 레벨 overhang 때문인지 구분해서 설명할 수 있습니다.

## 테스트

2026-05-29형 level-overhang 회귀 테스트를 추가했습니다.

- 저녁 실측 수요가 하락 중임
- 다음 예측 bucket이 로컬 반등하지 않음
- 서빙선이 허용 레벨 기준보다 높게 남아 있음
- 가드가 초과분을 줄이고 metadata에 `level_overhang`을 기록함
