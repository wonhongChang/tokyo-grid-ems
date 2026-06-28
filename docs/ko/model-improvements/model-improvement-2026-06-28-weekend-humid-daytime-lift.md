# 2026-06-28 주말 습도 기반 낮 시간 리프트

언어: [English](../../en/model-improvements/model-improvement-2026-06-28-weekend-humid-daytime-lift.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-28-weekend-humid-daytime-lift.md)

## 배경

2026-06-27 토요일 예측은 전체적으로 나쁘지 않았습니다. 일간 MAE 기준으로 모델이 TEPCO보다 좋았고, 실제값도 모두 p95 밴드 안에 있었습니다. 반면 2026-06-28 일요일 예측은 다른 주말 약점을 드러냈습니다.

- 새벽~이른 오전은 당일 실측이 충분히 들어오기 전이라 낮게 잡혔습니다.
- 오전 램프가 회복된 뒤에도 12:00-15:00 JST 낮 시간 선이 계속 낮았습니다.
- 습도는 높았지만 `cooling_delta_24h` 기준으로는 충분히 더운 날로 분류되지 않아 기존 비영업일 낮 리프트가 켜지지 않았습니다.

TEPCO 값은 진단용 외부 기준으로만 사용했습니다. 모델 입력이나 보정에는 섞지 않습니다.

## 변경 사항

### 비영업일 낮 리프트의 residual 반응 분리

`intraday_correction.daytime_sustained_underforecast_lift`에 비영업일 전용 residual 반응 파라미터를 추가했습니다.

- `non_business_residual_pressure_shrinkage`
- `non_business_residual_slack_mw`

평일 제어기는 그대로 유지하면서, 주말 낮 시간에는 실제 잔차가 연속으로 양수일 때 조금 더 직접적으로 반응할 수 있게 했습니다.

### 주말 대상 시간과 습도 조건 재조정

비영업일 target window를 `[14, 15]`에서 `[12, 13, 14, 15]`로 확장했습니다.

습도/불쾌지수 조건도 극단적인 습한 날 전용에서 중간 정도 습한 날까지 포착하도록 낮췄습니다.

- `non_business_min_discomfort_index`: `74.0 -> 70.0`
- `non_business_min_humidity_pct`: `90.0 -> 85.0`

단, 여전히 당일 실측 residual 근거가 있어야 작동하므로 모든 주말 낮 예측을 무작정 올리는 구조는 아닙니다.

## 검증

2026-06-28 일요일 패턴을 재현하는 회귀 테스트를 추가했습니다.

- 비영업일
- 오전 램프 구간에서 반복되는 양수 residual
- 불쾌지수 70 전후와 85% 이상의 습도
- 강한 양수 `cooling_delta_24h`는 없는 상황

기대 동작은 12:00-14:00 JST 예측이 residual-pressure 경로로 보수적으로 상향되고, 평일 동작은 그대로 유지되는 것입니다.

대상 테스트:

```powershell
python -m pytest tests/test_intraday_correction.py -q
```

결과: `65 passed`.

## 운영 메모

이 레이어는 TEPCO 추종이 아닙니다. 반복된 당일 실측 과소예측을 근거로 주말 낮 수요가 너무 낮게 남는 경우만 보정합니다.

다음 관찰 포인트:

- 일요일 낮 WAPE가 개선되는지
- 더 시원한 주말에 과하게 들어 올리지 않는지
- 06:00-07:00 JST 구간은 별도의 사전 주말 ramp prior가 필요한지
- 주말 낮 램프 주변 p95 밴드가 과하게 넓거나 좁지 않은지
