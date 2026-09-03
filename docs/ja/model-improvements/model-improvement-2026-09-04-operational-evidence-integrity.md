# 2026-09-04 運用証跡の整合性と補正状態のFail-Closed化

Languages: [English](../../en/model-improvements/model-improvement-2026-09-04-operational-evidence-integrity.md) / [한국어](../../ko/model-improvements/model-improvement-2026-09-04-operational-evidence-integrity.md)

## 問題

9月の運用レビューで、`same_regime_day_level_calibration` の状態が8月22日以降更新されていないことを確認した。補正器が標準フィールド `forecastBuild.series` ではなく、旧形式の `forecastBuild.hourly` を参照していたことが原因である。また日別スナップショットは上限数を超えると削除されるため、パーサー修正だけでは過去の初回D-1予測を安全に復元できなかった。

Championの健全性判定も直近28日を一括集計しており、旧契約や昇格日の混在予測を現在のartifactの性能として扱う可能性があった。

## 変更

- 標準の `forecastBuild.series` を読み、`hourly` は旧形式互換にのみ使用する。
- 対象日ごとの初回D-1 raw LightGBM予測を `forecast_origins/<date>/<artifact>.json` に一度だけ保存する。
- 固定originは通常のintradayスナップショット上限から分離し、120日保持する。
- 当日再計算をD-1 originへ読み替えず、モデル契約とartifact hashが一致する場合だけ残差状態へ取り込む。
- 最新確定残差が `max_state_lag_days` を超えた場合は補正を適用しないfail-closed動作とする。
- operational replayに、現在の契約とartifactだけを集計する `championScope` を追加する。昇格日の混在を避けるため、評価は翌日の完全な1日から開始する。
- Champion健全性で契約範囲のcoverageと補正状態の互換性・鮮度を検証する。
- 予測スナップショットへ補正状態、最新残差日、遅延日数、適用量を記録する。

## 移行

すでにrolling retentionで削除されたD-1 originを当日再計算から復元しない。デプロイ直後は、信頼できる新しいoriginと確定実績が蓄積するまで、同一レジーム補正が `stale_state` または `insufficient_same_regime_history` として迂回される場合がある。出所不明の予測を観測前残差として扱うより安全である。

## 影響

LightGBMの重み、q50、予測区間、後処理係数は変更しない。v15実験前に評価originと現在Championの健全性を再現可能にし、古い状態が予測を暗黙に移動させることを防ぐ変更である。

## 検証

- 標準 `series` による残差状態更新
- rollingスナップショット削除と独立した初回D-1 originの不変性
- 古い補正状態のfail-closed動作
- 契約・artifact単位のoperational replay
- Champion健全性における補正鮮度検証
- 全テスト: 577件成功
