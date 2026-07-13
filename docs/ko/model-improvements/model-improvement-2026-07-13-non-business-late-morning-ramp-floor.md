# 2026-07-13 비영업일 늦은 오전 ramp floor 보강

언어: [English](../../en/model-improvements/model-improvement-2026-07-13-non-business-late-morning-ramp-floor.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-13-non-business-late-morning-ramp-floor.md)

## 배경

2026-07-10부터 2026-07-13까지 확인한 결과, 가장 명확하게 손댈 수 있는 실패는 2026-07-11 토요일이었습니다.

공개 데이터 기준 요약:

| 날짜 | 판단 |
| --- | --- |
| 2026-07-10 | 모델 MAE 383.8 MW, TEPCO MAE 375.0 MW. 거의 비슷했고, 오전 shape와 11시 과대예측이 아쉬웠습니다. |
| 2026-07-11 | 모델 MAE 639.3 MW, TEPCO MAE 316.7 MW. 00~10시 과소예측이 큰 명확한 실패였습니다. |
| 2026-07-12 | 모델 MAE 384.4 MW, TEPCO MAE 326.2 MW. 12~14시 비영업일 점심 과대예측이 주된 문제였습니다. |
| 2026-07-13 | 부분 실측 기준으로는 모델이 TEPCO보다 우세했고, 광범위한 즉시 수정은 필요하지 않았습니다. |

2026-07-11은 토요일 오전 ramp가 늦게 시작한 뒤 급하게 붙었습니다.

- 05:00 -> 06:00: +430 MW
- 06:00 -> 07:00: +2,430 MW
- 07:00 -> 08:00: +3,440 MW
- 08:00 -> 09:00: +3,250 MW

기존 `morning_observed_ramp_floor`는 최근 두 구간 slope가 모두 같은 기준을 넘어야 켜졌습니다. 주말처럼 생활/상업 ramp가 늦게 붙는 날에는 이 조건이 너무 엄격했습니다. 첫 slope는 약했지만 최신 slope는 이미 실제 수요 전환을 보여주고 있었기 때문입니다.

## 변경 내용

`morning_observed_ramp_floor`의 비영업일 경로에서, 설정으로 허용한 경우 최신 실측 slope를 floor 기준으로 사용할 수 있게 했습니다.

운영 설정은 다음과 같습니다.

| Config key | 값 |
| --- | ---: |
| `non_business_min_latest_slope_mw` | `2000` |
| `non_business_min_mean_slope_mw` | `1200` |
| `non_business_floor_basis` | `latest` |
| `non_business_floor_slope_fraction` | `1.0` |
| `non_business_max_lift_mw` | `700` |

가드는 여전히 좁게 작동합니다.

- 당일 실측이 실제로 쌓인 뒤에만 작동
- `max_lead_hours` 이내의 근거리 미래만 보호
- 최신 실측 시간이 이미 크게 과대예측 상태이면 작동하지 않음
- 대상 시간의 lag/recent shape support가 있어야 함
- 최종 lift는 `non_business_max_lift_mw`로 제한

## 주말 하드코딩이 아닌 이유

이 규칙은 토요일/일요일을 무조건 올리지 않습니다. 비영업일에서 당일 실측이 이미 강한 ramp를 증명했을 때만 floor 계산 기준을 최신 slope로 바꿉니다.

이번 패치는 2026-07-12의 비영업일 점심 과대예측을 넓게 누르는 cap을 추가하지 않았습니다. 7/12는 12~14시가 높은 반대 방향 문제였고, 이를 7/11 과소예측과 한 규칙으로 동시에 해결하려 하면 실제 주말 수요를 누를 위험이 큽니다. 먼저 확인된 늦은 ramp 과소예측을 보강하고, 점심 과대예측은 별도 관측 대상으로 남기는 편이 안전합니다.

## 관측성

시간별 residual 조정 행에 다음 필드를 추가했습니다.

- `morningObservedRampFloorBasis`

이를 통해 ramp floor가 일반 `mean` slope 기준으로 만들어졌는지, 비영업일용 `latest` slope 기준으로 만들어졌는지 추적할 수 있습니다.

## 검증

- `python -m pytest tests/test_intraday_correction.py -k "weekend_morning_ramp_floor or observed_morning_ramp_floor"`

결과:

- `5 passed`

추가 회귀 테스트는 다음을 확인합니다.

- 2026-07-11형 늦은 주말 ramp에서는 가까운 시간만 보수적으로 lift
- 2026-07-12형 약한 초반 ramp에서는 latest-slope floor가 작동하지 않음
