# 2026-05-25 営業日復帰 anchor 不足分 guard
> 非営業日の前日 lag が営業日朝の復帰需要を過度に低くする場合だけ、保守的に補完します。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md)

---

## 背景

2026-05-25 月曜日の09時予測で、構造的な過小予測が見えました。営業日遷移特徴量は入っていましたが、24時間 lag は日曜日由来で、同時刻の最近の営業日 anchor より大きく低い状態でした。

09時の診断値は以下です。

- `lag_24h`: 22,830 MW
- `recent_same_business_type_mean`: 31,795 MW
- モデル予測: 29,570 MW

モデルは日曜日 lag の影響を一部回復していましたが、暖かい営業日復帰の朝需要を十分には戻せませんでした。

## 変更内容

`PostHolidayTimeBandGuard` 内に `business_return_anchor_shortfall` guard を追加しました。

この guard は以下の場合だけ作動します。

- 対象日が営業日である。
- `lag_24h_business_type_mismatch > 0`。
- `recent_same_business_type_mean - lag_24h` が設定閾値を超える。
- 現在の補正後予測が `recent_same_business_type_mean - allowance_mw` より低い。

条件を満たす場合、不足分の一部だけを上方補正します。

```text
shortfall = recent_same_business_type_mean - allowance_mw - forecast
adjustment = min(shortfall * shrinkage_by_hour, max_clipping_mw)
```

予測線を anchor まで強制的に引き上げるものではありません。非営業日 lag が営業日復帰カーブを過度に抑えるときだけ、制限された範囲で補完します。

## デフォルト

- `target_hours`: 06:00-11:00
- `gap_threshold_mw`: 6,000
- `allowance_mw`: 1,000
- `max_clipping_mw`: 1,000
- `shrinkage_map`: 06時 0.25、07時 0.35、08時 0.45、09時 0.50、10時 0.30、11時 0.20

## テスト

以下の単体テストを追加しました。

- 2026-05-25 09時の算術ケース: 1,225 MW の不足分に 612.5 MW の補正が適用される。
- `lag_24h_business_type_mismatch == 0` の通常営業日連続区間では介入しない。
- `enabled: false` の場合、この guard だけが無効になり、既存 warm-day guard は独立して動作する。
