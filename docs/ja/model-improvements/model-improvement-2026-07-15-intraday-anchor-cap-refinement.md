# 2026-07-15 intraday anchor cap の精緻化

言語: [English](../../en/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md)

## 背景

warm-day lag24 の気象許容幅を反映した後も、2026-07-14 のチャートは全体として不安定でした。snapshot を分解すると、原因は二つに分かれました。

- 10:00-12:00 の偽の谷は、旧 warm-day lag24 cap が遅れて解除されたことによる freeze 影響が大きい。
- 09:00 の spike と 14:00-18:00 の plateau 過大予測は、別の intraday 制御ギャップ。

2026-07-14 の観測済み区間での性能は次の通りです。

| 区間 | モデル MAE | TEPCO MAE |
| --- | ---: | ---: |
| 観測 21 時間 | 815 MW | 478 MW |
| 09:00-19:00 | 1,104 MW | 578 MW |
| 13:00-18:00 | 1,114 MW | 657 MW |

主な誤差は次の通りです。

- 09:00: +2,162 MW
- 14:00: +1,485 MW
- 16:00: +1,242 MW
- 18:00: +1,536 MW

## 原因

### 朝 09:00 の spike

08:00 の実績はモデルとほぼ一致していたため、既存の `morning_observed_anchor_cap` は作動しませんでした。しかし 09:00 予測は、`直近実績 + lag/recent ramp support` で説明できる水準を大きく上回っていました。

つまり、最新 residual がまだ負でなくても、強い昇温シグナルの下で近い将来の予測が ramp support を大きく超えるケースを別途防ぐ必要がありました。

### 午後 plateau の過大予測

13:00 実績は昼休み後に反発したため、既存の afternoon anchor cap は回復局面と判断して 14:00 cap をスキップしました。しかし 13:00 予測自体がすでに実績より約 +1.65GW 高い状態でした。そのため、最近の slope が正でも、residual が非常に大きな負であれば severe-overforecast override が必要でした。

## 変更内容

### Morning Support-Overhang Mode

`morning_observed_anchor_cap` に `support_overhang` モードを追加しました。以下の条件でのみ作動します。

- 営業日の朝 target hour
- 最新観測 residual が中立、または小さな過少予測程度
- 前日比の気温/冷房 delta が明確に正
- target 予測が `latest actual + lag/recent ramp support + buffer` を設定しきい値以上に超える

これにより、最新観測 bucket がまだ過大予測でなくても、09:00 近距離ジャンプが support を大きく外れる場合は保守的に抑えます。

### Afternoon Severe-Overforecast Mode

`afternoon_observed_anchor_cap` に `severe_overforecast` モードを追加しました。以下の条件でのみ作動します。

- 最新 residual と平均 residual がどちらも大きな負
- 最近の実績 slope が反発中でも保守的な上限内
- lag/recent support が raw plateau レベルを説明できない

このモードは通常の午後 cap より低い support fraction と cap buffer を使います。

## 運用効果

2026-07-14 snapshot の再シミュレーション結果:

- 09:32 snapshot: `support_overhang` により 09:00 予測を約 1.0GW 引き下げ
- 14:15 snapshot: `severe_overforecast` により 14:00-16:00 plateau を約 0.7-1.3GW 引き下げ
- 16:03 snapshot: 14:00 過大予測の実績確認後、15:00-16:00 plateau をさらに強く引き下げ

すでに freeze された過去点は書き換えません。同じパターンが次回 intraday 実行で再び配信されることを防ぎます。

## 検証

- `python -m pytest tests/test_intraday_correction.py`

結果:

- `83 passed`

