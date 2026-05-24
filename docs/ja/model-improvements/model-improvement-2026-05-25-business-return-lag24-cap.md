# 2026-05-25 営業日復帰 lag24 cap 修正
> 暖かい月曜日の予測を、日曜日の低い `lag_24h` を基準に抑えすぎる後処理 cap を防ぎます。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md)

---

## 背景

2026-05-25 の月曜日予測で、後処理の失敗パターンが確認されました。raw LightGBM は営業日の昼間ピークを出していましたが、`post_holiday_timeband_guard` の warm-day cap が作動し、公開予測線が過度に低く抑えられました。

問題は cap の参照値です。`lag24_warm_day_cap` は、暖かい日の予測が `lag_24h + 設定された許容幅` を大きく超えないように制限します。前日が同じ営業タイプなら妥当ですが、月曜日の `lag_24h` は日曜日需要です。日曜日需要を月曜日の営業日復帰カーブの上限として使ったため、昼間の予測が不適切に下げられました。

## 変更内容

`PostHolidayTimeBandGuard` で `lag_24h_business_type_mismatch > 0` の場合、`lag24_warm_day_cap` をスキップするようにしました。

平日→平日のように比較可能な日では既存の cap を維持します。一方、日曜→月曜、休日→営業日のように 24時間 lag が異なる運用タイプから来ている場合、その lag を上限基準として使いません。

## 運用上の意味

この修正は月曜日需要を強制的に押し上げるものではなく、TEPCO予測を追従するものでもありません。誤った参照値による cap を外すだけです。実際の予測水準は、引き続きモデル、analogous-day 調整、気象特徴量、intraday residual 補正が決めます。

## テスト

非営業日の翌日の暖かい月曜日ケースを単体テストに追加しました。比較可能な日では warm-day lag24 cap が残り、営業日復帰日では日曜日の低い `lag_24h` で予測線を抑えないことを検証します。
