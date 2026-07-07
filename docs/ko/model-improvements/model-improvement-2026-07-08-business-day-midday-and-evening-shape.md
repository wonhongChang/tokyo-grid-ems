# 2026-07-08 영업일 점심/저녁 Shape 제어 보강

## 배경

2026-07-07 운영일은 영업일 shape 전체가 흔들린 케이스였습니다. 일간 리포트는 22:00, 23:00이 아직 TEPCO forecast fallback 행이었기 때문에 비교 가능한 관측 22시간 기준으로 집계되었습니다.

관측 점수:

| 지표 | 모델 | TEPCO |
| --- | ---: | ---: |
| MAE | 427.1 MW | 215.0 MW |
| WAPE | 1.43% | 0.72% |
| RMSE | 479.7 MW | 289.5 MW |
| 우위 시간 | 5 / 22 | 17 / 22 |

주요 오차:

| 시간 | 실측 | 모델 | 오차 | 진단 |
| --- | ---: | ---: | ---: | --- |
| 12:00 | 33,630 MW | 34,420.9 MW | +790.9 MW | lag/recent 영업일 shape는 하락을 가리켰지만 점심 dip 감쇠가 부족했습니다. |
| 16:00 | 34,420 MW | 33,670.2 MW | -749.8 MW | 오래된 음수 residual이 첫 번째 오후 미래 구간을 과도하게 눌렀습니다. |
| 21:00 | 29,510 MW | 30,549.0 MW | +1,039.0 MW | 강한 저녁 하락 국면에서 raw level이 recent same-business anchor보다 높게 남았습니다. |

## 변경 사항

- 영업일 `midday_transition_guard`의 `shrinkage`를 `0.5`에서 `0.75`로 강화했습니다.
  - 음수 lag/recent shape 근거가 있을 때만 작동하므로 고정 점심 dip을 만드는 방식은 아닙니다.
- `negative_residual_near_term_floor.actual_reference_slack_mw`를 `500`에서 `150`으로 줄였습니다.
  - 오래된 음수 residual이 첫 번째 근거리 미래 구간을 최신 실측 레벨보다 과도하게 아래로 밀지 못하게 합니다.
  - 실측이 이미 강하게 하락하고 lag/recent shape도 하락을 지지하는 경우에는 기존 decline-support damping이 복원량을 제한합니다.
- `evening_decline_continuity_guard`의 대상에 21시를 추가했습니다.
- 저녁 guard 내부에 `strong_decline_level_anchor`를 추가했습니다.
  - `lag_24h_hourly_delta`와 `recent_same_business_type_delta_mean`이 모두 강한 저녁 하락을 가리킬 때, level-overhang cap이 최신 실측 레벨 대신 recent same-business anchor를 더 신뢰할 수 있게 했습니다.
  - 기상 allowance는 유지하여 실제로 더운 저녁 수요를 무조건 누르지 않도록 했습니다.

## 기대 효과

2026-07-07 스냅샷 기준 근사 재생 결과:

- 16:00 근거리 과도 하방 보정은 약 `-750 MW`에서 약 `-390 MW` 수준으로 완화됩니다.
- 21:00 강한 하락 국면 overhang은 약 `+1,039 MW`에서 약 `+560 MW` 수준으로 줄어듭니다.
- 12:00은 intraday 이후가 아니라 사전 shape 단계에서 처리되므로, 다음 예측 재생성부터 강화된 midday guard 설정이 반영됩니다.

## 검증

- `python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py::test_midday_transition_guard_dampens_unsupported_noon_jump tests/test_adjustment.py::test_midday_transition_guard_uses_lower_recent_quantile_when_same_day_softens tests/test_adjustment.py::test_midday_transition_guard_does_not_use_quantile_without_same_day_softening -q`
- 결과: `79 passed`

## 메모

이번 변경은 TEPCO 예측값을 모델 입력으로 사용하지 않습니다. TEPCO는 비교 기준으로만 유지합니다. 제어 근거는 당일 실측 residual, recent same-business anchor, lag/recent shape delta, weather allowance입니다.
