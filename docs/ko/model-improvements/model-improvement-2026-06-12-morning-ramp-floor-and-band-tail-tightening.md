# 2026-06-12 오전 실측 램프 floor와 밴드 tail 축소

언어: [English](../../en/model-improvements/model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md)

## 문제

2026-06-11과 2026-06-12 서빙 데이터에서 두 가지 문제가 확인되었습니다.

- 2026-06-11 09:00-15:00은 공개 차트상 나빴지만, 최신 운영 재계산선은 이미 실측에 훨씬 가까웠습니다. 이 케이스는 주로 published forecast freeze 영향이었습니다.
- 2026-06-12 09:00-13:00은 재계산 기준으로도 낮았습니다. 당일 실측 수요가 이미 강한 오전 ramp를 보였지만, 기존 intraday 보정은 음수 residual carryover를 줄이는 데 집중되어 있어 관측된 ramp 궤적보다 낮은 근거리 미래 예측을 지지하지 못했습니다.
- 예측 밴드가 한쪽으로 과하게 벌어졌습니다. 여러 시간대에서 한쪽 폭은 500MW 근처로 붙고 반대쪽은 4,000MW까지 열려 p95/p99 밴드가 운영 검토용으로 보기 어려웠습니다.

## 변경 사항

- `IntradayResidualCorrector`에 `morning_observed_ramp_floor`를 추가했습니다.
- 이 floor는 영업일 오전 기준 구간에서 당일 실측이 두 시간 연속 강한 양의 기울기를 보였을 때만 켜집니다.
- 근거리 미래에만 적용하고 cap을 둡니다.
  - 기본 target hour: 08:00-11:00
  - 최대 lead: 2시간
  - 최대 lift: 1,200MW
  - 최소 lift: 100MW
- 운영 메타데이터를 추가했습니다.
  - `morningObservedRampFloorApplied`
  - `morningObservedRampFloorMaxLiftMw`
  - `morningObservedRampFloorLiftMw`
  - `morningObservedRampFloorMw`
  - `morningObservedRampLatestSlopeMw`
- interval sanity calibration을 조정했습니다.
  - `max_p95_half_width_mw`: 4,500 -> 3,000
  - `max_p95_asymmetry_ratio`: 4.0 -> 2.5
  - `asymmetry_reference_half_width_mw`: 1,000 -> 900

## 적용 범위

이 레이어는 TEPCO 추종도 아니고 특정 시간대 고정 lift도 아닙니다. 당일 실측이 이미 강한 오전 ramp를 증명했고, 바로 다음 1~2시간 예측이 보수적인 연장 floor보다 낮을 때만 작동합니다.

밴드 조정은 q50 예측선을 움직이지 않습니다. 드문 한쪽 quantile tail 폭주를 제한해서 대시보드 밴드가 운영자가 해석 가능한 형태로 유지되도록 합니다.

## 검증

```text
tests/test_intraday_correction.py: 46 passed
tests/test_lgbm_model.py + tests/test_run_batch.py: 72 passed
targeted smoke checks: 3 passed
```

추가 단위 테스트는 06:00-08:00 실측 ramp가 강할 때 09:00-10:00 근거리 예측만 제한적으로 lift되고, 관련 메타데이터가 기록되는지 확인합니다.

## 운영 메모

2026-06-12 14:00-15:00의 튐은 일부 freeze 문제였지만, 09:00-13:00 오차는 raw/recalculated 기준으로도 실제 과소예측이었습니다. 이번 변경은 근거리 실측 증거 공백을 줄이기 위한 조치이며, 오전 습도/불쾌지수/lag 과열 상호작용의 장기 백테스트 필요성을 대체하지 않습니다.
