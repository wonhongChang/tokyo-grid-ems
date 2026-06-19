# 2026-06-19 昼間の継続的な過小予測リフト

Languages: [English](../../en/model-improvements/model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md)

## 問題

2026-06-19 の配信予測では、先に対応した予測バンドの非対称性とは別の失敗モードが見えた。p95 バンドの再調整は反映されていたが、暑い営業日の昼間帯で中心予測線(q50)が継続的に低く出た。

- 10:00 は実績に対して約 `-2.9 GW` 低かった。
- 13:00 は実績に対して約 `-2.2 GW` 低かった。
- 16:00 は実績に対して約 `-1.5 GW` 低かった。

イントラデイ残差ループはミスを検知して `baseAdjustmentMw` を引き上げたが、published forecast freeze のため、すでに配信済みの時間帯は書き換えられなかった。残った問題は区間幅ではなく、当日実績がモデルを継続的に上回る状況で、近い昼間の時間帯を十分に早く持ち上げられなかった点だった。

## 変更

- イントラデイ補正レイヤーに `daytime_sustained_underforecast_lift` を追加した。
- リフトは、営業日、直近観測時間の継続的な正の残差、十分に大きい正の `baseAdjustmentMw`、暑いランプアップ気象文脈、近い将来時間帯がそろう場合だけ発動する。
- デフォルト範囲は意図的に狭くした: `10:00-14:00`、最大 lead `3` 時間、最大 lift `900 MW`。
- `daytimeSustainedUnderforecastLiftApplied`、`daytimeSustainedUnderforecastMaxLiftMw`、`residualCarryoverByHour` 内の時間別 lift 診断値を追加した。

## 期待される効果

暑い営業日のランプアップでモデルが実績より継続的に低い場合、通常の残差 carryover だけを待たず、近い昼間バケットをより早く回復させる。

涼しい日や中立的な日は発動しない想定であり、TEPCO 予測を追従しない。当日実績残差と気象/ランプアップ文脈だけを使うため、第三者予測の混合ではなく、保守的な運用補正として扱う。

## 検証

```text
tests/test_intraday_correction.py::test_intraday_daytime_sustained_underforecast_lifts_hot_business_day_future
tests/test_intraday_correction.py::test_intraday_daytime_sustained_underforecast_requires_heat_context

Full suite: 404 passed
```
