# 2026-07-16 저녁 ramp drop cap 재조정

## 배경

2026-07-15 예측은 오전부터 낮 피크까지는 전반적으로 나쁘지 않았지만, 저녁 구간에서 후처리 문제가 뚜렷하게 드러났다.

관측 완료 시간 기준 지표:

| 구간 | 모델 MAE | TEPCO MAE | 메모 |
| --- | ---: | ---: | --- |
| 전체 관측 구간 | 503.9 MW | 438.6 MW | 모델이 근소하게 열세 |
| 05:00-12:00 | 456.3 MW | 555.0 MW | 오전 블록은 모델 우세 |
| 17:00-20:00 | 1,038.6 MW | 500.0 MW | 핵심 실패 구간 |

가장 큰 오차는 18:00 JST였다.

| 시간 | 실측 | 모델 | 오차 | TEPCO |
| --- | ---: | ---: | ---: | ---: |
| 17:00 | 46,980 MW | 48,080 MW | +1,100 MW | 47,390 MW |
| 18:00 | 44,940 MW | 47,080 MW | +2,140 MW | 45,780 MW |

문제는 raw LightGBM spike가 아니었다. 18:04 JST 운영 보정 스냅샷에서 18:00의 pre-calibration 예측은 45,687.2 MW로 최종 실측에 훨씬 가까웠다. 하지만 마지막 단계의 `ramp_guard`가 16:00 실측을 기준으로 근거리 하한선을 강하게 적용하면서 최종 서빙선이 47,080 MW까지 다시 올라갔다.

## 변경 내용

마지막 ramp drop cap 완화 경로를 재조정했다.

```yaml
ramp_guard:
  observed_drop_relaxation:
    min_recent_drop_mw: 500
    decline_support:
      min_lead_hours: 1
      max_support_delta_mw: -900
      max_decrease_mw_by_lead_hour: [2600, 4800, 6500]
```

보수성은 유지했다.

- 당일 실측 수요가 이미 의미 있게 하락을 시작해야 한다.
- 대상 시간의 `lag_24h_hourly_delta`와 `recent_same_business_type_delta_mean`이 모두 하락을 지지해야 한다.
- TEPCO 예측값을 입력으로 사용하지 않고, 마지막 drop cap 허용폭만 넓힌다.

## 재현 결과

2026-07-15 18:04 JST 스냅샷을 새 설정으로 재현한 결과:

| 시간 | 기존 서빙선 | 재조정 후 | 최종 실측 |
| --- | ---: | ---: | ---: |
| 17:00 | 48,080.0 MW | 47,094.7 MW | 46,980 MW |
| 18:00 | 47,080.0 MW | 45,620.2 MW | 44,940 MW |
| 19:00 | 46,080.0 MW | 45,225.6 MW | 43,560 MW |

새 설정은 예측선을 16:00 실측 레벨 근처로 억지로 되돌리지 않고, 이미 확인된 저녁 하락 흐름을 보존한다.

## 검증

- `python -m pytest tests/test_intraday_correction.py -k "ramp_guard_relaxes_drop_cap or supported_evening_decline or ramp_guard_keeps_drop_cap or observed_demand_drop" -q`
- `python -m py_compile python\forecast\intraday_correction.py python\etl\run_batch.py`

결과:

- `4 passed`

## 메모

이번 변경은 신규 모델 피처가 아니라 후처리 안전장치 재조정이다. 당일 실측과 대상 시간 shape 신호가 모두 저녁 하락을 지지할 때, 마지막 ramp cap이 타당한 하락 경로를 다시 끌어올리는 문제를 줄이는 것이 목적이다.
