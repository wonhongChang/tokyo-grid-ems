# 2026-05-14 前週比気温変化特徴量

> 季節移行期に前週同時刻の需要ラグが低すぎる基準点になる問題を減らすための特徴量改善記録です。

言語: [English](../../en/model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md) · [한국어](../../ko/model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md)

---

## なぜ必要だったか

2026-05-14の予測では、前日のTEPCO実績は `lag_24h` として入っていました。それでも09:00-13:00の予測は、低い `lag_168h`、低い4週同時刻平均、弱い気温シグナルに引き下げられていました。

これは特徴量の不足を示しています。季節が変わる時期には、前週同時刻の需要が現在需要の良い基準点ではない場合があります。

## 予測改善内容

LightGBM特徴量に次の値を追加しました。

- `temp_delta_168h`: 現在同時刻の気温 - 168時間前同時刻の気温
- `cooling_delta_168h`: 現在同時刻の冷房degree - 168時間前同時刻の冷房degree

また、冷房/暖房degreeの基準温度は特徴量コードにハードコードせず、`config.yaml` に分離しました。

```yaml
weather_features:
  cooling_base_temp_c: 22.0
  heating_base_temp_c: 10.0
```

特徴量カラムが変わったため、LightGBMモデル互換バージョンも上げました。既存の保存モデルはstaleとして扱い、次回のETL/intraday実行で再学習します。

また、`actual_mw` がまだ空の仮想予測気温行は、intraday実行ごとに最新のOpen-Meteo値で更新します。これにより、朝に取得した古い気温予測が一日中モデル入力に固定される問題を防ぎます。

## 設計上の境界

この変更ではTEPCO予測値をモデル入力として使いません。気温から派生した文脈を追加し、モデルが前週需要ラグを信頼しすぎない状況を学べるようにする改善です。
