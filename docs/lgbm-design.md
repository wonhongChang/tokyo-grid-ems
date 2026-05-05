# LightGBM 예측 모델 설계

> Phase 5-A: 통계 기반 베이스라인을 LightGBM ML 모델로 교체  
> 기온 데이터 없이 캘린더·래그 피처만 사용

---

## 목표

| 항목 | 현재 (baseline) | 목표 (LightGBM) |
|---|---|---|
| 모델 종류 | 동일 요일 평균/표준편차 | Gradient Boosting (LightGBM) |
| 피처 수 | 암묵적 2개 (요일·시간) | 명시적 ~12개 |
| 공휴일 처리 | 계절 윈도우 수동 선택 | `is_holiday` 피처로 자동 학습 |
| 예측 불확실성 | 정규분포 가정 (1.96σ) | quantile regression (q10/q90) |
| 평가 지표 | 없음 | RMSE, MAE, MAPE |

---

## 피처 설계

```python
# 시간 피처 (캘린더)
'hour'          # 0–23
'dayofweek'     # 0(월)–6(일)
'month'         # 1–12
'is_holiday'    # 0/1  (jpholiday)
'is_weekend'    # 0/1

# 래그 피처 (과거 실적)
'lag_24h'       # 어제 같은 시간 actual_mw
'lag_48h'       # 2일 전 같은 시간
'lag_168h'      # 1주 전 같은 시간 (가장 중요)
'lag_336h'      # 2주 전 같은 시간

# 롤링 통계 (같은 시간대 + 같은 요일 최근 N주)
'roll_4w_mean'  # 최근 4주 같은 (hour, dayofweek) 평균
'roll_4w_std'   # 최근 4주 같은 (hour, dayofweek) 표준편차

# 공급 피처 (가용 시)
'supply_mw'     # 직전 알려진 공급력 (예측 시점에 알 수 있는 값)
```

> **래그 피처 주의사항**: 내일 예측 시점에는 오늘 실적이 일부만 확정.  
> lag_24h 등은 훈련 시에는 정확하지만 추론 시 마지막 확정 시간 기준으로 채워야 함.

---

## 파일 구조

```
python/
  forecast/
    baseline.py          # 기존 통계 모델 (폴백용으로 유지)
    lgbm_model.py        # 신규: LightGBM 훈련/추론
    feature_builder.py   # 신규: 공통 피처 엔지니어링
  etl/
    run_batch.py         # 수정: LightGBM 훈련 + 예측 통합
```

---

## lgbm_model.py 설계

```python
class LGBMForecaster:
    def __init__(self, n_estimators=500, learning_rate=0.05):
        ...

    def fit(self, cache: pd.DataFrame) -> None:
        """hourly_cache로 훈련. 최소 90일 이상 데이터 필요."""
        X, y = build_features(cache)
        # quantile regression: q10, q50, q90
        self.model_q10 = lgb.train(params_q10, ...)
        self.model_q50 = lgb.train(params_q50, ...)
        self.model_q90 = lgb.train(params_q90, ...)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """target_date의 24시간 예측 반환. HourlyForecast 리스트."""
        ...

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> 'LGBMForecaster':
        return joblib.load(path)
```

---

## 불확실성 추정: Quantile Regression

현재 baseline은 정규분포를 가정해 `mean ± 1.96σ`로 p95 구간을 만들어요.  
LightGBM에서는 quantile regression으로 직접 학습합니다:

```python
# 세 개의 모델을 각각 훈련
params_q10 = {'objective': 'quantile', 'alpha': 0.10, ...}
params_q50 = {'objective': 'quantile', 'alpha': 0.50, ...}  # 중앙값 = 예측값
params_q90 = {'objective': 'quantile', 'alpha': 0.90, ...}
```

출력:
- `forecastMw` = q50
- `p95LowerMw` = q10 (실제로는 80% 구간이지만 기존 필드 재활용)
- `p95UpperMw` = q90

> 나중에 기온 피처 추가 시 모델만 재훈련하면 되고, 출력 인터페이스는 동일.

---

## run_batch.py 통합 전략

```python
# 기존 흐름에 추가
from python.forecast.lgbm_model import LGBMForecaster

MODEL_PATH = out_dir / ".lgbm_model.pkl"
MIN_TRAIN_DAYS = 90

# 캐시 구축 완료 후
if len(hourly_cache) >= MIN_TRAIN_DAYS * 24:
    forecaster = LGBMForecaster()
    forecaster.fit(hourly_cache)
    forecaster.save(MODEL_PATH)
else:
    forecaster = None

def get_forecast(target_date):
    if forecaster:
        return forecaster.predict(target_date, hourly_cache)
    return compute_forecast(hourly_cache, target_date, ...)  # baseline 폴백
```

**모델 파일 관리**: `.lgbm_model.pkl`은 `web/public/`에 저장해 Actions 간 캐싱.  
`.gitignore`에는 추가하지 않음 (캐시 파일처럼 커밋).

---

## 평가 방법

### Walk-forward validation (Walk-forward CV)

```
전체 데이터: 2022-01-01 ~ 2026-05-04 (약 1220일)

훈련: 2023-01-01 ~ 2025-12-31
테스트: 2026-01-01 ~ 2026-05-04 (최근 4개월)
```

평가 지표:
```python
RMSE = sqrt(mean((actual - forecast)^2))
MAE  = mean(abs(actual - forecast))
MAPE = mean(abs((actual - forecast) / actual)) * 100
```

베이스라인과 수치 비교 후 `web/public/model_eval.json`으로 저장.  
(나중에 UI에 "모델 성능" 카드로 표시 가능)

---

## 구현 순서

1. `feature_builder.py` 작성 및 단위 테스트
2. `lgbm_model.py` 작성 (fit / predict / save / load)
3. walk-forward CV 스크립트 작성 (`python/eval/compare_models.py`)
4. `run_batch.py` 통합
5. `requirements.txt`에 `lightgbm`, `joblib` 추가
6. `.github/workflows/etl.yml` — 모델 파일 커밋 포함 확인

---

## 예상 효과

기온 없이 래그 피처만으로도:
- 연속적인 평일 트렌드 반영 (어제가 높으면 오늘도 높을 가능성)
- 공휴일 전날·후날 패턴 자동 학습
- 계절 전환기 급격한 수요 변화 포착

현재 baseline 대비 RMSE **10~20% 개선** 예상 (기온 없는 한계).
