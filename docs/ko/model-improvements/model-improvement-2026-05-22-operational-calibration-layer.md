# 2026-05-22 운영 보정 레이어

> 자정과 새벽 예측을 위한 구조적 post-processing 레이어입니다. LightGBM 자체는 건드리지 않고, 데이터 소스 신뢰도와 residual 보정을 분리합니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-22-operational-calibration-layer.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-22-operational-calibration-layer.md)

---

## 왜 필요했나

이전 접근은 특정 시간대의 실패를 막기 위해 여러 guard를 추가하는 방식이었습니다. 일부 날짜에는 도움이 됐지만, 운영 예측 관점에서는 예측선이 왜 움직였는지 설명하기 어려워졌습니다.

2026-05-22 자정 오차는 더 구조적인 문제였습니다.

- 22~23시 실측은 TEPCO API 지연이나 Actions 지연 때문에 다음날 아침까지 비어 있을 수 있습니다.
- 이 빈 행은 lag 피처를 유지하기 위해 임시로 `tepco_forecast_fallback`으로 채워집니다.
- fallback 값은 lag 입력으로는 유용하지만, 진짜 실측은 아닙니다.
- fallback을 residual 관측치처럼 쓰면 자정 직전에 모델이 잘 맞은 것처럼 착시가 생깁니다.
- 00시가 되면 당일 실측이 부족해서 intraday 보정이 사실상 리셋됩니다.
- 그 사이 모델은 과열된 `lag_24h`를 과신할 수 있습니다.

## 변경 내용

intraday post-processing 레이어의 역할을 세 가지로 분리했습니다.

1. 소스 인지 residual

`tepco_forecast_fallback`은 lag 피처 입력에는 계속 사용하지만, residual 보정에서는 제외합니다. 실시간 오차 보정은 실제 observed actual만 사용합니다.

2. 날짜 경계 residual 이월

새 날짜의 실제 observed 행이 부족하면, 전날의 마지막 실제 observed residual을 자정 너머로 이월할 수 있습니다. fallback 시간은 건너뛰고, 경과 시간에 따라 빠르게 감쇠합니다.

3. 하루 단위 스케일 보정

당일 observed가 충분히 쌓이기 전에는 `lag_24h`가 최근 같은 영업/비영업 유형 평균보다 과도하게 높고, 동시에 오늘이 어제보다 더 서늘한지 확인합니다. 두 조건이 맞으면 해당 미래 시간대에 제한된 하방 bias를 적용합니다. 이것은 LightGBM 피처 추가가 아니라 운영 보정 레이어입니다.

## 비활성화한 항목

활성 설정에서는 이전 시간대성 intraday guard를 껐습니다.

- 점심 residual deweight
- shape guard
- ramp guard
- midday transition guard
- 오후 전용 negative residual damping

코드 경로는 테스트 가능하게 남겨두되, 실제 운영 파이프라인은 시간대별 땜질보다 source confidence와 day-level scale calibration을 우선합니다.

## 디버깅 메타데이터

각 intraday 실행은 다음 파일을 생성합니다.

`reports/internal/operational-calibration/YYYY-MM-DD.json`

포함 내용:

- `source_confidence`
- `applied_regime_reason`
- `applied_day_bias`
- residual carry-over 메타데이터
- residual 계산에서 제외한 fallback 개수

따라서 "왜 자정 예측이 튀었는가?"를 UI에 내부 진단을 노출하지 않고도 추적할 수 있습니다.

## 테스트

- fallback 행은 residual 계산에서 제외됩니다.
- 날짜 경계 이월은 fallback을 건너뛰고 마지막 실제 observed residual만 사용합니다.
- day-level scale calibration은 lag 과열과 cooler-day 신호가 함께 있을 때만 적용됩니다.

