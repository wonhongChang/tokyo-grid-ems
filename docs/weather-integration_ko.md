# 기온 데이터 연동 설계

> 운영 기능: LightGBM 모델에 Open-Meteo 기온 피처 추가
> Open-Meteo API (무료, 인증 없음) — 도쿄 좌표 기준

언어: [English](weather-integration.md) · [日本語](weather-integration_ja.md)

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

## 신규 파일: `python/etl/fetch_weather.py`

```python
import requests
import pandas as pd
from pathlib import Path
from datetime import date

TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503
BASE_URL   = "https://api.open-meteo.com/v1/forecast"

def fetch_weather(past_days: int = 92, forecast_days: int = 2) -> pd.DataFrame:
    """
    Returns DataFrame: ts (tz-aware JST), temp_c (float)
    Covers past_days history + forecast_days future.
    """
    params = {
        "latitude":    TOKYO_LAT,
        "longitude":   TOKYO_LON,
        "hourly":      "temperature_2m",
        "timezone":    "Asia/Tokyo",
        "past_days":   past_days,
        "forecast_days": forecast_days,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["hourly"]

    df = pd.DataFrame({
        "ts":     pd.to_datetime(data["time"]).tz_localize("Asia/Tokyo"),
        "temp_c": data["temperature_2m"],
    })
    return df

def save_weather_cache(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path, index=False)

def load_weather_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_parquet(path)
```

---

## 기온 피처 설계

```python
# 현재 시점 기온 (실적 또는 예측)
'temp_c'         # 해당 시간의 기온 (°C)

# 전일 기온 래그 (수요 관성 반영)
'temp_lag_24h'   # 어제 같은 시간 기온

# 냉난방도일 (HDD/CDD)
'hdd'            # max(0, 18 - temp_c)  — 난방 필요도
'cdd'            # max(0, temp_c - 26)  — 냉방 필요도

# 예측 시점용 (내일 예측 시 Open-Meteo forecast 사용)
'temp_forecast'  # Open-Meteo 예측 기온 (추론 시에만)
```

> **HDD/CDD 선택 이유**: 기온의 비선형 효과를 선형화.
> 18°C 이하에서는 낮을수록 난방 수요 선형 증가.
> 26°C 이상에서는 높을수록 냉방 수요 선형 증가.

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
  .weather_cache.parquet   # 기온 캐시 (모델 파일처럼 커밋)
```

---

## `feature_builder.py` 수정

```python
def build_features(
    power_cache: pd.DataFrame,
    weather_cache: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    power_cache: hourly_cache (ts, actual_mw, supply_mw, ...)
    weather_cache: fetch_weather() 결과 (ts, temp_c)
    """
    df = power_cache.copy()

    # 기존 피처 (캘린더 + 래그)
    df['hour']      = df['ts'].dt.hour
    df['dayofweek'] = df['ts'].dt.dayofweek
    df['month']     = df['ts'].dt.month
    df['is_holiday'] = df['ts'].dt.date.apply(_is_holiday)
    df['is_weekend'] = df['dayofweek'].isin([5, 6]).astype(int)
    df['lag_24h']   = df['actual_mw'].shift(24)
    df['lag_168h']  = df['actual_mw'].shift(168)
    df['lag_336h']  = df['actual_mw'].shift(336)

    # 기온 피처 (weather_cache가 있을 때만)
    if weather_cache is not None:
        df = df.merge(weather_cache, on='ts', how='left')
        df['temp_lag_24h'] = df['temp_c'].shift(24)
        df['hdd'] = (18 - df['temp_c']).clip(lower=0)
        df['cdd'] = (df['temp_c'] - 26).clip(lower=0)

    feature_cols = [
        'hour', 'dayofweek', 'month', 'is_holiday', 'is_weekend',
        'lag_24h', 'lag_168h', 'lag_336h',
        *([ 'temp_c', 'temp_lag_24h', 'hdd', 'cdd' ] if weather_cache is not None else [])
    ]
    X = df[feature_cols].dropna()
    y = df.loc[X.index, 'actual_mw']
    return X, y
```

---

## `run_batch.py` 통합 전략

```python
WEATHER_CACHE_PATH = out_dir / ".weather_cache.parquet"

# ETL 실행 시 날씨 수집 (실패해도 계속 진행)
try:
    weather_df = fetch_weather(past_days=92, forecast_days=2)
    save_weather_cache(weather_df, WEATHER_CACHE_PATH)
except Exception as e:
    print(f"Weather fetch failed (non-fatal): {e}")
    weather_df = load_weather_cache(WEATHER_CACHE_PATH)  # 캐시 fallback

# LightGBM 훈련 시 기온 포함
if forecaster and weather_df is not None:
    forecaster.fit(hourly_cache, weather_cache=weather_df)
else:
    forecaster.fit(hourly_cache)  # 기온 없이 훈련

# 예측 시 내일 예측 기온 사용
tomorrow_weather = weather_df[weather_df['ts'].dt.date == tomorrow] if weather_df is not None else None
tomorrow_fc = forecaster.predict(tomorrow, hourly_cache, weather=tomorrow_weather)
```

---

## GitHub Actions 통합

```yaml
# .github/workflows/etl.yml 에 추가
- name: Fetch weather data
  run: python python/etl/fetch_weather.py --save web/public/.weather_cache.parquet
  continue-on-error: true   # 날씨 API 실패해도 ETL 전체 중단 안 함
```

### 캐시 파일 커밋

```yaml
- name: Commit outputs
  run: |
    git add web/public/forecast/ web/public/status.json
    git add web/public/.weather_cache.parquet || true  # 없어도 OK
    git add web/public/.lgbm_model.pkl || true
    git commit -m "auto: ETL $(date -u +%Y-%m-%dT%H:%M)Z" || true
```

---

## 훈련/추론 시점 기온 소스

| 시점 | 기온 소스 | 비고 |
|---|---|---|
| 훈련 (과거 전체) | `past_days=365` 실적 기온 | 연 1회 풀 재학습 가능 |
| 어제 예측 | 실적 기온 (확정) | 정확 |
| 오늘 예측 | 실적 기온 (오전) + 예측 기온 (오후) | 혼합 |
| 내일 예측 | Open-Meteo 48h 예측 기온 | ±1–2°C 오차 허용 |

> 내일 기온 예측 오차가 모델 오차에 전파됨.
> 여름 폭염 기간엔 예측 오차가 크므로 불확실성 밴드가 자동으로 넓어짐 (quantile regression 특성).

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

## 구현 순서

1. `fetch_weather.py` 작성 및 수동 테스트 (`python -m python.etl.fetch_weather`)
2. `feature_builder.py`에 기온 피처 추가 + 단위 테스트
3. `LGBMForecaster.fit()` — `weather_cache` 선택 인자 추가
4. `run_batch.py` 통합 (날씨 fetch → 모델 훈련 → 예측)
5. `requirements.txt`에 `requests` 확인 (이미 있을 가능성 높음)
6. `compare_models.py`로 A/B 평가 후 `model_eval.json` 저장
7. (선택) UI에 "모델 성능" 카드 추가

---

## 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|---|---|---|
| Open-Meteo API 일시 중단 | 낮음 | `continue-on-error: true` + 이전 캐시 사용 |
| 과거 기온 데이터 공백 | 낮음 | `past_days` 값 늘려 재수집 가능 |
| 기온 래그 feature leakage | 주의 | 추론 시 미래 기온은 예측값만 사용 |
| 여름 폭염 외삽 | 중간 | 훈련 데이터에 과거 폭염 기간 포함 확인 |
