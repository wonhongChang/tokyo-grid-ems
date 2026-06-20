# 2026-06-20 非営業日の prior と plateau ガード

言語: [English](../../en/model-improvements/model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md)

## 問題

2026-06-20 土曜日の配信予測では、非営業日として分離して扱うべき失敗パターンが三つ確認された。

- 当日実績が入る前に、複数の no-observation prior が重なり、早朝および日中の一部バケットを raw model より過度に下げた。00:54 JST の実行では cooler-day scale bias、day-boundary carryover、business-type transition prior が同時に入り、その一部が published forecast freeze により固定された。
- 朝の実績が入り始めた後、週末の ramp-up 自体は確認できたが、`morning_observed_ramp_floor` が営業日専用だったため、10:00-11:00 の支えが弱かった。
- 湿度の高い午後では、14:00-15:00 が実績より低く残った。前日比の気温 delta は低かったため、既存の営業日 heat/ramp lift は非営業日の高湿度 plateau を認識できなかった。

夕方のバケットも確認した。既存の non-business evening residual damping はすでに作動していたため、今回は近距離の実績根拠がない強い夕方 cap は追加していない。

## 変更

- `pre_observation_prior_stack_cap` を追加し、当日実績がない、またはほとんどない段階で no-observation prior が重なって生む過度な下方シフトを制限した。
- `morning_observed_ramp_floor` を非営業日にも適用できるようにし、非営業日では小さめの slope fraction と lift cap を使うようにした。
- `daytime_sustained_underforecast_lift` に、14:00-15:00 の非営業日高湿度 plateau 向け分岐を狭く追加した。
- 時間別 residual carryover ログに湿度と不快指数の診断値を残すようにした。
- AI 運用レポートが新しいガード名を直接参照できるよう feature catalog を更新した。

## リスク制御

- TEPCO 予測値は補正入力として使わない。
- no-observation cap は raw forecast からの過度な下方移動だけを戻し、新しい上方予測レジームは作らない。
- 週末 morning floor は、当日実績 ramp-up の根拠がある場合にのみ作動する。
- 高湿度 plateau lift は、継続的な正の residual、正の residual pressure、高い湿度または不快指数がそろう場合にのみ作動する。
- 夕方 shape は強制的に抑えず、引き続き監視対象とする。

## 検証

```text
tests/test_intraday_correction.py::test_intraday_caps_pre_observation_prior_stack_before_weekend_actuals
tests/test_intraday_correction.py::test_intraday_weekend_morning_ramp_floor_lifts_observed_non_business_ramp
tests/test_intraday_correction.py::test_intraday_weekend_humid_daytime_underforecast_lifts_plateau_hours
```
