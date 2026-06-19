# 2026-06-19 낮 시간 지속 과소예측 리프트

언어: [English](../../en/model-improvements/model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md)

## 문제

2026-06-19 서빙 예측에서는 이전의 밴드 비대칭 문제와 다른 실패 모드가 드러났다. p95 밴드 재조정은 배포되어 반영됐지만, 더운 영업일 낮 구간에서 중앙 예측선(q50)이 계속 낮게 잡혔다.

- 10:00은 실측 대비 약 `-2.9 GW` 낮았다.
- 13:00은 실측 대비 약 `-2.2 GW` 낮았다.
- 16:00은 실측 대비 약 `-1.5 GW` 낮았다.

인트라데이 잔차 루프는 오차를 감지해 `baseAdjustmentMw`를 올렸지만, published forecast freeze 정책 때문에 이미 서빙된 시간대는 다시 쓸 수 없었다. 남은 문제는 밴드 폭이 아니라, 당일 실측이 지속적으로 모델보다 높은 상황에서 가까운 낮 시간대를 충분히 빠르게 들어 올리지 못한 점이었다.

## 변경

- 인트라데이 보정 레이어에 `daytime_sustained_underforecast_lift`를 추가했다.
- 리프트는 영업일 문맥, 최근 관측 시간의 지속적인 양수 잔차, 의미 있는 양수 `baseAdjustmentMw`, 더운 램프업 기상 문맥, 가까운 미래 시간대가 함께 맞을 때만 작동한다.
- 기본 적용 범위는 의도적으로 좁게 잡았다: `10:00-14:00`, 최대 lead `3`시간, 최대 lift `900 MW`.
- `daytimeSustainedUnderforecastLiftApplied`, `daytimeSustainedUnderforecastMaxLiftMw`, `residualCarryoverByHour`의 시간별 lift 진단값을 추가했다.

## 기대 효과

더운 영업일 램프업에서 모델이 실측보다 지속적으로 낮게 붙는 경우, 단순 잔차 carryover만 기다리지 않고 가까운 낮 시간대 예측을 더 빠르게 회복시킨다.

시원하거나 중립적인 날에는 작동하지 않아야 하며, TEPCO 예측을 추종하지 않는다. 이 레이어는 당일 실측 잔차와 기상/램프업 문맥만 사용하므로, 제3자 예측 혼합이 아니라 보수적인 운영 보정이다.

## 검증

```text
tests/test_intraday_correction.py::test_intraday_daytime_sustained_underforecast_lifts_hot_business_day_future
tests/test_intraday_correction.py::test_intraday_daytime_sustained_underforecast_requires_heat_context

Full suite: 404 passed
```
