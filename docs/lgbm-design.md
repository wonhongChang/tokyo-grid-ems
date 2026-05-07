# LightGBM 예측 모델 설계

> Phase 5-A: 통계 기반 베이스라인을 LightGBM ML 모델로 교체  
> 기온 데이터 없이 캘린더·래그·공휴일 보정 피처만 사용

---

## 목표

| 항목 | 현재 (baseline) | 목표 (LightGBM) |
|---|---|---|
| 모델 종류 | 동일 요일 평균/표준편차 | Gradient Boosting (LightGBM) |
| 피처 수 | 암묵적 2개 (요일·시간) | 명시적 17개 |
| 공휴일 처리 | 계절 윈도우 수동 선택 | `is_holiday` + 연휴 래그 보정 피처 |
| 예측 불확실성 | 정규분포 가정 (1.96σ) | quantile regression (q10/q90) |
| 평가 지표 | 없음 | RMSE, MAE, MAPE |

---

## 피처 설계 (17개)

```python
# 캘린더 피처
'hour'                   # 0–23
'dayofweek'              # 0(월)–6(일)
'month'                  # 1–12
'is_holiday'             # 0/1  (jpholiday 법정 공휴일)
'is_weekend'             # 0/1  (토·일)
'is_non_business_day'    # 0/1  (is_holiday OR is_weekend)

# 래그 피처 (과거 실적)
'lag_24h'       # 어제 같은 시간 actual_mw
'lag_48h'       # 2일 전 같은 시간
'lag_168h'      # 1주 전 같은 시간 (가장 중요)
'lag_336h'      # 2주 전 같은 시간

# 롤링 통계 (같은 시간대 + 같은 요일 최근 4주)
'roll_4w_mean'  # 최근 4주 같은 (hour, dayofweek) 평균
'roll_4w_std'   # 최근 4주 같은 (hour, dayofweek) 표준편차

# 연휴 래그 보정 (골든위크·오봉 등 연휴 직후 과소예측 방지)
'lag_last_biz_hour'       # 마지막 평일(비공휴일 주중) 동일 시간 actual_mw
'lag_last_nonhol_hour'    # 마지막 비공휴일(주말 포함) 동일 시간 actual_mw
'consec_holiday_len'      # 해당 날짜 직전 연속 비업무일 수
'days_since_holiday_end'  # 연휴 종료 후 경과 일수 (최대 7, 업무일 중에만 유효)
'major_holiday_season'    # 0=보통 1=골든위크권 2=오봉권 3=연말연시권
```

> **연휴 래그 보정 배경**: 골든위크 직후처럼 lag_24h/lag_168h가 연휴(저수요)를 가리키는 경우,  
> lag_last_biz_hour가 직전 평일 수요를 참조해 과소예측을 보정합니다.

---

## 파일 구조

```
python/
  forecast/
    baseline.py          # 기존 통계 모델 (표시용으로 Phase 5-B까지 유지)
    lgbm_model.py        # LightGBM 훈련/추론/저장/로드
    feature_builder.py   # 공통 피처 엔지니어링 (훈련·추론 공유)
  eval/
    compare_models.py    # walk-forward 평가 스크립트
  etl/
    run_batch.py         # LightGBM 훈련·저장 통합 (표시는 baseline 유지)
```

---

## lgbm_model.py 설계

```python
class LGBMForecaster:
    MIN_TRAIN_ROWS = 90 * 24  # 최소 90일

    def fit(self, cache: pd.DataFrame) -> None:
        """hourly_cache로 q10/q50/q90 훈련. DataFrame 그대로 전달 (feature name 보존)."""
        X, y = build_training_features(cache)
        self.model_q10 = LGBMRegressor(objective='quantile', alpha=0.10, ...).fit(X, y)
        self.model_q50 = LGBMRegressor(objective='quantile', alpha=0.50, ...).fit(X, y)
        self.model_q90 = LGBMRegressor(objective='quantile', alpha=0.90, ...).fit(X, y)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """target_date의 24시간 예측 반환."""
        X = build_inference_features(cache, target_date)
        ...

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> 'LGBMForecaster':
        return joblib.load(path)
```

---

## 불확실성 추정: Quantile Regression

```python
params_q10 = {'objective': 'quantile', 'alpha': 0.10, ...}
params_q50 = {'objective': 'quantile', 'alpha': 0.50, ...}  # 중앙값 = 예측값
params_q90 = {'objective': 'quantile', 'alpha': 0.90, ...}
```

출력:
- `forecastMw` = q50
- `p95LowerMw` = q10 (실제로는 80% 구간이지만 기존 필드 재활용)
- `p95UpperMw` = q90

---

## run_batch.py 통합 전략 (Phase 5-A)

Phase 5-A에서는 모델을 **훈련·저장만** 하고 표시는 baseline을 유지합니다.  
기온 피처가 추가되는 Phase 5-B에서 LightGBM 예측으로 전환합니다.

```python
# 캐시 구축 완료 후 — 훈련·저장 (표시에는 미사용)
forecaster = _try_train_lgbm(hourly_cache, out_dir)  # .lgbm_model.pkl 저장

# 예측 — Phase 5-B까지 항상 baseline
def _get_forecast(forecaster, cache, target_date, n_weeks, min_samples):
    return compute_forecast(cache, target_date, n_weeks, min_samples), "baseline_dow_hour_mean"
```

**모델 파일 관리**: `.lgbm_model.pkl`은 `web/public/`에 저장해 Actions 간 캐싱.

---

## 평가 방법

### Walk-forward validation

```
훈련: 2023-01-01 ~ 2025-12-31
테스트: 2026-01-01 ~ 최근 (최근 4개월)
```

평가 지표:
```python
RMSE = sqrt(mean((actual - forecast)^2))
MAE  = mean(abs(actual - forecast))
MAPE = mean(abs((actual - forecast) / actual)) * 100
```

결과: `web/public/model_eval.json`

---

## 구현 순서

1. ✅ `feature_builder.py` 작성 및 단위 테스트 (17개 피처)
2. ✅ `lgbm_model.py` 작성 (fit / predict / save / load)
3. ✅ walk-forward CV 스크립트 작성 (`python/eval/compare_models.py`)
4. ✅ `run_batch.py` 통합 (훈련·저장, Phase 5-B까지 baseline 표시)
5. ✅ `requirements.txt`에 `lightgbm`, `joblib`, `scikit-learn` 추가
6. Phase 5-B: 기온 피처 추가 후 LightGBM 예측으로 전환

---

## 예상 효과

기온 없이 래그 피처만으로도:
- 연속 평일 트렌드 반영 (어제가 높으면 오늘도 높을 가능성)
- 골든위크·오봉 직후 복귀 수요 자동 보정 (연휴 래그 피처)
- 계절 전환기 급격한 수요 변화 포착

현재 baseline 대비 RMSE **10~20% 개선** 예상 (기온 없는 한계).  
기온 추가 시 추가 10~15% 개선 기대 (Phase 5-B).
