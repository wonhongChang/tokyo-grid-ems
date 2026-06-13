# 2026-06-13 非営業日のanalogおよびcarryoverガード

Languages: [English](../../en/model-improvements/model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md) / [Korean](../../ko/model-improvements/model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md)

## 問題

2026-06-13土曜日の配信チャートでは、非営業日特有のshape問題が2つ分離して見えました。

- 朝のraw LightGBM自体が主因ではありませんでした。analogous-day補正が08:00-13:00を約500-1,100MW押し下げ、実際には上昇していた土曜日の需要曲線を過度に低くしました。
- 16:37 JST時点では、昼間の過少予測によりintraday residual correctionのbase adjustmentが約+963MWになっていました。このcarryoverが18:00で約+815MW、19:00で約+750MW残っていましたが、週末夕方のlag/recent shapeはその反発を強く支持していませんでした。

## 変更内容

- `PostHolidayTimeBandGuard`に`non_business_analog_downshift_guard`を追加しました。
  - 非営業日のみを対象にします。
  - 07:00-13:00でlag/recent same-business deltaまたはanchor文脈がraw rampを支持する場合、大きな負のanalog shiftがrawの流れを消さないように制限します。
  - デフォルトの最大下方shift許容幅は300MWです。
- `IntradayResidualCorrector`に`non_business_evening_positive_residual_damping`を追加しました。
  - 現在は非営業日の18:00-20:00に限定します。
  - lag/recent deltaが反発を強く説明しない場合だけ、正のintraday residual carryoverを減衰させます。
  - 16:00-17:00の応答性は残し、リードが長い夕方overhangを主に抑えます。
- calibration metadataを追加しました。
  - `nonBusinessEveningPositiveResidualDampingApplied`
  - `nonBusinessEveningPositiveResidualDampingFactor`
  - `nonBusinessEveningPositiveResidualDampingMaxMw`
  - `residualCarryoverByHour`内の時間別support deltaおよび減衰MWフィールド

## 期待効果

2026-06-13の公開calibration snapshotに新しいルールをメモリ上で適用したところ、次の変化が確認されました。

- 08:00-13:00のpre-calibration線が、強く下げられたanalog線よりraw LGBMに近づきました。
- analog下方shiftによるrecent observed residualの過大化が減り、intraday base adjustmentは約+963MWから約+913MWへ低下しました。
- 18:00-19:00の正のcarryoverは、それぞれ約425MW、391MW減りました。

この変更はTEPCO追従ではありません。TEPCOは診断基準としてのみ参照し、実際のガードはraw、analog、lag、recent same-business shape、observed residualの内部信号だけで動作します。

## 検証

```text
tests/test_adjustment.py + tests/test_intraday_correction.py: 92 passed
```

追加した単体テストでは次を確認しています。

- ramp supportがある土曜朝のanalog downshift制限
- 実際に下降shapeである週末午後のanalog downshift維持
- 非営業日夕方でshape supportが弱い場合の正のresidual carryover減衰
