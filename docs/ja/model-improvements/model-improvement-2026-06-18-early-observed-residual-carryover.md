# 2026-06-18 早朝early observed residual carryover

Languages: [English](../../en/model-improvements/model-improvement-2026-06-18-early-observed-residual-carryover.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-18-early-observed-residual-carryover.md)

## 問題

2026-06-18 00-01時 JST の配信データで、大きな夜間過小予測が発生しました。

- 00時の実績は24,240MW、モデル配信値は23,233.7MWでした。
- 01時の実績は22,950MW、モデル配信値は22,050.3MWでした。
- 02:26 JST の補正実行時点では実観測が2点ありましたが、`min_observed_hours=3` により標準 intraday residual ループはそれらを使いませんでした。
- 標準ループが待機している間、パイプラインは前日の day-boundary residual carryover 約 `-120MW` を使い続け、当日の実績が強い正の残差を示しているにもかかわらず未来時間をさらに下げました。

これは TEPCO 追従の問題ではありません。当日の誤差方向はすでに見えていたのに、正式な residual ループが開始する前だったため、その証拠を使えなかった低観測区間の handoff ギャップです。

## 変更

`early_observed_residual_carryover` を追加しました。

- 当日実績数が通常の `min_observed_hours` 未満の間だけ動作します。
- デフォルトでは実観測2点以上が必要です。
- early residual の符号が同じである必要があります。
- 平均残差の絶対値が `500MW` 以上である必要があります。
- 適用量は `0.5` の shrinkage を通し、`700MW` で上限をかけます。
- 条件を満たした場合、古い前日 day-boundary carryover より当日の early residual を優先します。

2026-06-18のパターンでは、2つの early residual から約 `+416MW` の保守的な未来上方補正が入り、従来の `-120MW` carryover は使いません。

## 期待効果

00-01時がどちらも明確な過小予測または過大予測であれば、3つ目の実績が入る前でも、まだ閉じていない近未来時間を観測方向へ動かせます。単一の noisy bucket だけでは動作しません。

すでに閉じた時間は書き換えません。最初の未来時間から改善する構造です。

## 検証

```text
tests/test_intraday_correction.py::test_intraday_correction_prefers_early_same_day_residuals_over_stale_midnight_carryover

Full suite: 399 passed
```
