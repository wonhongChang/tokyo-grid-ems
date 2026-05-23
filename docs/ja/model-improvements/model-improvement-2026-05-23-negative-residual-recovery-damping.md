# 2026-05-23 負の残差回復ダンピング
> 営業日 lag 過熱後の非営業日需要回復時に、intraday の負の残差 carry-over を弱める運用補正です。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-23-negative-residual-recovery-damping.md)

---

## 背景

2026-05-23 の土曜日ライブ予測では、非営業日遷移 prior を追加した後にも別の失敗パターンが見つかりました。

早朝は金曜日の `lag_24h` の慣性が残り、モデルは過大予測になりました。通常の intraday residual 補正がこの誤差を見て負の補正を作るところまでは正しい挙動でした。しかしその後、実測需要が最近の同一非営業日 anchor に向かって素早く回復したにもかかわらず、早朝の大きな負の residual が未来時間へ残り続け、すでに良かった raw 予測線まで下げてしまいました。

これは特定時刻の問題ではなく、residual 伝播の問題です。実測系列が回復を示したなら、初期の負の誤差が残り時間全体を支配し続けないようにする必要があります。

## 変更内容

intraday 補正レイヤーに `negative_residual_recovery_damping` を追加しました。

このレイヤーは raw LightGBM 予測値を直接変更しません。すでに計算された負の `base_adjustment_mw` が未来時間に carry-over される強さだけを弱めます。

以下をすべて満たす場合だけ評価されます。

- 対象日が非営業日である。
- 24時間 lag が異なる営業/非営業タイプから来ている。
- residual 補正値が負である。
- 最近の実測需要が上昇している。
- 最近の1時間 slope のうち少なくとも1つが設定された回復基準を超えている。
- 最新実測需要が同一非営業日 anchor 付近まで戻っている。
- 最近の residual が明確に改善している。例: `-2400 -> -1600 -> -1100`

実測需要が上がっていても residual が悪化している場合、このレイヤーは作動しません。実際に低需要の日を偽の回復として扱わないための防御です。

## 運用パラメータ

デフォルト設定:

- `recovery_slope_base_mw`: 1000
- `anchor_proximity_tolerance_mw`: 1200
- `damping_factor_default`: 0.4
- `damping_factor_strong`: 0.2
- `strong_recovery_mean_slope_mw`: 500

未来時間の補正は以下の形で適用されます。

```text
base_adjustment_mw * recovery_damping_factor * decay_per_hour^(lead_hours - 1)
```

プロジェクト全体の `max_abs_adjustment_mw` 上限は、このレイヤーより前に適用されます。デフォルト上限では、`-1200 MW` にクリップされた residual に strong recovery factor `0.2` が適用されると、lead-time 減衰前の未来補正は `-240 MW` になります。

## 診断メタデータ

補正 metadata には以下を記録します。

- `negResidualRecoveryDampingApplied`
- `negResidualRecoveryDampingFactor`
- `negative_residual_recovery_damping_triggered` (`appliedRegimeReason`)

これにより、intraday レイヤーが回復中の raw 予測線を保つために負の residual carry-over を弱めたか確認できます。

## テスト

2つの回帰テストを追加しました。

- 土曜日回復ケース: 早朝の負の residual が改善し、実測需要が非営業日 anchor 側へ回復した場合、負の residual carry-over を弱めます。
- 偽回復防止ケース: 実測需要は上昇しても residual が悪化している場合、ダンピングレイヤーは作動しません。
