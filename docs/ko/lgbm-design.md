# LightGBM 예측 모델 설계

> 현재 운영 설계: 캘린더, 래그, 공휴일, 기온, intraday 보정 피처를 사용하는 LightGBM quantile regression.

언어: [English](../en/lgbm-design.md) · [日本語](../ja/lgbm-design.md)

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
| 기온 | 기온, 체감온도, 설정 가능한 냉방/난방 degree, 기온 이상치, 24시간/168시간 기온·냉방 변화량, 72시간 열 관성 | 냉난방 수요와 전일/전주 대비 계절 변화 반영 |
| 교호작용 | holiday x heat, post-holiday x heat | 골든위크 이후 복귀 수요 보정 |
| 래그 컨텍스트 | lag_24h_dsh, lag_24h_consec, lag_168h_dsh, lag_24h 영업/비영업 mismatch, 최근 같은 영업타입 평균 | 래그값이 휴일 수요에 오염됐거나 영업/비영업 경계를 건넜는지 알려줌 |

현재 명시적 LightGBM 학습 피처 수는 50개입니다.

냉방/난방 degree의 기준온도는 `config.yaml`에서 설정합니다.

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 18.0
```

`temp_delta_24h`와 `cooling_delta_24h`는 오늘 날씨가 어제 같은 시간과 달라졌을 때, 전날 수요 lag를 얼마나 믿을지 모델에 알려주는 피처입니다. `temp_delta_168h`와 `cooling_delta_168h`는 전주 같은 시간대 수요에 대해 같은 역할을 합니다. `temp_72h_mean`, `cooling_degree_72h_mean`, `heating_degree_72h_mean`은 지속적인 더위나 추위의 누적 효과를 반영합니다. `apparent_temp_c`와 `apparent_cooling_degree`는 데이터 소스가 체감온도를 제공할 때 이를 보완 신호로 사용합니다.

`lag_24h_business_type_mismatch`와 `lag_24h_mismatch_x_business_hour`는 금요일→토요일, 일요일→월요일처럼 전날 lag가 영업/비영업 경계를 건너는 경우를 모델에 알려줍니다. 특히 낮 시간대 업무 수요 차이를 조심해서 보게 하는 신호입니다. `recent_same_business_type_mean`은 최근 같은 영업 타입의 같은 시간대 평균을 추가 기준선으로 제공합니다.

`lag_24h_hourly_delta`, `lag_168h_hourly_delta`, `recent_same_business_type_delta_mean`은 내부 진단과 12시 전환 guard를 위한 추론 전용 context로 생성합니다. 검증 결과 전역 hourly-delta를 학습 피처에 넣으면 무관한 오전 시간대까지 흔들 수 있어 LightGBM 학습 피처에는 포함하지 않았습니다.

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

## 주간 고온 보호 보정

`python/forecast/adjustment.py`는 intraday 보정 전에 보수적인 후처리 보호 장치를 적용합니다. 영업일에 같은 시간대 168시간 래그가 휴일 또는 주말을 가리키고, 현재 주간 기온 편차가 높은 경우 유사일 보정이 낮 시간대 예측을 아래로 끌어내리지 못하게 막습니다. 또 휴일 래그가 없어도 계절 대비 따뜻한 평일 낮에는 더 작은 일반 고온 guard를 적용합니다. 비영업일의 더위 효과는 수동 상향 guard가 아니라 LightGBM 날씨 피처에 맡깁니다.

자세한 사고 분석, 구현 내용, 검증 결과는 [2026-05-13 주간 고온 보호 보정](model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md)에 정리했습니다.

후속 일반화 내용은 [2026-05-14 따뜻한 낮 시간대 과소예측 보정](model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md)에 정리했습니다.

피처 측면의 후속 개선은 [2026-05-14 전주 대비 기온 변화 피처](model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md)에 정리했습니다.

다음 피처 개선은 [2026-05-15 전일 대비 날씨 변화와 체감온도 피처](model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md)에 정리했습니다.

주말/평일 전환 개선은 [2026-05-16 영업 타입 전환 lag 피처](model-improvements/model-improvement-2026-05-16-business-type-lag-features.md)에 정리했습니다.

12:00 시간 전환 개선은 [2026-05-20 점심 시간대 전환 guard](model-improvements/model-improvement-2026-05-20-midday-transition-features.md)에 정리했습니다.

---

## 학습과 추론 흐름

1. ETL이 TEPCO 월별 ZIP에서 확정 이력 데이터를 읽습니다.
2. Open-Meteo 기온/체감온도 데이터를 붙입니다.
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
