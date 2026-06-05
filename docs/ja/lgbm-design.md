# LightGBM 予測モデル設計

> 現在の運用設計: カレンダー、ラグ、祝日、気象特徴量、運用補正レイヤーを組み合わせたLightGBM quantile regression。

言語: [English](../en/lgbm-design.md) · [한국어](../ko/lgbm-design.md)

運用参考文書: [モデル運用仕様](model-operations-spec.md)

---

## システム内の役割

このモデルはTokyo Grid EMSの時間別電力需要を予測します。

- 今日の予測
- 明日の予測
- ダッシュボードの予測バンド
- 異常検知で使う期待需要

LightGBMが利用できない場合、学習データが不足する場合、または予測時に失敗した場合は、`baseline_dow_hour_mean` 統計モデルへfallbackします。

---

## モデル構造

`python/forecast/lgbm_model.py` は3つのLightGBM quantileモデルを学習します。

| モデル | 役割 |
|---|---|
| q025 | p95下側区間推定 |
| q50 | 中心予測値 |
| q975 | p95上側区間推定 |

ダッシュボードではq50を予測線として使用します。q025/q975はp95予測バンドとして表示し、p99風の広い区間はq025/q975の幅から拡張します。片側のquantile区間がq50近くに潰れた場合、反対側の大きな不確実性をそのまま反映せず、その方向には最小幅のみを維持します。独立したquantileモデルが気象regime変化後に片側tailだけを稀に過度に広げる場合は、interval sanity calibrationがp95最大half-widthと上下非対称比率を制限し、q50予測線は変更しません。

最小学習データ:

```text
90日 * 24時間
```

この条件を満たさない場合はbaselineへ戻ります。

---

## 特徴量

特徴量エンジニアリングは `python/forecast/feature_builder.py` にあります。

| グループ | 例 | 理由 |
|---|---|---|
| カレンダー | 時刻、曜日、月、週末、祝日 | 日・週単位の需要リズムを表す |
| ラグ | 24h, 48h, 168h, 336h | 電力需要の慣性を表す |
| ローリング統計 | 直近4週の同曜日・同時刻平均と標準偏差 | 安定した過去基準を与える |
| 祝日補正 | 直前平日、連続休日数、休日終了後日数 | 連休直後の過少予測を抑える |
| 気象 | 気温、体感温度、設定可能な冷房/暖房degree、気温偏差、1時間/2時間/24時間/168時間の気温・冷房変化量、3時間/6時間/72時間の熱慣性 | 冷暖房需要、気象変化方向、前日比/前週比のレジーム変化を反映する |
| 交互作用 | holiday x heat, post-holiday x heat | GW後などの復帰需要を補正する |
| 営業/気象交互作用 | business-morning x 気温変化/偏差、late-afternoon x 気温・冷房変化 | 朝のramp-up、午後の冷房減衰、同じ気温でも上昇局面と下降局面で異なる需要を表す |
| ラグ文脈 | lag_24h_dsh, lag_24h_consec, lag_168h_dsh, lag_24h営業/非営業mismatch, 直近同営業タイプ平均, lag-to-anchor gap | ラグ値が休日需要に影響されたか、または営業/非営業境界をまたいだかを伝える |

現在の明示的なLightGBM学習特徴量数は56個です。

冷房/暖房degreeの基準温度は `config.yaml` で設定します。

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 18.0
```

気象補強では、過去/現在時間はJMA AMeDAS観測を優先し、未来時間の気温はJMA公式予報を優先します。Open-Meteo JMAは湿度fallback専用で、JMA予報気温を上書きしません。公式予報に湿度がない場合でも、湿度由来の体感温度と不快指数を安定して計算できるようにfallbackを使います。

`temp_delta_24h` と `cooling_delta_24h` は、今日の天候が前日同時刻から変わった場合に、前日需要ラグをどの程度信頼するかをモデルに伝える特徴量です。`temp_delta_168h` と `cooling_delta_168h` は、前週同時刻の需要に対して同じ役割を持ちます。`temp_delta_1h`、`temp_delta_2h`、`apparent_temp_delta_1h`、`cooling_delta_1h` は短期の気象変化方向を表します。`cooling_degree_3h_mean`、`cooling_degree_6h_mean`、`heating_degree_3h_mean`、`heating_degree_6h_mean`、`temp_72h_mean`、`cooling_degree_72h_mean`、`heating_degree_72h_mean` は、持続的な暑さや寒さの蓄積効果を反映します。`apparent_temp_c` と `apparent_cooling_degree` は、データソースが体感温度を提供する場合に補助信号として使います。

`business_morning_x_temp_delta_24h`、`business_morning_x_temp_anomaly_7d`、`business_morning_x_temp_anomaly_doy` は、営業日の朝rampが気象レジーム変化に反応するための特徴量です。`business_late_afternoon_x_temp_delta_1h` と `business_late_afternoon_x_cooling_delta_1h` は、午後の気温上昇局面と下降局面を同じ需要状態として扱わないための信号です。

`lag_24h_business_type_mismatch` と `lag_24h_mismatch_x_business_hour` は、金曜→土曜、日曜→月曜のように前日ラグが営業/非営業境界をまたぐ場合をモデルに伝えます。特に日中の業務需要差を慎重に扱うための信号です。`recent_same_business_type_mean`、`lag_24h_to_last_biz_gap`、`lag_24h_to_same_business_type_gap`、`lag_24h_gap_x_business_hour` は、直近同営業タイプの同時刻平均とgap基準を与えます。

`lag_24h_hourly_delta`、`lag_168h_hourly_delta`、`recent_same_business_type_delta_mean`、`recent_same_business_type_delta_q25`、当日最新実績時刻/傾き、昼休み遷移interaction contextは、内部診断と局所shape guard向けの推論専用contextとして生成します。検証では、グローバルなhourly-deltaを学習特徴量に入れると無関係な午前時間帯も揺れる可能性があったため、LightGBM学習特徴量には含めていません。

---

## Intraday補正

`python/forecast/intraday_correction.py` は当日の実績が積み上がると、残り時間の予測を補正します。

```text
residual = actualMw - modelForecastMw
```

直近の実績残差を平均し、shrinkageと最大補正幅を適用したうえで、未来時間ほど補正を弱めます。

現在のintraday補正は単純な残差carry-overだけではなく、以下の運用補正レイヤーを含みます。

- TEPCO予測fallback行を除外する日付境界の残差carry-over
- 過熱したlagと低下した当日気温が衝突する場合のday-level scale bias
- 営業/非営業遷移priorと実績ベースの遷移補正
- 過熱した週末rampを持ち上げないためのpositive residual mitigation
- 非営業日需要がanchorへ回復する場合に負の残差伝播を弱めるnegative residual recovery damping
- 実績需要が折り返す場合に正の残差伝播を弱めるpositive residual slope damping
- 営業日朝の近距離dipを防ぐmorning ramp continuity guard
- 夕方の下落局面で近距離の反発spikeを抑えるevening decline continuity guard

時間別のresidual carry-overとguard metadataはoperational calibration snapshotに保存され、日次AI/Opsレポートが予測線の変化を説明できるようにしています。

23:40 JST時点でも23:00実績が未公開の場合、TEPCO予測値を一時的な入力として使用できます。

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

この値は運用予測の入力には使いますが、モデル検証指標と異常検知の実績判定からは除外します。

---

## 日中高温ガード

`python/forecast/adjustment.py` はintraday補正の前に、保守的な後処理ガードを適用します。営業日に同時刻168時間ラグが祝日または週末を指し、現在の日中気温偏差が高い場合、類似日補正が日中予測を下方向へ押し下げることを防ぎます。また、祝日ラグがない場合でも、季節に対して暖かい平日の日中には小さめの通常高温ガードを適用します。非営業日の暑さ効果は手動の上方向ガードではなく、LightGBMの気象特徴量に任せます。

詳しい事象分析、実装内容、検証結果は [2026-05-13 日中高温ガード改善](model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md) に整理しています。

後続の一般化は [2026-05-14 暖かい日中の過少予測補正](model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md) に整理しています。

特徴量側の後続改善は [2026-05-14 前週比気温変化特徴量](model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md) に整理しています。

次の特徴量改善は [2026-05-15 前日比気象変化と体感温度特徴量](model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md) に整理しています。

週末/平日遷移の改善は [2026-05-16 営業タイプ遷移lag特徴量](model-improvements/model-improvement-2026-05-16-business-type-lag-features.md) に整理しています。

12:00の時間遷移改善は [2026-05-20 昼時間帯の遷移ガード](model-improvements/model-improvement-2026-05-20-midday-transition-features.md) と [2026-05-27 昼休み遷移ガード再有効化](model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md) に整理しています。

最新の運用補正レイヤーは [2026-05-25 営業日復帰 anchor 不足分 guard](model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md)、[2026-05-25 正の残差スロープ減衰](model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md)、[2026-05-27 朝ランプ継続ガード](model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md)、[2026-05-27 夕方下落継続ガード](model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md)、[2026-05-30 負の残差連続性 floor](model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md)、[2026-06-03 予測区間の上側 tail 安定化](model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)、[2026-06-04 朝の warm-lag 過反応ガード](model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)、[2026-06-05 朝の正の残差 carryover 減衰](model-improvements/model-improvement-2026-06-05-morning-positive-carryover-damping.md) に整理しています。

---

## 学習と推論の流れ

1. ETLがTEPCO月次ZIPから確定済み履歴データを読み込みます。
2. JMA AMeDAS観測気象、JMA公式予報気温、湿度fallbackフィールドを付与します。
3. LightGBMを学習し `web/public/.lgbm_model.pkl` に保存します。
4. status/intraday workflowがモデルを再ロードします。
5. 月次ZIPがまだ更新されていない期間は、直近のactual JSONでcacheを補完します。
6. 今日の予測を生成し、intraday residual correctionを適用します。
7. 同じcacheから明日の予測も生成します。
8. `web/public/forecast/` 以下にJSONとして保存します。

---

## 評価

2種類のレポートを生成します。

- `metrics/model_backtest.json`: train/test分離を守ったLightGBM vs baselineのオフラインバックテスト
- `metrics/forecast_accuracy.json`: 運用中のTEPCO公式予測と自社モデルの誤差比較。MAE、WAPE、RMSE、優位時間数、最大誤差リスクを含みます。

TEPCO予測は内部情報を反映している可能性がある強い基準線です。このプロジェクトの目的はTEPCOに常に勝つことではなく、公開データだけで構築したモデルを透明に比較し、運用することです。
