# モデル運用仕様

> TokyoGridEMSのLightGBM予測モデルを運用、点検、変更するときに参照するモデル運用仕様書です。

言語: [English](../en/model-operations-spec.md) · [한국어](../ko/model-operations-spec.md)

---

## 1. モデル概要

### タイムゾーン運用原則

システム全体の基準時刻はJST(UTC+9)に統一します。TEPCOとJMAのデータは日本時間基準で提供されますが、GitHub ActionsのcronはUTC基準で動作するため、スケジュール表現とデータ処理時刻を分けて管理します。

運用ルール:

- データrowのtimestamp、forecast date、actual dateはJSTで解釈します。
- GitHub Actions cronはUTCで記述し、コメントや文書ではJST実行時刻を併記します。
- ETL、intraday update、daily report、snapshot生成はJST日付で評価します。
- 日付境界のresidual carry-overはUTC深夜ではなくJST日付境界を使います。

| 項目 | 現在値 |
|---|---|
| 運用モデル | LightGBM quantile regression |
| 実装 | `python/forecast/lgbm_model.py` |
| 特徴量生成 | `python/forecast/feature_builder.py` |
| 後処理 | `python/forecast/adjustment.py`, `python/forecast/intraday_correction.py` |
| interval version | `q025_q50_q975_p95_v9_weather_direction` |
| 最小学習量 | `90 * 24 = 2160` hourly rows |
| fallback | `baseline_dow_hour_mean` |

モデルは時間別の電力需要を予測し、今日/明日の予測線、p95/p99予測バンド、異常検知用のexpected demandを生成します。

LightGBMは3つのquantile regressorを学習します。

| モデル | alpha | 役割 |
|---|---:|---|
| `q025` | 0.025 | p95下側推定 |
| `q50` | 0.50 | 中心予測線 |
| `q975` | 0.975 | p95上側推定 |

ダッシュボードでは`q50`を中心予測線として使用します。`q025/q975`はp95バンドになり、p99風の外側バンドはq025/q975のhalf-widthをさらに拡張して計算します。

---

## 2. データソースと優先順位

### 電力データ

| 優先 | データ | 役割 | 運用メモ |
|---:|---|---|---|
| 1 | TEPCO月次ZIP CSV | 確定済み過去実績、学習target | 通常は翌朝更新。GitHub-hosted runnerでは403の可能性 |
| 2 | TEPCO intraday CSV | 当日実績補完 | ライブ画面とintraday residual correctionで使用 |
| 3 | `actual/YYYY-MM-DD.json` | 月次ZIP更新前のgap補完 | ETL遅延時にcacheを補強 |
| 4 | TEPCO forecast fallback | 23時など未確定実績の一時入力 | lag入力安定化用。検証actual扱いは禁止 |

TEPCO forecast fallbackは継続性のための一時入力です。lag構築には使えますが、residual計算、モデル検証、異常検知actual判定からは除外します。

### 気象データ

| 時間範囲 | 気温優先順位 | 湿度優先順位 | 運用メモ |
|---|---|---|---|
| 過去/現在 | JMA AMeDAS観測 | JMA AMeDAS観測 | 公式観測を優先 |
| 近未来 | JMA公式予報 | 最新AMeDAS湿度forward fill | 気温はJMA forecastを信頼 |
| 未来湿度補完 | JMA forecast temperature維持 | Open-Meteo JMA humidity fallback | Open-Meteoは湿度補完専用 |
| 最終fallback | 既存値または保守的平均 | 月/時刻別seasonal humidity | 通信障害対策 |

`weather_source`は予測線が急に変化した時の重要な診断フィールドです。

---

## 3. LightGBMハイパーパラメータ

| パラメータ | 現在値 | 意図 |
|---|---:|---|
| `objective` | `quantile` | 予測バンド生成 |
| `alpha` | `0.025 / 0.50 / 0.975` | 下側/中心/上側モデル |
| `n_estimators` | `500` | 非線形需要パターンを十分に学習 |
| `learning_rate` | `0.05` | 安定したboosting step |
| `num_leaves` | `31` | 中程度の木の複雑度 |
| `min_child_samples` | `20` | 小さなsplitの過学習防止 |
| `subsample` | `0.8` | row samplingでvarianceを抑制 |
| `colsample_bytree` | `0.8` | 特定lag群への依存を緩和 |
| `min_p95_half_width_mw` | `500` | 非現実的に狭いバンドを防止 |

運用上は、LightGBMの複雑度を変える前に、データ品質、lag regime、calibration挙動を先に確認します。

---

## 4. 特徴量カタログ

現在のLightGBM学習特徴量は56個です。現在の実装ではLightGBMに`categorical_feature`を明示的に渡しておらず、多くの特徴量はnumeric matrixとして入力されます。そのため「論理型」は人間が解釈する意味、「モデル入力型」はモデルに渡る形式を表します。

### カレンダー

| No. | 特徴量 | 論理型 | モデル入力型 | 出所 | 意味 | 運用メモ |
|---:|---|---|---|---|---|---|
| 1 | `hour` | categorical-like integer | Integer/Numeric | timestamp | 0-23時 | 日内需要リズムの中心 |
| 2 | `dayofweek` | categorical-like integer | Integer/Numeric | timestamp | 曜日 | 平日/週末パターン |
| 3 | `month` | categorical-like integer | Integer/Numeric | timestamp | 月 | 季節性 |
| 4 | `is_holiday` | binary flag | Integer/Numeric | `jpholiday` | 日本の祝日 | 祝日需要の変化 |
| 5 | `is_weekend` | binary flag | Integer/Numeric | timestamp | 土日 | 非営業日需要 |
| 6 | `is_non_business_day` | binary flag | Integer/Numeric | weekend or holiday | 非営業日統合flag | 遷移ロジックの主要gate |

### Lagとrolling統計

| No. | 特徴量 | 論理型 | モデル入力型 | 出所 | 意味 | 運用メモ |
|---:|---|---|---|---|---|---|
| 7 | `lag_24h` | continuous lag | Float/Numeric | actual cache | 前日同時刻需要 | 強い短期慣性。営業/非営業境界で汚染されやすい |
| 8 | `lag_48h` | continuous lag | Float/Numeric | actual cache | 2日前同時刻需要 | 前日が異常な場合の補完 |
| 9 | `lag_168h` | continuous lag | Float/Numeric | actual cache | 1週前同時刻需要 | 週間リズム。祝日/天候差に弱い |
| 10 | `lag_336h` | continuous lag | Float/Numeric | actual cache | 2週前同時刻需要 | 安定した曜日/季節基準 |
| 11 | `roll_4w_mean` | rolling statistic | Float/Numeric | actual cache | 直近4週同曜日/同時刻平均 | 安定したanchor |
| 12 | `roll_4w_std` | rolling statistic | Float/Numeric | actual cache | 直近4週の変動性 | パターン不安定性 |

### 祝日/営業日文脈

| No. | 特徴量 | 論理型 | モデル入力型 | 出所 | 意味 | 運用メモ |
|---:|---|---|---|---|---|---|
| 13 | `lag_last_biz_hour` | continuous lag | Float/Numeric | actual + calendar | 直前営業日同時刻需要 | 連休後復帰を補完 |
| 14 | `lag_last_nonhol_hour` | continuous lag | Float/Numeric | actual + calendar | 直前非祝日同時刻需要 | 祝日歪みを緩和 |
| 15 | `consec_holiday_len` | ordinal count | Integer/Numeric | calendar | 直前連続休日数 | GW/連休後文脈 |
| 16 | `days_since_holiday_end` | ordinal count | Integer/Numeric | calendar | 休日終了後日数 | 復帰1日目/2日目の分離 |
| 17 | `major_holiday_season` | categorical-like integer | Integer/Numeric | date range | GW/Obon/New Year zone | 大型連休周辺の処理 |

### 気象/環境

| No. | 特徴量 | 論理型 | モデル入力型 | 出所 | 意味 | 運用メモ |
|---:|---|---|---|---|---|---|
| 18 | `temp_c` | continuous weather | Float/Numeric | JMA/AMeDAS | 気温 | 冷暖房需要の基本driver |
| 19 | `cooling_degree` | continuous derived | Float/Numeric | derived | `max(0, temp_c - 22)` | 冷房需要 |
| 20 | `heating_degree` | continuous derived | Float/Numeric | derived | `max(0, 18 - temp_c)` | 暖房需要 |
| 21 | `apparent_temp_c` | continuous weather | Float/Numeric | humidity-derived | 体感温度 | 湿度影響 |
| 22 | `apparent_cooling_degree` | continuous derived | Float/Numeric | derived | 体感冷房degree | 高湿度日の冷房信号 |
| 23 | `temp_anomaly_7d` | continuous delta | Float/Numeric | weather history | 直近7日平均との差 | 急な暑さ/寒さ |
| 24 | `temp_anomaly_doy` | continuous delta | Float/Numeric | month/hour baseline | 季節基準偏差 | 季節外れの気温 |
| 25 | `temp_delta_24h` | continuous delta | Float/Numeric | weather lag | 前日同時刻との差 | `lag_24h`信頼度調整 |
| 26 | `cooling_delta_24h` | continuous delta | Float/Numeric | weather lag | 前日冷房degreeとの差 | 前日慣性を調整 |
| 27 | `temp_delta_168h` | continuous delta | Float/Numeric | weather lag | 前週同時刻との差 | `lag_168h`信頼度調整 |
| 28 | `cooling_delta_168h` | continuous delta | Float/Numeric | weather lag | 前週冷房degreeとの差 | 週間天候差 |
| 29 | `temp_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1時間気温変化 | 朝上昇/午後下降 |
| 30 | `temp_delta_2h` | continuous delta | Float/Numeric | weather sequence | 2時間気温変化 | 短期方向安定化 |
| 31 | `apparent_temp_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1時間体感温度変化 | 湿度込み方向 |
| 32 | `cooling_delta_1h` | continuous delta | Float/Numeric | weather sequence | 1時間冷房degree変化 | 冷房負荷方向 |
| 33 | `cooling_degree_3h_mean` | rolling weather | Float/Numeric | rolling weather | 3時間冷房蓄積 | 短期熱慣性 |
| 34 | `cooling_degree_6h_mean` | rolling weather | Float/Numeric | rolling weather | 6時間冷房蓄積 | 半日熱慣性 |
| 35 | `heating_degree_3h_mean` | rolling weather | Float/Numeric | rolling weather | 3時間暖房蓄積 | 短期寒さ慣性 |
| 36 | `heating_degree_6h_mean` | rolling weather | Float/Numeric | rolling weather | 6時間暖房蓄積 | 半日寒さ慣性 |
| 37 | `temp_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72時間平均気温 | 熱メモリ |
| 38 | `cooling_degree_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72時間冷房蓄積 | 猛暑継続 |
| 39 | `heating_degree_72h_mean` | rolling weather | Float/Numeric | rolling weather | 72時間暖房蓄積 | 寒波継続 |

### Interactionとlag context

| No. | 特徴量 | 論理型 | モデル入力型 | 出所 | 意味 | 運用メモ |
|---:|---|---|---|---|---|---|
| 40 | `business_morning_x_temp_delta_24h` | interaction | Float/Numeric | derived | 営業日朝 x 24h気温変化 | 朝rampの気象反応 |
| 41 | `business_morning_x_temp_anomaly_7d` | interaction | Float/Numeric | derived | 営業日朝 x 直近偏差 | 急な冷暖房負荷 |
| 42 | `business_morning_x_temp_anomaly_doy` | interaction | Float/Numeric | derived | 営業日朝 x 季節偏差 | 季節外れ冷暖房 |
| 43 | `business_late_afternoon_x_temp_delta_1h` | interaction | Float/Numeric | derived | 営業日午後 x 気温方向 | 上昇/下降午後を分離 |
| 44 | `business_late_afternoon_x_cooling_delta_1h` | interaction | Float/Numeric | derived | 営業日午後 x 冷房方向 | 冷房負荷の減少/増加 |
| 45 | `holiday_x_heat` | interaction | Float/Numeric | derived | 休日長 x 暑さ | 暑い休日の歪み |
| 46 | `post_holiday_x_heat` | interaction | Float/Numeric | derived | 休日後 x 暑さ | 復帰日の熱負荷 |
| 47 | `business_hour_x_post_holiday_heat` | interaction | Float/Numeric | derived | 営業時間 x 休日後 x 暑さ | 日中復帰需要 |
| 48 | `lag_24h_dsh` | ordinal context | Integer/Numeric | calendar lag | 前日の休日終了後日数 | lag汚染文脈 |
| 49 | `lag_24h_consec` | ordinal context | Integer/Numeric | calendar lag | 前日の連続休日数 | 前日holiday regime |
| 50 | `lag_168h_dsh` | ordinal context | Integer/Numeric | calendar lag | 前週の休日終了後日数 | 週lag汚染 |
| 51 | `lag_24h_business_type_mismatch` | binary flag | Integer/Numeric | calendar | 当日と前日の営業タイプ差 | Fri->Sat, Sun->Mon |
| 52 | `lag_24h_mismatch_x_business_hour` | interaction | Float/Numeric | derived | mismatch x 営業時間 | 日中遷移差 |
| 53 | `recent_same_business_type_mean` | anchor statistic | Float/Numeric | actual history | 同営業タイプanchor | 営業/非営業基準 |
| 54 | `lag_24h_to_last_biz_gap` | continuous gap | Float/Numeric | derived | 直前営業日需要 - `lag_24h` | 復帰shortfall |
| 55 | `lag_24h_to_same_business_type_gap` | continuous gap | Float/Numeric | derived | 同営業タイプanchor - `lag_24h` | business return guard入力 |
| 56 | `lag_24h_gap_x_business_hour` | interaction | Float/Numeric | derived | gap x 営業時間 | 日中lag gap |

---

## 5. Inference-only ContextとGuard変数

これらはLightGBM学習特徴量ではなく、推論時の診断とguard判定に使います。

| 変数 | 用途 |
|---|---|
| `lag_24h_hourly_delta` | 前日同日内の時間変化 |
| `lag_168h_hourly_delta` | 前週同日内の時間変化 |
| `recent_same_business_type_delta_mean` | 直近同営業タイプの平均時間変化 |
| `recent_same_business_type_delta_q25` | 同営業タイプ変化の下位quantile |
| `same_day_latest_actual_hour` | 当日最新実績hour |
| `same_day_latest_hourly_delta` | 最新当日実績slope |
| `same_day_recent_hourly_delta_mean` | 直近当日平均slope |
| `business_midday_x_lag_24h_delta` | 営業日昼 x lag24 slope |
| `business_midday_x_recent_delta_mean` | 営業日昼 x 最近平均slope |
| `business_midday_x_recent_delta_q25` | 営業日昼 x 下位quantile slope |
| `business_midday_x_same_day_recent_delta_mean` | 営業日昼 x 当日最近slope |

---

## 6. 後処理レイヤー

### 実行順序

後処理は直列パイプラインです。各段階の出力が次の段階の入力になるため、順序は提供される予測線のshapeに直接影響します。

```text
Raw LightGBM Forecast
  -> Analogous Day Adjustment
  -> Post-holiday / Timeband Guard
  -> Midday Transition Guard
  -> Intraday Residual Correction
  -> Forecast Snapshots / Operational Calibration / Reports
```

現在の`run_batch.py`のstage名は`raw_lgbm`、`analog_adjusted`、`post_holiday_guarded`、`midday_guarded`、`pre_calibration`です。Intraday residual correctionは`pre_calibration`の後に当日実績を反映する運用補正段階です。

| レイヤー | 実装 | 目的 |
|---|---|---|
| Analogous day | `AnalogousDayAdjuster` | 類似過去日のresidualでraw forecastを補正 |
| Post-holiday timeband | `PostHolidayTimeBandGuard` | 類似日補正の誤方向shiftを制限 |
| Business return anchor shortfall | `PostHolidayTimeBandGuard` | 予測shapeも不足している場合のみ、非営業日lagが営業日朝を下げすぎる問題を緩和 |
| Midday transition guard | `MiddayTransitionGuard` | 営業日12時のlunch dip形状を復元 |
| Intraday residual correction | `IntradayResidualCorrector` | 当日実績residualを未来時間へ反映 |
| Day-boundary carryover | intraday calibration | 最後の実績residualを日付境界で弱くcarry-over |
| Business transition prior | intraday calibration | 観測不足時の営業/非営業遷移prior |
| Negative residual recovery damping | intraday calibration | 非営業日回復時の負residual過剰伝播を防止 |
| Negative residual continuity floor | intraday calibration | 非営業日序盤の負residualが安定した当日plateauを実績水準より押し下げすぎることを防止 |
| Positive residual slope damping | intraday calibration | 実績slope鈍化時の正residual伝播を抑制 |
| Morning ramp continuity guard | intraday calibration | 営業日朝の近距離dipを防止 |
| Evening decline continuity guard | intraday calibration | 夕方下落時の近距離反発spikeと高水準overhangを制限 |

各guardにはcap、shrinkage、metadataを持たせます。

---

## 7. Configと検証

### 主要config

| 領域 | Config Key | 現在値 | 運用ガイド |
|---|---|---:|---|
| weather | `cooling_base_temp_c` | 22.0 | 下げると冷房感度が早く立ち上がり、上げると初夏の過反応を抑えます。暖候期全体で検証します。 |
| weather | `heating_base_temp_c` | 18.0 | 上げると暖房信号が強くなり、下げると冬の過敏反応を抑えます。 |
| weather bias | `min_abs_bias_c` | 1.5 | 下げると予報bias補正が頻繁に作動します。低すぎると気象noiseを追います。 |
| interval | `min_p95_half_width_mw` | 500 | 狭すぎるbandを防ぎます。上げると安定しますがalert感度が下がる場合があります。 |
| intraday | `lookback_hours` | 3 | 短いほど反応が速く、長いほど滑らかですが遅れます。 |
| intraday | `decay_per_hour` | 0.92 | 高いほどresidualが遠い時間まで残り、低いほど近距離中心になります。shape汚染時は引き下げを検討します。 |
| intraday | `max_abs_adjustment_mw` | 1200 | 当日residual補正のhard capです。上げると大きなmissに追従しやすい一方、overshootリスクが増えます。 |
| intraday | `morning_warm_lag_overreaction_guard.max_reduction_mw` | 800 | 暖かくなった朝のlag/気象上昇シグナルが当日実績で確認されない場合のq50追加下方ブレーキを制限します。上げると過大予測への反応は速くなりますが、実際の冷房rampを抑える可能性があります。 |
| intraday | `morning_positive_residual_carryover_damping.damping_factor` | 0.4 | 朝の早い時間帯の過少予測から生じた正の residual が、対象slotのlag/recent ramp根拠なしに10-13時へ過伝播する場合、一部だけ通過させます。下げると過伝播を速く抑え、上げると実際のramp momentumをより保持します。 |
| intraday | `negative_residual_continuity_floor.max_restore_mw` | 900 | 非営業日の予測線が安定した当日plateauより下へ押された場合に戻せる最大値です。上げると土曜plateau保護は強くなりますが、実際の下落反映が遅れる場合があります。 |
| intraday | `negative_residual_continuity_floor.floor_slack_mw` | 500 | 最新実績plateauよりどれだけ下がったらfloorを作動させるかのbufferです。下げると早めに介入し、上げると明確なundercut時だけ作動します。 |
| intraday | `evening_decline_continuity_guard.level_overhang_enabled` | true | 夕方下落局面で局所的なreboundだけでなく、高水準に残るoverhangも制限します。暑い夕方の実需要まで抑える場合だけ無効化を検討します。 |
| post-processing | `business_return_anchor_shortfall.min_shape_shortfall_mw` | 800 | 営業日復帰anchorのリフト前に、予測ランプが最近の同営業タイプランプより十分に不足しているかを確認します。下げるとリフト頻度が増え、上げると健全なraw shapeを過剰に支援するリスクを抑えます。 |
| forecast snapshots | `retention_days` | 21 | 公開lead-time forecast履歴の保持期間です。 |
| calibration snapshots | `retention_days` | 14 | 内部calibration履歴です。短すぎると障害分析が難しくなります。 |
| reserve risk | warning | 92% | TEPCO基準のwarning thresholdです。下げると警告が増え、上げると早期警戒性が弱まります。 |
| reserve risk | critical | 97% | TEPCO基準のcritical thresholdです。warningと視覚的に明確に分けます。 |

### 指標

| 指標 | 定義 | 用途 |
|---|---|---|
| MAE | 平均絶対誤差, MW | 直感的な平均誤差 |
| WAPE | `sum(abs(error)) / sum(actual)` | 需要scaleに対する日次誤差 |
| RMSE | 二乗平均平方根誤差 | 大きなmissリスク |
| Max Error MW | 最大絶対誤差 | 運用tail risk |
| Dominance Hours | TEPCOより誤差が小さい時間数 | 補助比較 |

### Known Risks

| リスク | 症状 | 対応 |
|---|---|---|
| 季節遷移 | lag regimeと当日天候が合わない | `temp_delta`とday-level scaleを確認 |
| 昼休みdip | 12時bucketが平坦または過度に低い | midday guardとq25 deltaを確認 |
| 夕方rebound | 実績下降中に予測が反発 | evening decline guardを確認 |
| 月曜朝 | 日曜lagが営業日rampを下げる | business return anchor shortfallを確認 |
| 土曜朝 | 金曜lagが非営業日朝を過熱させる | business transition priorを確認 |
| 23時実績遅延 | 前日最終実績が欠ける | fallback source flagを確認 |
| TEPCO ZIP 403 | GitHub Actions ETLが月次CSVを取得できない | ローカルETLまたは別runnerを使う |
| 気象API障害 | 気温/湿度NaNまたはfallback過多 | `weather_source`比率を確認 |
| モデルbatch再学習失敗(Dry rot) | データは増えるがモデルが再学習されない、または古い`.lgbm_model.pkl`で推論が続く | 最小学習量90日、モデル保存時刻、interval version、ETL学習ログを確認します。最新有効モデルで推論は継続しつつ、運用レポートに再学習失敗を記録します。 |

---

## 8. 変更Runbook

特徴量変更:

- `FEATURE_COLS`に入れるかinference-only contextにするか決めます。
- 欠損率と学習row減少を確認します。
- training/inferenceの特徴量生成を揃えます。
- future actualや確定後データのleakageを避けます。
- 時間帯別WAPE/RMSEとshape副作用を確認します。
- `lgbm-design.md`、この文書、必要なmodel-improvement noteを更新します。

Guard変更:

- raw model変更とresidual carryover変更を分離します。
- 特定日hardcodingを避けます。
- cap、shrinkage、max lead-timeを維持します。
- TEPCO forecastを直接追従しません。
- observed past hourのforecast freezeを尊重します。
- `...Applied`、`...MaxMw`、`appliedRegimeReason` metadataを記録します。
- unit testとoperational calibration snapshotを確認します。

最初に見る診断:

| 症状 | 最初に見る成果物 |
|---|---|
| 予測線が急に跳ねる | `reports/internal/operational-calibration/YYYY-MM-DD.json` |
| 1日中高い/低い | `reports/internal/daily-diagnostics/YYYY-MM-DD.json` |
| 昼だけおかしい | forecast snapshot と midday context |
| 夕方spike | evening guard metadata |
| 朝ramp miss | business return / morning ramp metadata |
| bandが狭い | `interval_calibration` |
| AI reportがおかしい | `reports/ai/daily/` generator metadata |

基本方針は、まずデータソース品質とresidual carryoverを確認し、次に特徴量、最後にモデル複雑度を見ることです。
