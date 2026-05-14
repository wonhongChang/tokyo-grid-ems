# 기온 데이터 연동 설계

> 운영 기능: LightGBM 모델에 Open-Meteo 기온 피처 추가
> Open-Meteo API (무료, 인증 없음) — 도쿄 좌표 기준

언어: [English](../en/weather-integration.md) · [日本語](../ja/weather-integration.md)

---

## 왜 기온인가

전력 수요의 30–40%는 기온으로 설명됩니다.

| 계절 | 메커니즘 | 수요 영향 |
|---|---|---|
| 여름 (7–9월) | 기온 ↑ → 에어컨 부하 ↑ | 강한 양의 상관 |
| 겨울 (12–2월) | 기온 ↓ → 난방 부하 ↑ | 강한 음의 상관 |
| 봄/가을 | 기온 15–20°C 쾌적 구간 | 수요 최소 |

초기 목적은 캘린더·래그 피처만 사용할 때보다 예측을 안정화하는 것이었습니다. 현재 운영에서는 냉난방 수요를 설명하고 고온/저온일 예측을 보정하기 위해 기온 피처를 사용합니다.

---

## 데이터 소스: Open-Meteo

```
API: https://api.open-meteo.com/v1/forecast
도쿄 좌표: latitude=35.6762, longitude=139.6503
시간대: Asia/Tokyo
```

### 무료 엔드포인트 두 가지

| 용도 | 엔드포인트 파라미터 | 내용 |
|---|---|---|
| 과거 실적 | `&past_days=92` | 과거 92일 시간별 실적 기온 |
| 미래 예측 | `&forecast_days=2` | 오늘+내일 시간별 예측 기온 |

### 응답 예시

```json
{
  "hourly": {
    "time": ["2026-05-05T00:00", "2026-05-05T01:00", ...],
    "temperature_2m": [18.3, 17.9, 17.5, ...]
  }
}
```

인증 키 불필요, 상업적 이용 가능 (CC BY 4.0).

---

## 기온 수집 모듈: `python/etl/fetch_weather.py`

```python
TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503
_ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_MAX_RETRIES  = 3

def fetch_past_temps(start: date, end: date) -> pd.DataFrame:
    """도쿄 시간별 과거 기온을 archive API에서 가져옵니다."""

def fetch_forecast_temps(days: int = 3) -> pd.DataFrame:
    """오늘과 앞으로 며칠의 시간별 예측 기온을 가져옵니다."""

def enrich_cache_with_weather(cache: pd.DataFrame) -> pd.DataFrame:
    """actual_mw가 있는 hourly cache 행의 누락된 temp_c를 채웁니다."""
```

`run_batch.py`는 기온을 `.hourly_cache.parquet` 안에 저장하므로 전력 수요 이력과 기온 이력이 함께 이동합니다.

---

## 기온 피처 설계

```python
# 현재 시점 기온 (실적 archive 또는 예측)
'temp_c'              # 해당 시간의 기온 (°C)

# 냉방/난방 degree
'cooling_degree'      # max(0, temp_c - cooling_base_temp_c)
'heating_degree'      # max(0, heating_base_temp_c - temp_c)

# 기온 레짐 컨텍스트
'temp_anomaly_7d'     # temp_c - 최근 7일 평균
'temp_anomaly_doy'    # temp_c - 과거 같은 월/시간 평균
'temp_delta_168h'     # 현재 같은 시간 기온 - 168시간 전 기온
'cooling_delta_168h'  # 현재 냉방 degree - 168시간 전 냉방 degree

# 연휴 복귀 수요와 더위의 교호작용
'holiday_x_heat'
'post_holiday_x_heat'
'business_hour_x_post_holiday_heat'
```

냉방/난방 degree 기준온도는 설정값으로 관리합니다.

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 10.0
```

> **degree 값과 168시간 변화량을 쓰는 이유**: degree 값은 냉난방 수요의 비선형 효과를 다루기 쉽게 만들고, `temp_delta_168h`와 `cooling_delta_168h`는 전주 같은 시간대 수요를 그대로 믿기 어려운 상황을 모델에 알려줍니다.

---

## 파일 구조 변경

```
python/
  etl/
    fetch_weather.py    # 신규: Open-Meteo 수집
    run_batch.py        # 수정: 날씨 캐시 통합
  forecast/
    feature_builder.py  # 수정: 기온 피처 추가
```

```
web/public/
  .hourly_cache.parquet    # temp_c를 포함하는 전력 수요 캐시
  .lgbm_model.pkl          # 학습된 LightGBM 모델
```

---

## `feature_builder.py` 수정

```python
def build_training_features(
    cache: pd.DataFrame,
    config: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    cache: ts, actual_mw, supply_mw, temp_c 등을 포함하는 hourly cache
    config: weather_features 기준온도 포함
    """
    cooling_base_temp_c, heating_base_temp_c = _weather_feature_config(config)
    df["cooling_degree"] = (df["temp_c"] - cooling_base_temp_c).clip(lower=0.0)
    df["heating_degree"] = (heating_base_temp_c - df["temp_c"]).clip(lower=0.0)
    df["temp_delta_168h"] = df["temp_c"] - df["temp_c_168h"]
    df["cooling_delta_168h"] = df["cooling_degree"] - df["cooling_degree_168h"]
    return df[FEATURE_COLS], df["actual_mw"]
```

---

## `run_batch.py` 통합 전략

```python
# hourly cache의 누락된 과거 temp_c를 채웁니다.
hourly_cache = enrich_cache_with_weather(hourly_cache)

# 오늘/내일 예측에 쓸 temp_c를 위해 미래 기온 행을 가상으로 추가합니다.
# 이 행들은 actual_mw가 NaN이라 실측 수요로 취급되지 않습니다.
extended_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)

# 같은 weather feature 설정으로 학습과 추론을 수행합니다.
forecaster = LGBMForecaster(config=config)
forecaster.fit(hourly_cache)
tomorrow_fc = forecaster.predict(tomorrow, extended_cache)
```

---

## GitHub Actions 통합

```yaml
# ETL과 intraday는 python/etl/run_batch.py를 실행합니다.
# 기온 archive/forecast 수집은 batch job 내부에서 처리됩니다.
```

### 캐시 파일 커밋

```yaml
- name: Commit outputs
  run: |
    git add web/public/forecast/ web/public/status.json
    git add web/public/.hourly_cache.parquet || true
    git add web/public/.lgbm_model.pkl || true
    git commit -m "auto: ETL $(date -u +%Y-%m-%dT%H:%M)Z" || true
```

---

## 훈련/추론 시점 기온 소스

| 시점 | 기온 소스 | 비고 |
|---|---|---|
| 훈련 (과거 전체) | Open-Meteo archive API | 과거 `temp_c`는 `.hourly_cache.parquet`에 저장 |
| 어제 예측 | 실적 기온 (확정) | 정확 |
| 오늘 예측 | 실적 기온 (오전) + 예측 기온 (오후) | 혼합 |
| 내일 예측 | Open-Meteo 48h 예측 기온 | ±1–2°C 오차 허용 |

> 내일 기온 예측 오차가 모델 오차에 전파됨.
> 여름 폭염 기간엔 예측 오차가 커질 수 있으므로 quantile 모델과 이상탐지 결과를 그 불확실성까지 고려해 해석해야 합니다.

---

## 평가 계획

Phase 5-A (기온 없음) 대비 비교:

```
테스트 기간: 2026-01-01 ~ 2026-05-04

지표        Phase 5-A    Phase 5-B    개선율
RMSE (MW)   측정 예정     측정 예정     예상 -20~35%
MAE  (MW)   측정 예정     측정 예정
여름 RMSE   측정 예정     측정 예정     개선 더 큼
겨울 RMSE   측정 예정     측정 예정
```

결과는 `web/public/model_eval.json`에 저장:

```json
{
  "evaluated_at": "2026-05-05T09:20:00+09:00",
  "test_period": { "from": "2026-01-01", "to": "2026-05-04" },
  "baseline":  { "rmse": null, "mae": null, "mape": null },
  "lgbm_no_temp": { "rmse": null, "mae": null, "mape": null },
  "lgbm_with_temp": { "rmse": null, "mae": null, "mape": null }
}
```

---

## 현재 구현 체크리스트

1. `fetch_weather.py`는 Open-Meteo archive/forecast 엔드포인트를 retry/backoff와 함께 사용합니다.
2. `run_batch.py`는 과거 `temp_c`를 `.hourly_cache.parquet`에 채웁니다.
3. 미래 예측 기온은 `actual_mw = NaN`인 가상 cache 행으로 추가하고, intraday 실행 때마다 갱신합니다.
4. `feature_builder.py`는 degree 값, 기온 이상치, 168시간 기온 변화량을 포함한 30개 LightGBM 피처를 생성합니다.
5. `LGBMForecaster(config=config)`는 학습과 추론에서 같은 weather feature 설정을 사용합니다.
6. 피처 버전이 바뀌면 기존 저장 모델을 stale로 보고 다음 실행에서 재학습합니다.

---

## 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|---|---|---|
| Open-Meteo API 일시 중단 | 낮음 | retry/backoff 적용, 과거 기온 수집 실패는 non-fatal이며 기존 cache 값 유지 |
| 과거 기온 데이터 공백 | 낮음 | API 복구 후 ETL 재실행, 누락 행은 `temp_c = NaN`으로 남고 모델 학습에서 제외 |
| 기온 래그 feature leakage | 주의 | 추론 시 미래 기온은 예측값만 사용 |
| 여름 폭염 외삽 | 중간 | 훈련 데이터에 과거 폭염 기간 포함 확인 |
