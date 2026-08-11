# Rolling Conformal 予測バンド最小幅補正

Languages: [English](../../en/model-improvements/model-improvement-2026-08-11-rolling-conformal-interval-floor.md) / [한국어](../../ko/model-improvements/model-improvement-2026-08-11-rolling-conformal-interval-floor.md)

## 問題

独立学習したq025/q975 tailは、気象レジーム変化後に不安定になる場合がある。既存の3,000MW半幅上限は極端なbandがUIを支配することを防ぐが、固定上限だけではundercoverageを解消できない。直近確定28日の運用replayでは、p95 coverageは全体93.8%、非営業日90.7%、朝89.3%だった。

## 変更

公開予測区間にleakage-safeなrolling conformal最小幅を適用する。各対象日について次を実行する。

1. 対象日より前にETL完了と記録された直近28日を選ぶ。
2. 24時間が揃わないfileと`tepco_forecast_fallback`値を除外する。
3. 対象日と同じ営業日・非営業日レジームだけを残す。
4. 実績と当時公開されたq50の絶対誤差を深夜、朝、昼間、午後遅め、夕方に分ける。
5. 24標本以上ある時間帯で有限標本95%上側分位点を計算する。
6. その値を対称なp95最小半幅としてのみ適用する。

既存bandを狭めず、既存の3,000MW上限も超えない。対象日の実績とTEPCO予測はcalibration入力に使わない。

## Walk-Forward Replay

直近確定28日の各日について、その日より前のdataだけを使う因果的な方法で検証した。

| 区間 | 既存coverage | 候補coverage |
|---|---:|---:|
| 全体 | 93.8% | 95.8% |
| 営業日 | 95.2% | 95.8% |
| 非営業日 | 90.7% | 95.8% |
| 深夜 | 97.0% | 97.0% |
| 朝 | 89.3% | 94.3% |
| 昼間 | 91.4% | 95.7% |
| 午後遅め | 89.3% | 90.5% |
| 夕方 | 99.3% | 99.3% |

平均p95半幅は2,349.3MWから2,493.9MWへ144.6MW増加し、最大値は3,000MWのまま維持された。

## 2026-08-11確認

非営業日profileには9日が寄与した。最小半幅は深夜1,561.5MW、朝2,949.6MW、昼間2,230.6MW、午後遅め3,000MW、夕方1,870MWである。07時の公開下限は24,613.6MWから24,186.3MWへ移動し、24,350MWの実績を含む。すでに十分広い時間は変わらない。

## 追跡性と失敗時の挙動

forecast JSONの`intervalCalibration`に、方式、対象レジーム、履歴範囲、寄与日数、時間帯別標本数と最小幅を記録する。state欠落、不完全な履歴、24標本未満の場合、その時間帯は変更せずfail-closedとする。

## 残存リスク

午後遅めのcoverageは3,000MW上限でも90.5%にとどまる。主因は中心予測とshape driftであり、より広いbandで隠さない。夕方のovercoverageも残る。このpolicyは最小幅だけを補強するため、別の両側calibration実験が安全性を示すまでは既存bandを狭めない。

## 検証

- 有限標本rank、対象日leakage、確定source、標本不足、JSON根拠、3,000MW上限のtestを追加した。
- 全test: `500 passed`。
- v11 Champion、q50、raw quantile model、intraday補正、TEPCO非依存のmodeling方針は変更していない。
