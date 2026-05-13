# LightGBM 예측 모델 설계

> 현재 운영 설계: 캘린더, 래그, 공휴일, 기온, intraday 보정 피처를 사용하는 LightGBM quantile regression.

언어: [English](lgbm-design.md) · [日本語](lgbm-design_ja.md)

---

## 시스템에서의 역할

이 모델은 Tokyo Grid EMS의 시간별 전력 수요를 예측합니다.

- 오늘 예측
- 내일 예측
- 대시보드의 예측 밴드
- 이상탐지에서 사용하는 기대 수요

LightGBM을 사용할 수 없거나, 학습 데이터가 부족하거나, 예측 중 오류가 나면 `baseline_dow_hour_mean` 통계 모델로 fallback합니다.

---

## 모델 구조

`python/forecast/lgbm_model.py`는 세 개의 LightGBM quantile 모델을 학습합니다.

| 모델 | 역할 |
|---|---|
| q025 | p95 하단 구간 추정 |
| q50 | 중심 예측값 |
| q975 | p95 상단 구간 추정 |

대시보드는 q50을 예측선으로 사용합니다. q025/q975는 p95 예측 밴드로 표시하고, p99 스타일의 더 넓은 구간은 q025/q975 폭을 바탕으로 확장합니다.

최소 학습 데이터:

```text
90일 * 24시간
```

조건을 만족하지 못하면 baseline으로 돌아갑니다.

---

## 피처

피처 엔지니어링은 `python/forecast/feature_builder.py`에 있습니다.

| 그룹 | 예시 | 이유 |
|---|---|---|
| 캘린더 | 시간, 요일, 월, 주말, 공휴일 | 일/주 단위 수요 리듬 반영 |
| 래그 | 24h, 48h, 168h, 336h | 전력 수요의 관성 반영 |
| 롤링 통계 | 최근 4주 같은 요일/시간 평균과 표준편차 | 안정적인 과거 기준 제공 |
| 공휴일 보정 | 직전 평일, 연속 휴일 수, 휴일 종료 후 경과일 | 연휴 직후 과소예측 완화 |
| 기온 | 기온, 냉방/난방 degree, 기온 이상치 | 냉난방 수요 반영 |
| 교호작용 | holiday x heat, post-holiday x heat | 골든위크 이후 복귀 수요 보정 |
| 래그 컨텍스트 | lag_24h_dsh, lag_24h_consec, lag_168h_dsh | 래그값이 휴일 수요에 오염됐는지 알려줌 |

현재 명시적 피처 수는 28개입니다.

---

## Intraday 보정

`python/forecast/intraday_correction.py`는 당일 실측이 쌓이면 남은 시간의 예측을 보정합니다.

```text
residual = actualMw - modelForecastMw
```

최근 실측 잔차를 평균내고, shrinkage와 최대 보정폭 제한을 적용한 뒤, 미래 시간으로 갈수록 보정 강도를 줄입니다.

23:40 JST 시점에도 23:00 실측이 없으면 TEPCO 예측값을 임시 입력으로 사용할 수 있습니다.

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

이 값은 운영 예측 입력에는 쓰지만, 모델 검증 지표와 이상탐지의 실측 판정에서는 제외합니다.

---

## 학습과 추론 흐름

1. ETL이 TEPCO 월별 ZIP에서 확정 이력 데이터를 읽습니다.
2. Open-Meteo 기온 데이터를 붙입니다.
3. LightGBM을 학습하고 `web/public/.lgbm_model.pkl`로 저장합니다.
4. status/intraday workflow가 모델을 다시 로드합니다.
5. 월별 ZIP이 아직 갱신되지 않은 구간은 최근 actual JSON으로 cache를 보강합니다.
6. 오늘 예측을 만들고 intraday residual correction을 적용합니다.
7. 같은 cache로 내일 예측도 만듭니다.
8. `web/public/forecast/` 아래 JSON으로 저장합니다.

---

## 평가

두 가지 리포트를 생성합니다.

- `metrics/model_backtest.json`: train/test 분리를 지킨 LightGBM vs baseline 오프라인 백테스트
- `metrics/forecast_accuracy.json`: 운영 중 TEPCO 공식 예측과 자체 모델의 오차 비교

TEPCO 예측은 내부 정보가 반영될 수 있는 강한 기준선입니다. 이 프로젝트의 목적은 TEPCO를 항상 이긴다고 주장하는 것이 아니라, 공개 데이터만으로 만든 모델을 투명하게 비교하고 운영하는 것입니다.
