# 気温データ連携設計

> 運用機能: LightGBMモデルへのOpen-Meteo気温・体感温度特徴量追加
> Open-Meteo API（無料、認証不要）— 東京座標基準

言語: [English](../en/weather-integration.md) · [한국어](../ko/weather-integration.md)

---

## なぜ気温か

電力需要の30〜40%は気温で説明されます。体感温度は、湿度・風・日射などにより実際の気温と感じ方がずれる場合の冷房需要を補う信号です。

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
    "temperature_2m": [18.3, 17.9, 17.5, ...],
    "apparent_temperature": [18.1, 17.6, 17.0, ...]
  }
}
```

認証キー不要、商用利用可能 (CC BY 4.0)。

---

## 気温取得モジュール: `python/etl/fetch_weather.py`

```python
TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503
_ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_MAX_RETRIES  = 3

def fetch_past_temps(start: date, end: date) -> pd.DataFrame:
    """東京の時間別過去気象をarchive APIから取得します。"""

def fetch_forecast_temps(days: int = 3) -> pd.DataFrame:
    """今日と今後数日の時間別予測気象を取得します。"""

def enrich_cache_with_weather(cache: pd.DataFrame) -> pd.DataFrame:
    """actual_mwがあるhourly cache行の欠損気象値を補完します。"""
```

`run_batch.py` は気温と体感温度を `.hourly_cache.parquet` 内に保存するため、電力需要履歴と気象履歴が一緒に移動します。

---

## 気温特徴量設計

```python
# 現時点の気温（実績archiveまたは予測）
'temp_c'              # その時刻の気温 (°C)
'apparent_temp_c'     # その時刻の体感温度 (°C)

# 冷房/暖房degree
'cooling_degree'      # max(0, temp_c - cooling_base_temp_c)
'heating_degree'      # max(0, heating_base_temp_c - temp_c)
'apparent_cooling_degree'  # max(0, apparent_temp_c - cooling_base_temp_c)

# 気温レジームの文脈
'temp_anomaly_7d'     # temp_c - 直近7日平均
'temp_anomaly_doy'    # temp_c - 過去同月/同時刻平均
'temp_delta_24h'      # 現在同時刻の気温 - 前日同時刻の気温
'cooling_delta_24h'   # 現在の冷房degree - 前日同時刻の冷房degree
'temp_delta_168h'     # 現在同時刻の気温 - 168時間前の気温
'cooling_delta_168h'  # 現在の冷房degree - 168時間前の冷房degree
'temp_72h_mean'       # 直近3日間の平均気温
'cooling_degree_72h_mean'  # 直近3日間の冷房負荷の持続性
'heating_degree_72h_mean'  # 直近3日間の暖房負荷の持続性

# 連休明け需要と暑さの交互作用
'holiday_x_heat'
'post_holiday_x_heat'
'business_hour_x_post_holiday_heat'
```

冷房/暖房degreeの基準温度は設定値として管理します。

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 18.0
```

> **degree値と気象変化量を使う理由**: degree値は冷暖房需要の非線形効果を扱いやすくします。24時間変化量は、今日の天候が前日と違い、前日同時刻の需要を信頼しすぎない方がよい状況を伝えます。168時間変化量は前週同時刻の需要に対して同じ役割を持ちます。

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
  .hourly_cache.parquet    # temp_c/apparent_temp_cを含む電力需要キャッシュ
  .lgbm_model.pkl          # 学習済みLightGBMモデル
```

---

## `feature_builder.py` の修正

```python
def build_training_features(
    cache: pd.DataFrame,
    config: dict | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    cache: ts, actual_mw, supply_mw, temp_c, apparent_temp_c などを含む hourly cache
    config: weather_features の基準温度を含む
    """
    cooling_base_temp_c, heating_base_temp_c = _weather_feature_config(config)
    df["apparent_temp_c"] = df["apparent_temp_c"].fillna(df["temp_c"])
    df["cooling_degree"] = (df["temp_c"] - cooling_base_temp_c).clip(lower=0.0)
    df["heating_degree"] = (heating_base_temp_c - df["temp_c"]).clip(lower=0.0)
    df["apparent_cooling_degree"] = (df["apparent_temp_c"] - cooling_base_temp_c).clip(lower=0.0)
    df["temp_delta_24h"] = df["temp_c"] - df["temp_c_24h"]
    df["cooling_delta_24h"] = df["cooling_degree"] - df["cooling_degree_24h"]
    df["temp_delta_168h"] = df["temp_c"] - df["temp_c_168h"]
    df["cooling_delta_168h"] = df["cooling_degree"] - df["cooling_degree_168h"]
    return df[FEATURE_COLS], df["actual_mw"]
```

---

## `run_batch.py` 統合戦略

```python
# hourly cache の欠損した過去 temp_c/apparent_temp_c を補完します。
hourly_cache = enrich_cache_with_weather(hourly_cache)

# 今日/明日の予測で使う気象値のため、将来気象行を仮想的に追加します。
# これらの行は actual_mw が NaN なので実績需要としては扱われません。
extended_cache = _extend_cache_with_forecast_weather(hourly_cache, days=3)

# 同じ weather feature 設定で学習と推論を行います。
forecaster = LGBMForecaster(config=config)
forecaster.fit(hourly_cache)
tomorrow_fc = forecaster.predict(tomorrow, extended_cache)
```

---

## GitHub Actions 統合

```yaml
# ETLとintradayは python/etl/run_batch.py を実行します。
# 気温archive/forecast取得はbatch job内部で処理されます。
```

### キャッシュファイルのコミット

```yaml
- name: Commit outputs
  run: |
    git add web/public/forecast/ web/public/status.json
    git add web/public/.hourly_cache.parquet || true
    git add web/public/.lgbm_model.pkl || true
    git commit -m "auto: ETL $(date -u +%Y-%m-%dT%H:%M)Z" || true
```

---

## 訓練/推論時点の気温ソース

| タイミング | 気温ソース | 備考 |
|---|---|---|
| 訓練（過去全体） | Open-Meteo archive API | 過去 `temp_c` / `apparent_temp_c` は `.hourly_cache.parquet` に保存 |
| 昨日予測 | 実績気温（確定） | 正確 |
| 今日予測 | 実績気温（午前）+ 予測気温（午後） | 混合 |
| 明日予測 | Open-Meteo 48h予測気温 | ±1〜2°C誤差許容 |

> 明日の気温予測誤差がモデル誤差に伝播する。
> 夏の猛暑期は予測誤差が大きくなる可能性があるため、quantileモデルと異常検知結果はその不確実性も含めて解釈する必要があります。

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

## 現在の実装チェックリスト

1. `fetch_weather.py` はOpen-Meteo archive/forecastエンドポイントをretry/backoff付きで使用します。
2. `run_batch.py` は過去 `temp_c` と `apparent_temp_c` を `.hourly_cache.parquet` に補完します。
3. 将来予測気象は `actual_mw = NaN` の仮想cache行として追加し、intraday実行ごとに更新します。
4. `feature_builder.py` はdegree値、体感温度、気温偏差、24時間/168時間気象変化量、72時間の熱慣性、営業タイプlag文脈を含む50個のLightGBM学習特徴量を生成します。追加のlag-shape contextは内部診断と12時遷移guard向けに生成し、LightGBM学習には入れません。
5. `LGBMForecaster(config=config)` は学習と推論で同じweather feature設定を使用します。
6. 特徴量バージョンが変わった場合、既存保存モデルはstale扱いとなり次回実行で再学習されます。

---

## リスクと対応

| リスク | 可能性 | 対応 |
|---|---|---|
| Open-Meteo API一時停止 | 低 | retry/backoffを適用、過去気温取得失敗はnon-fatalで既存cache値を維持 |
| 過去気温データの空白 | 低 | API復旧後にETL再実行、欠損行は `temp_c = NaN` のまま残りモデル学習から除外 |
| 気温ラグのfeature leakage | 注意 | 推論時の将来気温は予測値のみ使用 |
| 夏の猛暑外挿 | 中 | 訓練データに過去猛暑期間が含まれていることを確認 |
