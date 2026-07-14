# 모델 운영 명세

> TokyoGridEMS의 LightGBM 예측 모델을 운영, 점검, 수정할 때 참고하는 모델 운영 명세서입니다.

언어: [English](../en/model-operations-spec.md) · [日本語](../ja/model-operations-spec.md)

---

## 1. 모델 개요 및 역할

### 타임존 운영 원칙

시스템의 모든 파이프라인 기준 시각은 JST(UTC+9)로 통일합니다. TEPCO와 JMA 데이터는 일본 기준 시간으로 제공되고, GitHub Actions cron은 UTC 기준으로 동작하므로, 스케줄 표현과 데이터 처리 시각을 분리해서 관리해야 합니다.

운영 원칙:

- 데이터 row의 timestamp, forecast date, actual date는 JST 기준으로 해석합니다.
- GitHub Actions cron은 UTC로 작성하되, 주석과 문서에는 JST 실행 시각을 함께 적습니다.
- ETL, intraday update, daily report, forecast snapshot의 `generatedAt`과 운영 판단 기준은 JST를 기준으로 맞춥니다.
- 날짜 경계 residual carry-over는 UTC 자정이 아니라 JST 날짜 경계를 기준으로 판단합니다.

| 항목 | 현재 값 |
|---|---|
| 운영 모델 | LightGBM quantile regression |
| 구현 | `python/forecast/lgbm_model.py` |
| 피처 생성 | `python/forecast/feature_builder.py` |
| 후처리 | `python/forecast/adjustment.py`, `python/forecast/intraday_correction.py` |
| interval version | `q025_q50_q975_p95_v10_humidity_discomfort` |
| 최소 학습량 | `90 * 24 = 2160` hourly rows |
| fallback | `baseline_dow_hour_mean` |

모델은 시간별 전력 수요를 예측하고, 오늘/내일 예측선, p95/p99 예측 밴드, 이상탐지 expected demand를 생성합니다.

LightGBM은 세 개의 quantile regressor를 학습합니다.

| 모델 | alpha | 역할 |
|---|---:|---|
| `q025` | 0.025 | p95 하단 추정 |
| `q50` | 0.50 | 중심 예측선 |
| `q975` | 0.975 | p95 상단 추정 |

대시보드는 `q50`을 중심 예측선으로 사용합니다. `q025/q975`는 p95 밴드가 되고, p99 스타일 외곽 밴드는 q025/q975 half-width를 한 번 더 확장해 계산합니다. 한쪽 quantile이 q50에 붙는 경우에는 반대쪽의 큰 폭을 그대로 복사하지 않고, 해당 방향의 최소 폭만 유지합니다.

---

## 2. 데이터 소스 파이프라인 및 우선순위

### 전력 데이터

| 우선순위 | 데이터 | 역할 | 운영 메모 |
|---:|---|---|---|
| 1 | TEPCO 월별 ZIP CSV | 확정 과거 실측, 학습 target | 보통 익일 오전 갱신. GitHub-hosted runner에서 403 가능 |
| 2 | TEPCO intraday CSV | 당일 실측 보강 | 실시간 차트와 intraday residual correction에 사용 |
| 3 | `actual/YYYY-MM-DD.json` | 월별 ZIP 갱신 전 gap 보완 | ETL 지연 시 cache 보강 |
| 4 | TEPCO forecast fallback | 23시 등 미확정 실측 임시 입력 | lag 입력 안정화용. 검증 actual로 취급 금지 |

TEPCO forecast fallback은 pipeline continuity를 위한 임시값입니다. LightGBM의 lag 입력에는 사용할 수 있지만, residual 계산, 모델 성능 검증, 이상탐지 actual 판정에서는 진짜 실측으로 보면 안 됩니다.

### 기상 데이터

| 시간 범위 | 기온 우선순위 | 습도 우선순위 | 운영 메모 |
|---|---|---|---|
| 과거/현재 | JMA AMeDAS 관측 | JMA AMeDAS 관측 | 공식 실측 우선 |
| 가까운 미래 | JMA 공식 예보 | 최신 AMeDAS 습도 forward fill | 기온은 JMA forecast를 신뢰 |
| 미래 습도 보완 | JMA forecast temperature 유지 | Open-Meteo JMA humidity fallback | Open-Meteo는 습도 보완용으로 제한 |
| 최종 fallback | 기존 값 또는 보수적 평균 | 월/시간대 seasonal humidity | 통신 장애 방어 |

운영 원칙:

- 미래 기온은 JMA 공식 forecast를 우선합니다.
- Open-Meteo JMA는 기온을 덮어쓰지 않고 습도 결측 보완에만 사용합니다.
- `weather_source`는 예측 튐 원인을 추적하는 핵심 필드입니다.

---

## 3. LightGBM 하이퍼파라미터

| 파라미터 | 현재 값 | 튜닝 의도 |
|---|---:|---|
| `objective` | `quantile` | 예측 밴드 생성을 위한 quantile regression |
| `alpha` | `0.025 / 0.50 / 0.975` | 하단/중심/상단 모델 분리 |
| `n_estimators` | `500` | 충분한 비선형 패턴 학습 |
| `learning_rate` | `0.05` | 안정적인 boosting step |
| `num_leaves` | `31` | 중간 수준의 트리 복잡도 |
| `min_child_samples` | `20` | 작은 split 과적합 방지 |
| `subsample` | `0.8` | row sampling으로 variance 완화 |
| `colsample_bytree` | `0.8` | 특정 lag/피처 의존 완화 |
| `min_p95_half_width_mw` | `500` | 밴드 과소폭 방지 |

운영 판단:

- hyperparameter를 자주 흔들기보다 먼저 데이터 소스, lag regime, post-processing carryover를 점검합니다.
- 특정 하루의 shape를 맞추기 위해 모델 복잡도를 올리는 수정은 피합니다.
- 신규 피처는 전체 MAE뿐 아니라 시간대별 WAPE/RMSE와 shape 부작용을 함께 봅니다.

---

## 4. 전체 피처 카탈로그

현재 LightGBM 학습 피처는 63개입니다. 현재 구현은 LightGBM에 `categorical_feature`를 명시적으로 넘기지 않고 대부분 numeric matrix로 학습합니다. 따라서 아래의 "논리 타입"은 사람이 해석하는 의미이고, "모델 입력 타입"은 실제 모델에 들어가는 형태입니다.

### 캘린더

| No. | 피처명 | 논리 타입 | 모델 입력 타입 | 출처 | 의미 | 운영 메모 |
|---:|---|---|---|---|---|---|
| 1 | `hour` | categorical-like integer | Integer/Numeric | timestamp | 0-23시 | 하루 수요 리듬의 핵심 |
| 2 | `dayofweek` | categorical-like integer | Integer/Numeric | timestamp | 요일 | 평일/주말 패턴 반영 |
| 3 | `month` | categorical-like integer | Integer/Numeric | timestamp | 월 | 계절성 반영 |
| 4 | `is_holiday` | binary flag | Integer/Numeric | `jpholiday` | 일본 공휴일 여부 | 공휴일 수요 변화 반영 |
| 5 | `is_weekend` | binary flag | Integer/Numeric | timestamp | 토/일 여부 | 비영업일 패턴 반영 |
| 6 | `is_non_business_day` | binary flag | Integer/Numeric | weekend or holiday | 주말/공휴일 통합 flag | 영업/비영업 전환의 핵심 gate |

### Lag 및 rolling 통계

| No. | 피처명 | 논리 타입 | 모델 입력 타입 | 출처 | 의미 | 운영 메모 |
|---:|---|---|---|---|---|---|
| 7 | `lag_24h` | continuous lag | Float/Numeric | actual cache | 전날 같은 시간 수요 | 강한 단기 관성. 영업/비영업 전환 때 오염 가능 |
| 8 | `lag_48h` | continuous lag | Float/Numeric | actual cache | 이틀 전 같은 시간 수요 | 전날이 비정상일 때 보완 |
| 9 | `lag_168h` | continuous lag | Float/Numeric | actual cache | 1주 전 같은 시간 수요 | 요일 패턴 반영. 공휴일/날씨 차이에 취약 |
| 10 | `lag_336h` | continuous lag | Float/Numeric | actual cache | 2주 전 같은 시간 수요 | 안정적 계절/요일 기준 |
| 11 | `roll_4w_mean` | rolling statistic | Float/Numeric | actual cache | 최근 4주 같은 요일/시간 평균 | 안정적 기준선 |
| 12 | `roll_4w_std` | rolling statistic | Float/Numeric | actual cache | 최근 4주 변동성 | 패턴 불안정성 신호 |

### 휴일/영업일 보정

| No. | 피처명 | 논리 타입 | 모델 입력 타입 | 출처 | 의미 | 운영 메모 |
|---:|---|---|---|---|---|---|
| 13 | `lag_last_biz_hour` | continuous lag | Float/Numeric | actual + calendar | 직전 영업일 같은 시간 수요 | 연휴 후 평일 복귀 보완 |
| 14 | `lag_last_nonhol_hour` | continuous lag | Float/Numeric | actual + calendar | 직전 비공휴일 같은 시간 수요 | 공휴일 영향 완화 |
| 15 | `consec_holiday_len` | ordinal count | Integer/Numeric | calendar | 직전 연속 휴일 길이 | Golden Week/연휴 후 복귀 감지 |
| 16 | `days_since_holiday_end` | ordinal count | Integer/Numeric | calendar | 휴일 종료 후 경과일 | 복귀 첫날/둘째날 분리 |
| 17 | `major_holiday_season` | categorical-like integer | Integer/Numeric | date range | GW/Obon/New Year zone | 대형 연휴 주변 특수 패턴 |

### 기상/환경

| No. | 피처명 | 논리 타입 | 모델 입력 타입 | 출처 | 의미 | 운영 메모 |
|---:|---|---|---|---|---|---|
| 18 | `temp_c` | continuous weather | Float/Numeric | JMA/AMeDAS | 기온 | 냉난방 수요의 기본 driver |
| 19 | `cooling_degree` | continuous derived | Float/Numeric | derived | `max(0, temp_c - 22)` | 여름 냉방 수요 반영 |
| 20 | `heating_degree` | continuous derived | Float/Numeric | derived | `max(0, 18 - temp_c)` | 겨울 난방 수요 반영 |
| 21 | `apparent_temp_c` | continuous weather | Float/Numeric | humidity-derived | 체감온도 | 습도 영향 반영 |
| 22 | `apparent_cooling_degree` | continuous derived | Float/Numeric | derived | 체감온도 기반 냉방 degree | 고습 냉방 수요 보완 |
| 23 | `temp_anomaly_7d` | continuous delta | Float/Numeric | weather history | 최근 7일 평균 대비 기온 편차 | 갑작스런 더위/추위 감지 |
| 24 | `temp_anomaly_doy` | continuous delta | Float/Numeric | month/hour baseline | 계절 기준 기온 편차 | 계절 대비 이상 기온 감지 |
| 25 | `temp_delta_24h` | continuous delta | Float/Numeric | weather lag | 전날 같은 시간 대비 기온 변화 | `lag_24h` 신뢰도 조절 |
| 26 | `cooling_delta_24h` | continuous delta | Float/Numeric | weather lag | 전날 대비 냉방 degree 변화 | 어제 수요 관성 보정 |
| 27 | `temp_delta_168h` | continuous delta | Float/Numeric | weather lag | 전주 같은 시간 대비 기온 변화 | `lag_168h` 신뢰도 조절 |
| 28 | `cooling_delta_168h` | continuous delta | Float/Numeric | weather lag | 전주 대비 냉방 degree 변화 | 주간 패턴의 날씨 차이 반영 |
| 29 | `temp_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1시간 전 대비 기온 변화 | 오전 상승/오후 하강 방향성 |
| 30 | `temp_delta_2h` | continuous delta | Float/Numeric | weather sequence | 2시간 전 대비 기온 변화 | 단기 방향성 안정화 |
| 31 | `apparent_temp_delta_1h` | continuous delta | Float/Numeric | weather sequence | 체감온도 1시간 변화 | 습도 포함 체감 변화 |
| 32 | `cooling_delta_1h` | continuous delta | Float/Numeric | weather sequence | 냉방 degree 1시간 변화 | 냉방 수요 증가/감소 방향 |
| 33 | `cooling_degree_3h_mean` | rolling weather | Float/Numeric | rolling weather | 최근 3시간 냉방 누적 | 단기 열 관성 |
| 34 | `cooling_degree_6h_mean` | rolling weather | Float/Numeric | rolling weather | 최근 6시간 냉방 누적 | 반나절 열 관성 |
| 35 | `heating_degree_3h_mean` | rolling weather | Float/Numeric | rolling weather | 최근 3시간 난방 누적 | 단기 추위 관성 |
| 36 | `heating_degree_6h_mean` | rolling weather | Float/Numeric | rolling weather | 최근 6시간 난방 누적 | 반나절 추위 관성 |
| 37 | `temp_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72시간 평균 기온 | 건물 열 축적/방열 반영 |
| 38 | `cooling_degree_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72시간 냉방 누적 | 폭염 지속 효과 |
| 39 | `heating_degree_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72시간 난방 누적 | 한파 지속 효과 |

### Interaction 및 lag context

| No. | 피처명 | 논리 타입 | 모델 입력 타입 | 출처 | 의미 | 운영 메모 |
|---:|---|---|---|---|---|---|
| 40 | `business_morning_x_temp_delta_24h` | interaction | Float/Numeric | derived | 영업일 오전 x 전일 대비 기온 변화 | 평일 오전 ramp의 날씨 반응 |
| 41 | `business_morning_x_temp_anomaly_7d` | interaction | Float/Numeric | derived | 영업일 오전 x 최근 7일 대비 기온 편차 | 갑작스런 오전 냉난방 수요 |
| 42 | `business_morning_x_temp_anomaly_doy` | interaction | Float/Numeric | derived | 영업일 오전 x 계절 대비 기온 편차 | 계절 평균 대비 이른 냉난방 |
| 43 | `business_late_afternoon_x_temp_delta_1h` | interaction | Float/Numeric | derived | 영업일 15-18시 x 기온 방향 | 오후 상승/하강 국면 분리 |
| 44 | `business_late_afternoon_x_cooling_delta_1h` | interaction | Float/Numeric | derived | 영업일 15-18시 x 냉방 변화 | 냉방 감소/증가 방향 반영 |
| 45 | `holiday_x_heat` | interaction | Float/Numeric | derived | 연속 휴일 x 더위 | 연휴 중 더운 날의 수요 왜곡 |
| 46 | `post_holiday_x_heat` | interaction | Float/Numeric | derived | 연휴 종료 직후 x 더위 | 복귀일 업무/냉방 spike 보완 |
| 47 | `business_hour_x_post_holiday_heat` | interaction | Float/Numeric | derived | 영업시간 x 연휴 직후 x 더위 | 낮 업무 수요 복귀와 더위 결합 |
| 48 | `lag_24h_dsh` | ordinal context | Integer/Numeric | calendar lag | 전날의 휴일 종료 후 경과일 | 전날 lag의 post-holiday 오염 감지 |
| 49 | `lag_24h_consec` | ordinal context | Integer/Numeric | calendar lag | 전날 기준 연속 휴일 길이 | 전날 lag가 휴일 체제였는지 감지 |
| 50 | `lag_168h_dsh` | ordinal context | Integer/Numeric | calendar lag | 1주 전 휴일 종료 후 경과일 | 전주 lag 오염 감지 |
| 51 | `lag_24h_business_type_mismatch` | binary flag | Integer/Numeric | calendar | 오늘과 전날 영업 타입 차이 | Fri->Sat, Sun->Mon 전환 핵심 |
| 52 | `lag_24h_mismatch_x_business_hour` | interaction | Float/Numeric | derived | mismatch x 영업시간 | 영업시간 차이를 집중 반영 |
| 53 | `recent_same_business_type_mean` | anchor statistic | Float/Numeric | actual history | 최근 같은 영업 타입 평균 | 영업/비영업 anchor |
| 54 | `lag_24h_to_last_biz_gap` | continuous gap | Float/Numeric | derived | 직전 영업일 수요 - `lag_24h` | 휴일 후 평일 복귀 shortfall 감지 |
| 55 | `lag_24h_to_same_business_type_gap` | continuous gap | Float/Numeric | derived | same-business anchor - `lag_24h` | business return guard와 연결 |
| 56 | `lag_24h_gap_x_business_hour` | interaction | Float/Numeric | derived | gap x 영업시간 | 낮 시간대 lag 부족/과열 신호 |
| 57 | `humidity_pct` | continuous weather | Float/Numeric | JMA/AMeDAS or fallback | 상대습도 | 고습 부하 직접 신호 |
| 58 | `discomfort_index` | continuous derived | Float/Numeric | temp + humidity | 습도 기반 불쾌지수 | 덥고 습한 날 수요 신호 |
| 59 | `humidity_delta_24h` | continuous delta | Float/Numeric | weather lag | 전날 같은 시간 대비 습도 변화 | 오전/낮 체감 변화 |
| 60 | `discomfort_delta_24h` | continuous delta | Float/Numeric | weather lag | 전날 대비 불쾌지수 변화 | 체감 부하 regime 변화 |
| 61 | `business_morning_x_humidity_delta_24h` | interaction | Float/Numeric | derived | 영업일 오전 x 습도 변화 | 습한 오전 ramp 문맥 |
| 62 | `business_morning_x_discomfort_delta_24h` | interaction | Float/Numeric | derived | 영업일 오전 x 불쾌지수 변화 | 고습 영업일 오전 냉방 부하 |
| 63 | `business_daytime_x_discomfort_index` | interaction | Float/Numeric | derived | 영업일 낮 x 불쾌지수 | 고습 낮 시간대 레벨 문맥 |

---

## 5. Inference-only Context & Guard 변수

아래 변수는 LightGBM 학습에는 사용하지 않고, 예측 생성 시점의 진단 및 guard 판단에 사용합니다.

| 변수명 | 용도 |
|---|---|
| `lag_24h_hourly_delta` | 전날 같은 날의 시간별 변화율 |
| `lag_168h_hourly_delta` | 전주 같은 날의 시간별 변화율 |
| `recent_same_business_type_delta_mean` | 최근 같은 영업 타입의 평균 시간별 변화 |
| `recent_same_business_type_delta_q25` | 같은 영업 타입 변화량의 하위 quantile |
| `same_day_latest_actual_hour` | 당일 최신 실측 hour |
| `same_day_latest_hourly_delta` | 최신 당일 실측 기울기 |
| `same_day_recent_hourly_delta_mean` | 최근 당일 실측 평균 기울기 |
| `business_midday_x_lag_24h_delta` | 영업일 점심 x lag24 delta |
| `business_midday_x_recent_delta_mean` | 영업일 점심 x 최근 평균 delta |
| `business_midday_x_recent_delta_q25` | 영업일 점심 x 최근 q25 delta |
| `business_midday_x_same_day_recent_delta_mean` | 영업일 점심 x 당일 최근 기울기 |

전역 학습 피처로 승격하기 전에는 특정 시간대 외 부작용을 반드시 확인해야 합니다.

---

## 6. 후처리 레이어

### 후처리 파이프라인 실행 순서

후처리는 직렬 파이프라인입니다. 앞 단계의 결과가 다음 단계의 입력이 되므로 순서가 예측선 shape에 직접 영향을 줍니다.

```text
Raw LightGBM Forecast
  -> Analogous Day Adjustment
  -> Post-holiday / Timeband Guard
  -> Midday Transition Guard
  -> Localized Shape Spike Guard
  -> Intraday Residual Correction
  -> Forecast Snapshots / Operational Calibration / Reports
```

현재 `run_batch.py` 기준 stage 이름은 `raw_lgbm`, `analog_adjusted`, `post_holiday_guarded`, `midday_guarded`, `localized_shape_guarded`, `pre_calibration`입니다. Intraday residual correction은 `pre_calibration` 이후 당일 실측을 반영하는 운영 보정 단계입니다.

| 레이어 | 구현 | 목적 |
|---|---|---|
| Analogous day | `AnalogousDayAdjuster` | 유사 과거일 residual로 raw forecast 보정 |
| Post-holiday timeband | `PostHolidayTimeBandGuard` | 유사일 보정이 잘못된 방향으로 밀리는 것을 제한 |
| Business return anchor shortfall | `PostHolidayTimeBandGuard` | 예측 shape도 부족할 때만 휴일/주말 lag가 영업일 오전을 과도하게 낮추는 문제 완화 |
| Midday transition guard | `MiddayTransitionGuard` | 영업일 12시 lunch dip이 지나치게 평활화되는 문제 완화 |
| Localized shape spike guard | `LocalizedShapeSpikeGuard` | intraday residual 적용 전에 근거 없는 한 시간짜리 오후 피크를 감쇠 |
| Intraday residual correction | `IntradayResidualCorrector` | 당일 실측 residual을 남은 시간에 보수적으로 반영 |
| Day-boundary carryover | intraday calibration | 자정 경계에서 마지막 진짜 실측 residual을 약하게 이월 |
| Business transition prior | intraday calibration | 실측 부족 구간에서 영업/비영업 전환 prior 적용 |
| Negative residual recovery damping | intraday calibration | 주말 회복 국면에서 음수 residual 전파 과잉 방지 |
| Negative residual continuity floor | intraday calibration | 비영업일 초반 음수 residual이 안정적인 당일 plateau를 최신 실측보다 과하게 낮추는 문제 방지 |
| Positive residual slope damping | intraday calibration | 실측 slope 둔화/하락 시 양수 residual 폭주 방지 |
| Morning ramp continuity guard | intraday calibration | 영업일 오전 near-term dip 방지 |
| Morning observed ramp floor | intraday calibration | 당일 실측이 이미 강한 오전 ramp를 보였을 때 다음 1~2시간 영업일 오전 예측을 보수적으로 지지 |
| Evening decline continuity guard | intraday calibration | 저녁 하락 국면의 near-term rebound spike와 높은 레벨 overhang 제한 |

후처리 레이어의 기본 원칙:

- TEPCO 예측을 직접 따라가지 않습니다.
- 특정 하루만 맞추는 날짜 하드코딩을 넣지 않습니다.
- cap, shrinkage, max lead time을 둡니다.
- 적용 여부와 MW 효과를 metadata에 남깁니다.

---

## 7. 운영 Config 및 검증 기준

### 주요 config

| 영역 | 설정 (Config Key) | 현재 값 | 운영 가이드 및 튜닝 팁 |
|---|---|---:|---|
| weather | `cooling_base_temp_c` | 22.0 | 낮추면 냉방 민감도가 빨리 켜지고, 올리면 여름 초입 과대반응을 줄입니다. 계절 전체 backtest로 조정해야 합니다. |
| weather | `heating_base_temp_c` | 18.0 | 올리면 난방 수요 신호가 강해지고, 내리면 겨울철 과민 반응을 줄입니다. |
| weather bias | `min_abs_bias_c` | 1.5 | 낮추면 예보 bias correction이 자주 켜지고, 높이면 작은 예보 오차를 무시합니다. 너무 낮으면 날씨 noise를 추종합니다. |
| interval | `min_p95_half_width_mw` | 500 | 밴드 과소폭 방지 하한입니다. 올리면 안정적으로 보이지만 경보 민감도가 낮아질 수 있습니다. |
| interval | `max_p95_half_width_mw` | 3000 | 드문 한쪽 quantile tail 폭주를 제한합니다. 낮추면 밴드가 읽기 쉬워지지만 불안정한 날의 실제 불확실성을 과소표현할 수 있습니다. |
| interval | `max_p95_asymmetry_ratio` | 2.5 | 상단/하단 tail 비대칭을 제한합니다. 낮추면 밴드가 더 대칭적이고, 높이면 모델이 추정한 skew를 더 보존합니다. |
| intraday | `lookback_hours` | 3 | 짧게 잡으면 최근 변화에 민감하고, 길게 잡으면 안정적이지만 반응이 늦습니다. |
| intraday | `decay_per_hour` | 0.92 | 높이면 residual 영향이 먼 미래까지 남고, 낮추면 근거리 보정 중심이 됩니다. shape 오염이 있으면 낮추는 쪽을 검토합니다. |
| intraday | `max_abs_adjustment_mw` | 1200 | 당일 residual 보정의 하드 상한입니다. 올리면 큰 오차를 빠르게 따라가지만 폭주 위험이 커집니다. |
| intraday | `morning_observed_ramp_floor.max_lift_mw` | 1200 | 당일 실측 ramp 증거가 강할 때만 08~11시 근거리 영업일 오전 예측을 지지합니다. 올리면 갑작스러운 ramp 과소예측에는 강해지지만, 일시적 실측 급등을 과도하게 따라갈 수 있습니다. |
| intraday | `morning_observed_ramp_floor.non_business_floor_basis` | latest | 비영업일 늦은 ramp에서는 최신 slope가 2,000 MW 이상이고 평균 slope가 1,200 MW 이상일 때, 두 구간 평균 대신 최신 실측 slope를 floor 기준으로 씁니다. 주말 오전을 무조건 올리지 않도록 `non_business_max_lift_mw`는 보수적으로 유지합니다. |
| intraday | `morning_observed_anchor_cap.max_reduction_mw` | 1000 | 당일 실측이 이미 모델 과대예측을 보여주고 lag/recent shape가 공개 예측 레벨을 설명하지 못할 때, 가까운 09~13시 예측만 제한합니다. |
| intraday | `morning_observed_anchor_cap.ramp_veto` | enabled | 최신 당일 ramp가 폭발적으로 강하고, 최근 2구간 평균 ramp도 강하며, shape support가 충분하고 최신 over-forecast가 작을 때 cap을 건너뜁니다. 실제 오전 ramp-up을 보호하되 심각한 과대예측 방어는 유지합니다. |
| intraday | `afternoon_observed_anchor_cap.max_reduction_mw` | 1200 | 당일 오후 실측이 지속적인 과대예측을 보여줄 때, 가까운 14~16시 plateau overhang만 제한합니다. 올리면 미지원 낮 시간대 plateau에 더 빨리 반응하지만 실제 오후 수요 상승을 누를 수 있습니다. |
| intraday | `morning_warm_lag_overreaction_guard.max_reduction_mw` | 800 | 따뜻해진 오전의 lag/기상 상승 신호가 당일 실측으로 확인되지 않을 때 q50 추가 하방 제동을 제한합니다. 올리면 과대예측 반응은 빨라지지만 실제 냉방 ramp를 누를 수 있습니다. |
| intraday | `morning_positive_residual_carryover_damping.damping_factor` | 0.4 | 오전 초반 과소예측에서 생긴 양수 residual이 target slot의 lag/recent 램프 근거 없이 10~13시로 과전파될 때 일부만 통과시킵니다. 낮추면 과전파를 더 빨리 줄이고, 높이면 실제 램프 모멘텀을 더 보존합니다. |
| intraday | `negative_residual_continuity_floor.max_restore_mw` | 900 | 비영업일 예측선이 안정적인 당일 plateau 아래로 밀렸을 때 되돌릴 수 있는 최대치입니다. 올리면 토요일 plateau 보호가 강해지지만 실제 하락을 늦게 반영할 수 있습니다. |
| intraday | `negative_residual_continuity_floor.floor_slack_mw` | 500 | 최신 실측 plateau보다 어느 정도 낮아져야 floor가 개입할지 정하는 버퍼입니다. 낮추면 더 빨리 개입하고, 높이면 명확한 undercut에서만 작동합니다. |
| intraday | `evening_decline_continuity_guard.level_overhang_enabled` | true | 저녁 하락 국면에서 국소 rebound뿐 아니라 높은 레벨로 버티는 overhang도 제한합니다. 더운 저녁의 실제 수요까지 누르는 경우에만 비활성화를 검토합니다. |
| intraday | `ramp_guard.observed_drop_relaxation.decline_support` | enabled | 실측 수요가 이미 하락 중이고 대상 시간의 lag/recent delta가 모두 강한 하락을 지지할 때만 마지막 drop cap을 더 넓게 허용합니다. cap을 올리면 저녁 급락을 더 보존하고, 낮추면 직전 실측 레벨에 더 가깝게 유지합니다. |
| post-processing | `post_holiday_timeband_guard.daytime.lag24_warm_day_weather_allowance_mw_per_c` | 1200 | 오늘이 전날보다 뚜렷하게 더울 때 warm-day lag24 cap에 추가 여유를 줍니다. 올리면 급격한 기온 상승일의 가짜 골짜기를 줄이고, 낮추면 어제 수요 anchor를 더 엄격하게 적용합니다. |
| post-processing | `business_return_anchor_shortfall.min_shape_shortfall_mw` | 800 | 영업일 복귀 anchor 리프트 전에 예측 램프가 최근 같은 영업 타입 램프보다 충분히 부족한지 확인합니다. 낮추면 더 자주 올리고, 높이면 이미 건강한 raw shape를 과하게 돕는 위험을 줄입니다. |
| post-processing | `localized_shape_spike_guard.max_reduction_mw` | 700 | intraday 보정 전에 근거 없는 단일 오후 피크를 줄일 수 있는 최대치입니다. 올리면 artifact 제거가 강해지고, 내리면 raw/analog 피크 shape를 더 보존합니다. |
| post-processing | `localized_shape_spike_guard.min_neighbor_excess_mw` | 600 | 양쪽 이웃 시간보다 이 값 이상 높을 때만 guard를 평가합니다. 낮추면 작은 artifact도 잡지만 실제 국소 피크를 건드릴 수 있습니다. |
| forecast snapshots | `retention_days` | 21 | 예측선 변화를 사후 분석할 수 있는 공개 snapshot 보관 기간입니다. |
| calibration snapshots | `retention_days` | 14 | 보정 레이어 원인 분석용 내부 snapshot 보관 기간입니다. 너무 짧으면 장애 원인 추적이 어려워집니다. |
| reserve risk | warning | 92% | TEPCO 기준 경고 구간입니다. 낮추면 경고가 많아지고, 높이면 사전 경보성이 약해집니다. |
| reserve risk | critical | 97% | TEPCO 기준 위험 구간입니다. 운영 UI에서는 warning과 명확히 구분해 표시합니다. |

### 평가 지표

| 지표 | 정의 | 운영 해석 |
|---|---|---|
| MAE | 평균 절대 오차, MW | 직관적인 평균 오차 |
| WAPE | `sum(abs(error)) / sum(actual)` | 하루 수요 scale 대비 오차율 |
| RMSE | 제곱 평균 오차의 제곱근 | 큰 오차 spike에 민감 |
| Max Error MW | 하루 최대 절대 오차 | 운영 리스크 확인 |
| Dominance Hours | TEPCO보다 오차가 작은 시간 수 | 보조 지표 |

### Known Risks

| 리스크 | 증상 | 대응 |
|---|---|---|
| 계절 전환기 | lag와 오늘 기온 regime 불일치 | `temp_delta`, day-level scale 확인 |
| 점심 dip | 12시 bucket이 너무 평평하거나 과도하게 꺼짐 | midday guard와 q25 delta 확인 |
| 저녁 rebound | 실측 하락 중 예측 반등 | evening decline guard 확인 |
| 월요일 오전 | 일요일 lag가 평일 ramp를 낮춤 | business return anchor shortfall 확인 |
| 토요일 오전 | 금요일 lag가 주말 수요를 높임 | business transition prior 확인 |
| 23시 실측 지연 | 전날 마지막 실측 공백 | fallback source flag 확인 |
| TEPCO ZIP 403 | GitHub Actions ETL 실패 | 로컬 ETL 또는 별도 runner 사용 |
| 기상 API 장애 | 온도/습도 NaN 또는 fallback 과다 | `weather_source` 비율 확인 |
| 모델 배치 재학습 실패(Dry rot) | 데이터는 쌓이지만 모델이 재학습되지 않거나 오래된 `.lgbm_model.pkl`로 계속 추론 | 최소 학습량 90일 유지, 모델 저장 시각, interval version, ETL 학습 로그를 확인합니다. 실패 시 기존 최신 가중치로 추론은 유지하되 운영 리포트에 재학습 실패를 남깁니다. |

---

## 8. 모델 수정 Runbook

### 피처 추가/변경

- `FEATURE_COLS`에 넣을지 inference-only context로 둘지 먼저 결정합니다.
- 학습 피처라면 결측률과 row 감소량을 확인합니다.
- `build_training_features`와 `build_inference_features` 양쪽에서 동일하게 생성되는지 확인합니다.
- 미래 actual이나 확정 후 데이터가 섞이는 leakage가 없는지 확인합니다.
- 전체 MAE뿐 아니라 시간대별 WAPE/RMSE와 shape 부작용을 확인합니다.
- `lgbm-design.md`, 이 문서, 필요한 model-improvement 문서를 갱신합니다.

### Guard 수정

- raw LightGBM forecast를 직접 바꾸는지, residual carryover만 바꾸는지 구분합니다.
- trigger가 특정 날짜/사건 하드코딩이 아닌지 확인합니다.
- cap, shrinkage, max lead hours를 반드시 둡니다.
- 이미 관측된 과거 forecast freeze 정책을 침범하지 않습니다.
- metadata에 `...Applied`, `...MaxMw`, `appliedRegimeReason`이 남는지 확인합니다.
- 단위 테스트와 운영 snapshot을 함께 확인합니다.

### 사고 대응

| 상황 | 먼저 볼 산출물 |
|---|---|
| 예측선이 갑자기 튐 | `reports/internal/operational-calibration/YYYY-MM-DD.json` |
| TEPCO보다 하루 종일 낮음/높음 | `reports/internal/daily-diagnostics/YYYY-MM-DD.json` |
| 점심만 이상함 | forecast snapshot + midday context |
| 저녁 spike | evening guard metadata |
| 오전 ramp 실패 | business return/morning ramp metadata |
| 밴드가 너무 좁음 | `interval_calibration` |
| AI 리포트가 이상함 | `reports/ai/daily/`, generator metadata |

운영 개선의 기본 원칙은 단순합니다. 먼저 데이터 소스와 residual carryover를 의심하고, 그 다음 feature와 guard를 봅니다. 상방 보정은 보수적으로, residual damping은 근거리 중심으로 적용하며, 모든 guard는 설명 가능한 metadata를 남겨야 합니다.
