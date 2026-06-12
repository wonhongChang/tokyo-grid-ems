# 2026-06-12 朝の実績ランプ floor と予測バンド tail 縮小

Languages: [English](../../en/model-improvements/model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md)

## 問題

2026-06-11 と 2026-06-12 の配信データで、2つの問題が確認されました。

- 2026-06-11 09:00-15:00 は公開チャート上では悪く見えましたが、最新の運用再計算線は実績にかなり近くなっていました。このケースは主に published forecast freeze の影響でした。
- 2026-06-12 09:00-13:00 は再計算ベースでも低すぎました。当日実績はすでに強い朝 ramp を示していた一方、既存の intraday 補正は負の residual carryover を抑える方向が中心で、観測済み ramp 軌道より低い近距離予測を支えられませんでした。
- 予測バンドが片側に過度に広がりました。複数時間で片側幅は 500MW 近くまで潰れ、反対側は 4,000MW まで開き、p95/p99 バンドが運用レビューで読みにくくなっていました。

## 変更

- `IntradayResidualCorrector` に `morning_observed_ramp_floor` を追加しました。
- この floor は、営業日朝の参照窓で当日実績が2時間連続の強い正の傾きを示した場合だけ有効になります。
- 近距離の未来だけに適用し、cap を持ちます。
  - target hour: 08:00-11:00 がデフォルト
  - 最大 lead: 2時間
  - 最大 lift: 1,200MW
  - 最小 lift: 100MW
- 運用メタデータを追加しました。
  - `morningObservedRampFloorApplied`
  - `morningObservedRampFloorMaxLiftMw`
  - `morningObservedRampFloorLiftMw`
  - `morningObservedRampFloorMw`
  - `morningObservedRampLatestSlopeMw`
- interval sanity calibration を絞りました。
  - `max_p95_half_width_mw`: 4,500 -> 3,000
  - `max_p95_asymmetry_ratio`: 4.0 -> 2.5
  - `asymmetry_reference_half_width_mw`: 1,000 -> 900

## 適用範囲

このレイヤーは TEPCO 追従でも固定時刻 lift でもありません。当日実績がすでに強い朝 ramp を証明しており、次の1-2時間の予測が保守的な継続 floor より低い場合だけ作動します。

バンド調整は q50 予測線を動かしません。まれに発生する片側 quantile tail の過大化だけを制限し、ダッシュボードのバンドを運用者が解釈しやすい形に保ちます。

## 検証

```text
tests/test_intraday_correction.py: 46 passed
tests/test_lgbm_model.py + tests/test_run_batch.py: 72 passed
targeted smoke checks: 3 passed
```

追加単体テストでは、06:00-08:00 の実績 ramp が強い場合に 09:00-10:00 の近距離予測だけが限定的に lift され、メタデータが記録されることを確認します。

## 運用メモ

2026-06-12 14:00-15:00 の跳ねは一部 freeze の問題でしたが、09:00-13:00 のミスは raw/recalculated ベースでも実際の過小予測でした。今回の変更は近距離の実績証拠ギャップを埋めるものであり、朝の湿度・不快指数・lag 過熱 interaction の長期 backtest を置き換えるものではありません。
