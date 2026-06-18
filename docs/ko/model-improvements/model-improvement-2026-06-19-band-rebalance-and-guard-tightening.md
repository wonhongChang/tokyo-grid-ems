# 2026-06-19 밴드 재정렬과 가드 조건 강화

언어: [English](../../en/model-improvements/model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md)

## 문제

2026-06-19 오전 예측에서 두 가지 운영상 문제가 드러났다.

- 09:00-11:00 p95 밴드가 한쪽으로 크게 쏠렸다. 예를 들어 09:00과 10:00은 q50 기준 대략 `-2250 / +500 MW` 형태라, 화면에서 밴드가 중앙 예측선을 자연스럽게 감싸지 못했다.
- 2026-06-18 10:00 서빙 스냅샷에서는 `morning_observed_ramp_floor`가 양수 residual carryover 위에 lift를 과하게 겹쳤다.
- 2026-06-18 오후 스냅샷에서는 당일 실측이 이미 회복 중인데도 `afternoon_observed_anchor_cap`이 14:00-16:00을 너무 눌렀다.

## 변경

- 극단적인 p95 비대칭을 재정렬하는 옵션을 추가했다. 전체 p95 폭은 유지하되, 한쪽 tail이 너무 작아질 때 하단/상단 half-width를 재분배한다.
- `morning_positive_residual_carryover_damping.weak_support_delta_mw`를 올려, 10:00-13:00 target slot의 lag/recent shape support가 약한 경우 양수 carryover를 더 자주 감쇠한다.
- `morning_observed_ramp_floor.max_floor_delta_over_support_mw`를 `0`으로 낮춰, floor가 target-hour lag/recent shape support를 넘어서 들어올리지 못하게 했다.
- `afternoon_observed_anchor_cap.max_latest_slope_mw`를 추가해, 최신 당일 실측 수요가 강하게 회복 중이면 cap을 건너뛰게 했다.

## 기대 효과

밴드 재정렬은 중앙 예측선(q50)을 바꾸지 않는다. 후처리로 q50이 이동했거나 quantile 한쪽 tail이 무너진 경우에도, 대시보드 밴드가 덜 비뚤어져 보이도록 만든다.

오전 ramp 보호는 유지하되, target slot의 lag/recent shape 근거가 약할 때 과하게 들어올리지 않는다. 오후 plateau cap도 유지하되, 명확한 당일 회복 slope와 싸우지 않도록 했다.

## 검증

```text
tests/test_run_batch.py::test_build_forecast_json_rebalances_extreme_one_sided_band
tests/test_intraday_correction.py::test_intraday_damps_morning_positive_carryover_before_ramp_floor_lift
tests/test_intraday_correction.py::test_intraday_afternoon_observed_anchor_cap_skips_when_actuals_are_recovering

Full suite: 402 passed
```
