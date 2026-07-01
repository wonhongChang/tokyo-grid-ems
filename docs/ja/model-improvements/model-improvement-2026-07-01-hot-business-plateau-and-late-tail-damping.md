# 2026-07-01 高温多湿の営業日 plateau と夜間 tail 減衰

言語: [English](../../en/model-improvements/model-improvement-2026-07-01-hot-business-plateau-and-late-tail-damping.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-01-hot-business-plateau-and-late-tail-damping.md)

## 背景

2026-06-30 の営業日予測では、明確な失敗モードが確認された。

- 02:18 JST の intraday スナップショットでは、午後ピークは実績に近い水準だった。
- 07:31 JST の ETL 再生成後、raw LGBM 曲線が午後を大きく低めに再解釈した。
- その後、14:00-17:00 JST の高温多湿 plateau を過小予測した。
- 午後の miss 後、正の residual が 21:00-23:00 JST まで carryover されたが、その時点の lag/recent shape はすでに低下を示していた。

今回の修正も TEPCO から独立している。TEPCO は診断用の外部ベンチマークとしてのみ使う。

## 変更内容

### 営業日 daytime lift に絶対 heat context を追加

`intraday_correction.daytime_sustained_underforecast_lift` が、営業日でも以下の絶対的な高温多湿条件を参照できるようにした。

- `business_min_discomfort_index`
- `business_min_apparent_temp_c`

従来の営業日経路は主に 24h 気象 delta に依存していた。そのため、すでに十分高温多湿で午後 plateau が続く日でも、その時間の delta が強くなければ lift が発動しにくかった。

ただし、実績 residual の根拠は引き続き必須である。蒸し暑いという理由だけで forecast を上げることはしない。

### 午後 handoff を遅い時間まで許可

daytime underforecast lift が 15:00 実績まで参照し、17:00 まで保護できるようにした。2026-06-30 のように、14:00-15:00 実績が入ってから sustained peak が明確になるケースを対象にする。

### 20:00 以降の夜間 positive carryover を減衰

`afternoon_positive_residual_carryover_damping` を調整した。

- 23:00 まで対象に含める
- 最新実績が 20:00 の場合でも damping context を維持

午後の過小予測で発生した正の residual が、lag/recent shape が低下する夜間 tail まで機械的に伝播することを抑える。

## 検証

以下の回帰テストを追加した。

- 2026-06-30 に類似した高温多湿の営業日 plateau で、実績の過小予測根拠が確認された後にのみ 16:00-17:00 を lift
- 20:00 実績後、21:00-23:00 の positive residual carryover を減衰

検証コマンド:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_daytime_lift_uses_business_discomfort_plateau_after_hot_afternoon_miss tests/test_intraday_correction.py::test_intraday_damps_business_late_evening_positive_carryover_after_20_observed_hour -q
```

結果: `2 passed`.

## 運用メモ

2026-06-30 からの重要な学びは、ETL 再生成が raw LGBM 曲線を大きく変える場合があることだ。保存済み forecast snapshot により、初期 intraday 曲線は最終的な午後ピークに近く、ETL 後の曲線がピークを過度に下げたことを確認できた。

今後は AI/Ops レポートが以下をより明確に分離して説明できるかを確認する。

- freeze によって残った served forecast error
- 最新再計算 forecast error
- ETL 再生成後の raw LGBM shape error
