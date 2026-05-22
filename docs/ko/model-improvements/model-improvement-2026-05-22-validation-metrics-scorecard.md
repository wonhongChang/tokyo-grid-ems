# 검증 지표 스코어카드

언어: [English](../../../en/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md) / [日本語](../../../ja/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md)

## 배경

기존 검증 탭은 `MAE`와 시간별 승패 카운트를 중심으로 보여줬습니다. 첫 대시보드로는 충분했지만, 운영 예측에서는 스포츠 경기처럼 “몇 시간 이겼는가”만으로 판단하기 어렵습니다. 전력 수요 예측은 평균 오차, 하루 전체 수요 대비 오차율, 큰 단일 오차 리스크, 시간별 우위 구간을 함께 봐야 합니다.

## 변경 내용

- `MAE`는 MW 단위로 가장 직관적인 대표 지표라 유지했습니다.
- 전체 실적 수요 대비 오차율을 보기 위해 `WAPE`를 추가했습니다.
- 큰 오차 리스크를 보기 위해 `RMSE`와 최대 오차 필드를 추가했습니다.
- UI 표현을 승패가 아니라 운영 판단과 우위 시간으로 변경했습니다.
- 평균 오차와 큰 오차 리스크가 서로 다른 방향을 가리키는 날은 `mixed` 판정으로 표시합니다.
- 하위 호환을 위해 기존 `modelWins`, `tepcoWins`, `modelWinRate` 필드는 유지했습니다.

## 운영 해석

대시보드는 이제 시간별 우위 시간을 보조 지표로 취급합니다. 어떤 모델이 더 많은 시간대에서 가까웠더라도, 한두 시간의 큰 오차가 발생하면 운영상 더 위험할 수 있습니다. 이 경우 `WAPE`, `RMSE`, `mixed` 판정으로 리스크를 드러냅니다.

## 영향 산출물

- `web/public/metrics/forecast_accuracy.json`
- `web/public/reports/daily/*.json`
- 대시보드 검증 탭

## 검증

- `py -m pytest -q`
- `npm.cmd run build`
