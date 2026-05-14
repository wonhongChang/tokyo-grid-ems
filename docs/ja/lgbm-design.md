# LightGBM 予測モデル設計

> 現在の運用設計: カレンダー、ラグ、祝日、気温、intraday補正特徴量を使うLightGBM quantile regression。

言語: [English](../en/lgbm-design.md) · [한국어](../ko/lgbm-design.md)

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

ダッシュボードではq50を予測線として使用します。q025/q975はp95予測バンドとして表示し、p99風の広い区間はq025/q975の幅から拡張します。

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
| 気温 | 気温、冷房/暖房degree、気温偏差 | 冷暖房需要を反映する |
| 交互作用 | holiday x heat, post-holiday x heat | GW後などの復帰需要を補正する |
| ラグ文脈 | lag_24h_dsh, lag_24h_consec, lag_168h_dsh | ラグ値が休日需要に影響されたかを伝える |

現在の明示的特徴量数は28個です。

---

## Intraday補正

`python/forecast/intraday_correction.py` は当日の実績が積み上がると、残り時間の予測を補正します。

```text
residual = actualMw - modelForecastMw
```

直近の実績残差を平均し、shrinkageと最大補正幅を適用したうえで、未来時間ほど補正を弱めます。

23:40 JST時点でも23:00実績が未公開の場合、TEPCO予測値を一時的な入力として使用できます。

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

この値は運用予測の入力には使いますが、モデル検証指標と異常検知の実績判定からは除外します。

---

## 日中高温ガード

`python/forecast/adjustment.py` はintraday補正の前に、保守的な後処理ガードを適用します。同時刻168時間ラグが祝日または週末を指し、現在の日中気温偏差が高い場合、類似日補正が日中予測を下方向へ押し下げることを防ぎます。また、祝日ラグがない場合でも、季節に対して暖かい平日の日中には小さめの通常高温ガードを適用します。

詳しい事象分析、実装内容、検証結果は [2026-05-13 日中高温ガード改善](model-improvement-2026-05-13-daytime-heat-guard.md) に整理しています。

後続の一般化は [2026-05-14 暖かい日中の過少予測補正](model-improvement-2026-05-14-warm-daytime-bias-guard.md) に整理しています。

---

## 学習と推論の流れ

1. ETLがTEPCO月次ZIPから確定済み履歴データを読み込みます。
2. Open-Meteoの気温データを付与します。
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
- `metrics/forecast_accuracy.json`: 運用中のTEPCO公式予測と自社モデルの誤差比較

TEPCO予測は内部情報を反映している可能性がある強い基準線です。このプロジェクトの目的はTEPCOに常に勝つことではなく、公開データだけで構築したモデルを透明に比較し、運用することです。
