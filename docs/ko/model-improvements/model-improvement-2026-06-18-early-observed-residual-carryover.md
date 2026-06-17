# 2026-06-18 새벽 early observed residual carryover

언어: [English](../../en/model-improvements/model-improvement-2026-06-18-early-observed-residual-carryover.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-18-early-observed-residual-carryover.md)

## 문제

2026-06-18 00~01시 JST 서빙 데이터에서 큰 새벽 과소예측이 발생했습니다.

- 00시 실측은 24,240MW였고 모델 서빙값은 23,233.7MW였습니다.
- 01시 실측은 22,950MW였고 모델 서빙값은 22,050.3MW였습니다.
- 02:26 JST 보정 실행 시점에는 이미 실제 관측 2개가 있었지만, `min_observed_hours=3` 때문에 표준 intraday residual 루프가 이 잔차를 사용하지 않았습니다.
- 표준 루프가 대기하는 동안 파이프라인은 전날 day-boundary residual carryover 약 `-120MW`를 계속 사용했고, 당일 실측은 강한 양수 잔차를 보였는데도 미래 시간을 더 낮췄습니다.

이 문제는 TEPCO 추종 문제가 아닙니다. 당일 오차 방향은 이미 보였지만, 정식 residual 루프가 켜지기 전이라 그 증거를 활용하지 못한 저관측 구간 handoff 공백입니다.

## 변경

`early_observed_residual_carryover`를 추가했습니다.

- 당일 실측 수가 정상 `min_observed_hours`보다 적을 때만 작동합니다.
- 기본 조건은 실제 관측 2개 이상입니다.
- early residual의 부호가 같아야 합니다.
- 평균 잔차의 절대값이 `500MW` 이상이어야 합니다.
- 적용량은 `0.5` shrinkage를 거치고 `700MW`로 상한을 둡니다.
- 이 조건이 만족되면 오래된 전날 day-boundary carryover보다 당일 early residual을 우선합니다.

2026-06-18 패턴에서는 두 early residual이 약 `+416MW`의 보수적 미래 상향 보정을 만들고, 기존 `-120MW` carryover는 사용하지 않습니다.

## 기대 효과

00~01시가 모두 명확히 과소예측 또는 과대예측이면, 세 번째 실측이 들어오기 전에도 아직 닫히지 않은 가까운 미래 시간은 관측 방향으로 움직일 수 있습니다. 단일 noisy bucket만으로는 작동하지 않습니다.

이미 닫힌 시간은 다시 쓰지 않습니다. 첫 번째 미래 시간부터 개선하는 구조입니다.

## 검증

```text
tests/test_intraday_correction.py::test_intraday_correction_prefers_early_same_day_residuals_over_stale_midnight_carryover

Full suite: 399 passed
```
