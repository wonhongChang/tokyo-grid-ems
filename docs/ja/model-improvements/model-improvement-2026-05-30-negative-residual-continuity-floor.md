# 2026-05-30 負の残差連続性 floor
> 非営業日に、序盤の負の残差がフラットな当日需要カーブを最新実績レベルより過度に押し下げないようにする intraday 補正ガードです。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md)

---

## 背景

2026-05-30 の土曜日ライブ予測では、2026-05-29 夕方ケースとは逆方向の controller overshoot が見られました。

モデルは午前後半の一部を過大予測し、intraday 補正はその負の残差を午後へ持ち越しました。しかし 11:00-13:00 付近の当日実績需要は下落ではなく、ほぼフラットな plateau でした。この状態で負の残差が近い午後予測を最新実績 plateau より下へ押し下げ、14:00-16:00 の過小予測を作りました。

## 変更内容

intraday 補正レイヤーに `negative_residual_continuity_floor` を追加しました。

このガードは狭い条件でのみ動作します。

- 既定では非営業日にのみ適用
- 十分な当日実績履歴がある場合のみ評価
- 最新実績 slope と平均 slope がフラット、または強い下落ではない場合のみ適用
- 近い将来の bucket のみに適用
- 最新実績基準の保守的 floor を守るために必要な分だけ復元
- 設定されたガード範囲外の本番挙動を自動で変えない

## 運用パラメータ

デフォルト設定:

- `target_hours`: 10-17
- `min_reference_hour`: 10
- `max_lead_hours`: 2
- `latest_slope_min_mw`: -300
- `mean_slope_min_mw`: -300
- `floor_slack_mw`: 500
- `floor_slope_fraction`: 0.25
- `max_floor_slope_mw`: 300
- `max_restore_mw`: 900
- `min_restore_mw`: 100

## 診断メタデータ

補正 metadata には次のフィールドを記録します。

- `negativeResidualContinuityFloorApplied`
- `negativeResidualContinuityFloorMaxRestoreMw`
- 時刻別 `negativeResidualContinuityFloorMw`
- 時刻別 `negativeResidualContinuityRestoreMw`

これらは運用レポート fact packet にも圧縮して渡されるため、AI レポートは residual overshoot と raw モデル bias を区別できます。

## テスト

序盤の負の残差が14時予測を最新実績需要の文脈より過度に低くする、2026-05-30型の土曜日 plateau 回帰テストを追加しました。
