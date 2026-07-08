# 2026-07-09 오전 anchor cap ramp veto

언어: [English](../../en/model-improvements/model-improvement-2026-07-09-morning-anchor-cap-ramp-veto.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-09-morning-anchor-cap-ramp-veto.md)

## 배경

2026-07-08 예측 실패는 단발성 spike 문제가 아니라, 실제 오전 ramp가 강해진 뒤에도 모델이 09시 이후 수요 레벨을 낮게 본 문제였습니다.

확정 평가:

| 지표 | 모델 | TEPCO |
| --- | ---: | ---: |
| MAE | 376.3 MW | 172.9 MW |
| WAPE | 1.18% | 0.54% |
| RMSE | 441.1 MW | 231.9 MW |
| 우위 시간 | 3 / 21 | 18 / 21 |

가장 큰 shape miss는 08:00 -> 09:00 전환이었습니다. 실측은 약 `+3,810 MW` 상승했지만 모델은 약 `+2,542 MW`만 상승했습니다. 이후 09:32 JST intraday 스냅샷에서 `morning_observed_anchor_cap`이 09:00~12:00 구간을 추가로 낮췄고, 이미 당일 실측 ramp가 강하게 확인된 상황에서는 과한 제어였습니다.

## 변경 내용

`intraday_correction.morning_observed_anchor_cap`에 보수적인 `ramp_veto` 하위 규칙을 추가했습니다.

다음 조건이 모두 만족될 때만 cap을 건너뜁니다.

- 최근 당일 실측 slope가 매우 강함
- 최근 2구간 평균 실측 slope도 매우 강함
- 대상 시간까지의 lag/recent shape 누적 support가 충분함
- 최신 over-forecast가 크지 않아, 심각한 과대예측이 확정된 상황이 아님

운영 기본값:

| Config key | 값 |
| --- | ---: |
| `min_latest_slope_mw` | 3000 |
| `min_mean_slope_mw` | 3000 |
| `min_cumulative_support_mw` | 2500 |
| `max_latest_overforecast_mw` | 650 |

## 기대 효과

이 변경은 예측을 직접 끌어올리지 않습니다. 강한 실측 ramp가 이미 확인됐고 lag/recent shape도 이를 지지할 때, morning anchor cap이 그 ramp를 잘못 눌러버리는 것만 막습니다.

2026-07-08과 유사한 상황에서는 06:00~08:00 실측 ramp가 고기울기 regime을 확인한 뒤 09:00과 10:00 bucket이 morning cap으로 추가 하향되지 않습니다. 반대로 최신 over-forecast가 이미 큰 경우에는 veto가 차단되어 기존 cap 보호가 유지됩니다.

## 검증

- `python -m pytest tests/test_intraday_correction.py -k "morning_observed_anchor_cap"`
- `python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py`
- `python -m pytest tests/test_ai_daily_report.py tests/test_daily_operation_report.py tests/test_feature_builder.py tests/test_lgbm_model.py`

결과:

- morning anchor cap targeted test `4 passed`
- intraday correction / adjustment `129 passed`
- report / feature-builder / LGBM `136 passed`

## 메모

이 변경은 TEPCO 예측값을 모델 입력으로 사용하지 않습니다. TEPCO는 비교 기준으로만 유지합니다. veto 판단은 당일 실측 수요 slope, lag/recent shape support, 최신 모델 residual을 기준으로 합니다.
