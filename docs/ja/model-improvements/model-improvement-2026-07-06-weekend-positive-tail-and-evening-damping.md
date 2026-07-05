# 2026-07-06 週末 positive-tail lift と17時減衰

Languages: [English](../../en/model-improvements/model-improvement-2026-07-06-weekend-positive-tail-and-evening-damping.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-06-weekend-positive-tail-and-evening-damping.md)

## 背景

2026-07-04 土曜日の予測はおおむね良好だった。公開 JSON 基準でモデル MAE は約 245MW、TEPCO は約 268MW で、モデルがわずかに良かった。

明確な問題は 2026-07-05 日曜日に出た。

- 12:00 JST は約 1.5GW の過小予測だった。10:00 と 11:00 の残差はすでに正だったが、09:00 の過大予測が rolling residual gate を過度に保守的にしていた。
- 17:00 JST は約 0.9GW の過大予測だった。raw/pre-calibration 予測は実績に近かったが、昼から午後に発生した正の residual carryover が配信線を持ち上げすぎた。

2026-07-06 月曜日は、分析時点で 00:00 の実績しかなかったため、不完全な根拠だけで月曜日専用の補正は追加しなかった。

この変更では TEPCO 予測を入力として使わない。TEPCO は外部ベンチマークとしてのみ扱う。

## 変更内容

### 非営業日の positive-tail override による daytime lift

`intraday_correction.daytime_sustained_underforecast_lift` に、狭い範囲の非営業日 positive-tail override を追加した。

週末の最新実績残差が連続して正の場合、1つ前の過大予測が rolling mean 全体を抑えすぎないよう、最新 positive tail を別に評価できる。これは 2026-07-05 のように、10:00 と 11:00 はどちらも過小予測だったが 09:00 が過大予測だったケースを対象にしている。

この override は引き続き次の条件を必要とする。

- 非営業日コンテキスト
- 連続した正の residual
- latest/mean/peak residual の閾値
- 対象時間の暑さ/湿度コンテキスト
- 既存の時間別 lift cap

運用スナップショットには `daytimeSustainedUnderforecastPositiveTailOverrideActive` を残し、AI/Ops レポートが lift を許可した理由を説明できるようにした。

### 非営業日17時の positive residual damping

`intraday_correction.non_business_evening_positive_residual_damping` の対象に 17:00 JST を追加し、lead hour 2 から動作できるようにした。

2026-07-05 の 17:00 のように、対象時間の lag/recent shape support が弱いにもかかわらず、午後の正の residual が流れ込む隙間を閉じるための修正である。damping は引き続き次の条件を要求する。

- 非営業日コンテキスト
- 十分に大きい正の base adjustment
- 対象時間の弱い lag/recent support
- 最小減衰 MW 閾値

## 検証

次の回帰テストを追加した。

- 2026-07-05 に近い週末昼のケースで、1つ前の過大予測があっても最新 positive tail が daytime lift を有効化すること
- 週末 17:00 の weak-shape ケースで positive residual carryover が減衰されること

対象テスト:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_weekend_daytime_lift_uses_positive_tail_after_one_earlier_overforecast tests/test_intraday_correction.py::test_intraday_damps_non_business_17h_positive_carryover_when_shape_is_weak -q
```

結果: `2 passed`.

関連テスト:

```powershell
python -m pytest tests/test_intraday_correction.py tests/test_ai_daily_report.py -q
```

結果: `105 passed`.

## 運用メモ

今回の変更は週末専用の運用補正改善であり、週末需要を全体的に引き上げるものではない。当日実績の residual evidence が蓄積された後にだけ反応する。

2026-07-06 は、朝から昼の実績がさらに蓄積された後で再評価する必要がある。00:00 の1時間だけでは、月曜日専用 guard を追加する根拠として不十分だった。
