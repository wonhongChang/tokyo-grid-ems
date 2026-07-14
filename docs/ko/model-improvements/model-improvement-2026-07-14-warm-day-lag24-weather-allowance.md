# 2026-07-14 warm-day lag24 cap 기상 허용폭 보강

언어: [English](../../en/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md)

## 배경

2026-07-14 실시간 예측선에서 인위적인 오전/낮 shape 단절이 보였습니다.

- 09:00은 약 46.1GW로 높게 유지
- 10:00은 약 42.8GW까지 강제로 하락
- 11:00~12:00도 낮게 눌림
- 13:00은 다시 약 50.3GW로 점프

문제는 intraday residual carryover가 아니었습니다. 09:32 JST 보정 스냅샷 기준 residual 보정은 약 -194MW에 불과했습니다. 실제 shape 단절은 그 이전 단계인 `PostHolidayTimeBandGuard`에서 발생했습니다.

근본 원인은 고정형 warm-day `lag24_warm_day_cap`이었습니다.

```text
max forecast = lag_24h + 2500 MW
```

이 cap은 모델이 따뜻한 날에 과반응할 때는 유효하지만, 오늘이 전날보다 몇 도 이상 더 더운 경우에는 너무 경직됩니다. 2026-07-14 오전은 전날 대비 냉방 delta가 대략 +3.8C~+5.2C였고, 08:00 실측도 모델보다 낮지 않았습니다. 그런데 고정 cap은 더 시원했던 전날 수요를 상한 anchor처럼 사용하면서 10~12시를 잘못 눌렀습니다.

## 변경 내용

warm-day lag24 cap에 기상 기반 허용폭을 추가했습니다.

```text
max forecast =
  lag_24h
  + lag24_warm_day_max_increase_mw
  + min(weather_delta_c * allowance_per_c, max_weather_allowance)
```

운영 설정:

| Config key | 값 |
| --- | ---: |
| `lag24_warm_day_max_increase_mw` | `2500` |
| `lag24_warm_day_weather_allowance_mw_per_c` | `1200` |
| `lag24_warm_day_max_weather_allowance_mw` | `5000` |

기상 delta는 다음 냉방 관련 신호 중 가장 강한 값을 사용합니다.

- `temp_delta_24h`
- `cooling_delta_24h`
- `apparent_cooling_delta_24h`

## 기대 효과

전날보다 훨씬 더운 영업일에는 cap이 10~12시에 가짜 골짜기를 만들지 않습니다. cap 자체는 여전히 남아 있으므로 극단적인 예측은 제한하지만, 상한선이 실제 냉방 부하 레짐 변화에 맞춰 넓어집니다.

즉 기존 안전장치는 유지하되, 어제가 오늘의 공정한 상한 anchor가 아닌 날에는 고정 lag 상한이 예측선을 망가뜨리지 않게 합니다.

## 검증

- `python -m pytest tests/test_adjustment.py`

결과:

- `53 passed`

추가 회귀 테스트는 2026-07-14 패턴을 반영합니다. 허용폭이 없으면 10:00 예측이 약 42.8GW 근처로 눌리지만, 허용폭 적용 후에는 raw/analog 수준을 유지해 인위적인 dip을 만들지 않습니다.
