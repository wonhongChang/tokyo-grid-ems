# 2026-06-11 湿度/不快指数特徴量と局所shape spikeガード

## 問題

直近の提供データで、別々の2つのshape問題が確認されました。

- 2026-06-10の15:00予測が、1時間だけ突出する局所ピークを作りました。前後時間、lag slope、直近同営業タイプshape、気象方向のいずれも単独の15時ピークを強く支持していませんでした。
- 2026-06-11は、暖かく湿度の高い営業日日中需要が低めに出ました。既存モデルは体感温度と冷房degreeを使っていましたが、湿度/不快指数の変化量や営業時間帯との交互作用をLightGBMに直接渡していませんでした。

## 変更内容

- LightGBM学習特徴量を56個から63個へ拡張しました。
- 直接的な湿度/不快指数特徴量を追加しました。
  - `humidity_pct`
  - `discomfort_index`
  - `humidity_delta_24h`
  - `discomfort_delta_24h`
  - `business_morning_x_humidity_delta_24h`
  - `business_morning_x_discomfort_delta_24h`
  - `business_daytime_x_discomfort_index`
- 古いweather cacheに湿度フィールドがない場合でも学習rowが落ちないよう、保守的なfill処理を追加しました。
- モデル互換versionを `q025_q50_q975_p95_v10_humidity_discomfort` に上げ、古いpickleを再利用せず再学習させます。
- `MiddayTransitionGuard` の後、intraday補正の前に `LocalizedShapeSpikeGuard` を追加しました。前後時間より1時間だけ高く、lag/recent/weather文脈がそれを支持しない場合だけ限定的に減衰します。
- operational calibration snapshotとAIレポートのfeature catalogに、湿度/不快指数フィールドを追加しました。

## ガード範囲

局所shapeガードは意図的に狭い範囲で動作します。

- 営業日のみ、
- デフォルト対象時間は13:00-17:00、
- 両隣の時間より明確に高い1時間ピークだけを評価、
- lag shape、直近同営業タイプshape、当日実績slope、気象deltaが実ピークを支持する場合は介入しない、
- shrinkageと最大減衰capを適用。

目的は暑い日の正当なピークを平坦化することではなく、analog/post-processingで稀に出る局所shape artifactを抑えることです。

## 検証

```text
389 passed
```

追加単体テストでは以下を確認しています。

- 根拠の弱い15時単独spikeは減衰される、
- 気象的に支持されるピークは維持される。

## 運用メモ

この変更はまず原始特徴量側の改善であり、ガードは補助的な安全網です。湿度/不快指数特徴量は、暖かく湿った日中需要をモデルが直接学習するための入力で、局所ガードは稀な後処理shape artifactを抑えます。
