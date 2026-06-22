# 2026-06-22 日中 shape 連鎖ガード

言語: [English](../../en/model-improvements/model-improvement-2026-06-22-daytime-shape-chain-guards.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-22-daytime-shape-chain-guards.md)

## 背景

2026-06-22 のライブ予測は、単一時間帯の問題ではなく連鎖的に崩れました。

- 09:00-11:00 JST は過小予測でした。最近の同一営業日 shape は強い月曜朝ランプを示していましたが、business-return excess cap が analogous-day ラインを約 700-900MW 抑制しました。
- 12:00 JST は昼休みガードで下がりましたが、朝の過小予測で生じた正の intraday residual が 13:00-14:00 に持ち越されました。
- 13:00-15:00 は過大予測に反転しました。午後の shape support が弱い、または鈍化しているにもかかわらず、analogous-day 補正が raw LightGBM ラインを 700-1,100MW 程度押し上げました。

TEPCO 値は外部比較基準としてのみ確認しました。モデル入力や補正値には混ぜていません。

## 変更内容

### Business-return excess cap の緩和

`PostHolidayTimeBandGuard.business_return_anchor_excess_cap` が target hour のランプ支持を確認するようになりました。

- `lag_24h_hourly_delta`
- `recent_same_business_type_delta_mean`

営業日復帰の 09:00-11:00 で shape support が強い場合、限定的な追加 allowance を与え、cap shrinkage を下げます。正しい月曜朝ランプを guard が削り過ぎないための調整です。

### Business afternoon analog excess cap

`PostHolidayTimeBandGuard` に `business_afternoon_analog_excess_cap` を追加しました。

以下がすべて成立する場合だけ、正の analogous-day uplift を制限します。

- 営業日の午後時間帯である
- analogous-day shift が十分に大きい正の値である
- lag/recent same-business delta が上昇を強く支持していない
- 天候/冷房変化の文脈がある

通常の良性な analog 上昇は触らず、根拠の弱い午後 plateau だけを抑える目的です。

### Post-lunch decline continuity guard

`IntradayResidualCorrector` に `post_lunch_decline_continuity_guard` を追加しました。

営業日の 11:00 -> 12:00 実績低下が確認された後、13:00-14:00 の近距離未来線が実績基準より過度に跳ねる場合だけ制限します。朝の正 residual が昼休み dip を打ち消して午後前半を押し上げる問題を抑えます。

### Daytime sustained under-forecast lift の shape gate

`daytime_sustained_underforecast_lift` に `post_midday_shape_gate` を追加しました。

営業日の 12:00-14:00 では、lag と最近の同一営業日 delta の両方が回復を支持する場合だけ lift を許可します。朝の過小予測 residual が昼以降を過剰に持ち上げることを防ぎます。

## 検証

以下の回帰テストを追加しました。

- shape が支持する月曜朝ランプでは cap を緩和
- 支持が弱い午後 analogous-day uplift を制限
- post-midday shape gate が `daytime_sustained_underforecast_lift` を遮断
- 13:00-14:00 post-lunch decline continuity cap を検証

ローカル全体テスト:

```text
413 passed
```

## 運用メモ

この変更は保守的に設計しています。TEPCO 追従は行わず、すでに公開済みの過去予測スロットも書き換えません。次回実行時の pre-calibration と近距離 residual 処理を改善し、朝の過小予測が午後の過大予測へ連鎖するリスクを下げます。
