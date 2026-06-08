# 2026-06-08 営業日復帰 shape veto

Languages: [English](../../en/model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md)

---

## 問題

2026-06-08 のライブ予測では、raw LightGBM のライン自体は月曜日の営業日復帰ランプをある程度表現できていました。しかし後処理レイヤーの `business_return_anchor_shortfall` が、最近の平日 anchor レベルと前日週末の `lag_24h` レベル差だけを見て追加の上方補正を適用しました。

その結果、08:00-11:00 の served 予測線が raw よりさらに高くなり、誤差が拡大しました。この日の主因は raw モデルの弱さではなく、すでに十分な shape を持つ予測線に対してレベル anchor guard が介入したことです。

## 変更

`business_return_anchor_shortfall` に shape ベースの veto 条件を追加しました。

ガードは現在の予測線の時間差分を `recent_same_business_type_delta_mean` と比較します。最近の同一営業タイプのランプに対して、予測ランプが明確に不足している場合だけレベル anchor のリフトを適用します。

新しい設定:

```yaml
business_return_anchor_shortfall:
  min_shape_shortfall_mw: 800
```

また、11:00 の引き継ぎ時間帯の過熱を抑えるため、late-morning excess cap の対象を 11:00 まで拡張しました。

```yaml
business_return_anchor_excess_cap:
  target_hours: [8, 9, 10, 11]
```

## 運用効果

本当に月曜日/休日明けの under-ramp がある場合は、従来どおり保守的な上方補正を許可します。一方で、raw または analogous-day 補正後の線がすでに十分なランプ shape を持つ場合は、不要な追加リフトを抑制します。

この変更は TEPCO 予測値を補正入力として使用しません。TEPCO は性能比較の参照に限定します。

## 検証

- 実際の 09:00 営業日復帰不足分は引き続きリフトされる回帰テストを追加しました。
- 朝のランプ shape がすでに十分な場合はリフトをスキップする回帰テストを追加しました。
- 11:00 にも business-return excess cap が適用される回帰テストを追加しました。
- 全体テスト: `383 passed`.
