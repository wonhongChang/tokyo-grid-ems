# LightGBM 予測モデル設計

> Phase 5-A: 統計ベースラインをLightGBM MLモデルへ置き換え  
> 気温データなし — カレンダー・ラグ・祝日補正特徴量のみ使用

---

## 目標

| 項目 | 現在 (baseline) | 目標 (LightGBM) |
|---|---|---|
| モデル種別 | 同曜日平均/標準偏差 | Gradient Boosting (LightGBM) |
| 特徴量数 | 暗黙的2個 (曜日・時刻) | 明示的 17個 |
| 祝日処理 | 季節ウィンドウ手動選択 | `is_holiday` + 連休ラグ補正特徴量 |
| 予測不確実性 | 正規分布仮定 (1.96σ) | quantile regression (q10/q90) |
| 評価指標 | なし | RMSE, MAE, MAPE |

---

## 特徴量設計（17個）

```python
# カレンダー特徴量
'hour'                   # 0–23
'dayofweek'              # 0(月)–6(日)
'month'                  # 1–12
'is_holiday'             # 0/1  (jpholiday 法定祝日)
'is_weekend'             # 0/1  (土・日)
'is_non_business_day'    # 0/1  (is_holiday OR is_weekend)

# ラグ特徴量（過去実績）
'lag_24h'       # 昨日同時刻の actual_mw
'lag_48h'       # 2日前同時刻
'lag_168h'      # 1週前同時刻（最重要）
'lag_336h'      # 2週前同時刻

# ローリング統計（同時刻帯 + 同曜日 直近4週）
'roll_4w_mean'  # 直近4週の同 (hour, dayofweek) 平均
'roll_4w_std'   # 直近4週の同 (hour, dayofweek) 標準偏差

# 連休ラグ補正（ゴールデンウィーク・お盆等の連休直後の過少予測を防ぐ）
'lag_last_biz_hour'       # 直前の平日（非祝日・平日）同時刻の actual_mw
'lag_last_nonhol_hour'    # 直前の非祝日（週末含む）同時刻の actual_mw
'consec_holiday_len'      # 対象日直前の連続非営業日数
'days_since_holiday_end'  # 連休終了後の経過日数（最大7、平日のみ有効）
'major_holiday_season'    # 0=通常 1=GW圏 2=お盆圏 3=年末年始圏
```

> **連休ラグ補正の背景**: GW直後はlag_24h/lag_168hが連休（低需要）を参照するため  
> 系統的な過少予測が発生します。lag_last_biz_hourが直前平日の需要を参照して補正します。

---

## ファイル構造

```
python/
  forecast/
    baseline.py          # 既存統計モデル（Phase 5-Bまで表示用として維持）
    lgbm_model.py        # LightGBM 訓練/推論/保存/ロード
    feature_builder.py   # 共通特徴量エンジニアリング（訓練・推論共用）
  eval/
    compare_models.py    # walk-forward 評価スクリプト
  etl/
    run_batch.py         # LightGBM 訓練統合済み（表示はPhase 5-Bまでbaseline）
```

---

## lgbm_model.py 設計

```python
class LGBMForecaster:
    MIN_TRAIN_ROWS = 90 * 24  # 最低90日

    def fit(self, cache: pd.DataFrame) -> None:
        """hourly_cacheでq10/q50/q90を訓練。DataFrameのまま渡す（特徴量名を保持）。"""
        X, y = build_training_features(cache)
        self.model_q10 = LGBMRegressor(objective='quantile', alpha=0.10, ...).fit(X, y)
        self.model_q50 = LGBMRegressor(objective='quantile', alpha=0.50, ...).fit(X, y)
        self.model_q90 = LGBMRegressor(objective='quantile', alpha=0.90, ...).fit(X, y)

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        """target_dateの24時間予測を返す。"""
        X = build_inference_features(cache, target_date)
        ...

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> 'LGBMForecaster':
        return joblib.load(path)
```

---

## 不確実性推定: Quantile Regression

```python
params_q10 = {'objective': 'quantile', 'alpha': 0.10, ...}
params_q50 = {'objective': 'quantile', 'alpha': 0.50, ...}  # 中央値 = 予測値
params_q90 = {'objective': 'quantile', 'alpha': 0.90, ...}
```

出力マッピング:
- `forecastMw` = q50
- `p95LowerMw` = q10 (実際には80%区間だが既存フィールドを再利用)
- `p95UpperMw` = q90

---

## run_batch.py 統合戦略（Phase 5-A）

Phase 5-Aではモデルを**訓練・保存のみ**し、表示はbaselineを維持します。  
気温特徴量を追加するPhase 5-BでLightGBM予測へ切り替えます。

```python
# キャッシュ構築完了後 — 訓練・保存（表示には未使用）
forecaster = _try_train_lgbm(hourly_cache, out_dir)  # .lgbm_model.pkl を保存

# 予測 — Phase 5-Bまで常にbaseline
def _get_forecast(forecaster, cache, target_date, n_weeks, min_samples):
    return compute_forecast(cache, target_date, n_weeks, min_samples), "baseline_dow_hour_mean"
```

**モデルファイル管理**: `.lgbm_model.pkl`は`web/public/`に保存してActions間でキャッシュ。

---

## 評価方法

### Walk-forward Validation

```
訓練: 2023-01-01 ~ 2025-12-31
テスト: 2026-01-01 ~ 最近（直近約4ヶ月）
```

評価指標:
```python
RMSE = sqrt(mean((actual - forecast)^2))
MAE  = mean(abs(actual - forecast))
MAPE = mean(abs((actual - forecast) / actual)) * 100
```

結果: `web/public/model_eval.json`

---

## 実装状況

1. ✅ `feature_builder.py` 作成 + 単体テスト（17特徴量）
2. ✅ `lgbm_model.py` 作成 (fit / predict / save / load)
3. ✅ walk-forward CVスクリプト作成 (`python/eval/compare_models.py`)
4. ✅ `run_batch.py` 統合（訓練・保存、Phase 5-Bまでbaseline表示）
5. ✅ `requirements.txt` に `lightgbm`, `joblib`, `scikit-learn` 追加
6. Phase 5-B: 気温特徴量追加後にLightGBM予測へ切り替え

---

## 期待される効果

気温なしでラグ特徴量のみでも:
- 連続する平日トレンドの反映（昨日が高ければ今日も高い可能性）
- GW・お盆直後の復帰需要を連休ラグ特徴量で自動補正
- 季節変わり目の急激な需要変化の捕捉

現在のbaseline対比 RMSE **10〜20%改善**予想（気温なしの限界）。  
Phase 5-Bで気温追加後、さらに10〜15%の改善を期待。
