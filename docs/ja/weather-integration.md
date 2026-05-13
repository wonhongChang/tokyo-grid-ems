# 気温データ連携設計

> 運用機能: LightGBMモデルへのOpen-Meteo気温特徴量追加
> Open-Meteo API（無料、認証不要）— 東京座標基準

言語: [English](../en/weather-integration.md) · [한국어](../ko/weather-integration.md)

---

## なぜ気温か

電力需要の30〜40%は気温で説明されます。

| 季節 | メカニズム | 需要への影響 |
|---|---|---|
| 夏 (7〜9月) | 気温 ↑ → エアコン負荷 ↑ | 強い正の相関 |
| 冬 (12〜2月) | 気温 ↓ → 暖房負荷 ↑ | 強い負の相関 |
| 春/秋 | 気温15〜20°C 快適域 | 需要最小 |

当初の目的は、カレンダー・ラグ特徴量のみの場合より予測を安定させることでした。現在の運用では、冷暖房需要を説明し、高温・低温日の予測を補正するために気温特徴量を使用しています。

---

## データソース: Open-Meteo

```
API: https://api.open-meteo.com/v1/forecast
東京座標: latitude=35.6762, longitude=139.6503
タイムゾーン: Asia/Tokyo
```

### 無料エンドポイント 2種類

| 用途 | エンドポイントパラメータ | 内容 |
|---|---|---|
| 過去実績 | `&past_days=92` | 過去92日の時間別実績気温 |
| 将来予測 | `&forecast_days=2` | 今日・明日の時間別予測気温 |

### レスポンス例

```json
{
  "hourly": {
    "time": ["2026-05-05T00:00", "2026-05-05T01:00", ...],
    "temperature_2m": [18.3, 17.9, 17.5, ...]
  }
}
```

認証キー不要、商用利用可能 (CC BY 4.0)。

---

## 新規ファイル: `python/etl/fetch_weather.py`

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

## 気温特徴量設計

```python
# 現時点の気温（実績または予測）
'temp_c'         # その時刻の気温 (°C)

# 前日気温ラグ（需要の慣性を反映）
'temp_lag_24h'   # 昨日同時刻の気温

# 冷暖房度日 (HDD/CDD)
'hdd'            # max(0, 18 - temp_c)  — 暖房必要度
'cdd'            # max(0, temp_c - 26)  — 冷房必要度

# 予測時点用（明日予測時にOpen-Meteo forecastを使用）
'temp_forecast'  # Open-Meteo予測気温（推論時のみ）
```

> **HDD/CDD選択の理由**: 気温の非線形効果を線形化。
> 18°C以下では低いほど暖房需要が線形増加。
> 26°C以上では高いほど冷房需要が線形増加。

---

## ファイル構造変更

```
python/
  etl/
    fetch_weather.py    # 新規: Open-Meteo収集
    run_batch.py        # 修正: 気象キャッシュ統合
  forecast/
    feature_builder.py  # 修正: 気温特徴量追加
```

```
web/public/
  .weather_cache.parquet   # 気温キャッシュ（モデルファイルと同様にコミット）
```

---

## `feature_builder.py` の修正

```python
def build_features(
    power_cache: pd.DataFrame,
    weather_cache: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    power_cache: hourly_cache (ts, actual_mw, supply_mw, ...)
    weather_cache: fetch_weather() の結果 (ts, temp_c)
    """
    df = power_cache.copy()

    # 既存特徴量（カレンダー + ラグ）
    df['hour']      = df['ts'].dt.hour
    df['dayofweek'] = df['ts'].dt.dayofweek
    df['month']     = df['ts'].dt.month
    df['is_holiday'] = df['ts'].dt.date.apply(_is_holiday)
    df['is_weekend'] = df['dayofweek'].isin([5, 6]).astype(int)
    df['lag_24h']   = df['actual_mw'].shift(24)
    df['lag_168h']  = df['actual_mw'].shift(168)
    df['lag_336h']  = df['actual_mw'].shift(336)

    # 気温特徴量（weather_cacheがある場合のみ）
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

## `run_batch.py` 統合戦略

```python
WEATHER_CACHE_PATH = out_dir / ".weather_cache.parquet"

# ETL実行時に気象データ収集（失敗しても継続）
try:
    weather_df = fetch_weather(past_days=92, forecast_days=2)
    save_weather_cache(weather_df, WEATHER_CACHE_PATH)
except Exception as e:
    print(f"Weather fetch failed (non-fatal): {e}")
    weather_df = load_weather_cache(WEATHER_CACHE_PATH)  # キャッシュフォールバック

# LightGBM訓練時に気温を含める
if forecaster and weather_df is not None:
    forecaster.fit(hourly_cache, weather_cache=weather_df)
else:
    forecaster.fit(hourly_cache)  # 気温なしで訓練

# 予測時に明日の予測気温を使用
tomorrow_weather = weather_df[weather_df['ts'].dt.date == tomorrow] if weather_df is not None else None
tomorrow_fc = forecaster.predict(tomorrow, hourly_cache, weather=tomorrow_weather)
```

---

## GitHub Actions 統合

```yaml
# .github/workflows/etl.yml に追加
- name: Fetch weather data
  run: python python/etl/fetch_weather.py --save web/public/.weather_cache.parquet
  continue-on-error: true   # 気象API失敗でもETL全体を止めない
```

### キャッシュファイルのコミット

```yaml
- name: Commit outputs
  run: |
    git add web/public/forecast/ web/public/status.json
    git add web/public/.weather_cache.parquet || true  # なくてもOK
    git add web/public/.lgbm_model.pkl || true
    git commit -m "auto: ETL $(date -u +%Y-%m-%dT%H:%M)Z" || true
```

---

## 訓練/推論時点の気温ソース

| タイミング | 気温ソース | 備考 |
|---|---|---|
| 訓練（過去全体） | `past_days=365` 実績気温 | 年1回フル再学習可能 |
| 昨日予測 | 実績気温（確定） | 正確 |
| 今日予測 | 実績気温（午前）+ 予測気温（午後） | 混合 |
| 明日予測 | Open-Meteo 48h予測気温 | ±1〜2°C誤差許容 |

> 明日の気温予測誤差がモデル誤差に伝播する。
> 夏の猛暑期は予測誤差が大きいため、不確実性バンドが自動的に広がる（quantile regression の特性）。

---

## 評価計画

Phase 5-A（気温なし）対比:

```
テスト期間: 2026-01-01 ~ 2026-05-04

指標        Phase 5-A    Phase 5-B    改善率
RMSE (MW)   測定予定      測定予定      予想 -20~35%
MAE  (MW)   測定予定      測定予定
夏RMSE      測定予定      測定予定      より大きな改善
冬RMSE      測定予定      測定予定
```

結果は `web/public/model_eval.json` に保存:

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

## 実装順序

1. `fetch_weather.py` 作成 + 手動テスト (`python -m python.etl.fetch_weather`)
2. `feature_builder.py` に気温特徴量追加 + 単体テスト
3. `LGBMForecaster.fit()` — `weather_cache` オプション引数追加
4. `run_batch.py` 統合（気象fetch → モデル訓練 → 予測）
5. `requirements.txt` に `requests` を確認（既存の可能性大）
6. `compare_models.py` でA/B評価後 `model_eval.json` 保存
7. （選択）UIに「モデル性能」カード追加

---

## リスクと対応

| リスク | 可能性 | 対応 |
|---|---|---|
| Open-Meteo API一時停止 | 低 | `continue-on-error: true` + 前回キャッシュ使用 |
| 過去気温データの空白 | 低 | `past_days` 値を増やして再収集可能 |
| 気温ラグのfeature leakage | 注意 | 推論時の将来気温は予測値のみ使用 |
| 夏の猛暑外挿 | 中 | 訓練データに過去猛暑期間が含まれていることを確認 |
