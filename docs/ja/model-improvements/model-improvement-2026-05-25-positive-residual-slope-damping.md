# 2026-05-25 正の残差スロープ減衰
> 正の residual が直近の将来ピークを過度に押し上げないよう、観測需要の傾きも見る intraday 補正です。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-25-positive-residual-slope-damping.md)

---

## なぜ必要か

2026-05-25 月曜日のライブ予測では、12時から15時にかけて予測曲線の shape risk が見えました。

raw model は 12時から14時、特に昼休みの dip 後の業務日リバウンドを低く見積もりました。その結果、intraday residual 補正では正の `base_adjustment_mw` が大きくなりました。正の residual 自体は問題ではありません。実績がモデルより高い場合、将来予測を一部持ち上げることは必要です。

問題は、観測需要の上昇ペースがすでに鈍化し、residual も改善しているにもかかわらず、その正の residual が次のピーク時間帯へそのまま carry-over されたことです。

つまり、14時までは低く見ていた予測線が、15時には逆に高く押し上げられる controller overshoot が発生しました。

## 変更内容

intraday 補正レイヤーに `positive_residual_slope_damping` を追加しました。

このレイヤーは raw LightGBM 予測を直接変更しません。すでに観測済み、または freeze された過去の予測線も変更しません。将来時間へ伝播する正の residual carry-over の強さだけを弱めます。

次の条件をすべて満たす場合のみ評価されます。

- residual 補正が正で、十分に大きい
- 実観測 residual が少なくとも3点ある
- 最新観測時刻が設定された基準時刻以降である
- 直近3点の residual がすべて正である
- 最新 residual が直前 residual より改善している
- 直近の観測需要が低下、または明確に上昇鈍化している
- 最新実績が同一営業タイプ anchor の近くにある
- residual 適用後の将来予測が最新実績/anchor 水準を許容幅以上に上回る

## 運用パラメータ

デフォルト設定:

- `min_reference_hour`: 12
- `max_lead_hours`: 3
- `min_base_adjustment_mw`: 300
- `min_positive_residual_mw`: 300
- `min_residual_improvement_mw`: 300
- `min_slope_deceleration_mw`: 500
- `drop_slope_threshold_mw`: 300
- `latest_slope_max_mw`: 400
- `anchor_proximity_tolerance_mw`: 1200
- `peak_excess_allowance_mw`: 300
- `damping_factor`: 0.4

条件を満たす近い将来時間の正の residual 補正は、次の形で弱められます。

```text
base_adjustment_mw * decay_per_hour^(lead_hours - 1) * positive_residual_slope_damping_factor
```

## 診断メタデータ

補正 metadata に次のフィールドを追加しました。

- `positiveResidualSlopeDampingApplied`
- `positiveResidualSlopeDampingFactor`
- `positiveResidualSlopeDampingMaxMw`
- `positive_residual_slope_damping_triggered` (`appliedRegimeReason`)
- `residualCarryoverByHour`: 時間別 decay、damping factor、最終 residual 補正値

operational calibration の時間別診断行にも `residualCarryover` が入ります。これにより、どの intraday 実行がどの将来時間をどれだけ押し上げたかを追跡できます。

## テスト

次の回帰テストを追加しました。

- 月曜日午後の上昇鈍化局面で、正の residual carry-over が減衰されるケース
- 実需要が強く上昇し続け、residual も悪化している場合は、正の residual を維持するケース
