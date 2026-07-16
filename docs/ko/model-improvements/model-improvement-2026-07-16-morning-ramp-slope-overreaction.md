# 2026-07-16 오전 ramp slope 과반응 가드

언어: [English](../../en/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md)

## 배경

2026-07-16 차트에서 반복적으로 보이던 09:00 JST 튐 문제가 다시 드러났습니다. 10:00-12:00 구간은 실제에 가까웠지만, 09:00만 과하게 위로 튀었습니다.

최종 진단 기준 핵심 행은 다음과 같습니다.

| 시각 | 실측 | 보정 전 예측 | 오차 | 예측 증가폭 | lag24 증가폭 | 최근 같은 영업 타입 증가폭 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 08:00 | 41,540 MW | 42,369.9 MW | +829.9 MW | +7,275.7 MW | +6,120.0 MW | +4,867.5 MW |
| 09:00 | 45,800 MW | 48,196.1 MW | +2,396.1 MW | +5,826.2 MW | +4,760.0 MW | +3,863.8 MW |
| 10:00 | 47,790 MW | 49,695.6 MW | +1,905.6 MW | +1,499.5 MW | +2,060.0 MW | +1,486.2 MW |

이번 문제는 intraday 잔차 보정이 9시를 끌어올린 케이스가 아닙니다. raw/pre-calibration 단계에서 이미 08:00 -> 09:00 ramp를 과하게 본 것이 핵심입니다. 기존 guard들은 당일 실측이 충분히 쌓인 뒤에는 방어할 수 있지만, 09:00처럼 관측 전 또는 관측 직전 서빙되는 shape spike에는 공백이 남아 있었습니다.

## 변경

기존 `localized_shape_spike_guard.morning_spike` 경로를 실제 운영 config에서 켜고, 별도의 `slope_overreaction` 모드를 추가했습니다.

새 모드는 다음 조건이 모두 맞을 때만 작동합니다.

- 대상 시간이 오전 ramp 구간(`08:00-10:00`)일 것
- 모델의 시간당 예측 상승폭이 클 것
- 그 상승폭이 lag/recent same-business shape support보다 충분히 클 것
- 기온 또는 불쾌지수 변화가 warm-up regime을 가리킬 것
- 하루 전체를 누르지 않고 인접 예측 시간 기준으로 국소 cap을 적용할 수 있을 것

운영 config:

```yaml
localized_shape_spike_guard:
  morning_spike:
    enabled: true
    hours: [8, 9, 10]
    neighbor_buffer_mw: 400
    shrinkage: 0.75
    max_reduction_mw: 1400
    slope_overreaction:
      enabled: true
      min_forecast_delta_mw: 4000
      min_forecast_delta_over_support_mw: 900
      min_weather_delta_c: 1.5
      min_discomfort_delta: 2.0
      max_weather_delta_c: 6.0
```

## 안전장치

이 guard는 TEPCO 예측값을 입력으로 사용하지 않습니다. 모델 자신의 예측 기울기, 내부 lag/recent-business shape 신호, 기상/불쾌지수 변화만 비교합니다.

또한 2026-07-15처럼 09:00 ramp가 크지만 실제로 잘 맞았던 cooler morning 회귀 테스트를 추가했습니다. 기상/불쾌지수 조건이 warm-ramp 과반응을 가리키지 않으면 guard가 꺼진 상태를 유지합니다.

## 검증

- `python -m pytest tests/test_adjustment.py tests/test_intraday_correction.py tests/test_run_batch.py -q`
- `python -m py_compile python\forecast\adjustment.py python\etl\run_batch.py`

결과:

- `191 passed`
