# LightGBM 예측 모델 설계

> 현재 운영 설계: 캘린더, 래그, 공휴일, 기상 피처와 운영 보정 레이어를 함께 사용하는 LightGBM quantile regression.

언어: [English](../en/lgbm-design.md) · [日本語](../ja/lgbm-design.md)

운영 참고 문서: [모델 운영 명세](model-operations-spec.md)

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

대시보드는 q50을 예측선으로 사용합니다. q025/q975는 p95 예측 밴드로 표시하고, p99 스타일의 더 넓은 구간은 q025/q975 폭을 바탕으로 확장합니다. 한쪽 quantile 구간이 q50 근처로 붙는 경우에는 반대쪽의 큰 불확실성을 그대로 복사하지 않고, 해당 방향의 최소 폭만 유지합니다. 독립 quantile 모델이 날씨 regime 변화 이후 한쪽 tail만 드물게 과도하게 넓히는 경우에는 interval sanity calibration이 p95 최대 half-width와 상단/하단 비대칭 비율을 제한하며, q50 예측선은 변경하지 않습니다.

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
| 기상 | 기온, 체감온도, 설정 가능한 냉방/난방 degree, 기온 이상치, 1시간/2시간/24시간/168시간 기온·냉방 변화량, 3시간/6시간/72시간 열 관성 | 냉난방 수요, 기상 변화 방향, 전일/전주 대비 레짐 변화 반영 |
| 교호작용 | holiday x heat, post-holiday x heat | 골든위크 이후 복귀 수요 보정 |
| 영업/기상 교호작용 | business-morning x 기온 변화/이상치, late-afternoon x 기온·냉방 변화 | 오전 램프업, 오후 냉방 둔화, 같은 기온에서도 상승기/하강기가 다른 수요 패턴 반영 |
| 래그 컨텍스트 | lag_24h_dsh, lag_24h_consec, lag_168h_dsh, lag_24h 영업/비영업 mismatch, 최근 같은 영업타입 평균, lag-to-anchor gap | 래그값이 휴일 수요에 오염됐거나 영업/비영업 경계를 건넜는지 알려줌 |

현재 명시적 LightGBM 학습 피처 수는 56개입니다.

냉방/난방 degree의 기준온도는 `config.yaml`에서 설정합니다.

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 18.0
```

기상 보강은 과거/현재 시간에는 JMA AMeDAS 실측을 우선 사용하고, 미래 시간의 기온은 JMA 공식 예보를 우선 사용합니다. Open-Meteo JMA는 습도 보완용 fallback으로만 사용하며 JMA 예보 기온을 덮어쓰지 않습니다. 공식 예보 습도가 없을 때도 습도 기반 체감온도와 불쾌지수 계산이 끊기지 않도록 humidity fallback을 적용합니다.

`temp_delta_24h`와 `cooling_delta_24h`는 오늘 날씨가 어제 같은 시간과 달라졌을 때, 전날 수요 lag를 얼마나 믿을지 모델에 알려주는 피처입니다. `temp_delta_168h`와 `cooling_delta_168h`는 전주 같은 시간대 수요에 대해 같은 역할을 합니다. `temp_delta_1h`, `temp_delta_2h`, `apparent_temp_delta_1h`, `cooling_delta_1h`는 단기 기상 변화 방향을 반영합니다. `cooling_degree_3h_mean`, `cooling_degree_6h_mean`, `heating_degree_3h_mean`, `heating_degree_6h_mean`, `temp_72h_mean`, `cooling_degree_72h_mean`, `heating_degree_72h_mean`은 지속적인 더위나 추위의 누적 효과를 반영합니다. `apparent_temp_c`와 `apparent_cooling_degree`는 데이터 소스가 체감온도를 제공할 때 이를 보완 신호로 사용합니다.

`business_morning_x_temp_delta_24h`, `business_morning_x_temp_anomaly_7d`, `business_morning_x_temp_anomaly_doy`는 평일 오전 램프가 기상 레짐 변화에 반응하도록 돕습니다. `business_late_afternoon_x_temp_delta_1h`와 `business_late_afternoon_x_cooling_delta_1h`는 오후 기온 상승 국면과 하강 국면을 같은 수요 상태로 보지 않도록 돕습니다.

`lag_24h_business_type_mismatch`와 `lag_24h_mismatch_x_business_hour`는 금요일→토요일, 일요일→월요일처럼 전날 lag가 영업/비영업 경계를 건너는 경우를 모델에 알려줍니다. 특히 낮 시간대 업무 수요 차이를 조심해서 보게 하는 신호입니다. `recent_same_business_type_mean`, `lag_24h_to_last_biz_gap`, `lag_24h_to_same_business_type_gap`, `lag_24h_gap_x_business_hour`는 최근 같은 영업 타입의 같은 시간대 평균과 gap 기준선을 제공합니다.

`lag_24h_hourly_delta`, `lag_168h_hourly_delta`, `recent_same_business_type_delta_mean`, `recent_same_business_type_delta_q25`, 당일 최신 실측 시간/기울기, 점심 전환 interaction context는 내부 진단과 국소 shape guard를 위한 추론 전용 context로 생성합니다. 검증 결과 전역 hourly-delta를 학습 피처에 넣으면 무관한 오전 시간대까지 흔들 수 있어 LightGBM 학습 피처에는 포함하지 않았습니다.

---

## Intraday 보정

`python/forecast/intraday_correction.py`는 당일 실측이 쌓이면 남은 시간의 예측을 보정합니다.

```text
residual = actualMw - modelForecastMw
```

최근 실측 잔차를 평균내고, shrinkage와 최대 보정폭 제한을 적용한 뒤, 미래 시간으로 갈수록 보정 강도를 줄입니다.

현재 intraday 보정은 단순 잔차 이월만이 아니라 다음 운영 보정 레이어를 포함합니다.

- TEPCO 예측 fallback 행을 건너뛰는 날짜 경계 잔차 이월
- 과열된 lag와 더 낮아진 당일 기온이 충돌할 때의 day-level scale bias
- 영업/비영업 전환 prior와 실측 기반 전환 보정
- 과열된 주말 램프를 올리지 않도록 하는 positive residual mitigation
- 비영업일 수요가 anchor로 회복될 때 음수 잔차 전파를 줄이는 negative residual recovery damping
- 실측 수요가 꺾일 때 양수 잔차 전파를 줄이는 positive residual slope damping
- 영업일 오전 근거리 dip을 막는 morning ramp continuity guard
- 저녁 하락 국면에서 근거리 반등 spike를 제한하는 evening decline continuity guard

시간별 residual carry-over와 guard metadata는 operational calibration snapshot에 저장되어 일일 AI/Ops 리포트가 예측선 변화를 설명할 수 있게 합니다.

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

12:00 시간 전환 개선은 [2026-05-20 점심 시간대 전환 guard](model-improvements/model-improvement-2026-05-20-midday-transition-features.md)와 [2026-05-27 점심 전환 가드 재활성화](model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md)에 정리했습니다.

최신 운영 보정 레이어는 [2026-05-25 영업일 복귀 anchor 부족분 가드](model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md), [2026-05-25 양수 잔차 슬로프 감쇠](model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md), [2026-05-27 오전 램프 연속성 가드](model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md), [2026-05-27 저녁 하락 연속성 가드](model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md), [2026-05-30 음수 잔차 연속성 floor](model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md), [2026-06-03 예측 구간 상단 tail 안정화](model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)에 정리했습니다.

---

## 학습과 추론 흐름

1. ETL이 TEPCO 월별 ZIP에서 확정 이력 데이터를 읽습니다.
2. JMA AMeDAS 실측 기상, JMA 공식 예보 기온, 습도 fallback 필드를 붙입니다.
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
- `metrics/forecast_accuracy.json`: 운영 중 TEPCO 공식 예측과 자체 모델의 오차 비교. MAE, WAPE, RMSE, 우세 시간 수, 최대 오차 리스크를 포함합니다.

TEPCO 예측은 내부 정보가 반영될 수 있는 강한 기준선입니다. 이 프로젝트의 목적은 TEPCO를 항상 이긴다고 주장하는 것이 아니라, 공개 데이터만으로 만든 모델을 투명하게 비교하고 운영하는 것입니다.
