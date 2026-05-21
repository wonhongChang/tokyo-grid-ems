# 2026-05-21 予測バンド補正

> 片側のquantile不確実性が反対側の予測バンドへそのままコピーされる問題を抑える改善メモ。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-21-forecast-band-calibration.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-21-forecast-band-calibration.md)

---

## なぜ必要だったか

2026-05-21 のintraday予測で、14:00の予測バンドが視覚的に不自然に広がった。中心予測線そのものが主因ではなかった。LightGBMのquantileが以下のように強く非対称だった。

- q50は想定需要線の近くにあった。
- q025はq50にかなり近かった。
- q975は大きく上側に残っていた。

従来のinterval calibrationは、下側がq50に近く潰れた状態を補うため、上側の大きなhalf-widthを下側にもコピーしていた。その結果、表示上の下限バンドがモデルの下側quantileよりも大きく下がった。

---

## 変更内容

運用configで `interval_calibration.mirror_collapsed_side` を無効化した。

バンドが線のように潰れないよう、p95 half-widthの最小値は維持する。ただし、大きな上側不確実性を下側へコピーしたり、大きな下側不確実性を上側へコピーしたりしない。

```yaml
interval_calibration:
  min_p95_half_width_mw: 500
  mirror_collapsed_side: false
```

---

## 期待される効果

quantileモデルが片側方向の不確実性だけを大きく表した場合でも、予測バンドを読みやすい形に保てる。

再現した2026-05-21 14:00ケースでは、p95幅が約 `9,260 MW` から約 `5,130 MW` に縮小した。上側不確実性は残しつつ、根拠の薄い下側範囲を表示しない。

---

## テスト

追加/更新したテストは以下を確認する。

- デフォルトのcalibrationは、潰れた方向には最小幅のみを維持する。
- 旧来のmirroring動作は、明示的に設定した場合のみ使用できる。
