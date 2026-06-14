# 2026-06-14 非営業日のshapeおよびresidualガード

Languages: [English](../../en/model-improvements/model-improvement-2026-06-14-non-business-shape-and-residual-guards.md) / [Korean](../../ko/model-improvements/model-improvement-2026-06-14-non-business-shape-and-residual-guards.md)

## 問題

2026-06-14日曜日の配信チャートでは、09:00-19:00に3種類の問題が混在していました。

- 09:00-10:00は、analogous-day補正が非営業日の朝の線をraw LightGBMより下へ押し下げたことで過小予測が大きくなりました。raw線の方が実績に近かったにもかかわらず、後処理線が小さな負のanalog shiftを許容していました。
- 14:00-17:00では、午後plateauの過大予測が日曜日にも出ました。直近実績はモデルが高めであることを示していましたが、`afternoon_observed_anchor_cap`が営業日専用だったため、日曜日午後には作動しませんでした。
- 18:00-19:00は、18:31スナップショットの負のintraday residual carryoverが強く残りすぎて予測線を下げました。この時点では15:00-17:00の実績がすでに回復していたため、下方向のresidualはそのまま繰り越すのではなく減衰すべきでした。

11:00-12:00の過大予測は、主にraw LightGBMのshape問題として残っています。その時間帯が確定する前に安全に介入できる当日証拠が少なく、無理に抑えると別のハードコードされた昼時間ルールになりやすいためです。

## 変更内容

- `non_business_analog_downshift_guard`をより厳格にしました。
  - 非営業日のramp supportがある場合、小さな負のanalog downshiftも止めます。
  - ガード条件下のデフォルト下方shift許容幅を300MWから0MWへ変更しました。
  - analog dayが支えられているweekend morning rampを消さないよう、raw LightGBMの流れをより保持します。
- `afternoon_observed_anchor_cap`を非営業日にも適用可能にしました。
  - `business_day_only`を`false`に変更しました。
  - 対象時間に17:00を追加しました。
  - 直近実績による過大予測の証拠が必要な点は変えていないため、日曜日専用の固定ルールではなく観測ベースのreactive guardです。
- `non_business_evening_negative_residual_damping`を追加しました。
  - 現在は非営業日の18:00-20:00に限定します。
  - base residualが強い負値で、直近の当日実績slopeが回復しており、lag/recent same-business deltaが平坦または上昇する夕方を否定しない場合だけ作動します。
  - raw予測を引き上げるのではなく、負のresidual carryoverだけを減衰します。TEPCO追従ではありません。
- AI運用レポートが新しい負のresidual dampingをcalibration JSONから説明できるよう、関連contextフィールドを追加しました。

## 期待効果

2026-06-14の公開データでは、次のパターンを抑えることを目的としています。

- 09:00と10:00で、支持されている非営業日のanalog downshiftがraw LightGBMを下回る問題
- 16:00と17:00で、日曜日であることだけを理由にobserved over-forecast capが抜ける問題
- 18:00と19:00で、当日実績がすでに回復しているにもかかわらず負のresidual carryoverが未来予測線を過度に押し下げる問題

すでにfreezeされた過去の配信線は書き換えません。同じ証拠パターンが次回のintraday実行で入ったときに予測線をより安定させる変更であり、TEPCOは診断基準であって補正ターゲットではありません。

## 残るリスク

11:00-12:00の日曜日の過大予測は、まだrawモデルshapeの問題です。次の段階では広い後処理capではなく、非営業日の昼時間shapeに対するfeature/backtest作業がより安全です。

## 検証

```text
tests/test_adjustment.py::test_guard_caps_non_business_analog_downshift_when_ramp_is_supported
tests/test_adjustment.py::test_guard_keeps_non_business_analog_downshift_without_shape_support
tests/test_intraday_correction.py::test_intraday_afternoon_observed_anchor_cap_can_run_on_non_business_days
tests/test_intraday_correction.py::test_intraday_damps_non_business_evening_negative_carryover_when_actual_recovers

Full suite: 395 passed
```
