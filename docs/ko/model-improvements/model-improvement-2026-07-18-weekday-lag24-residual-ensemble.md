# 2026-07-18 평일 Lag-24 잔차 앙상블

언어: [English](../../en/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md)

## 문제

7월 운영 예측은 모델과 가드가 여러 번 변경되었으므로 하나의 동일 모델 백테스트처럼 합산할 수 없습니다. 현재 코드로 원천 LightGBM, 결정적 후처리, intraday 보정, published forecast 보존을 분리해 재생한 결과, 반복되는 평일 오차는 특정 시간 가드 하나로 설명되지 않았습니다.

절대수요 q50은 lag와 anchor 수준에 강하게 의존했습니다. 현재 수요가 전날과 최근 같은 영업일 anchor를 넘어서는 날에는 충분히 올라오지 못했고, 반대로 더 시원해진 날에도 lag-24가 높으면 과대예측을 유지했습니다. 시간별 delta 피처 추가, 평일 전용 단일 모델, 점심 규칙 강화는 최근 구간과 과거 holdout을 동시에 안정적으로 개선하지 못했습니다.

## 변경

네 번째 LightGBM 중앙값 모델은 다음 target을 학습합니다.

```text
target = actual_mw - lag_24h
```

영업일에만 중심 예측을 다음과 같이 결합합니다.

```text
q50_final = 0.5 * q50_absolute + 0.5 * (lag_24h + q50_residual)
```

비영업일은 기존 절대수요 q50을 유지합니다. q025/q975 half-width는 기존처럼 보정한 뒤 결합 q50 주위로 이동하므로, 이 변경 자체가 밴드 폭을 별도로 바꾸지 않습니다.

## 검증

2026-07-06부터 2026-07-17까지 영업일 10일을 현재 코드와 결정적 후처리까지 포함해 rolling replay한 결과입니다.

| 지표 | 기존 | 앙상블 |
|---|---:|---:|
| 최종 MAE | 718.3 MW | 660.9 MW |
| 00-05 MAE | 327.7 MW | 292.0 MW |
| 06-10 MAE | 824.3 MW | 754.1 MW |
| 11-13 MAE | 1,009.0 MW | 938.3 MW |
| 14-18 MAE | 1,046.3 MW | 952.1 MW |
| 19-23 MAE | 578.7 MW | 553.0 MW |

후보 모델은 10일 중 8일을 개선했습니다. 나빠진 2일의 차이는 작았고, 불안정성이 컸던 날짜의 개선폭은 더 컸습니다.

2026년 1-5월 frozen-origin holdout에서도 모든 월과 모든 시간대가 개선되었습니다.

| 지표 | 기존 | 앙상블 |
|---|---:|---:|
| 전체 MAE | 819.0 MW | 775.7 MW |
| Shape-delta MAE | 409.8 MW | 371.0 MW |
| 일간 최대 MAE | 2,442.4 MW | 2,086.1 MW |

이 재생은 target 날짜의 확정 기상을 사용했으므로 라이브 기상 예보 오차까지 포함한 운영 성능 주장이 아니라 모델 비교의 상한선 성격입니다.

## 안전장치

- TEPCO 예측은 모델 입력이나 보정 target으로 사용하지 않습니다.
- 특정 시간대 보정 규칙을 추가하지 않았습니다.
- 피처 집합과 기존 후처리 순서는 유지합니다.
- 주말과 공휴일 중심 예측은 변경하지 않습니다.
- interval version을 올려 구형 pickle이 서빙 전에 재학습되게 합니다.
- `config.yaml`에서 앙상블을 끄거나 가중치를 조정할 수 있습니다.

## 검증 명령

- `pytest tests/test_lgbm_model.py -q`
- 전체 회귀 테스트
- 현재 후처리를 포함한 버전 인지 rolling replay
- 2026년 1-5월 frozen-origin holdout
