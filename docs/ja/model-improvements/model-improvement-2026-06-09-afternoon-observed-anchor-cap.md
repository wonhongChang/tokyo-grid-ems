# 2026-06-09 午後実績 anchor cap

> 営業日の午後 plateau で、当日実績がすでにモデルの過大予測を示している場合に、近い将来の予測線だけを保守的に下げる intraday cap です。

Languages: [English](../../en/model-improvements/model-improvement-2026-06-09-afternoon-observed-anchor-cap.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-09-afternoon-observed-anchor-cap.md)

---

## 背景

2026-06-09 のライブ予測では、朝の ramp 問題とは別の失敗パターンが見えました。

既存の `morning_observed_anchor_cap` は意図的に午前後半だけを対象にしていたため、13:00-15:00 の plateau には適用されませんでした。一方で、12:00-15:00 の当日実績はモデルより低く入り続け、raw/analog-adjusted の予測線は高い午後 plateau を維持しました。

これは夕方の下降局面でもありません。需要が急落しているというより、当日実績がすでに否定した昼間の高いレベルをモデルが維持したケースです。

## 変更内容

`intraday_correction.afternoon_observed_anchor_cap` を追加しました。

この guard は営業日の午後における近い将来の時間帯だけで動作し、最近の実績 residual が継続的な過大予測を示す場合にのみ有効になります。TEPCO 予測値は使わず、すでに実績または freeze 済みの時間帯も書き換えません。

対象となる未来時間ごとに、次の cap を計算します。

```text
直近の実績
+ lag/recent shape support の一部
+ buffer
```

現在の予測線がこの cap を超える場合だけ、超過分の一部を最大 reduction の範囲で下げます。

## 安全条件

- 午後時間帯の当日実績根拠を必要とします。
- 最新 overforecast と最近平均 overforecast の両方を要求します。
- 設定された近距離の未来時間だけを対象にします。
- この失敗パターンは lag/recent shape support の過信なので、positive support 全体ではなく一部だけを cap 計算に使います。
- 昼休みの単発 dip だけでは作動せず、最近の residual 文脈が継続的な high bias を示す場合だけ作動します。

## 設定

```yaml
intraday_correction:
  afternoon_observed_anchor_cap:
    enabled: true
    business_day_only: true
    target_hours: [14, 15, 16]
    min_reference_hour: 12
    max_reference_hour: 15
    max_lead_hours: 3
    lookback_observed_hours: 3
    min_latest_overforecast_mw: 500
    min_mean_overforecast_mw: 500
    cap_buffer_mw: 350
    support_fraction: 0.6
    shrinkage: 0.75
    max_reduction_mw: 1200
    min_reduction_mw: 100
```

## 診断フィールド

運用補正メタデータに以下を追加しました。

- `afternoonObservedAnchorCapApplied`
- `afternoonObservedAnchorCapMaxReductionMw`
- `afternoonObservedAnchorCapReductionMw`
- `afternoonObservedAnchorCapMw`
- `afternoonObservedAnchorCapCumulativeSupportMw`
- `afternoonObservedAnchorCapLatestResidualMw`
- `afternoonObservedAnchorCapMeanResidualMw`

AI 日次レポートの feature catalog にも `intraday_correction.afternoon_observed_anchor_cap` を追加しました。

## 検証

- 2026-06-09 に近い午後 plateau 過大予測の regression test を追加しました。
- 昼休みの単発 dip だけでは guard が作動しない counter-test を追加しました。
- 対象テスト: `tests/test_intraday_correction.py` 通過。
