# LightGBM 予測モデル設計

> Phase 5-A: 統計ベースラインをLightGBM MLモデルへ置き換え  
> 気温データなし — カレンダー・ラグ特徴量のみ使用

---

## 目標

| 項目 | 現在 (baseline) | 目標 (LightGBM) |
|---|---|---|
| モデル種別 | 同曜日平均/標準偏差 | Gradient Boosting (LightGBM) |
| 特徴量数 | 暗黙的2個 (曜日・時刻) | 明示的 ~12個 |
| 祝日処理 | 季節ウィンドウ手動選択 | `is_holiday` 特徴量で自動学習 |
| 予測不確実性 | 正規分布仮定 (1.96σ) | quantile regression (q10/q90) |
| 評価指標 | なし | RMSE, MAE, MAPE |

---

## 特徴量設計

```python
# 時間特徴量（カレンダー）
'hour'          # 0–23
'dayofweek'     # 0(月)–6(日)
'month'         # 1–12
'is_holiday'    # 0/1  (jpholiday)
'is_weekend'    # 0/1

# ラグ特徴量（過去実績）
'lag_24h'       # 昨日同時刻の actual_mw
'lag_48h'       # 2日前同時刻
'lag_168h'      # 1週前同時刻（最重要）
'lag_336h'      # 2週前同時刻

# ローリング統計（同時刻帯 + 同曜日 直近N週）
'roll_4w_mean'  # 直近4週の同 (hour, dayofweek) 平均
'roll_4w_std'   # 直近4週の同 (hour, dayofweek) 標準偏差

# 供給特徴量（利用可能な場合）
'supply_mw'     # 直前に判明している供給力（予測時点で既知の値）
```

> **ラグ特徴量の注意**: 明日の予測時点では今日の実績が一部のみ確定。  
> lag_24h等は訓練時は正確だが、推論時は最後に確定した時刻基準で埋める必要がある。

---

## ファイル構造

```
python/
  forecast/
    baseline.py          # 既存統計モデル（フォールバック用として維持）
    lgbm_model.py        # 新規: LightGBM 訓練/推論
    feature_builder.py   # 新規: 共通特徴量エンジニアリング
  etl/
    run_batch.py         # 修正: LightGBM 訓練 + 予測統合
```

---

## lgbm_model.py 設計

```python
class LGBMForecaster:
    def __init__(self, n_estimators=500, learning_rate=0.05):
        ...

    def fit(self, cache: pd.DataFrame) -> None:
        """hourly_cacheで訓練。最低90日以上のデータが必要。"""
        X, y = build_features(cache)
        # quantile regression: q10, q50, q90
        self.model_q10 = lgb.train(params_q10, ...)
        self.model_q50 = lgb.train(params_q50, ...)
        self.model_q90 = lgb.train(params_q90, ...)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """target_dateの24時間予測を返す。HourlyForecastのリスト。"""
        ...

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> 'LGBMForecaster':
        return joblib.load(path)
```

---

## 不確実性推定: Quantile Regression

現在のbaselineは正規分布を仮定して `mean ± 1.96σ` でp95区間を生成しています。  
LightGBMではquantile regressionで直接学習します:

```python
# 3つのモデルをそれぞれ訓練
params_q10 = {'objective': 'quantile', 'alpha': 0.10, ...}
params_q50 = {'objective': 'quantile', 'alpha': 0.50, ...}  # 中央値 = 予測値
params_q90 = {'objective': 'quantile', 'alpha': 0.90, ...}
```

出力:
- `forecastMw` = q50
- `p95LowerMw` = q10 (実際には80%区間だが既存フィールドを再利用)
- `p95UpperMw` = q90

> 後で気温特徴量を追加する場合もモデルの再訓練のみで済み、出力インターフェースは同一。

---

## run_batch.py 統合戦略

```python
from python.forecast.lgbm_model import LGBMForecaster

MODEL_PATH = out_dir / ".lgbm_model.pkl"
MIN_TRAIN_DAYS = 90

# キャッシュ構築完了後
if len(hourly_cache) >= MIN_TRAIN_DAYS * 24:
    forecaster = LGBMForecaster()
    forecaster.fit(hourly_cache)
    forecaster.save(MODEL_PATH)
else:
    forecaster = None

def get_forecast(target_date):
    if forecaster:
        return forecaster.predict(target_date, hourly_cache)
    return compute_forecast(hourly_cache, target_date, ...)  # baselineフォールバック
```

**モデルファイル管理**: `.lgbm_model.pkl` は `web/public/` に保存してActions間でキャッシュ。  
`.gitignore` には追加しない（キャッシュファイルと同様にコミット）。

---

## 評価方法

### Walk-forward Validation

```
全データ: 2023-01-01 ~ 2026-05-04 (約1220日)

訓練: 2023-01-01 ~ 2025-12-31
テスト: 2026-01-01 ~ 2026-05-04 (直近4ヶ月)
```

評価指標:
```python
RMSE = sqrt(mean((actual - forecast)^2))
MAE  = mean(abs(actual - forecast))
MAPE = mean(abs((actual - forecast) / actual)) * 100
```

baselineとの数値比較後、`web/public/model_eval.json` として保存。  
（後でUIに「モデル性能」カードとして表示可能）

---

## 実装順序

1. `feature_builder.py` 作成 + 単体テスト
2. `lgbm_model.py` 作成 (fit / predict / save / load)
3. walk-forward CVスクリプト作成 (`python/eval/compare_models.py`)
4. `run_batch.py` 統合
5. `requirements.txt` に `lightgbm`, `joblib` 追加
6. `.github/workflows/etl.yml` — モデルファイルのコミット確認

---

## 期待される効果

気温なしでラグ特徴量のみでも:
- 連続する平日トレンドの反映（昨日が高ければ今日も高い可能性）
- 祝日前後のパターン自動学習
- 季節変わり目の急激な需要変化の捕捉

現在のbaseline対比 RMSE **10〜20%改善**予想（気温なしの限界）。
